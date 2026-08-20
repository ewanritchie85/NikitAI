"""Unit tests for nikitai.subagents.trainer (NikitAI Trainer sub-agent config)."""

from __future__ import annotations

from unittest.mock import patch

from nikitai.subagents import trainer

TOKEN = "fake-token"


# ── trainer_agent_config ─────────────────────────────────────────────────────


def test_trainer_config_shape(monkeypatch):
    monkeypatch.setenv("NIKITAI_TRAINER_MODEL", "trainer-model")

    config = trainer.trainer_agent_config()

    assert set(config) == {
        "system_prompt",
        "tool_definitions",
        "tool_dispatcher",
        "confirmation_required_tools",
        "model",
    }
    assert config["confirmation_required_tools"] == set()  # read-only domain, nothing gated
    assert config["model"] == "trainer-model"
    assert config["tool_dispatcher"] is trainer._execute_trainer_tool
    tool_names = {t["name"] for t in config["tool_definitions"]}
    assert tool_names == {
        "get_recent_activities",
        "get_activity_details",
        "get_daily_summary",
        "get_sleep_data",
        "get_body_battery",
        "get_profile",
        "get_body_composition",
    }
    assert "NikitAI Trainer" in config["system_prompt"]


def test_trainer_config_model_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("NIKITAI_TRAINER_MODEL", raising=False)
    monkeypatch.setenv("NIKITAI_DEFAULT_MODEL", "shared-default")

    assert trainer.trainer_agent_config()["model"] == "shared-default"


# ── _execute_trainer_tool ────────────────────────────────────────────────────
# The Garmin client is mocked at the tools/garmin.py module level; no real API
# calls are made.


def test_execute_trainer_recent_activities_json():
    activities = [{"id": "1", "name": "Morning Run"}, {"id": "2", "name": "Slow Ride"}]
    with patch("nikitai.subagents.trainer.garmin.get_recent_activities", return_value=activities):
        result, refreshed = trainer._execute_trainer_tool(
            "get_recent_activities", {"limit": 2}, TOKEN
        )

    assert '"name": "Morning Run"' in result
    assert refreshed is None


def test_execute_trainer_activity_details_json():
    with patch(
        "nikitai.subagents.trainer.garmin.get_activity_details", return_value={"activityId": 123}
    ):
        result, refreshed = trainer._execute_trainer_tool(
            "get_activity_details", {"activity_id": "123"}, TOKEN
        )

    assert '"activityId": 123' in result
    assert refreshed is None


def test_execute_trainer_daily_summary_json():
    with patch("nikitai.subagents.trainer.garmin.get_daily_summary", return_value={"steps": 8000}):
        result, refreshed = trainer._execute_trainer_tool("get_daily_summary", {}, TOKEN)

    assert '"steps": 8000' in result
    assert refreshed is None


def test_execute_trainer_sleep_data_passes_date():
    with patch(
        "nikitai.subagents.trainer.garmin.get_sleep_data", return_value={"isSleepTime": True}
    ) as mock_sleep:
        result, refreshed = trainer._execute_trainer_tool(
            "get_sleep_data", {"date": "2026-08-01"}, TOKEN
        )

    mock_sleep.assert_called_once_with(date="2026-08-01")
    assert '"isSleepTime": true' in result
    assert refreshed is None


def test_execute_trainer_body_battery_json():
    with patch(
        "nikitai.subagents.trainer.garmin.get_body_battery", return_value={"bodyBatteryValues": []}
    ):
        result, refreshed = trainer._execute_trainer_tool("get_body_battery", {}, TOKEN)

    assert '"bodyBatteryValues": []' in result
    assert refreshed is None


def test_execute_trainer_profile_json():
    with patch(
        "nikitai.subagents.trainer.garmin.get_profile",
        return_value={"height": 1.83, "weight": 80.5},
    ) as mock_profile:
        result, refreshed = trainer._execute_trainer_tool("get_profile", {}, TOKEN)

    mock_profile.assert_called_once_with()
    assert '"height": 1.83' in result
    assert refreshed is None


def test_execute_trainer_body_composition_passes_date():
    with patch(
        "nikitai.subagents.trainer.garmin.get_body_composition",
        return_value={"dateWeight": 79.0},
    ) as mock_comp:
        result, refreshed = trainer._execute_trainer_tool(
            "get_body_composition", {"date": "2026-08-01"}, TOKEN
        )

    mock_comp.assert_called_once_with(date="2026-08-01")
    assert '"dateWeight": 79.0' in result
    assert refreshed is None


def test_execute_trainer_unknown_tool():
    result, refreshed = trainer._execute_trainer_tool("nuke_activity", {}, TOKEN)

    assert result == "Unknown tool: nuke_activity"
    assert refreshed is None


@patch(
    "nikitai.subagents.trainer.garmin.get_daily_summary",
    side_effect=RuntimeError(
        "GARMIN_CONNECT_USERNAME and GARMIN_CONNECT_PASSWORD must both be set"
    ),
)
def test_execute_trainer_tool_error_is_caught(mock_summary):
    result, refreshed = trainer._execute_trainer_tool("get_daily_summary", {}, TOKEN)

    assert (
        result == "Tool error: GARMIN_CONNECT_USERNAME and GARMIN_CONNECT_PASSWORD must both be set"
    )
    assert refreshed is None
