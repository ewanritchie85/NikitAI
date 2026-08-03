"""Claude-powered personal assistant agent with Outlook tool use."""
from __future__ import annotations

import json
import os
from typing import Any

import anthropic

from .auth import get_access_token
from .tools import outlook

MODEL = "claude-opus-4-5"

SYSTEM_PROMPT = """You are NikitAI, a personal assistant with access to the user's Outlook email and calendar.

You can:
- List and read emails
- Search emails by keyword
- Send emails on the user's behalf (always confirm before sending)
- List upcoming calendar events

Be concise and helpful. When showing emails or events, format them clearly.
Always ask for confirmation before sending any email."""

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
        "name": "list_calendar_events",
        "description": "List upcoming calendar events within an optional date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start": {
                    "type": "string",
                    "description": "ISO 8601 start datetime, e.g. '2026-08-03T00:00:00Z'. Defaults to now.",
                },
                "end": {
                    "type": "string",
                    "description": "ISO 8601 end datetime. Defaults to one month from now.",
                },
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
]


def _execute_tool(name: str, inputs: dict[str, Any], token: str) -> str:
    try:
        if name == "list_emails":
            result = outlook.list_emails(token, **inputs)
        elif name == "get_email":
            result = outlook.get_email(token, **inputs)
        elif name == "search_emails":
            result = outlook.search_emails(token, **inputs)
        elif name == "send_email":
            result = outlook.send_email(token, **inputs)
        elif name == "list_calendar_events":
            result = outlook.list_calendar_events(token, **inputs)
        else:
            return f"Unknown tool: {name}"
        return json.dumps(result, indent=2)
    except Exception as exc:  # noqa: BLE001
        return f"Tool error: {exc}"


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
                    result_str = _execute_tool(block.name, block.input, token)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })

            if assistant_text:
                print(f"\nNikitAI: {assistant_text}\n")

            # Append assistant turn
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                messages.append({"role": "user", "content": tool_results})
                # Loop back to let Claude process tool results
            else:
                break  # end_turn — conversation step complete
