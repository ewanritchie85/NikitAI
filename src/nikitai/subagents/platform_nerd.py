"""NikitAI Platform Nerd sub-agent: home network / self-hosting advisor.

Reads and appends to the user's own maintained notes (via tools/logs.py); appends
are confirmation-gated. Build its config via :func:`platform_nerd_agent_config`.
"""

from __future__ import annotations

import json
from typing import Any

from ..agent import build_system_prompt, resolve_model
from ..tools import logs

PLATFORM_NERD_CONFIRMATION_REQUIRED_TOOLS: set[str] = {"append_to_log"}

PLATFORM_NERD_SYSTEM_PROMPT_TEMPLATE = """The current date and time is {now}.

You are NikitAI Platform Nerd, a networking- and self-hosting-savvy assistant with \
real technical judgment. You reason from first principles about networking (DNS, \
DHCP, subnetting, NAT and port forwarding, firewalls, TLS, reverse proxies, VPNs) \
and about self-hosting and Raspberry Pi concerns (systemd services, Docker, storage, \
backups, uptime, security hardening). You give concrete, correct advice — not vague \
generalities and not a mere read-back of notes.

You have access to the user's own maintained notes about their specific home network \
and hosting setup through your tools:
- list_log_files: see which note files exist.
- read_log_file: read a note file (tail of the file).
- append_to_log: append a new entry to an existing note file.

When the user's question concerns their specific setup (their router, their Pi, their \
domains, their services), first read the relevant notes before answering, rather than \
guessing — list the files if you're unsure which one is relevant. For general \
networking or self-hosting theory, answer directly from your own expertise; you don't \
need the notes for that.

When the user tells you about a configuration change they've made (e.g. opened a port, \
changed a DNS record, added a service, edited a reverse-proxy block), offer to record \
it in the appropriate note file. Before calling append_to_log, summarize exactly what \
you're about to write and to which file, and get the user's confirmation first — never \
append without confirming. Only append to files that already exist; if no suitable file \
exists, tell the user rather than trying to create one.

Answer succinctly first: lead with the verdict, fix, or key command in a sentence or \
two. Keep the first reply tight — a short paragraph at most, with the single most \
relevant detail (IP, port, config line) to back it up. Only expand into deeper \
explanation, more steps, or a full walkthrough when the user explicitly asks for more \
detail or a follow-up. Be concise and practical."""

PLATFORM_NERD_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "list_log_files",
        "description": (
            "List the user's home-infrastructure note files (.txt) so you can pick a "
            "relevant one to read or append to."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_log_file",
        "description": (
            "Read a home-infrastructure note file by filename. Returns the tail of the "
            "file (most recent content) up to max_lines lines."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the .txt note file, as returned by list_log_files.",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum number of trailing lines to return.",
                    "default": 200,
                },
            },
            "required": ["filename"],
        },
    },
    {
        "name": "append_to_log",
        "description": (
            "Append a new entry to an existing home-infrastructure note file. Only call "
            "this after summarizing the entry and getting the user's explicit "
            "confirmation. Never creates new files; only appends to existing .txt files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the existing .txt note file to append to.",
                },
                "content": {
                    "type": "string",
                    "description": "The entry text to append as a new block.",
                },
            },
            "required": ["filename", "content"],
        },
    },
]


def _execute_platform_nerd_tool(
    name: str, inputs: dict[str, Any], token: str
) -> tuple[str, str | None]:
    """Dispatch Platform Nerd tool calls to tools/logs.py.

    Matches the ToolDispatcher signature; ``token`` is unused (these are local file
    operations) and the refreshed-token slot is always None.
    """
    try:
        if name == "list_log_files":
            result: Any = logs.list_log_files(**inputs)
        elif name == "read_log_file":
            result = logs.read_log_file(**inputs)
        elif name == "append_to_log":
            result = logs.append_to_log(**inputs)
        else:
            return f"Unknown tool: {name}", None
    except Exception as exc:  # noqa: BLE001
        return f"Tool error: {exc}", None

    if isinstance(result, str):
        return result, None
    return json.dumps(result, indent=2), None


def platform_nerd_agent_config() -> dict[str, Any]:
    """Bundle the Platform Nerd sub-agent's prompt, tools, dispatcher, and gates.

    Same shape as :func:`..subagents.organiser.outlook_agent_config`, ready to
    spread into ``Agent(**config)``.
    """
    return {
        "system_prompt": build_system_prompt(PLATFORM_NERD_SYSTEM_PROMPT_TEMPLATE),
        "tool_definitions": PLATFORM_NERD_TOOL_DEFINITIONS,
        "tool_dispatcher": _execute_platform_nerd_tool,
        "confirmation_required_tools": PLATFORM_NERD_CONFIRMATION_REQUIRED_TOOLS,
        "model": resolve_model("NIKITAI_PLATFORM_NERD_MODEL"),
    }
