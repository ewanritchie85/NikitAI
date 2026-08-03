"""Unit tests for nikitai.agent."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from nikitai import agent

TOKEN = "fake-token"


def _http_error(status_code: int) -> requests.HTTPError:
    response = MagicMock()
    response.status_code = status_code
    return requests.HTTPError(response=response)


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


@patch("nikitai.agent.outlook.list_calendar_events")
def test_execute_tool_list_calendar_events(mock_list_events):
    mock_list_events.return_value = [{"id": "evt1"}]

    result, refreshed = agent._execute_tool("list_calendar_events", {"limit": 5}, TOKEN)

    mock_list_events.assert_called_once_with(TOKEN, limit=5)
    assert refreshed is None


def test_execute_tool_unknown_tool_returns_message():
    result, refreshed = agent._execute_tool("delete_everything", {}, TOKEN)

    assert result == "Unknown tool: delete_everything"
    assert refreshed is None


# ── send_email confirmation flow ─────────────────────────────────────────────

@patch("nikitai.agent.outlook.send_email")
@patch("builtins.input", return_value="y")
def test_execute_tool_send_email_confirmed(mock_input, mock_send_email):
    mock_send_email.return_value = {"status": "sent"}
    inputs = {"to": "a@b.com", "subject": "Hi", "body": "Hello"}

    result, refreshed = agent._execute_tool("send_email", inputs, TOKEN)

    mock_send_email.assert_called_once_with(TOKEN, **inputs)
    assert "sent" in result
    assert refreshed is None


@patch("nikitai.agent.outlook.send_email")
@patch("builtins.input", return_value="n")
def test_execute_tool_send_email_declined(mock_input, mock_send_email):
    inputs = {"to": "a@b.com", "subject": "Hi", "body": "Hello"}

    result, refreshed = agent._execute_tool("send_email", inputs, TOKEN)

    mock_send_email.assert_not_called()
    assert result == "User declined to send this email."
    assert refreshed is None


# ── create_calendar_event confirmation flow ─────────────────────────────────

@patch("nikitai.agent.outlook.create_calendar_event")
@patch("builtins.input", return_value="y")
def test_execute_tool_create_calendar_event_confirmed(mock_input, mock_create_event):
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


@patch("nikitai.agent.outlook.create_calendar_event")
@patch("builtins.input", return_value="n")
def test_execute_tool_create_calendar_event_declined(mock_input, mock_create_event):
    inputs = {
        "subject": "Team sync",
        "start": "2026-08-10T14:00:00",
        "end": "2026-08-10T15:00:00",
    }

    result, refreshed = agent._execute_tool("create_calendar_event", inputs, TOKEN)

    mock_create_event.assert_not_called()
    assert result == "User declined to create this event."
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


# ── run_agent ────────────────────────────────────────────────────────────────

def test_run_agent_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
        agent.run_agent()


@patch("nikitai.agent.get_access_token", return_value=TOKEN)
@patch("nikitai.agent.anthropic.Anthropic")
@patch("builtins.input", side_effect=["hello", "quit"])
def test_run_agent_exits_on_quit_without_calling_model(
    mock_input, mock_anthropic_cls, mock_get_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text="Hi there!")]
    response.stop_reason = "end_turn"
    mock_client.messages.create.return_value = response
    mock_anthropic_cls.return_value = mock_client

    agent.run_agent()

    mock_client.messages.create.assert_called_once()
