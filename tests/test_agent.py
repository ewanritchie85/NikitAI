"""Unit tests for nikitai.agent (the domain-agnostic core)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import anthropic
import pytest

from nikitai import agent

TOKEN = "fake-token"

# A tool name that must be confirmed, and one that runs immediately, for the fake
# config below — deliberately domain-agnostic so these tests exercise only Agent.
_GATED_TOOL = "do_dangerous_thing"
_FREE_TOOL = "do_safe_thing"


def _fake_dispatcher(name, inputs, token):
    """Records nothing; returns a deterministic result and no refreshed token."""
    return f"ran:{name}", None


def _fake_config(dispatcher=None) -> dict:
    return {
        "system_prompt": "You are a test agent.",
        "tool_definitions": [{"name": _FREE_TOOL}, {"name": _GATED_TOOL}],
        "tool_dispatcher": dispatcher or _fake_dispatcher,
        "confirmation_required_tools": {_GATED_TOOL},
        "model": "test-model",
    }


def _agent(dispatcher=None) -> agent.Agent:
    return agent.Agent(**_fake_config(dispatcher))


def _text_block(text: str) -> MagicMock:
    return MagicMock(type="text", text=text)


def _tool_use_block(name: str, tool_id: str, tool_input: dict) -> MagicMock:
    # MagicMock(name=...) sets the mock's repr name, not a `.name` attribute — set it after.
    block = MagicMock(type="tool_use", id=tool_id, input=tool_input)
    block.name = name
    return block


def _response(content: list, stop_reason: str) -> MagicMock:
    return MagicMock(content=content, stop_reason=stop_reason)


class _FakeStream:
    """Stand-in for anthropic's MessageStream: iterable text deltas + final message."""

    def __init__(self, chunks: list[str], message) -> None:
        self._chunks = chunks
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    @property
    def text_stream(self):
        yield from self._chunks

    def get_final_message(self):
        return self._message


def _stream_response(chunks: list[str], content: list, stop_reason: str) -> _FakeStream:
    return _FakeStream(chunks, _response(content, stop_reason))


# ── model resolution ─────────────────────────────────────────────────────────


def test_resolve_model_prefers_specific_override(monkeypatch):
    monkeypatch.setenv("NIKITAI_ORGANISER_MODEL", "override-model")
    monkeypatch.setenv("NIKITAI_DEFAULT_MODEL", "default-model")

    assert agent.resolve_model("NIKITAI_ORGANISER_MODEL") == "override-model"


def test_resolve_model_falls_back_to_default_when_specific_unset(monkeypatch):
    monkeypatch.delenv("NIKITAI_ORGANISER_MODEL", raising=False)
    monkeypatch.setenv("NIKITAI_DEFAULT_MODEL", "default-model")

    assert agent.resolve_model("NIKITAI_ORGANISER_MODEL") == "default-model"


def test_resolve_model_falls_back_to_hardcoded_when_nothing_set(monkeypatch):
    monkeypatch.delenv("NIKITAI_ORGANISER_MODEL", raising=False)
    monkeypatch.delenv("NIKITAI_DEFAULT_MODEL", raising=False)

    assert agent.DEFAULT_MODEL == "claude-sonnet-5"
    assert agent.resolve_model("NIKITAI_ORGANISER_MODEL") == agent.DEFAULT_MODEL


# ── build_system_prompt ───────────────────────────────────────────────────────


def test_build_system_prompt_fills_now_placeholder():
    prompt = agent.build_system_prompt("Now: {now}. End.")

    assert prompt.startswith("Now: ")
    assert prompt.endswith(". End.")
    assert "{now}" not in prompt


# ── classify_confirmation_reply ──────────────────────────────────────────────


def test_classify_confirmation_reply_affirmations():
    for phrase in ["yes", "Yes", "y", "Y", "yeah!", "okay.", "  sure  ", "go ahead", "please do"]:
        assert agent.classify_confirmation_reply(phrase) == "affirm"


def test_classify_confirmation_reply_negations():
    for phrase in ["no", "No", "n", "nope", "cancel", "decline", "no thanks", "don't"]:
        assert agent.classify_confirmation_reply(phrase) == "negate"


def test_classify_confirmation_reply_compound_is_other():
    # Compound messages ("yes, and also check my logs") are out of scope: they are
    # treated as non-replies so the orchestrator re-classifies them fresh.
    assert agent.classify_confirmation_reply("yes, and also check my logs") == "other"


def test_classify_confirmation_reply_unrelated_text_is_other():
    assert agent.classify_confirmation_reply("") == "other"
    assert agent.classify_confirmation_reply("what's the weather?") == "other"
    assert agent.classify_confirmation_reply("maybe later") == "other"


# ── Agent ────────────────────────────────────────────────────────────────────


