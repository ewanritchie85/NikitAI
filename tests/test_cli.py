from unittest.mock import MagicMock, patch

import pytest

from nikitai.agent import AgentResponse, PendingConfirmation
from nikitai.cli import main, run_agent


def test_main_importable():
    assert callable(main)


@patch("nikitai.cli.run_agent")
@patch("dotenv.load_dotenv")
def test_main_loads_dotenv_and_runs_agent(mock_load_dotenv, mock_run_agent):
    main()

    mock_load_dotenv.assert_called_once_with()
    mock_run_agent.assert_called_once_with()


# ── run_agent ────────────────────────────────────────────────────────────────


def test_run_agent_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
        run_agent()


@patch("nikitai.cli.Agent")
@patch("builtins.input", side_effect=["hello", "quit"])
def test_run_agent_exits_on_quit(mock_input, mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent.send.return_value = AgentResponse(text="Hi there!")
    mock_agent_cls.return_value = mock_agent

    run_agent()

    mock_agent.send.assert_called_once_with("hello")
    mock_agent.confirm.assert_not_called()


@patch("nikitai.cli.Agent")
@patch("builtins.input", side_effect=["email bob", "y", "quit"])
def test_run_agent_confirms_pending_tool_when_approved(mock_input, mock_agent_cls):
    mock_agent = MagicMock()
    pending = PendingConfirmation(
        id="p1",
        tool_name="send_email",
        tool_input={"to": "a@b.com", "subject": "Hi", "body": "Hello"},
    )
    mock_agent.send.return_value = AgentResponse(pending=pending)
    mock_agent.confirm.return_value = AgentResponse(text="Sent it!")
    mock_agent_cls.return_value = mock_agent

    run_agent()

    mock_agent.confirm.assert_called_once_with("p1", True)


@patch("nikitai.cli.Agent")
@patch("builtins.input", side_effect=["email bob", "n", "quit"])
def test_run_agent_confirms_pending_tool_when_declined(mock_input, mock_agent_cls):
    mock_agent = MagicMock()
    pending = PendingConfirmation(
        id="p1",
        tool_name="send_email",
        tool_input={"to": "a@b.com", "subject": "Hi", "body": "Hello"},
    )
    mock_agent.send.return_value = AgentResponse(pending=pending)
    mock_agent.confirm.return_value = AgentResponse(text="Okay, not sending.")
    mock_agent_cls.return_value = mock_agent

    run_agent()

    mock_agent.confirm.assert_called_once_with("p1", False)
