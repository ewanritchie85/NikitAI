"""Unit tests for nikitai.subagents.platform_nerd (Platform Nerd sub-agent config)."""

from __future__ import annotations

from unittest.mock import patch

from nikitai.subagents import platform_nerd

TOKEN = "fake-token"


# ── platform_nerd_agent_config ────────────────────────────────────────────────


def test_platform_nerd_config_shape(monkeypatch):
    monkeypatch.setenv("NIKITAI_PLATFORM_NERD_MODEL", "nerd-model")

    config = platform_nerd.platform_nerd_agent_config()

    assert set(config) == {
        "system_prompt",
        "tool_definitions",
        "tool_dispatcher",
        "confirmation_required_tools",
        "model",
    }
    assert config["confirmation_required_tools"] == {"append_to_log"}
    assert config["model"] == "nerd-model"
    assert config["tool_dispatcher"] is platform_nerd._execute_platform_nerd_tool
    tool_names = {t["name"] for t in config["tool_definitions"]}
    assert tool_names == {"list_log_files", "read_log_file", "append_to_log"}
    assert "NikitAI Platform Nerd" in config["system_prompt"]


def test_platform_nerd_config_model_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("NIKITAI_PLATFORM_NERD_MODEL", raising=False)
    monkeypatch.setenv("NIKITAI_DEFAULT_MODEL", "shared-default")

    assert platform_nerd.platform_nerd_agent_config()["model"] == "shared-default"


# ── _execute_platform_nerd_tool ───────────────────────────────────────────────


@patch("nikitai.subagents.platform_nerd.logs.read_log_file")
def test_execute_platform_nerd_read(mock_read):
    mock_read.return_value = "line1\nline2"

    result, refreshed = platform_nerd._execute_platform_nerd_tool(
        "read_log_file", {"filename": "router.txt"}, TOKEN
    )

    mock_read.assert_called_once_with(filename="router.txt")
    assert result == "line1\nline2"  # str results pass through unwrapped
    assert refreshed is None


@patch("nikitai.subagents.platform_nerd.logs.append_to_log")
def test_execute_platform_nerd_append_returns_json(mock_append):
    mock_append.return_value = {"filename": "router.txt", "lines_appended": 1}

    result, refreshed = platform_nerd._execute_platform_nerd_tool(
        "append_to_log", {"filename": "router.txt", "content": "x"}, TOKEN
    )

    mock_append.assert_called_once_with(filename="router.txt", content="x")
    assert '"filename": "router.txt"' in result
    assert refreshed is None


@patch("nikitai.subagents.platform_nerd.logs.list_log_files")
def test_execute_platform_nerd_list(mock_list):
    mock_list.return_value = ["router.txt", "pi.txt"]

    result, refreshed = platform_nerd._execute_platform_nerd_tool("list_log_files", {}, TOKEN)

    mock_list.assert_called_once_with()
    assert "router.txt" in result
    assert refreshed is None


def test_execute_platform_nerd_unknown_tool():
    result, refreshed = platform_nerd._execute_platform_nerd_tool("nuke_everything", {}, TOKEN)

    assert result == "Unknown tool: nuke_everything"
    assert refreshed is None


@patch(
    "nikitai.subagents.platform_nerd.logs.read_log_file",
    side_effect=ValueError("outside the notes directory"),
)
def test_execute_platform_nerd_tool_error_is_caught(mock_read):
    result, refreshed = platform_nerd._execute_platform_nerd_tool(
        "read_log_file", {"filename": "../evil.txt"}, TOKEN
    )

    assert result == "Tool error: outside the notes directory"
    assert refreshed is None
