"""Microsoft Graph API wrappers for Outlook email and calendar."""
from __future__ import annotations

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


# ── Calendar ───────────────────────────────────────────────────────────────────

def list_calendar_events(
    token: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = 10,
) -> list[dict]:
    now = datetime.now(timezone.utc)
    start_dt = start or now.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_dt = end or now.replace(month=now.month % 12 + 1).strftime("%Y-%m-%dT%H:%M:%SZ")

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
