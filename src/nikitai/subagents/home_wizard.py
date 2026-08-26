"""NikitAI Home Wizard sub-agent: smart home automation assistant.

Currently scoped to WiZ smart lighting control via tools/wiz.py — local UDP
control over the LAN, no cloud account or API key required. Built to be
extended to other home automation domains (e.g. Spotify) later.

Build its config via :func:`home_wizard_agent_config`.
"""

from __future__ import annotations

import json
from typing import Any

from ..agent import build_system_prompt, resolve_model
from ..tools import wiz

# Lighting control runs immediately — no confirmation gate for on/off/dim/colour.
HOME_WIZARD_CONFIRMATION_REQUIRED_TOOLS: set[str] = set()

HOME_WIZARD_SYSTEM_PROMPT_TEMPLATE = """The current date and time is {now}. Use it to resolve \
relative times like 'tonight' or 'in 10 minutes' if the user schedules a lighting change.

You are NikitAI Home Wizard, a practical home-automation assistant currently scoped to \
WiZ smart lighting. You have direct local control over the user's bulbs — no cloud, no \
accounts, just UDP over their LAN.

You have access to the user's lights through your tools:
- list_lights: returns the friendly names of all configured lights (read from the
  user's local JSON config file). Call this when you're unsure what's available.
- get_light_state: query a specific light for its current on/off state, brightness,
  and colour.
- turn_on: turn a light on, optionally setting brightness (0-100) and/or an RGB
  colour in the same call.
- turn_off: turn a light off.
- set_brightness: adjust a light's brightness (0-100) while keeping it on.

When the user references a light or room, match against the friendly names from
list_lights. If they mention a light/room not in the config, ask for clarification
rather than guessing. If a request is ambiguous between two similarly-named lights
(e.g. "living room lamp" vs "living room light"), ask which one they mean — do not
assume.

Answer succinctly first: lead with the action taken or the key state in a sentence
or two. Keep the first reply tight — a short paragraph at most. Only expand into
deeper detail or multi-light scenes when the user explicitly asks for more."""

HOME_WIZARD_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "list_lights",
        "description": (
            "Return the friendly names of all configured WiZ lights. "
            "Call this when you're unsure what lights are available."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_light_state",
        "description": (
            "Query a specific light for its current on/off state, brightness (0-100), "
            "and RGB colour if available. The light is identified by its friendly name "
            "from the user's config file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Friendly name of the light (from list_lights).",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "turn_on",
        "description": (
            "Turn a light on, optionally setting brightness (0-100) and/or an RGB "
            "colour in the same call. The light is identified by its friendly name "
            "from the user's config file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Friendly name of the light (from list_lights).",
                },
                "brightness": {
                    "type": "integer",
                    "description": "Brightness level 0-100. Optional.",
                    "minimum": 0,
                    "maximum": 100,
                },
                "rgb": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 255},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": "RGB colour as [R, G, B] with each component 0-255. Optional.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "turn_off",
        "description": (
            "Turn a light off. The light is identified by its friendly name from "
            "the user's config file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Friendly name of the light (from list_lights).",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "set_brightness",
        "description": (
            "Set a light's brightness (0-100) while keeping it on. The light is "
            "identified by its friendly name from the user's config file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Friendly name of the light (from list_lights).",
                },
                "level": {
                    "type": "integer",
                    "description": "Brightness level 0-100.",
                    "minimum": 0,
                    "maximum": 100,
                },
            },
            "required": ["name", "level"],
        },
    },
]


def _execute_home_wizard_tool(
    name: str, inputs: dict[str, Any], token: str
) -> tuple[str, str | None]:
    """Dispatch Home Wizard tool calls to tools/wiz.py.

    Matches the ToolDispatcher signature; ``token`` is unused (WiZ access uses
    local UDP, not OAuth) and the refreshed-token slot is always None.
    """
    try:
        if name == "list_lights":
            result: Any = wiz.list_lights()
        elif name == "get_light_state":
            result = wiz.get_light_state(**inputs)
        elif name == "turn_on":
            result = wiz.turn_on(**inputs)
        elif name == "turn_off":
            result = wiz.turn_off(**inputs)
        elif name == "set_brightness":
            result = wiz.set_brightness(**inputs)
        else:
            return f"Unknown tool: {name}", None
    except (
        wiz.WizConfigError,
        wiz.WizLightNotFoundError,
        wiz.WizConnectionError,
        ValueError,
    ) as exc:
        return f"Tool error: {exc}", None
    except Exception as exc:  # noqa: BLE001
        return f"Tool error: {exc}", None

    if isinstance(result, str):
        return result, None
    return json.dumps(result, indent=2), None


def home_wizard_agent_config() -> dict[str, Any]:
    """Bundle the Home Wizard sub-agent's prompt, tools, dispatcher, and gates.

    Same shape as :func:`..subagents.trainer.trainer_agent_config` and
    :func:`..subagents.platform_nerd.platform_nerd_agent_config`, ready to
    spread into ``Agent(**config)``.
    """
    return {
        "system_prompt": build_system_prompt(HOME_WIZARD_SYSTEM_PROMPT_TEMPLATE),
        "tool_definitions": HOME_WIZARD_TOOL_DEFINITIONS,
        "tool_dispatcher": _execute_home_wizard_tool,
        "confirmation_required_tools": HOME_WIZARD_CONFIRMATION_REQUIRED_TOOLS,
        "model": resolve_model("NIKITAI_HOME_WIZARD_MODEL", "claude-haiku-4-5"),
    }
