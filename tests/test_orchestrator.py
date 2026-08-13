"""Unit tests for nikitai.orchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nikitai import orchestrator
from nikitai.agent import AgentResponse, PendingConfirmation
from nikitai.orchestrator import Orchestrator, SubAgentSpec
from nikitai.subagents.organiser import outlook_agent_config
from nikitai.subagents.platform_nerd import platform_nerd_agent_config
from nikitai.subagents.trainer import trainer_agent_config


def _router_response(text: str) -> MagicMock:
    """Mimic an Anthropic response carrying a single text block."""
    block = MagicMock(type="text", text=text)
    return MagicMock(content=[block])


def _registry(config_factory=None) -> dict[str, SubAgentSpec]:
    return {
        "organiser": SubAgentSpec(
            key="organiser",
            display_name="NikitAI Organiser",
            description="Outlook email and calendar.",
            config_factory=config_factory or (lambda: {}),
        )
    }


def _two_key_registry() -> dict[str, SubAgentSpec]:
    return {
        "organiser": SubAgentSpec(
            key="organiser",
            display_name="NikitAI Organiser",
            description="Outlook email and calendar.",
            config_factory=lambda: {"who": "organiser"},
        ),
        "platform_nerd": SubAgentSpec(
            key="platform_nerd",
            display_name="NikitAI Platform Nerd",
            description="Home network, self-hosting, Raspberry Pi, networking.",
            config_factory=lambda: {"who": "platform_nerd"},
        ),
    }


def _three_key_registry() -> dict[str, SubAgentSpec]:
    return {
        "organiser": SubAgentSpec(
            key="organiser",
            display_name="NikitAI Organiser",
            description="Outlook email and calendar.",
            config_factory=lambda: {"who": "organiser"},
        ),
        "platform_nerd": SubAgentSpec(
            key="platform_nerd",
            display_name="NikitAI Platform Nerd",
            description="Home network, self-hosting, Raspberry Pi, networking.",
            config_factory=lambda: {"who": "platform_nerd"},
        ),
        "trainer": SubAgentSpec(
            key="trainer",
            display_name="NikitAI Trainer",
            description="Fitness, workouts, sleep, recovery, health.",
            config_factory=lambda: {"who": "trainer"},
        ),
    }


def _orchestrator(monkeypatch, registry=None) -> Orchestrator:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("nikitai.orchestrator.anthropic.Anthropic"):
        orch = Orchestrator(registry=registry or _registry())
    orch.client = MagicMock()  # controllable router client for classification calls
    return orch


def test_init_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
        Orchestrator()


def test_send_routes_outlook_message_to_organiser(monkeypatch):
    orch = _orchestrator(monkeypatch)
    orch.client.messages.create.return_value = _router_response("organiser")

    mock_agent = MagicMock()
    mock_agent.send.return_value = AgentResponse(text="Here are your emails.")

    with patch("nikitai.orchestrator.Agent", return_value=mock_agent) as mock_agent_cls:
        result = orch.send("show me my latest emails")

    mock_agent_cls.assert_called_once()  # sub-agent constructed lazily on first use
    mock_agent.send.assert_called_once_with("show me my latest emails")
    assert result.text == "Here are your emails."
    assert result.pending is None


def test_send_routes_infra_message_to_platform_nerd(monkeypatch):
    orch = _orchestrator(monkeypatch, registry=_two_key_registry())
    orch.client.messages.create.return_value = _router_response("platform_nerd")

    mock_agent = MagicMock()
    mock_agent.send.return_value = AgentResponse(text="Port 443 forwards to your Pi.")

    with patch("nikitai.orchestrator.Agent", return_value=mock_agent) as mock_agent_cls:
        result = orch.send("how is port forwarding set up on my home router?")

    # Built with the platform_nerd factory's config, not organiser's.
    assert mock_agent_cls.call_args.kwargs == {"who": "platform_nerd"}
    mock_agent.send.assert_called_once_with("how is port forwarding set up on my home router?")
    assert result.text == "Port 443 forwards to your Pi."


def test_default_registry_includes_platform_nerd():
    assert set(orchestrator.SUB_AGENT_REGISTRY) == {"organiser", "platform_nerd", "trainer"}
    spec = orchestrator.SUB_AGENT_REGISTRY["platform_nerd"]
    assert spec.display_name == "NikitAI Platform Nerd"
    assert spec.config_factory is platform_nerd_agent_config


def test_default_registry_includes_trainer():
    spec = orchestrator.SUB_AGENT_REGISTRY["trainer"]
    assert spec.display_name == "NikitAI Trainer"
    assert spec.config_factory is trainer_agent_config


def test_send_routes_fitness_message_to_trainer(monkeypatch):
    orch = _orchestrator(monkeypatch, registry=_three_key_registry())
    orch.client.messages.create.return_value = _router_response("trainer")

    mock_agent = MagicMock()
    mock_agent.send.return_value = AgentResponse(text="Your training load is trending up.")

    with patch("nikitai.orchestrator.Agent", return_value=mock_agent) as mock_agent_cls:
        result = orch.send("how is my recovery looking after this week's runs?")

    assert mock_agent_cls.call_args.kwargs == {"who": "trainer"}
    mock_agent.send.assert_called_once_with("how is my recovery looking after this week's runs?")
    assert result.text == "Your training load is trending up."


def test_send_unclear_message_asks_for_clarification(monkeypatch):
    orch = _orchestrator(monkeypatch)
    orch.client.messages.create.return_value = _router_response("unclear")

    with patch("nikitai.orchestrator.Agent") as mock_agent_cls:
        result = orch.send("what's the meaning of life?")

    # No sub-agent is built and nothing is dispatched — we ask rather than guess.
    mock_agent_cls.assert_not_called()
    assert result.pending is None
    assert result.error is None
    assert "NikitAI Organiser" in result.text
    assert "clarify" in result.text.lower()


def test_send_unregistered_key_is_treated_as_unclear(monkeypatch):
    orch = _orchestrator(monkeypatch)
    orch.client.messages.create.return_value = _router_response("trainer")

    with patch("nikitai.orchestrator.Agent") as mock_agent_cls:
        result = orch.send("how many steps did I walk?")

    mock_agent_cls.assert_not_called()
    assert result.text is not None
    assert "NikitAI Organiser" in result.text


def test_send_reuses_same_agent_instance(monkeypatch):
    orch = _orchestrator(monkeypatch)
    orch.client.messages.create.return_value = _router_response("organiser")

    mock_agent = MagicMock()
    mock_agent.send.return_value = AgentResponse(text="ok")

    with patch("nikitai.orchestrator.Agent", return_value=mock_agent) as mock_agent_cls:
        orch.send("list my folders")
        orch.send("list my emails")

    # Lazy init happens once; the same instance handles subsequent messages.
    mock_agent_cls.assert_called_once()
    assert mock_agent.send.call_count == 2


def test_confirm_round_trip_routes_to_originating_subagent(monkeypatch):
    orch = _orchestrator(monkeypatch)
    orch.client.messages.create.return_value = _router_response("organiser")

    pending = PendingConfirmation(
        id="p1",
        tool_name="send_email",
        tool_input={"to": "a@b.com", "subject": "Hi", "body": "Hello"},
    )
    mock_agent = MagicMock()
    mock_agent.send.return_value = AgentResponse(pending=pending)
    mock_agent.confirm.return_value = AgentResponse(text="Sent it!")

    with patch("nikitai.orchestrator.Agent", return_value=mock_agent):
        send_result = orch.send("email bob")
        assert send_result.pending is pending
        assert orch._pending_routes["p1"] == "organiser"

        confirm_result = orch.confirm("p1", approved=True)

    # confirm() dispatched to the same sub-agent instance without re-classifying.
    mock_agent.confirm.assert_called_once_with("p1", True)
    orch.client.messages.create.assert_called_once()  # only the send() classification
    assert confirm_result.text == "Sent it!"
    assert "p1" not in orch._pending_routes


def test_confirm_unknown_pending_id_returns_error(monkeypatch):
    orch = _orchestrator(monkeypatch)

    result = orch.confirm("bogus", approved=True)

    assert result.error == "Unknown confirmation id: 'bogus'"
    assert result.text is None
    assert result.pending is None


def test_send_with_active_pending_routes_reply_straight_to_subagent(monkeypatch):
    orch = _orchestrator(monkeypatch)
    orch._pending_routes["p1"] = "organiser"

    mock_agent = MagicMock()
    mock_agent.resolve_pending_reply.return_value = AgentResponse(text="Sent it!")
    with patch("nikitai.orchestrator.Agent", return_value=mock_agent):
        result = orch.send("yes")

    # Sticky routing: classifier never runs; the reply goes to the originating agent.
    mock_agent.resolve_pending_reply.assert_called_once_with("p1", "yes")
    orch.client.messages.create.assert_not_called()
    assert result.text == "Sent it!"
    assert "p1" not in orch._pending_routes
    assert orch._last_active_key == "organiser"


def test_send_with_active_pending_implicit_cancel_reclassifies(monkeypatch):
    orch = _orchestrator(monkeypatch)
    orch._pending_routes["p1"] = "organiser"
    orch.client.messages.create.return_value = _router_response("organiser")

    mock_agent = MagicMock()
    mock_agent.resolve_pending_reply.return_value = None
    mock_agent.send.return_value = AgentResponse(text="Here are your emails.")
    with patch("nikitai.orchestrator.Agent", return_value=mock_agent):
        result = orch.send("yes, and also check my logs")

    # Not a confirmation reply -> pending cancelled, message re-classified normally.
    mock_agent.resolve_pending_reply.assert_called_once_with("p1", "yes, and also check my logs")
    mock_agent.send.assert_called_once_with("yes, and also check my logs")
    orch.client.messages.create.assert_called_once()  # classifier ran for the fresh turn
    assert "p1" not in orch._pending_routes
    assert orch._last_active_key == "organiser"
    assert result.text == "Here are your emails."


def test_send_unclear_with_no_last_active_asks_for_clarification(monkeypatch):
    orch = _orchestrator(monkeypatch, registry=_two_key_registry())
    orch.client.messages.create.return_value = _router_response("unclear")

    with patch("nikitai.orchestrator.Agent") as mock_agent_cls:
        result = orch.send("what's the meaning of life?")

    mock_agent_cls.assert_not_called()
    assert orch._last_active_key is None
    assert "NikitAI Organiser" in result.text
    assert "clarify" in result.text.lower()


def test_send_unclear_with_last_active_routes_to_last_active(monkeypatch):
    orch = _orchestrator(monkeypatch, registry=_two_key_registry())
    orch._last_active_key = "platform_nerd"
    orch.client.messages.create.return_value = _router_response("unclear")

    mock_agent = MagicMock()
    mock_agent.send.return_value = AgentResponse(text="Port 443 forwards to your Pi.")
    with patch("nikitai.orchestrator.Agent", return_value=mock_agent):
        result = orch.send("yes")

    # Off-topic "unclear" reply stays with the previously active sub-agent.
    mock_agent.send.assert_called_once_with("yes")
    assert result.text == "Port 443 forwards to your Pi."
    assert orch._last_active_key == "platform_nerd"


def test_send_unregistered_key_with_last_active_routes_to_last_active(monkeypatch):
    orch = _orchestrator(monkeypatch, registry=_two_key_registry())
    orch._last_active_key = "platform_nerd"
    orch.client.messages.create.return_value = _router_response("trainer")

    mock_agent = MagicMock()
    mock_agent.send.return_value = AgentResponse(text="Port 80 is forwarded.")
    with patch("nikitai.orchestrator.Agent", return_value=mock_agent):
        result = orch.send("ok")

    mock_agent.send.assert_called_once_with("ok")
    assert result.text == "Port 80 is forwarded."
    assert orch._last_active_key == "platform_nerd"


def test_send_confident_key_wins_over_last_active(monkeypatch):
    orch = _orchestrator(monkeypatch, registry=_two_key_registry())
    orch._last_active_key = "platform_nerd"
    orch.client.messages.create.return_value = _router_response("organiser")

    mock_agent = MagicMock()
    mock_agent.send.return_value = AgentResponse(text="Here are your emails.")
    with patch("nikitai.orchestrator.Agent", return_value=mock_agent) as mock_agent_cls:
        result = orch.send("show my emails")

    # A confidently classified registered key wins over the last-active fallback.
    assert mock_agent_cls.call_args.kwargs == {"who": "organiser"}
    mock_agent.send.assert_called_once_with("show my emails")
    assert result.text == "Here are your emails."
    assert orch._last_active_key == "organiser"


def test_send_sets_last_active_key_on_successful_route(monkeypatch):
    orch = _orchestrator(monkeypatch)
    orch.client.messages.create.return_value = _router_response("organiser")

    mock_agent = MagicMock()
    mock_agent.send.return_value = AgentResponse(text="ok")
    with patch("nikitai.orchestrator.Agent", return_value=mock_agent):
        orch.send("list my emails")

    assert orch._last_active_key == "organiser"


def test_classify_falls_back_to_unclear_on_api_error(monkeypatch):
    orch = _orchestrator(monkeypatch)
    orch.client.messages.create.side_effect = orchestrator.anthropic.APIError(
        "boom", request=MagicMock(), body=None
    )

    with patch("nikitai.orchestrator.Agent") as mock_agent_cls:
        result = orch.send("anything")

    mock_agent_cls.assert_not_called()
    assert "NikitAI Organiser" in result.text


def test_default_registry_registers_organiser():
    spec = orchestrator.SUB_AGENT_REGISTRY["organiser"]
    assert spec.display_name == "NikitAI Organiser"
    assert spec.config_factory is outlook_agent_config


def test_classify_uses_resolved_router_model(monkeypatch):
    monkeypatch.setenv("NIKITAI_ROUTER_MODEL", "router-override")
    orch = _orchestrator(monkeypatch)
    orch.client.messages.create.return_value = _router_response("organiser")

    with patch("nikitai.orchestrator.Agent", return_value=MagicMock()):
        orch.send("list my emails")

    assert orch.client.messages.create.call_args.kwargs["model"] == "router-override"


def test_resolve_router_model_prefers_router_override(monkeypatch):
    monkeypatch.setenv("NIKITAI_ROUTER_MODEL", "router-override")
    monkeypatch.setenv("NIKITAI_DEFAULT_MODEL", "shared-default")

    assert orchestrator.resolve_router_model() == "router-override"


def test_resolve_router_model_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("NIKITAI_ROUTER_MODEL", raising=False)
    monkeypatch.setenv("NIKITAI_DEFAULT_MODEL", "shared-default")

    assert orchestrator.resolve_router_model() == "shared-default"


def test_resolve_router_model_falls_back_to_hardcoded(monkeypatch):
    monkeypatch.delenv("NIKITAI_ROUTER_MODEL", raising=False)
    monkeypatch.delenv("NIKITAI_DEFAULT_MODEL", raising=False)

    assert orchestrator.resolve_router_model() == orchestrator.DEFAULT_ROUTER_MODEL
