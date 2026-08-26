"""Unit tests for nikitai.subagents.organiser (Outlook sub-agent config)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from nikitai.subagents import organiser

TOKEN = "fake-token"


def _http_error(status_code: int) -> requests.HTTPError:
    response = MagicMock()
    response.status_code = status_code
    return requests.HTTPError(response=response)


# ── _execute_tool: happy paths ───────────────────────────────────────────────


@patch("nikitai.subagents.organiser.outlook.list_emails")
def test_execute_tool_list_emails(mock_list_emails):
    mock_list_emails.return_value = [{"id": "1"}]

    result, refreshed = organiser._execute_tool("list_emails", {"folder": "inbox"}, TOKEN)

    mock_list_emails.assert_called_once_with(TOKEN, folder="inbox")
    assert result == '[\n  {\n    "id": "1"\n  }\n]'
    assert refreshed is None


@patch("nikitai.subagents.organiser.outlook.get_email")
def test_execute_tool_get_email(mock_get_email):
    mock_get_email.return_value = {"id": "abc"}

    result, refreshed = organiser._execute_tool("get_email", {"message_id": "abc"}, TOKEN)

    mock_get_email.assert_called_once_with(TOKEN, message_id="abc")
    assert "abc" in result
    assert refreshed is None


@patch("nikitai.subagents.organiser.outlook.search_emails")
def test_execute_tool_search_emails(mock_search_emails):
    mock_search_emails.return_value = [{"id": "1"}]

    result, refreshed = organiser._execute_tool("search_emails", {"query": "budget"}, TOKEN)

    mock_search_emails.assert_called_once_with(TOKEN, query="budget")
    assert refreshed is None


@patch("nikitai.subagents.organiser.outlook.list_mail_folders")
def test_execute_tool_list_mail_folders(mock_list_folders):
    mock_list_folders.return_value = [{"id": "f1", "displayName": "Projects"}]

    result, refreshed = organiser._execute_tool("list_mail_folders", {}, TOKEN)

    mock_list_folders.assert_called_once_with(TOKEN)
    assert "Projects" in result
    assert refreshed is None


@patch("nikitai.subagents.organiser.outlook.move_email")
def test_execute_tool_move_email(mock_move_email):
    mock_move_email.return_value = {"id": "msg1", "parentFolderId": "f1"}
    inputs = {"message_id": "msg1", "destination_folder_id": "f1"}

    result, refreshed = organiser._execute_tool("move_email", inputs, TOKEN)

    mock_move_email.assert_called_once_with(TOKEN, **inputs)
    assert "msg1" in result
    assert refreshed is None


@patch("nikitai.subagents.organiser.outlook.create_mail_folder")
def test_execute_tool_create_mail_folder(mock_create_folder):
    mock_create_folder.return_value = {"id": "f2", "displayName": "Projects"}
    inputs = {"display_name": "Projects"}

    result, refreshed = organiser._execute_tool("create_mail_folder", inputs, TOKEN)

    mock_create_folder.assert_called_once_with(TOKEN, **inputs)
    assert "Projects" in result
    assert refreshed is None


@patch("nikitai.subagents.organiser.outlook.delete_mail_folder")
def test_execute_tool_delete_mail_folder(mock_delete_folder):
    mock_delete_folder.return_value = {"status": "deleted", "folder_id": "f2"}
    inputs = {"folder_id": "f2"}

    result, refreshed = organiser._execute_tool("delete_mail_folder", inputs, TOKEN)

    mock_delete_folder.assert_called_once_with(TOKEN, **inputs)
    assert "deleted" in result
    assert refreshed is None


@patch("nikitai.subagents.organiser.outlook.list_calendar_events")
def test_execute_tool_list_calendar_events(mock_list_events):
    mock_list_events.return_value = [{"id": "evt1"}]

    result, refreshed = organiser._execute_tool("list_calendar_events", {"limit": 5}, TOKEN)

    mock_list_events.assert_called_once_with(TOKEN, limit=5)
    assert refreshed is None


@patch("nikitai.subagents.organiser.outlook.send_email")
def test_execute_tool_send_email(mock_send_email):
    mock_send_email.return_value = {"status": "sent"}
    inputs = {"to": "a@b.com", "subject": "Hi", "body": "Hello"}

    result, refreshed = organiser._execute_tool("send_email", inputs, TOKEN)

    mock_send_email.assert_called_once_with(TOKEN, **inputs)
    assert "sent" in result
    assert refreshed is None


@patch("nikitai.subagents.organiser.outlook.create_calendar_event")
def test_execute_tool_create_calendar_event(mock_create_event):
    mock_create_event.return_value = {"id": "evt1"}
    inputs = {
        "subject": "Team sync",
        "start": "2026-08-10T14:00:00",
        "end": "2026-08-10T15:00:00",
    }

    result, refreshed = organiser._execute_tool("create_calendar_event", inputs, TOKEN)

    mock_create_event.assert_called_once_with(TOKEN, **inputs)
    assert "evt1" in result
    assert refreshed is None


def test_execute_tool_unknown_tool_returns_message():
    result, refreshed = organiser._execute_tool("delete_everything", {}, TOKEN)

    assert result == "Unknown tool: delete_everything"
    assert refreshed is None


# ── error handling ───────────────────────────────────────────────────────────


@patch("nikitai.subagents.organiser.get_access_token")
@patch("nikitai.subagents.organiser.outlook.list_emails")
def test_execute_tool_retries_once_on_401(mock_list_emails, mock_get_token):
    mock_list_emails.side_effect = [_http_error(401), [{"id": "1"}]]
    mock_get_token.return_value = "new-token"

    result, refreshed = organiser._execute_tool("list_emails", {}, TOKEN)

    assert mock_list_emails.call_count == 2
    assert refreshed == "new-token"
    assert "1" in result


@patch("nikitai.subagents.organiser.get_access_token")
@patch("nikitai.subagents.organiser.outlook.list_emails")
def test_execute_tool_fails_after_second_401(mock_list_emails, mock_get_token):
    mock_list_emails.side_effect = [_http_error(401), _http_error(401)]
    mock_get_token.return_value = "new-token"

    result, refreshed = organiser._execute_tool("list_emails", {}, TOKEN)

    # A second consecutive 401 is not retried again; the error is returned as-is.
    assert result.startswith("Tool error:")
    assert mock_list_emails.call_count == 2
    assert refreshed == "new-token"


@patch("nikitai.subagents.organiser.outlook.list_emails")
def test_execute_tool_non_401_http_error_does_not_retry(mock_list_emails):
    mock_list_emails.side_effect = _http_error(500)

    result, refreshed = organiser._execute_tool("list_emails", {}, TOKEN)

    assert mock_list_emails.call_count == 1
    assert result.startswith("Tool error:")
    assert refreshed is None


@patch("nikitai.subagents.organiser.outlook.list_emails")
def test_execute_tool_generic_exception_returns_error_message(mock_list_emails):
    mock_list_emails.side_effect = ValueError("boom")

    result, refreshed = organiser._execute_tool("list_emails", {}, TOKEN)

    assert result == "Tool error: boom"
    assert refreshed is None


# ── outlook_agent_config ──────────────────────────────────────────────────────


def test_outlook_config_shape(monkeypatch):
    monkeypatch.setenv("NIKITAI_ORGANISER_MODEL", "organiser-only")

    config = organiser.outlook_agent_config()

    assert set(config) == {
        "system_prompt",
        "tool_definitions",
        "tool_dispatcher",
        "confirmation_required_tools",
        "model",
    }
    assert config["tool_dispatcher"] is organiser._execute_tool
    assert config["confirmation_required_tools"] == {
        "send_email",
        "delete_mail_folder",
        "create_calendar_event",
    }
    assert config["model"] == "organiser-only"
    assert "NikitAI" in config["system_prompt"]


def test_outlook_config_uses_organiser_override(monkeypatch):
    monkeypatch.setenv("NIKITAI_ORGANISER_MODEL", "organiser-only")
    monkeypatch.setenv("NIKITAI_DEFAULT_MODEL", "shared-default")

    assert organiser.outlook_agent_config()["model"] == "organiser-only"


def test_outlook_config_falls_back_to_default_model(monkeypatch):
    monkeypatch.delenv("NIKITAI_ORGANISER_MODEL", raising=False)

    assert organiser.outlook_agent_config()["model"] == "claude-sonnet-5"
