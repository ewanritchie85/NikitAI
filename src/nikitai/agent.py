"""Claude-powered personal assistant agent with Outlook tool use."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import anthropic
import requests

from .auth import get_access_token
from .tools import outlook

MODEL = os.environ.get("NIKITAI_MODEL", "claude-sonnet-5")

# Tools that must not run until the caller (CLI, web backend, etc.) confirms them.
CONFIRMATION_REQUIRED_TOOLS: set[str] = {"send_email", "delete_mail_folder", "create_calendar_event"}

UK_TIMEZONE = ZoneInfo("Europe/London")

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


@dataclass
class PendingConfirmation:
    """A tool call awaiting external approval before `Agent.confirm()` runs it."""

    id: str
    tool_name: str
    tool_input: dict[str, Any]


@dataclass
class AgentResponse:
    """Result of `Agent.send()`/`Agent.confirm()`.

    `text` may accompany `pending` (narration before the tool call); `error` is
    mutually exclusive with the other two.
    """

    text: str | None = None
    pending: PendingConfirmation | None = None
    error: str | None = None


@dataclass
class _PendingToolUse:
    """Internal state needed to resume a paused conversation turn after confirmation."""

    assistant_content: list[Any]
    tool_use_id: str
    tool_name: str
    tool_input: dict[str, Any]
    completed_results: list[dict[str, str]]
    remaining_blocks: list[Any]


class Agent:
    """Drives a Claude conversation with Outlook tool use, independent of any UI.

    Callers interact only through `send()` and `confirm()`; neither blocks on
    terminal input, so this class can be driven by a CLI, a web backend, etc.
    """

    def __init__(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.token = get_access_token()
        self.messages: list[dict] = []
        self._pending: dict[str, _PendingToolUse] = {}
        now = datetime.now(UK_TIMEZONE)
        formatted_now = f"{now.strftime('%A, %-d %B %Y, %H:%M')} {now.tzname()}"
        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(now=formatted_now)

    def send(self, user_text: str) -> AgentResponse:
        self.messages.append({"role": "user", "content": user_text})
        return self._run_loop()

    def confirm(self, pending_id: str, approved: bool) -> AgentResponse:
        pending = self._pending.pop(pending_id, None)
        if pending is None:
            return AgentResponse(error=f"Unknown confirmation id: {pending_id!r}")

        if approved:
            result_str, new_token = _execute_tool(pending.tool_name, pending.tool_input, self.token)
            if new_token:
                self.token = new_token
        else:
            result_str = "User declined to run this action."

        results = [
            *pending.completed_results,
            {"type": "tool_result", "tool_use_id": pending.tool_use_id, "content": result_str},
        ]

        outcome = self._process_blocks(pending.remaining_blocks, pending.assistant_content, results)
        if isinstance(outcome, PendingConfirmation):
            return AgentResponse(pending=outcome)

        self.messages.append({"role": "assistant", "content": pending.assistant_content})
        self.messages.append({"role": "user", "content": outcome})
        return self._run_loop()

    def _run_loop(self) -> AgentResponse:
        while True:
            try:
                response = self.client.messages.create(
                    model=MODEL,
                    max_tokens=4096,
                    system=self.system_prompt,
                    tools=TOOL_DEFINITIONS,
                    messages=self.messages,
                )
            except anthropic.APIError as exc:
                return AgentResponse(error=str(exc))

            tool_use_blocks = [block for block in response.content if block.type == "tool_use"]
            outcome = self._process_blocks(tool_use_blocks, response.content, [])

            assistant_text = "".join(
                block.text for block in response.content if block.type == "text"
            )

            if isinstance(outcome, PendingConfirmation):
                return AgentResponse(text=assistant_text or None, pending=outcome)

            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                self.messages.append({"role": "user", "content": outcome})
                continue  # loop back to let Claude process tool results

            return AgentResponse(text=assistant_text)

    def _process_blocks(
        self,
        blocks: list[Any],
        assistant_content: list[Any],
        results: list[dict[str, str]],
    ) -> list[dict[str, str]] | PendingConfirmation:
        """Executes tool_use blocks in order, pausing at the first one needing confirmation."""
        for index, block in enumerate(blocks):
            if block.name in CONFIRMATION_REQUIRED_TOOLS:
                pending_id = uuid.uuid4().hex
                self._pending[pending_id] = _PendingToolUse(
                    assistant_content=assistant_content,
                    tool_use_id=block.id,
                    tool_name=block.name,
                    tool_input=block.input,
                    completed_results=results,
                    remaining_blocks=blocks[index + 1 :],
                )
                return PendingConfirmation(
                    id=pending_id, tool_name=block.name, tool_input=block.input
                )

            result_str, new_token = _execute_tool(block.name, block.input, self.token)
            if new_token:
                self.token = new_token
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_str})
        return results
