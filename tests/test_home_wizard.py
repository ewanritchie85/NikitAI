"""Unit tests for nikitai.subagents.home_wizard (NikitAI Home Wizard sub-agent config)."""

from __future__ import annotations

from unittest.mock import patch

from nikitai.subagents import home_wizard

TOKEN = "fake-token"


# ── home_wizard_agent_config ──────────────────────────────────────────────────


def test_home_wizard_config_shape(monkeypatch):
    monkeypatch.setenv("NIKITAI_HOME_WIZARD_MODEL", "home-wizard-model")

    config = home_wizard.home_wizard_agent_config()

    assert set(config) == {
        "system_prompt",
        "tool_definitions",
        "tool_dispatcher",
        "confirmation_required_tools",
        "model",
    }
    assert config["confirmation_required_tools"] == set()
    assert config["model"] == "home-wizard-model"
    assert config["tool_dispatcher"] is home_wizard._execute_home_wizard_tool
    tool_names = {t["name"] for t in config["tool_definitions"]}
    assert tool_names == {
        "list_lights",
        "get_light_state",
        "turn_on",
        "turn_off",
        "set_brightness",
    }
    assert "NikitAI Home Wizard" in config["system_prompt"]


def test_home_wizard_config_model_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("NIKITAI_HOME_WIZARD_MODEL", raising=False)

    assert home_wizard.home_wizard_agent_config()["model"] == "claude-haiku-4-5"


# ── _execute_home_wizard_tool ─────────────────────────────────────────────────


@patch("nikitai.subagents.home_wizard.wiz.list_lights")
def test_execute_home_wizard_list_lights(mock_list):
    mock_list.return_value = ["bedroom lamp", "desk light"]

    result, refreshed = home_wizard._execute_home_wizard_tool("list_lights", {}, TOKEN)

    mock_list.assert_called_once_with()
    assert "bedroom lamp" in result
    assert "desk light" in result
    assert refreshed is None


@patch("nikitai.subagents.home_wizard.wiz.get_light_state")
def test_execute_home_wizard_get_state(mock_get_state):
    mock_get_state.return_value = {"on": True, "brightness": 75, "rgb": [255, 200, 100]}

    result, refreshed = home_wizard._execute_home_wizard_tool(
        "get_light_state", {"name": "bedroom lamp"}, TOKEN
    )

    mock_get_state.assert_called_once_with(name="bedroom lamp")
    assert '"on": true' in result
    assert '"brightness": 75' in result
    assert refreshed is None


@patch("nikitai.subagents.home_wizard.wiz.turn_on")
def test_execute_home_wizard_turn_on(mock_turn_on):
    mock_turn_on.return_value = {"on": True, "brightness": 80, "rgb": [255, 0, 0]}

    result, refreshed = home_wizard._execute_home_wizard_tool(
        "turn_on", {"name": "bedroom lamp", "brightness": 80, "rgb": [255, 0, 0]}, TOKEN
    )

    mock_turn_on.assert_called_once_with(name="bedroom lamp", brightness=80, rgb=[255, 0, 0])
    assert '"on": true' in result
    assert refreshed is None


@patch("nikitai.subagents.home_wizard.wiz.turn_on")
def test_execute_home_wizard_turn_on_minimal(mock_turn_on):
    mock_turn_on.return_value = {"on": True, "brightness": 100, "rgb": [255, 255, 255]}

    result, refreshed = home_wizard._execute_home_wizard_tool(
        "turn_on", {"name": "bedroom lamp"}, TOKEN
    )

    mock_turn_on.assert_called_once_with(name="bedroom lamp")
    assert '"on": true' in result
    assert refreshed is None


@patch("nikitai.subagents.home_wizard.wiz.turn_off")
def test_execute_home_wizard_turn_off(mock_turn_off):
    mock_turn_off.return_value = {"on": False, "brightness": 0, "rgb": [0, 0, 0]}

    result, refreshed = home_wizard._execute_home_wizard_tool(
        "turn_off", {"name": "bedroom lamp"}, TOKEN
    )

    mock_turn_off.assert_called_once_with(name="bedroom lamp")
    assert '"on": false' in result
    assert refreshed is None


@patch("nikitai.subagents.home_wizard.wiz.set_brightness")
def test_execute_home_wizard_set_brightness(mock_set_brightness):
    mock_set_brightness.return_value = {"on": True, "brightness": 30, "rgb": [255, 255, 255]}

    result, refreshed = home_wizard._execute_home_wizard_tool(
        "set_brightness", {"name": "bedroom lamp", "level": 30}, TOKEN
    )

    mock_set_brightness.assert_called_once_with(name="bedroom lamp", level=30)
    assert '"brightness": 30' in result
    assert refreshed is None


def test_execute_home_wizard_unknown_tool():
    result, refreshed = home_wizard._execute_home_wizard_tool("nuke_lights", {}, TOKEN)

    assert result == "Unknown tool: nuke_lights"
    assert refreshed is None


@patch(
    "nikitai.subagents.home_wizard.wiz.get_light_state",
    side_effect=home_wizard.wiz.WizLightNotFoundError(
        "Light 'kitchen' not found in config. Available: bedroom lamp"
    ),
)
def test_execute_home_wizard_tool_error_name_not_found(mock_get_state):
    result, refreshed = home_wizard._execute_home_wizard_tool(
        "get_light_state", {"name": "kitchen"}, TOKEN
    )

    assert result == "Tool error: Light 'kitchen' not found in config. Available: bedroom lamp"
    assert refreshed is None


@patch(
    "nikitai.subagents.home_wizard.wiz.get_light_state",
    side_effect=home_wizard.wiz.WizConnectionError("Failed to reach bulb at 192.168.1.42: timeout"),
)
def test_execute_home_wizard_tool_error_connection(mock_get_state):
    result, refreshed = home_wizard._execute_home_wizard_tool(
        "get_light_state", {"name": "bedroom lamp"}, TOKEN
    )

    assert result == "Tool error: Failed to reach bulb at 192.168.1.42: timeout"
    assert refreshed is None


@patch(
    "nikitai.subagents.home_wizard.wiz.set_brightness",
    side_effect=ValueError("brightness must be 0-100"),
)
def test_execute_home_wizard_tool_error_value_error(mock_set_brightness):
    result, refreshed = home_wizard._execute_home_wizard_tool(
        "set_brightness", {"name": "bedroom lamp", "level": 150}, TOKEN
    )

    assert result == "Tool error: brightness must be 0-100"
    assert refreshed is None


@patch(
    "nikitai.subagents.home_wizard.wiz.get_light_state",
    side_effect=home_wizard.wiz.WizConfigError("NIKITAI_WIZ_LIGHTS_CONFIG is not set"),
)
def test_execute_home_wizard_tool_error_config(mock_get_state):
    result, refreshed = home_wizard._execute_home_wizard_tool(
        "get_light_state", {"name": "bedroom lamp"}, TOKEN
    )

    assert result == "Tool error: NIKITAI_WIZ_LIGHTS_CONFIG is not set"
    assert refreshed is None
