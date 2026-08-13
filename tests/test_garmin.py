"""Unit tests for nikitai.tools.garmin (read-only Garmin Connect tools)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from nikitai.tools import garmin

TODAY = datetime.now().strftime("%Y-%m-%d")


# ── _get_client (lazy authentication + disk session) ─────────────────────────


def test_get_client_raises_without_credentials(monkeypatch):
    monkeypatch.delenv("GARMIN_CONNECT_USERNAME", raising=False)
    monkeypatch.delenv("GARMIN_CONNECT_PASSWORD", raising=False)
    monkeypatch.setattr(garmin, "_client", None)
    monkeypatch.setattr(garmin, "_auth_failed", None)

    with pytest.raises(RuntimeError, match="GARMIN_CONNECT_USERNAME and GARMIN_CONNECT_PASSWORD"):
        garmin._get_client()


def test_get_client_raises_if_only_username_set(monkeypatch):
    monkeypatch.setenv("GARMIN_CONNECT_USERNAME", "user")
    monkeypatch.delenv("GARMIN_CONNECT_PASSWORD", raising=False)
    monkeypatch.setattr(garmin, "_client", None)
    monkeypatch.setattr(garmin, "_auth_failed", None)

    with pytest.raises(RuntimeError, match="must both be set"):
        garmin._get_client()


def test_get_client_logs_in_lazily_and_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("GARMIN_CONNECT_USERNAME", "user")
    monkeypatch.setenv("GARMIN_CONNECT_PASSWORD", "pass")
    monkeypatch.setattr(garmin, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(garmin, "_client", None)
    monkeypatch.setattr(garmin, "_auth_failed", None)

    client = MagicMock()
    with patch("nikitai.tools.garmin.Garmin", return_value=client) as mock_garmin:
        first = garmin._get_client()
        second = garmin._get_client()

    # Built once with the configured credentials and logged in against the
    # on-disk session dir (so tokens are resumed/saved between runs)…
    mock_garmin.assert_called_once_with("user", "pass")
    client.login.assert_called_once_with(str(tmp_path))
    # …and cached: the second call reuses the same instance with no new login.
    assert first is client
    assert second is client


def test_second_tool_call_does_not_trigger_second_login(monkeypatch, tmp_path):
    monkeypatch.setenv("GARMIN_CONNECT_USERNAME", "user")
    monkeypatch.setenv("GARMIN_CONNECT_PASSWORD", "pass")
    monkeypatch.setattr(garmin, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(garmin, "_client", None)
    monkeypatch.setattr(garmin, "_auth_failed", None)

    client = MagicMock()
    client.get_activities.return_value = []
    client.get_stats.return_value = {"steps": 1}
    with patch("nikitai.tools.garmin.Garmin", return_value=client) as mock_garmin:
        garmin.get_recent_activities()
        garmin.get_daily_summary()

    # One shared client built once with a single login/resume attempt for the
    # whole process — the second tool call reuses it, not re-authenticates.
    mock_garmin.assert_called_once_with("user", "pass")
    client.login.assert_called_once_with(str(tmp_path))
    client.get_activities.assert_called_once_with(0, 10)
    client.get_stats.assert_called_once_with(TODAY)


def test_failed_login_is_cached_not_retried_per_call(monkeypatch, tmp_path):
    monkeypatch.setenv("GARMIN_CONNECT_USERNAME", "user")
    monkeypatch.setenv("GARMIN_CONNECT_PASSWORD", "pass")
    monkeypatch.setattr(garmin, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(garmin, "_client", None)
    monkeypatch.setattr(garmin, "_auth_failed", None)

    client = MagicMock()
    client.login.side_effect = RuntimeError("network down")
    with patch("nikitai.tools.garmin.Garmin", return_value=client) as mock_garmin:
        with pytest.raises(RuntimeError, match="network down"):
            garmin.get_daily_summary()
        # A second tool call after the failed attempt fails fast with the same
        # error and does NOT re-attempt the login/resume dance.
        with pytest.raises(RuntimeError, match="network down"):
            garmin.get_body_battery()

    mock_garmin.assert_called_once()
    client.login.assert_called_once()


# ── get_recent_activities ────────────────────────────────────────────────────


def test_get_recent_activities_summarises_activity(monkeypatch):
    client = MagicMock()
    client.get_activities.return_value = [
        {
            "activityId": 42,
            "activityName": "Easy Run",
            "activityType": {"typeKey": "running", "typeId": 1},
            "startTimeLocal": "2026-08-12 07:30:00",
            "duration": 1800,
            "distance": 5000,
            "calories": 300,
            "averageHR": 140,
            "maxHR": 165,
            "unneededNoise": "not in summary",
        }
    ]
    with patch.object(garmin, "_get_client", return_value=client):
        result = garmin.get_recent_activities(limit=3)

    client.get_activities.assert_called_once_with(0, 3)
    assert result == [
        {
            "id": 42,
            "name": "Easy Run",
            "type": "running",
            "start_time": "2026-08-12 07:30:00",
            "duration_seconds": 1800,
            "distance_meters": 5000,
            "calories": 300,
            "average_heart_rate": 140,
            "max_heart_rate": 165,
        }
    ]


def test_get_recent_activities_returns_empty_on_non_list(monkeypatch):
    client = MagicMock()
    client.get_activities.return_value = None
    with patch.object(garmin, "_get_client", return_value=client):
        assert garmin.get_recent_activities() == []


# ── get_activity_details / get_daily_summary / get_sleep_data ────────────────


def test_get_activity_details_passes_id(monkeypatch):
    client = MagicMock()
    client.get_activity.return_value = {"activityId": 42}
    with patch.object(garmin, "_get_client", return_value=client):
        result = garmin.get_activity_details("42")

    client.get_activity.assert_called_once_with("42")
    assert result == {"activityId": 42}


def test_get_daily_summary_defaults_to_today(monkeypatch):
    client = MagicMock()
    client.get_stats.return_value = {"steps": 8000}
    with patch.object(garmin, "_get_client", return_value=client):
        result = garmin.get_daily_summary()

    client.get_stats.assert_called_once_with(TODAY)
    assert result == {"steps": 8000}


def test_get_sleep_data_passes_explicit_date(monkeypatch):
    client = MagicMock()
    client.get_sleep_data.return_value = {"sleepTimeInSeconds": 28800}
    with patch.object(garmin, "_get_client", return_value=client):
        result = garmin.get_sleep_data("2026-08-01")

    client.get_sleep_data.assert_called_once_with("2026-08-01")
    assert result == {"sleepTimeInSeconds": 28800}


# ── get_body_battery ─────────────────────────────────────────────────────────


def test_get_body_battery_unwraps_single_day(monkeypatch):
    client = MagicMock()
    day = {"bodyBatteryValues": [{"date": "2026-08-12"}]}
    client.get_body_battery.return_value = [day]
    with patch.object(garmin, "_get_client", return_value=client):
        result = garmin.get_body_battery("2026-08-12")

    client.get_body_battery.assert_called_once_with("2026-08-12")
    assert result == day


def test_get_body_battery_wraps_multiple_days(monkeypatch):
    client = MagicMock()
    client.get_body_battery.return_value = [{"day": 1}, {"day": 2}]
    with patch.object(garmin, "_get_client", return_value=client):
        result = garmin.get_body_battery("2026-08-12")

    assert result == {"body_battery": [{"day": 1}, {"day": 2}]}
