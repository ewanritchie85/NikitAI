"""Unit tests for nikitai.tools.outlook."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from nikitai.tools import outlook

TOKEN = "fake-token"


def _mock_response(json_data):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


# ── _get / _post ────────────────────────────────────────────────────────────

@patch("nikitai.tools.outlook.requests.get")
def test_get_builds_url_and_headers(mock_get):
    mock_get.return_value = _mock_response({"value": []})

    result = outlook._get(TOKEN, "/me/messages", params={"$top": 5})

    mock_get.assert_called_once_with(
        f"{outlook.GRAPH_BASE}/me/messages",
        headers={"Authorization": f"Bearer {TOKEN}"},
        params={"$top": 5},
        timeout=15,
    )
    assert result == {"value": []}


@patch("nikitai.tools.outlook.requests.get")
def test_get_raises_for_http_error(mock_get):
    resp = MagicMock()
    resp.raise_for_status.side_effect = outlook.requests.HTTPError("boom")
    mock_get.return_value = resp

    with pytest.raises(outlook.requests.HTTPError):
        outlook._get(TOKEN, "/me/messages")


@patch("nikitai.tools.outlook.requests.post")
def test_post_builds_url_headers_and_body(mock_post):
    mock_post.return_value = _mock_response({"id": "1"})

    result = outlook._post(TOKEN, "/me/sendMail", {"message": {}})

    mock_post.assert_called_once_with(
        f"{outlook.GRAPH_BASE}/me/sendMail",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        json={"message": {}},
        timeout=15,
    )
    assert result == {"id": "1"}


# ── Email ────────────────────────────────────────────────────────────────────

@patch("nikitai.tools.outlook._get")
def test_list_emails_default_folder_and_limit(mock_get):
    mock_get.return_value = {"value": [{"id": "1"}]}

    result = outlook.list_emails(TOKEN)

    mock_get.assert_called_once_with(
        TOKEN,
        "/me/mailFolders/inbox/messages",
        params={
            "$top": 10,
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview",
        },
    )
    assert result == [{"id": "1"}]


@patch("nikitai.tools.outlook._get")
def test_list_emails_custom_folder_and_limit(mock_get):
    mock_get.return_value = {"value": []}

    result = outlook.list_emails(TOKEN, folder="drafts", limit=3)

    args, kwargs = mock_get.call_args
    assert args[1] == "/me/mailFolders/drafts/messages"
    assert kwargs["params"]["$top"] == 3
    assert result == []


@patch("nikitai.tools.outlook._get")
def test_list_emails_missing_value_key_returns_empty_list(mock_get):
    mock_get.return_value = {}

    assert outlook.list_emails(TOKEN) == []


@patch("nikitai.tools.outlook._get")
def test_get_email_calls_correct_endpoint(mock_get):
    mock_get.return_value = {"id": "abc", "subject": "hi"}

    result = outlook.get_email(TOKEN, "abc")

    mock_get.assert_called_once_with(TOKEN, "/me/messages/abc")
    assert result == {"id": "abc", "subject": "hi"}


@patch("nikitai.tools.outlook._get")
def test_search_emails_wraps_query_in_quotes(mock_get):
    mock_get.return_value = {"value": [{"id": "1"}]}

    result = outlook.search_emails(TOKEN, "budget report", limit=5)

    args, kwargs = mock_get.call_args
    assert args[1] == "/me/messages"
    assert kwargs["params"]["$search"] == '"budget report"'
    assert kwargs["params"]["$top"] == 5
    assert result == [{"id": "1"}]


@patch("nikitai.tools.outlook._get")
def test_search_emails_missing_value_key_returns_empty_list(mock_get):
    mock_get.return_value = {}

    assert outlook.search_emails(TOKEN, "query") == []


@patch("nikitai.tools.outlook._post")
def test_send_email_builds_expected_body(mock_post):
    mock_post.return_value = {"status": "sent"}

    result = outlook.send_email(TOKEN, "a@b.com", "Subject", "Body text")

    mock_post.assert_called_once_with(
        TOKEN,
        "/me/sendMail",
        {
            "message": {
                "subject": "Subject",
                "body": {"contentType": "Text", "content": "Body text"},
                "toRecipients": [{"emailAddress": {"address": "a@b.com"}}],
            }
        },
    )
    assert result == {"status": "sent"}


# ── Calendar ─────────────────────────────────────────────────────────────────

@patch("nikitai.tools.outlook._get")
@patch("nikitai.tools.outlook.datetime")
def test_list_calendar_events_defaults_computed_from_now(mock_datetime, mock_get):
    fixed_now = datetime(2026, 1, 15, 9, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = fixed_now

    mock_get.return_value = {"value": [{"id": "evt1"}]}

    result = outlook.list_calendar_events(TOKEN)

    args, kwargs = mock_get.call_args
    assert args[1] == "/me/calendarView"
    assert kwargs["params"]["startDateTime"] == "2026-01-15T09:00:00Z"
    assert kwargs["params"]["endDateTime"] == "2026-02-15T09:00:00Z"
    assert kwargs["params"]["$top"] == 10
    assert result == [{"id": "evt1"}]


@patch("nikitai.tools.outlook._get")
@patch("nikitai.tools.outlook.datetime")
def test_list_calendar_events_handles_december_year_rollover(mock_datetime, mock_get):
    fixed_now = datetime(2026, 12, 31, 8, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = fixed_now

    mock_get.return_value = {"value": []}

    outlook.list_calendar_events(TOKEN)

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["startDateTime"] == "2026-12-31T08:00:00Z"
    # January has 31 days, so day 31 is preserved; year rolls over.
    assert kwargs["params"]["endDateTime"] == "2027-01-31T08:00:00Z"


@patch("nikitai.tools.outlook._get")
@patch("nikitai.tools.outlook.datetime")
def test_list_calendar_events_clamps_day_to_shorter_month(mock_datetime, mock_get):
    fixed_now = datetime(2026, 1, 31, 8, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = fixed_now

    mock_get.return_value = {"value": []}

    outlook.list_calendar_events(TOKEN)

    _, kwargs = mock_get.call_args
    # February 2026 only has 28 days, so day is clamped.
    assert kwargs["params"]["endDateTime"] == "2026-02-28T08:00:00Z"


@patch("nikitai.tools.outlook._get")
@patch("nikitai.tools.outlook.datetime")
def test_list_calendar_events_uses_explicit_start_and_end(mock_datetime, mock_get):
    mock_datetime.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mock_get.return_value = {"value": []}

    outlook.list_calendar_events(
        TOKEN, start="2026-05-01T00:00:00Z", end="2026-05-10T00:00:00Z", limit=2
    )

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["startDateTime"] == "2026-05-01T00:00:00Z"
    assert kwargs["params"]["endDateTime"] == "2026-05-10T00:00:00Z"
    assert kwargs["params"]["$top"] == 2


@patch("nikitai.tools.outlook._get")
@patch("nikitai.tools.outlook.datetime")
def test_list_calendar_events_missing_value_key_returns_empty_list(mock_datetime, mock_get):
    mock_datetime.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mock_get.return_value = {}

    assert outlook.list_calendar_events(TOKEN) == []


@patch("nikitai.tools.outlook._post")
def test_create_calendar_event_minimal_required_fields(mock_post):
    mock_post.return_value = {"id": "evt1"}

    result = outlook.create_calendar_event(
        TOKEN, "Team sync", "2026-08-10T14:00:00", "2026-08-10T15:00:00"
    )

    mock_post.assert_called_once_with(
        TOKEN,
        "/me/events",
        {
            "subject": "Team sync",
            "start": {"dateTime": "2026-08-10T14:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2026-08-10T15:00:00", "timeZone": "UTC"},
            "isReminderOn": True,
            "reminderMinutesBeforeStart": 15,
        },
    )
    assert result == {"id": "evt1"}


@patch("nikitai.tools.outlook._post")
def test_create_calendar_event_includes_optional_fields(mock_post):
    mock_post.return_value = {"id": "evt2"}

    outlook.create_calendar_event(
        TOKEN,
        "Planning session",
        "2026-08-10T14:00:00",
        "2026-08-10T15:00:00",
        timezone_name="Pacific Standard Time",
        location="Conference Room A",
        body="Discuss roadmap",
        reminder_minutes_before_start=30,
        attendees=["a@b.com", "c@d.com"],
    )

    _, _, body = mock_post.call_args[0]
    assert body["start"] == {"dateTime": "2026-08-10T14:00:00", "timeZone": "Pacific Standard Time"}
    assert body["location"] == {"displayName": "Conference Room A"}
    assert body["body"] == {"contentType": "Text", "content": "Discuss roadmap"}
    assert body["reminderMinutesBeforeStart"] == 30
    assert body["attendees"] == [
        {"emailAddress": {"address": "a@b.com"}, "type": "required"},
        {"emailAddress": {"address": "c@d.com"}, "type": "required"},
    ]


@patch("nikitai.tools.outlook._post")
def test_create_calendar_event_omits_optional_fields_when_not_provided(mock_post):
    mock_post.return_value = {"id": "evt3"}

    outlook.create_calendar_event(
        TOKEN, "Quick call", "2026-08-10T14:00:00", "2026-08-10T15:00:00"
    )

    _, _, body = mock_post.call_args[0]
    assert "location" not in body
    assert "body" not in body
    assert "attendees" not in body
