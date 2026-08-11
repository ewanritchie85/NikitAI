"""Unit tests for nikitai.agent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from nikitai import agent

TOKEN = "fake-token"


def _agent() -> agent.Agent:
    """Construct an Agent wired with the real Outlook config, as the app does."""
    return agent.Agent(**agent.outlook_agent_config())


def _http_error(status_code: int) -> requests.HTTPError:
    response = MagicMock()
    response.status_code = status_code
    return requests.HTTPError(response=response)


def _text_block(text: str) -> MagicMock:
    return MagicMock(type="text", text=text)


def _tool_use_block(name: str, tool_id: str, tool_input: dict) -> MagicMock:
    # MagicMock(name=...) sets the mock's repr name, not a `.name` attribute — set it after.
    block = MagicMock(type="tool_use", id=tool_id, input=tool_input)
    block.name = name
    return block


def _response(content: list, stop_reason: str) -> MagicMock:
    return MagicMock(content=content, stop_reason=stop_reason)


# ── _execute_tool: happy paths ───────────────────────────────────────────────


@patch("nikitai.agent.outlook.list_emails")
def test_execute_tool_list_emails(mock_list_emails):
    mock_list_emails.return_value = [{"id": "1"}]

    result, refreshed = agent._execute_tool("list_emails", {"folder": "inbox"}, TOKEN)

    mock_list_emails.assert_called_once_with(TOKEN, folder="inbox")
    assert result == '[\n  {\n    "id": "1"\n  }\n]'
    assert refreshed is None


@patch("nikitai.agent.outlook.get_email")
def test_execute_tool_get_email(mock_get_email):
    mock_get_email.return_value = {"id": "abc"}

    result, refreshed = agent._execute_tool("get_email", {"message_id": "abc"}, TOKEN)

    mock_get_email.assert_called_once_with(TOKEN, message_id="abc")
    assert "abc" in result
    assert refreshed is None


@patch("nikitai.agent.outlook.search_emails")
def test_execute_tool_search_emails(mock_search_emails):
    mock_search_emails.return_value = [{"id": "1"}]

    result, refreshed = agent._execute_tool("search_emails", {"query": "budget"}, TOKEN)

    mock_search_emails.assert_called_once_with(TOKEN, query="budget")
    assert refreshed is None


@patch("nikitai.agent.outlook.list_mail_folders")
def test_execute_tool_list_mail_folders(mock_list_folders):
    mock_list_folders.return_value = [{"id": "f1", "displayName": "Projects"}]

    result, refreshed = agent._execute_tool("list_mail_folders", {}, TOKEN)

    mock_list_folders.assert_called_once_with(TOKEN)
    assert "Projects" in result
    assert refreshed is None


@patch("nikitai.agent.outlook.move_email")
def test_execute_tool_move_email(mock_move_email):
    mock_move_email.return_value = {"id": "msg1", "parentFolderId": "f1"}
    inputs = {"message_id": "msg1", "destination_folder_id": "f1"}

    result, refreshed = agent._execute_tool("move_email", inputs, TOKEN)

    mock_move_email.assert_called_once_with(TOKEN, **inputs)
    assert "msg1" in result
    assert refreshed is None


@patch("nikitai.agent.outlook.create_mail_folder")
def test_execute_tool_create_mail_folder(mock_create_folder):
    mock_create_folder.return_value = {"id": "f2", "displayName": "Projects"}
    inputs = {"display_name": "Projects"}

    result, refreshed = agent._execute_tool("create_mail_folder", inputs, TOKEN)

    mock_create_folder.assert_called_once_with(TOKEN, **inputs)
    assert "Projects" in result
    assert refreshed is None


@patch("nikitai.agent.outlook.delete_mail_folder")
def test_execute_tool_delete_mail_folder(mock_delete_folder):
    mock_delete_folder.return_value = {"status": "deleted", "folder_id": "f2"}
    inputs = {"folder_id": "f2"}

    result, refreshed = agent._execute_tool("delete_mail_folder", inputs, TOKEN)

    mock_delete_folder.assert_called_once_with(TOKEN, **inputs)
    assert "deleted" in result
    assert refreshed is None


@patch("nikitai.agent.outlook.list_calendar_events")
def test_execute_tool_list_calendar_events(mock_list_events):
    mock_list_events.return_value = [{"id": "evt1"}]

    result, refreshed = agent._execute_tool("list_calendar_events", {"limit": 5}, TOKEN)

    mock_list_events.assert_called_once_with(TOKEN, limit=5)
    assert refreshed is None


@patch("nikitai.agent.outlook.send_email")
def test_execute_tool_send_email(mock_send_email):
    mock_send_email.return_value = {"status": "sent"}
    inputs = {"to": "a@b.com", "subject": "Hi", "body": "Hello"}

    result, refreshed = agent._execute_tool("send_email", inputs, TOKEN)

    mock_send_email.assert_called_once_with(TOKEN, **inputs)
    assert "sent" in result
    assert refreshed is None


@patch("nikitai.agent.outlook.create_calendar_event")
def test_execute_tool_create_calendar_event(mock_create_event):
    mock_create_event.return_value = {"id": "evt1"}
    inputs = {
        "subject": "Team sync",
        "start": "2026-08-10T14:00:00",
        "end": "2026-08-10T15:00:00",
    }

    result, refreshed = agent._execute_tool("create_calendar_event", inputs, TOKEN)

    mock_create_event.assert_called_once_with(TOKEN, **inputs)
    assert "evt1" in result
    assert refreshed is None


def test_execute_tool_unknown_tool_returns_message():
    result, refreshed = agent._execute_tool("delete_everything", {}, TOKEN)

    assert result == "Unknown tool: delete_everything"
    assert refreshed is None


# ── error handling ───────────────────────────────────────────────────────────


@patch("nikitai.agent.get_access_token")
@patch("nikitai.agent.outlook.list_emails")
def test_execute_tool_retries_once_on_401(mock_list_emails, mock_get_token):
    mock_list_emails.side_effect = [_http_error(401), [{"id": "1"}]]
    mock_get_token.return_value = "new-token"

    result, refreshed = agent._execute_tool("list_emails", {}, TOKEN)

    assert mock_list_emails.call_count == 2
    assert refreshed == "new-token"
    assert "1" in result


@patch("nikitai.agent.get_access_token")
@patch("nikitai.agent.outlook.list_emails")
def test_execute_tool_fails_after_second_401(mock_list_emails, mock_get_token):
    mock_list_emails.side_effect = [_http_error(401), _http_error(401)]
    mock_get_token.return_value = "new-token"

    result, refreshed = agent._execute_tool("list_emails", {}, TOKEN)

    # A second consecutive 401 is not retried again; the error is returned as-is.
    assert result.startswith("Tool error:")
    assert mock_list_emails.call_count == 2
    assert refreshed == "new-token"


@patch("nikitai.agent.outlook.list_emails")
def test_execute_tool_non_401_http_error_does_not_retry(mock_list_emails):
    mock_list_emails.side_effect = _http_error(500)

    result, refreshed = agent._execute_tool("list_emails", {}, TOKEN)

    assert mock_list_emails.call_count == 1
    assert result.startswith("Tool error:")
    assert refreshed is None


@patch("nikitai.agent.outlook.list_emails")
def test_execute_tool_generic_exception_returns_error_message(mock_list_emails):
    mock_list_emails.side_effect = ValueError("boom")

    result, refreshed = agent._execute_tool("list_emails", {}, TOKEN)

    assert result == "Tool error: boom"
    assert refreshed is None


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
    mock_anthropic_cls.assert_called_once_with(api_key="test-key")


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
@patch("nikitai.agent.outlook.list_emails")
def test_agent_send_executes_non_confirmation_tool_and_continues(
    mock_list_emails, mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_list_emails.return_value = [{"id": "1"}]
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _response([_tool_use_block("list_emails", "tool_1", {})], "tool_use"),
        _response([_text_block("Here are your emails.")], "end_turn"),
    ]
    mock_anthropic_cls.return_value = mock_client

    instance = _agent()
    result = instance.send("show my emails")

    mock_list_emails.assert_called_once_with(TOKEN)
    assert result.text == "Here are your emails."
    assert result.pending is None
    assert mock_client.messages.create.call_count == 2


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
def test_agent_send_pauses_for_confirmation_required_tool(
    mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    tool_input = {"to": "a@b.com", "subject": "Hi", "body": "Hello"}
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _response(
        [_tool_use_block("send_email", "tool_1", tool_input)], "tool_use"
    )
    mock_anthropic_cls.return_value = mock_client

    instance = _agent()
    result = instance.send("email bob")

    assert result.pending is not None
    assert result.pending.tool_name == "send_email"
    assert result.pending.tool_input == tool_input
    assert result.pending.id in instance._pending
    mock_client.messages.create.assert_called_once()


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
@patch("nikitai.agent.outlook.send_email")
def test_agent_confirm_approved_executes_tool_and_continues(
    mock_send_email, mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_send_email.return_value = {"status": "sent"}
    tool_input = {"to": "a@b.com", "subject": "Hi", "body": "Hello"}
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _response([_tool_use_block("send_email", "tool_1", tool_input)], "tool_use"),
        _response([_text_block("Sent it!")], "end_turn"),
    ]
    mock_anthropic_cls.return_value = mock_client

    instance = _agent()
    pending = instance.send("email bob").pending
    result = instance.confirm(pending.id, approved=True)

    mock_send_email.assert_called_once_with(TOKEN, **tool_input)
    assert result.text == "Sent it!"
    assert pending.id not in instance._pending


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
@patch("nikitai.agent.outlook.send_email")
def test_agent_confirm_declined_skips_tool_and_continues(
    mock_send_email, mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    tool_input = {"to": "a@b.com", "subject": "Hi", "body": "Hello"}
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _response([_tool_use_block("send_email", "tool_1", tool_input)], "tool_use"),
        _response([_text_block("Okay, not sending.")], "end_turn"),
    ]
    mock_anthropic_cls.return_value = mock_client

    instance = _agent()
    pending = instance.send("email bob").pending
    result = instance.confirm(pending.id, approved=False)

    mock_send_email.assert_not_called()
    assert result.text == "Okay, not sending."
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