def test_agent_init_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
        _agent()


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_init_sets_up_client_and_token(mock_anthropic_cls, mock_get_token, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    instance = _agent()

    assert instance.token == TOKEN
    assert instance.messages == []
    assert instance.model == "test-model"
    mock_anthropic_cls.assert_called_once_with(api_key="test-key")


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_uses_model_in_api_call(mock_anthropic_cls, mock_get_token, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _response([_text_block("hi")], "end_turn")
    mock_anthropic_cls.return_value = mock_client

    _agent().send("hello")

    assert mock_client.messages.create.call_args.kwargs["model"] == "test-model"


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_send_returns_text_reply(mock_anthropic_cls, mock_get_token, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _response([_text_block("Hi there!")], "end_turn")
    mock_anthropic_cls.return_value = mock_client

    instance = _agent()
    result = instance.send("hello")

    assert result.text == "Hi there!"
    assert result.pending is None
    assert result.error is None
    assert instance.messages[0] == {"role": "user", "content": "hello"}


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_send_executes_non_confirmation_tool_and_continues(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    dispatcher = MagicMock(return_value=("tool ran", None))
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _response([_tool_use_block(_FREE_TOOL, "tool_1", {"x": 1})], "tool_use"),
        _response([_text_block("Done.")], "end_turn"),
    ]
    mock_anthropic_cls.return_value = mock_client

    instance = _agent(dispatcher=dispatcher)
    result = instance.send("do the safe thing")

    dispatcher.assert_called_once_with(_FREE_TOOL, {"x": 1}, TOKEN)
    assert result.text == "Done."
    assert result.pending is None
    assert mock_client.messages.create.call_count == 2


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_send_pauses_for_confirmation_required_tool(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    tool_input = {"target": "prod"}
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _response(
        [_tool_use_block(_GATED_TOOL, "tool_1", tool_input)], "tool_use"
    )
    mock_anthropic_cls.return_value = mock_client

    instance = _agent()
    result = instance.send("do the dangerous thing")

    assert result.pending is not None
    assert result.pending.tool_name == _GATED_TOOL
    assert result.pending.tool_input == tool_input
    assert result.pending.id in instance._pending
    mock_client.messages.create.assert_called_once()


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_confirm_approved_executes_tool_and_continues(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    dispatcher = MagicMock(return_value=("executed", None))
    tool_input = {"target": "prod"}
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _response([_tool_use_block(_GATED_TOOL, "tool_1", tool_input)], "tool_use"),
        _response([_text_block("Done it!")], "end_turn"),
    ]
    mock_anthropic_cls.return_value = mock_client

    instance = _agent(dispatcher=dispatcher)
    pending = instance.send("do the dangerous thing").pending
    result = instance.confirm(pending.id, approved=True)

    dispatcher.assert_called_once_with(_GATED_TOOL, tool_input, TOKEN)
    assert result.text == "Done it!"
    assert pending.id not in instance._pending


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_confirm_declined_skips_tool_and_continues(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    dispatcher = MagicMock(return_value=("executed", None))
    tool_input = {"target": "prod"}
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _response([_tool_use_block(_GATED_TOOL, "tool_1", tool_input)], "tool_use"),
        _response([_text_block("Okay, not doing it.")], "end_turn"),
    ]
    mock_anthropic_cls.return_value = mock_client

    instance = _agent(dispatcher=dispatcher)
    pending = instance.send("do the dangerous thing").pending
    result = instance.confirm(pending.id, approved=False)

    dispatcher.assert_not_called()
    assert result.text == "Okay, not doing it."
    tool_result_message = instance.messages[-2]
    assert tool_result_message["content"][0]["content"] == "User declined to run this action."


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_confirm_unknown_id_returns_error(mock_anthropic_cls, mock_get_token, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_anthropic_cls.return_value = MagicMock()

    instance = _agent()
    result = instance.confirm("bogus-id", approved=True)

    assert result.error == "Unknown confirmation id: 'bogus-id'"
    assert result.text is None
    assert result.pending is None


# ── resolve_pending_reply (sticky routing) ───────────────────────────────────


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_resolve_pending_reply_affirms_and_executes_tool(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    dispatcher = MagicMock(return_value=("executed", None))
    tool_input = {"target": "prod"}
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _response([_tool_use_block(_GATED_TOOL, "tool_1", tool_input)], "tool_use"),
        _response([_text_block("Done it!")], "end_turn"),
    ]
    mock_anthropic_cls.return_value = mock_client

    instance = _agent(dispatcher=dispatcher)
    pending = instance.send("do the dangerous thing").pending
    result = instance.resolve_pending_reply(pending.id, "yes")

    dispatcher.assert_called_once_with(_GATED_TOOL, tool_input, TOKEN)
    assert result.text == "Done it!"
    assert pending.id not in instance._pending


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_resolve_pending_reply_negates_and_skips_tool(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    dispatcher = MagicMock(return_value=("executed", None))
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _response([_tool_use_block(_GATED_TOOL, "tool_1", {"target": "prod"})], "tool_use"),
        _response([_text_block("Okay, not doing it.")], "end_turn"),
    ]
    mock_anthropic_cls.return_value = mock_client

    instance = _agent(dispatcher=dispatcher)
    pending = instance.send("do the dangerous thing").pending
    result = instance.resolve_pending_reply(pending.id, "no")

    dispatcher.assert_not_called()
    assert result.text == "Okay, not doing it."
    assert pending.id not in instance._pending


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_resolve_pending_reply_implicit_cancel_clears_pending(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _response(
        [_tool_use_block(_GATED_TOOL, "tool_1", {"target": "prod"})], "tool_use"
    )
    mock_anthropic_cls.return_value = mock_client

    instance = _agent()
    pending = instance.send("do the dangerous thing").pending
    result = instance.resolve_pending_reply(pending.id, "yes, and also check my logs")

    # Not a confirmation reply: pending cleared, no LLM call for the resolution.
    assert result is None
    assert pending.id not in instance._pending
    mock_client.messages.create.assert_called_once()  # only the original send() call


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_resolve_pending_reply_unknown_pending_returns_none(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_anthropic_cls.return_value = MagicMock()

    instance = _agent()
    assert instance.resolve_pending_reply("bogus-id", "yes") is None


# ── stream_send / stream_confirm (progressive rendering) ─────────────────────


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_stream_send_yields_text_deltas_then_done(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stream_response(
        ["Hel", "lo ", "wor", "ld!"], [_text_block("Hello world!")], "end_turn"
    )
    mock_anthropic_cls.return_value = mock_client

    events = list(_agent().stream_send("hello"))

    # Each delta streamed as it arrives, followed by one terminal done event.
    assert [k for k, _ in events[:-1]] == ["text", "text", "text", "text"]
    assert [p for _, p in events[:-1]] == ["Hel", "lo ", "wor", "ld!"]
    kind, payload = events[-1]
    assert kind == "done"
    assert payload.text == "Hello world!"
    assert payload.pending is None and payload.error is None


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_stream_send_streams_across_tool_loop(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    dispatcher = MagicMock(return_value=("tool ran", None))
    mock_client = MagicMock()
    mock_client.messages.stream.side_effect = [
        _stream_response(
            ["Lets ", "check..."], [_tool_use_block(_FREE_TOOL, "tool_1", {"x": 1})], "tool_use"
        ),
        _stream_response(["Done."], [_text_block("Done.")], "end_turn"),
    ]
    mock_anthropic_cls.return_value = mock_client

    events = list(_agent(dispatcher=dispatcher).stream_send("do the safe thing"))

    texts = [p for k, p in events if k == "text"]
    assert texts == ["Lets ", "check...", "Done."]
    kind, payload = events[-1]
    assert kind == "done"
    assert payload.text == "Done."
    dispatcher.assert_called_once_with(_FREE_TOOL, {"x": 1}, TOKEN)


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_stream_send_pauses_for_confirmation_then_streams_confirm(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    dispatcher = MagicMock(return_value=("executed", None))
    tool_input = {"target": "prod"}
    mock_client = MagicMock()
    mock_client.messages.stream.side_effect = [
        _stream_response(
            ["Hold on..."], [_tool_use_block(_GATED_TOOL, "tool_1", tool_input)], "tool_use"
        ),
        _stream_response(["Done it!"], [_text_block("Done it!")], "end_turn"),
    ]
    mock_anthropic_cls.return_value = mock_client

    instance = _agent(dispatcher=dispatcher)
    events = list(instance.stream_send("do the dangerous thing"))
    assert [k for k, _ in events] == ["text", "done"]
    kind, first = events[-1]
    assert kind == "done"
    assert first.text == "Hold on..."
    assert first.pending is not None
    assert first.pending.tool_name == _GATED_TOOL

    confirm_events = list(instance.stream_confirm(first.pending.id, approved=True))
    assert [k for k, _ in confirm_events] == ["text", "done"]
    kind, final = confirm_events[-1]
    assert kind == "done"
    assert final.text == "Done it!"
    dispatcher.assert_called_once_with(_GATED_TOOL, tool_input, TOKEN)


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_stream_send_error_emits_done_with_error(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_client.messages.stream.side_effect = anthropic.APIError(
        "boom", request=MagicMock(), body=None
    )
    mock_anthropic_cls.return_value = mock_client

    events = list(_agent().stream_send("hello"))

    assert len(events) == 1
    kind, payload = events[0]
    assert kind == "done"
    assert "boom" in payload.error


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_stream_confirm_unknown_id_emits_done_error(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_anthropic_cls.return_value = MagicMock()

    events = list(_agent().stream_confirm("bogus-id", True))

    assert len(events) == 1
    kind, payload = events[0]
    assert kind == "done"
    assert payload.error == "Unknown confirmation id: 'bogus-id'"
