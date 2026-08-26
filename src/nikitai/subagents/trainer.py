"""NikitAI Trainer sub-agent: Garmin health/fitness coach.

Read-only access to the user's Garmin Connect data via tools/garmin.py — recent
activities, activity details, daily summaries, sleep, and body battery. Nothing
is confirmation-gated. Build its config via :func:`trainer_agent_config`.
"""

from __future__ import annotations

import json
from typing import Any

from ..agent import build_system_prompt, resolve_model
from ..tools import garmin

# All Trainer tools are read-only, so nothing requires confirmation in this domain.
TRAINER_CONFIRMATION_REQUIRED_TOOLS: set[str] = set()

TRAINER_SYSTEM_PROMPT_TEMPLATE = """The current date and time is {now}. Use it to resolve \
relative dates like 'today', 'yesterday', or 'this week' against the user's Garmin data.

You are NikitAI Trainer, a knowledgeable and practical fitness and training coach with \
real judgment. You reason about the user's training load, recovery, and trends over time \
using their own Garmin Connect data — you do not simply recite numbers back, and you do \
not give generic, one-size-fits-all health advice. Tell them what the data actually \
means for them and what they should do next.

You have read-only access to the user's Garmin data through your tools:
- get_recent_activities: recent workouts/activities (type, date, duration, distance, key stats).
- get_activity_details: full detail on a single activity by its id.
- get_daily_summary: daily steps, calories, resting heart rate, and other stats for a date.
- get_sleep_data: sleep stages and duration for a date.
- get_body_battery: Garmin's body battery / energy metric for a date.
- get_profile: the user's static profile — height, weight, gender, birth date.
- get_body_composition: weight, body fat, muscle, and bone for a date.

When the user asks how they're doing, how their training is going, or what they should do \
next, pull the relevant recent data before answering rather than answering generically — \
e.g. recent activities together with recent sleep and body battery. Weigh training load \
against recovery signals (sleep, resting heart rate, body battery), notice trends and \
patterns over time, and give concrete, personalized guidance grounded in the numbers you \
actually fetched. If a data point is missing or a tool returns nothing useful, say so \
honestly instead of guessing.

Answer succinctly first: lead with the verdict or key takeaway in a sentence or two, \
with the most relevant number(s) to back it up. Keep the first reply tight — a short \
paragraph at most. Only expand into deeper analysis, more numbers, or a full training \
plan when the user explicitly asks for more detail or a follow-up. Be concise, \
encouraging, and honest."""

TRAINER_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "get_recent_activities",
        "description": (
            "Return the user's most recent workouts/activities (type, start date/time, "
            "duration, distance, calories, heart rate). Use this to see what they've done "
            "recently before reasoning about training load or planning the next session."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of activities to return.",
                    "default": 10,
                },
            },
        },
    },
    {
        "name": "get_activity_details",
        "description": (
            "Fetch the full Garmin record for a single activity by its id (from "
            "get_recent_activities), including detailed stats and splits."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "activity_id": {
                    "type": "string",
                    "description": "The activity id, as returned by get_recent_activities.",
                },
            },
            "required": ["activity_id"],
        },
    },
    {
        "name": "get_daily_summary",
        "description": (
            "Return daily health stats (steps, calories, resting heart rate, active time, "
            "floors, intensity minutes) for a date. Defaults to today."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format. Defaults to today.",
                },
            },
        },
    },
    {
        "name": "get_sleep_data",
        "description": (
            "Return sleep duration and stages (deep, light, REM, awake) for a date. "
            "Defaults to today."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format. Defaults to today.",
                },
            },
        },
    },
    {
        "name": "get_body_battery",
        "description": (
            "Return Garmin's body battery / energy metric for a date. Defaults to today. "
            "Use this with sleep to judge recovery."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format. Defaults to today.",
                },
            },
        },
    },
    {
        "name": "get_profile",
        "description": (
            "Return the user's static profile: height, weight, gender, and birth date "
            "from Garmin. Use this for body context whenever a goal or question depends "
            "on who they are (weight targets, BMI-adjacent reasoning, body-type advice)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_body_composition",
        "description": (
            "Return body composition (weight, body fat, muscle, bone) for a date. "
            "Defaults to today. Use this with get_profile to weigh weight or body-fat "
            "changes over time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format. Defaults to today.",
                },
            },
        },
    },
]


def _execute_trainer_tool(name: str, inputs: dict[str, Any], token: str) -> tuple[str, str | None]:
    """Dispatch Trainer tool calls to tools/garmin.py.

    Matches the ToolDispatcher signature; ``token`` is unused (Garmin access uses
    the module-level client, not the Microsoft token) and the refreshed-token
    slot is always None.
    """
    try:
        if name == "get_recent_activities":
            result: Any = garmin.get_recent_activities(**inputs)
        elif name == "get_activity_details":
            result = garmin.get_activity_details(**inputs)
        elif name == "get_daily_summary":
            result = garmin.get_daily_summary(**inputs)
        elif name == "get_sleep_data":
            result = garmin.get_sleep_data(**inputs)
        elif name == "get_body_battery":
            result = garmin.get_body_battery(**inputs)
        elif name == "get_profile":
            result = garmin.get_profile()
        elif name == "get_body_composition":
            result = garmin.get_body_composition(**inputs)
        else:
            return f"Unknown tool: {name}", None
    except Exception as exc:  # noqa: BLE001
        return f"Tool error: {exc}", None

    if isinstance(result, str):
        return result, None
    return json.dumps(result, indent=2), None


def trainer_agent_config() -> dict[str, Any]:
    """Bundle the Trainer sub-agent's prompt, tools, dispatcher, and gates.

    Same shape as :func:`..subagents.organiser.outlook_agent_config` and
    :func:`..subagents.platform_nerd.platform_nerd_agent_config`, ready to
    spread into ``Agent(**config)``.
    """
    return {
        "system_prompt": build_system_prompt(TRAINER_SYSTEM_PROMPT_TEMPLATE),
        "tool_definitions": TRAINER_TOOL_DEFINITIONS,
        "tool_dispatcher": _execute_trainer_tool,
        "confirmation_required_tools": TRAINER_CONFIRMATION_REQUIRED_TOOLS,
        "model": resolve_model("NIKITAI_TRAINER_MODEL", "claude-sonnet-5"),
    }
