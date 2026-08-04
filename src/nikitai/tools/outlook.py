"""Microsoft Graph API wrappers for Outlook email and calendar."""

from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Any

import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _get(token: str, path: str, params: dict | None = None) -> Any:
    resp = requests.get(
        f"{GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _post(token: str, path: str, body: dict) -> Any:
    resp = requests.post(
        f"{GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _delete(token: str, path: str) -> None:
    resp = requests.delete(
        f"{GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()


# ── Email ──────────────────────────────────────────────────────────────────────


def list_emails(token: str, folder: str = "inbox", limit: int = 10) -> list[dict]:
    data = _get(
        token,
        f"/me/mailFolders/{folder}/messages",
        params={
            "$top": limit,
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview",
        },
    )
    return data.get("value", [])


def get_email(token: str, message_id: str) -> dict:
    return _get(token, f"/me/messages/{message_id}")


def search_emails(token: str, query: str, limit: int = 10) -> list[dict]:
    data = _get(
        token,
        "/me/messages",
        params={
            "$search": f'"{query}"',
            "$top": limit,
            "$select": "id,subject,from,receivedDateTime,bodyPreview",
        },
    )
    return data.get("value", [])


def send_email(token: str, to: str, subject: str, body: str) -> dict:
    return _post(
        token,
        "/me/sendMail",
        {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to}}],
            }
        },
    )


def list_mail_folders(token: str, limit: int = 50) -> list[dict]:
    data = _get(
        token,
        "/me/mailFolders",
        params={
            "$top": limit,
            "$select": "id,displayName,parentFolderId,childFolderCount",
        },
    )
    return data.get("value", [])


def move_email(token: str, message_id: str, destination_folder_id: str) -> dict:
    return _post(
        token,
        f"/me/messages/{message_id}/move",
        {"destinationId": destination_folder_id},
    )


def create_mail_folder(
    token: str, display_name: str, parent_folder_id: str | None = None
) -> dict:
    path = (
        f"/me/mailFolders/{parent_folder_id}/childFolders"
        if parent_folder_id
        else "/me/mailFolders"
    )
    return _post(token, path, {"displayName": display_name})


def delete_mail_folder(token: str, folder_id: str) -> dict:
    _delete(token, f"/me/mailFolders/{folder_id}")
    return {"status": "deleted", "folder_id": folder_id}


# ── Calendar ───────────────────────────────────────────────────────────────────


def list_calendar_events(
    token: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = 10,
) -> list[dict]:
    now = datetime.now(timezone.utc)
    start_dt = start or now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if end:
        end_dt = end
    else:
        month = now.month % 12 + 1
        year = now.year + (1 if now.month == 12 else 0)
        day = min(now.day, calendar.monthrange(year, month)[1])
        end_dt = now.replace(year=year, month=month, day=day).strftime("%Y-%m-%dT%H:%M:%SZ")

    data = _get(
        token,
        "/me/calendarView",
        params={
            "startDateTime": start_dt,
            "endDateTime": end_dt,
            "$top": limit,
            "$orderby": "start/dateTime",
            "$select": "id,subject,start,end,location,organizer,isAllDay",
        },
    )
    return data.get("value", [])


def create_calendar_event(
    token: str,
    subject: str,
    start: str,
    end: str,
    timezone_name: str = "UTC",
    location: str | None = None,
    body: str | None = None,
    reminder_minutes_before_start: int = 15,
    attendees: list[str] | None = None,
) -> dict:
    event: dict[str, Any] = {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": timezone_name},
        "end": {"dateTime": end, "timeZone": timezone_name},
        "isReminderOn": True,
        "reminderMinutesBeforeStart": reminder_minutes_before_start,
    }
    if location:
        event["location"] = {"displayName": location}
    if body:
        event["body"] = {"contentType": "Text", "content": body}
    if attendees:
        event["attendees"] = [
            {"emailAddress": {"address": address}, "type": "required"} for address in attendees
        ]
    return _post(token, "/me/events", event)
