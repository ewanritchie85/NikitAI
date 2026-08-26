"""NikitAI Organiser sub-agent: Outlook email and calendar.

Bundles the Outlook system prompt, tool definitions, and tool dispatcher into an
agent config via :func:`outlook_agent_config`, ready to spread into ``Agent(**config)``.
"""

from __future__ import annotations

import json
from typing import Any

import requests

from ..agent import build_system_prompt, resolve_model
from ..auth import get_access_token
from ..tools import outlook

# Tools that must not run until the caller (CLI, web backend, etc.) confirms them.
CONFIRMATION_REQUIRED_TOOLS: set[str] = {
    "send_email",
    "delete_mail_folder",
    "create_calendar_event",
}

SYSTEM_PROMPT_TEMPLATE = """The current date and time is {now}. Use this to resolve relative \
dates like 'today', 'tomorrow', or 'this Saturday' — do not ask the user to confirm the date \
unless their phrasing is still ambiguous after applying this.

You are NikitAI, a personal assistant with access to the user's Outlook \
email and calendar.

You can:
- List and read emails
- Search emails by keyword
- Send emails on the user's behalf (always confirm before sending)
- List the user's mail folders, including custom folders
- Move emails to a different mail folder
- Create new mail folders
- Delete mail folders (always confirm before deleting, since it's irreversible)
- List upcoming calendar events
- Create new calendar events

Be concise and helpful. When showing emails or events, format them clearly.
Always ask for confirmation before sending any email.

When drafting emails, write and sign them from the user's own perspective (first \
person), as if the user wrote it themselves. Never sign as NikitAI or mention that \
you are an assistant acting on the user's behalf.

The user is based in the UK (Europe/London), so assume this timezone for all calendar \
events unless they explicitly mention a different one — never ask them which timezone \
to use.

When the user asks you to create a calendar event, you must first ask for (if not
already provided): the event title, the date and start/end time, and how many minutes
before the event they'd like a reminder (default to 15 minutes if they have no
preference). Never guess or assume these values. Once you have them, summarize the
event back to the user and confirm before creating it."""

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
        "name": "create_mail_folder",
        "description": (
            "Create a new mail folder. Optionally nest it inside an existing folder by "
            "providing its parent folder ID from list_mail_folders."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "display_name": {"type": "string", "description": "Name for the new folder."},
                "parent_folder_id": {
                    "type": "string",
                    "description": "Optional parent folder ID to nest the new folder under.",
                },
            },
            "required": ["display_name"],
        },
    },
    {
        "name": "delete_mail_folder",
        "description": (
            "Delete a mail folder and everything in it. Only call this after the user has "
            "explicitly confirmed, since this is irreversible."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_id": {
                    "type": "string",
                    "description": "ID of the folder to delete, from list_mail_folders.",
                },
            },
            "required": ["folder_id"],
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
            "title, date/time, and reminder lead time, and after they have explicitly "
            "confirmed the event details."
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
                        "Timezone for start/end. Defaults to the user's UK timezone — only "
                        "set this if the user explicitly specifies a different timezone."
                    ),
                    "default": "GMT Standard Time",
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
                result = outlook.send_email(token, **inputs)
            elif name == "create_calendar_event":
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
            elif name == "create_mail_folder":
                result = outlook.create_mail_folder(token, **inputs)
            elif name == "delete_mail_folder":
                result = outlook.delete_mail_folder(token, **inputs)
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


def outlook_agent_config() -> dict[str, Any]:
    """Bundle the Outlook sub-agent's system prompt, tools, dispatcher, and gates.

    Callers (CLI, web) spread this into ``Agent(**outlook_agent_config())`` so the
    Agent class stays free of any Outlook-specific imports or constants.
    """
    return {
        "system_prompt": build_system_prompt(SYSTEM_PROMPT_TEMPLATE),
        "tool_definitions": TOOL_DEFINITIONS,
        "tool_dispatcher": _execute_tool,
        "confirmation_required_tools": CONFIRMATION_REQUIRED_TOOLS,
        "model": resolve_model("NIKITAI_ORGANISER_MODEL", "claude-sonnet-5"),
    }
