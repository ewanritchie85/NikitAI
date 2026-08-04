"""Claude-powered personal assistant agent with Outlook tool use."""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic
import requests

from .auth import get_access_token
from .tools import outlook

MODEL = os.environ.get("NIKITAI_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You are NikitAI, a personal assistant with access to the user's Outlook \
email and calendar.

You can:
- List and read emails
- Search emails by keyword
- Send emails on the user's behalf (always confirm before sending)
- List the user's mail folders, including custom folders
- Move emails to a different mail folder
- List upcoming calendar events
- Create new calendar events

Be concise and helpful. When showing emails or events, format them clearly.
Always ask for confirmation before sending any email.

When drafting emails, write and sign them from the user's own perspective (first \
person), as if the user wrote it themselves. Never sign as NikitAI or mention that \
you are an assistant acting on the user's behalf.

When the user asks you to create a calendar event, you must first ask for (if not
already provided): the event title, the date and start/end time, the timezone, and
how many minutes before the event they'd like a reminder (default to 15 minutes if
they have no preference). Never guess or assume these values. Once you have them,
summarize the event back to the user and confirm before creating it."""

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "list_emails",
        "description": "List recent emails from a mail folder (default: inbox).",
        "input_schema": {
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "Mail folder name, e.g. 'inbox', 'sentitems', 'drafts'.",
                    "default": "inbox",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of emails to return (max 25).",
                    "default": 10,
                },
            },
        },
    },
    {
        "name": "get_email",
        "description": "Fetch the full content of a single email by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "The email message ID."}
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "search_emails",
        "description": "Search emails by keyword across all folders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword or phrase."},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "send_email",
        "description": "Send an email. Only call this after the user has explicitly confirmed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "list_mail_folders",
        "description": (
            "List the user's mail folders (including custom folders), with their IDs. "
            "Use this to find the destination folder ID before moving an email."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max folders to return.",
                    "default": 50,
                },
            },
        },
    },
    {
        "name": "move_email",
        "description": (
            "Move an email to a different mail folder. The destination folder can be a "
            "well-known name (e.g. 'inbox', 'archive', 'deleteditems') or a folder ID "
            "from list_mail_folders."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "The email message ID."},
                "destination_folder_id": {
                    "type": "string",
                    "description": "Target folder ID or well-known folder name.",
                },
            },
            "required": ["message_id", "destination_folder_id"],
        },
    },
    {
        "name": "list_calendar_events",
        "description": "List upcoming calendar events within an optional date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start": {
                    "type": "string",
                    "description": (
                        "ISO 8601 start datetime, e.g. '2026-08-03T00:00:00Z'. Defaults to now."
                    ),
                },
                "end": {
                    "type": "string",
                    "description": "ISO 8601 end datetime. Defaults to one month from now.",
                },
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "create_calendar_event",
        "description": (
            "Create a new calendar event. Only call this after asking the user for the "
            "title, date/time, timezone, and reminder lead time, and after they have "
            "explicitly confirmed the event details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Event title."},
                "start": {
                    "type": "string",
                    "description": "Start datetime, e.g. '2026-08-10T14:00:00'.",
                },
                "end": {
                    "type": "string",
                    "description": "End datetime, e.g. '2026-08-10T15:00:00'.",
                },
                "timezone_name": {
                    "type": "string",
                    "description": (
                        "Timezone for start/end, e.g. 'UTC' or 'Pacific Standard Time'."
                    ),
                    "default": "UTC",
                },
                "location": {"type": "string", "description": "Optional event location."},
                "body": {"type": "string", "description": "Optional event description/notes."},
                "reminder_minutes_before_start": {
                    "type": "integer",
                    "description": "Minutes before the event to send a reminder.",
                    "default": 15,
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of attendee email addresses.",
                },
            },
            "required": ["subject", "start", "end"],
        },
    },
]


def _execute_tool(name: str, inputs: dict[str, Any], token: str) -> tuple[str, str | None]:
    """Returns (result_str, refreshed_token).

    refreshed_token is set if a 401 forced re-auth.
    """
    refreshed: str | None = None
    for attempt in range(2):
        try:
            if name == "send_email":
                to = inputs.get("to", "")
                subject = inputs.get("subject", "")
                body = inputs.get("body", "")
                print(f"\nTo:      {to}\nSubject: {subject}\nBody:\n{body}\n")
                if input("Send this? [y/N] ").strip().lower() != "y":
                    return "User declined to send this email.", refreshed
                result = outlook.send_email(token, **inputs)
            elif name == "create_calendar_event":
                subject = inputs.get("subject", "")
                start = inputs.get("start", "")
                end = inputs.get("end", "")
                tz = inputs.get("timezone_name", "UTC")
                reminder = inputs.get("reminder_minutes_before_start", 15)
                print(
                    f"\nSubject:  {subject}\n"
                    f"Start:    {start} ({tz})\n"
                    f"End:      {end} ({tz})\n"
                    f"Reminder: {reminder} minutes before\n"
                )
                if input("Create this event? [y/N] ").strip().lower() != "y":
                    return "User declined to create this event.", refreshed
                result = outlook.create_calendar_event(token, **inputs)
            elif name == "list_emails":
                result = outlook.list_emails(token, **inputs)
            elif name == "get_email":
                result = outlook.get_email(token, **inputs)
            elif name == "search_emails":
                result = outlook.search_emails(token, **inputs)
            elif name == "list_mail_folders":
                result = outlook.list_mail_folders(token, **inputs)
            elif name == "move_email":
                result = outlook.move_email(token, **inputs)
            elif name == "list_calendar_events":
                result = outlook.list_calendar_events(token, **inputs)
            else:
                return f"Unknown tool: {name}", refreshed
            return json.dumps(result, indent=2), refreshed
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 401 and attempt == 0:
                token = get_access_token()  # expired — re-acquire and retry once
                refreshed = token
                continue
            return f"Tool error: {exc}", refreshed
        except Exception as exc:  # noqa: BLE001
            return f"Tool error: {exc}", refreshed
    return "Tool error: re-authentication failed.", refreshed


def run_agent() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    token = get_access_token()

    print("NikitAI is ready. Type 'quit' to exit.\n")
    messages: list[dict] = []

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in {"quit", "exit", "q"}:
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        while True:
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            # Collect any text to display and any tool calls to execute
            tool_results = []
            assistant_text = ""

            for block in response.content:
                if block.type == "text":
                    assistant_text += block.text
                elif block.type == "tool_use":
                    print(f"[calling {block.name}…]")
                    result_str, new_token = _execute_tool(block.name, block.input, token)
                    if new_token:
                        token = new_token
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        }
                    )

            if assistant_text:
                print(f"\nNikitAI: {assistant_text}\n")

            # Append assistant turn
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                messages.append({"role": "user", "content": tool_results})
                # Loop back to let Claude process tool results
            else:
                break  # end_turn — conversation step complete
