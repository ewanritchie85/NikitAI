"""Unit tests for nikitai.tools.wiz (WiZ smart lighting tools)."""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

from nikitai.tools import wiz

# ── _load_config ──────────────────────────────────────────────────────────────


def test_load_config_missing_env_var(monkeypatch):
    monkeypatch.delenv(wiz.CONFIG_ENV_VAR, raising=False)

    with pytest.raises(wiz.WizConfigError, match="is not set"):
        wiz._load_config()


def test_load_config_file_not_found(monkeypatch):
    monkeypatch.setenv(wiz.CONFIG_ENV_VAR, "/nonexistent/path.json")

    with pytest.raises(wiz.WizConfigError, match="not found"):
        wiz._load_config()


def test_load_config_malformed_json(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("not valid json")
        path = f.name
    try:
        monkeypatch.setenv(wiz.CONFIG_ENV_VAR, path)
        with pytest.raises(wiz.WizConfigError, match="not valid JSON"):
            wiz._load_config()
    finally:
        os.unlink(path)


def test_load_config_not_a_dict(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write('["not", "a", "dict"]')
        path = f.name
    try:
        monkeypatch.setenv(wiz.CONFIG_ENV_VAR, path)
        with pytest.raises(wiz.WizConfigError, match="must be a JSON object"):
            wiz._load_config()
    finally:
        os.unlink(path)


def test_load_config_invalid_value_types(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write('{"light": 123}')
        path = f.name
    try:
        monkeypatch.setenv(wiz.CONFIG_ENV_VAR, path)
        with pytest.raises(wiz.WizConfigError, match="must map string names to string IPs"):
            wiz._load_config()
    finally:
        os.unlink(path)


def test_load_config_success(monkeypatch):
    config_data = {"bedroom lamp": "192.168.1.42", "desk light": "192.168.1.43"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_data, f)
        path = f.name
    try:
        monkeypatch.setenv(wiz.CONFIG_ENV_VAR, path)
        result = wiz._load_config()
        assert result == config_data
    finally:
        os.unlink(path)


# ── _get_ip ───────────────────────────────────────────────────────────────────


def test_get_ip_success():
    config = {"bedroom lamp": "192.168.1.42"}
    assert wiz._get_ip("bedroom lamp", config) == "192.168.1.42"


def test_get_ip_not_found():
    config = {"bedroom lamp": "192.168.1.42"}
    with pytest.raises(wiz.WizLightNotFoundError, match="not found in config"):
        wiz._get_ip("kitchen light", config)


# ── list_lights ───────────────────────────────────────────────────────────────


def test_list_lights(monkeypatch):
    config_data = {"bedroom lamp": "192.168.1.42", "desk light": "192.168.1.43"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_data, f)
        path = f.name
    try:
        monkeypatch.setenv(wiz.CONFIG_ENV_VAR, path)
        result = wiz.list_lights()
        assert result == ["bedroom lamp", "desk light"]
    finally:
        os.unlink(path)


# ── Network-touching tools (mocked) ───────────────────────────────────────────


class MockState:
    def __init__(self, on=True, brightness=50, rgb=(255, 128, 0)):
        self._on = on
        self._brightness = brightness
        self._rgb = rgb

    def get_state(self):
        return self._on

    def get_brightness(self):
        return self._brightness

    def get_rgb(self):
        return self._rgb


@patch("nikitai.tools.wiz.wizlight")
def test_get_light_state(mock_wizlight_class, monkeypatch):
    config_data = {"bedroom lamp": "192.168.1.42"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_data, f)
        path = f.name
    try:
        monkeypatch.setenv(wiz.CONFIG_ENV_VAR, path)

        mock_bulb = AsyncMock()
        mock_bulb.updateState.return_value = MockState(on=True, brightness=75, rgb=(255, 200, 100))
        mock_wizlight_class.return_value = mock_bulb

        result = wiz.get_light_state("bedroom lamp")

        assert result["on"] is True
        assert result["brightness"] == 75
        assert result["rgb"] == [255, 200, 100]
        mock_bulb.async_close.assert_awaited_once()
    finally:
        os.unlink(path)


@patch("nikitai.tools.wiz.wizlight")
def test_turn_on_with_brightness_and_rgb(mock_wizlight_class, monkeypatch):
    config_data = {"bedroom lamp": "192.168.1.42"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_data, f)
        path = f.name
    try:
        monkeypatch.setenv(wiz.CONFIG_ENV_VAR, path)

        mock_bulb = AsyncMock()
        mock_bulb.updateState.return_value = MockState(on=True, brightness=80, rgb=(255, 0, 0))
        mock_wizlight_class.return_value = mock_bulb

        result = wiz.turn_on("bedroom lamp", brightness=80, rgb=[255, 0, 0])

        assert result["on"] is True
        assert result["brightness"] == 80
        assert result["rgb"] == [255, 0, 0]
        mock_bulb.turn_on.assert_awaited_once()
        mock_bulb.async_close.assert_awaited_once()
    finally:
        os.unlink(path)


@patch("nikitai.tools.wiz.wizlight")
def test_turn_on_minimal(mock_wizlight_class, monkeypatch):
    config_data = {"bedroom lamp": "192.168.1.42"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_data, f)
        path = f.name
    try:
        monkeypatch.setenv(wiz.CONFIG_ENV_VAR, path)

        mock_bulb = AsyncMock()
        mock_bulb.updateState.return_value = MockState(on=True, brightness=100, rgb=(255, 255, 255))
        mock_wizlight_class.return_value = mock_bulb

        result = wiz.turn_on("bedroom lamp")

        assert result["on"] is True
        mock_bulb.turn_on.assert_awaited_once()
        mock_bulb.async_close.assert_awaited_once()
    finally:
        os.unlink(path)


@patch("nikitai.tools.wiz.wizlight")
def test_turn_off(mock_wizlight_class, monkeypatch):
    config_data = {"bedroom lamp": "192.168.1.42"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_data, f)
        path = f.name
    try:
        monkeypatch.setenv(wiz.CONFIG_ENV_VAR, path)

        mock_bulb = AsyncMock()
        mock_bulb.updateState.return_value = MockState(on=False, brightness=0, rgb=(0, 0, 0))
        mock_wizlight_class.return_value = mock_bulb

        result = wiz.turn_off("bedroom lamp")

        assert result["on"] is False
        mock_bulb.turn_off.assert_awaited_once()
        mock_bulb.async_close.assert_awaited_once()
    finally:
        os.unlink(path)


@patch("nikitai.tools.wiz.wizlight")
def test_set_brightness(mock_wizlight_class, monkeypatch):
    config_data = {"bedroom lamp": "192.168.1.42"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_data, f)
        path = f.name
    try:
        monkeypatch.setenv(wiz.CONFIG_ENV_VAR, path)

        mock_bulb = AsyncMock()
        mock_bulb.updateState.return_value = MockState(on=True, brightness=30, rgb=(255, 255, 255))
        mock_wizlight_class.return_value = mock_bulb

        result = wiz.set_brightness("bedroom lamp", 30)

        assert result["brightness"] == 30
        mock_bulb.turn_on.assert_awaited_once()
        mock_bulb.async_close.assert_awaited_once()
    finally:
        os.unlink(path)


# ── Error handling for network-touching tools ─────────────────────────────────


@patch("nikitai.tools.wiz.wizlight")
def test_get_light_state_connection_error(mock_wizlight_class, monkeypatch):
    config_data = {"bedroom lamp": "192.168.1.42"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_data, f)
        path = f.name
    try:
        monkeypatch.setenv(wiz.CONFIG_ENV_VAR, path)

        mock_bulb = AsyncMock()
        mock_bulb.updateState.side_effect = Exception("timeout")
        mock_wizlight_class.return_value = mock_bulb

        with pytest.raises(wiz.WizConnectionError, match="Failed to reach bulb"):
            wiz.get_light_state("bedroom lamp")
    finally:
        os.unlink(path)


def test_get_light_state_name_not_found(monkeypatch):
    config_data = {"bedroom lamp": "192.168.1.42"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_data, f)
        path = f.name
    try:
        monkeypatch.setenv(wiz.CONFIG_ENV_VAR, path)

        with pytest.raises(wiz.WizLightNotFoundError, match="kitchen light"):
            wiz.get_light_state("kitchen light")
    finally:
        os.unlink(path)


def test_set_brightness_invalid_level(monkeypatch):
    config_data = {"bedroom lamp": "192.168.1.42"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_data, f)
        path = f.name
    try:
        monkeypatch.setenv(wiz.CONFIG_ENV_VAR, path)

        with pytest.raises(ValueError, match="brightness must be 0-100"):
            wiz.set_brightness("bedroom lamp", 150)
    finally:
        os.unlink(path)
