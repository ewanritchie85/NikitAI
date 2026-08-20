"""Unit tests for nikitai.tools.garmin (read-only Garmin Connect tools)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

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


def test_failed_login_429_persists_cooldown_across_processes(monkeypatch, tmp_path):
    monkeypatch.setenv("GARMIN_CONNECT_USERNAME", "user")
    monkeypatch.setenv("GARMIN_CONNECT_PASSWORD", "pass")
    monkeypatch.setattr(garmin, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(garmin, "RATE_LIMIT_COOLDOWN_SECONDS", 3600)
    monkeypatch.setattr(garmin, "_client", None)
    monkeypatch.setattr(garmin, "_auth_failed", None)

    client = MagicMock()
    client.login.side_effect = GarminConnectTooManyRequestsError("429 from Garmin")
    with patch("nikitai.tools.garmin.Garmin", return_value=client):
        with pytest.raises(GarminConnectTooManyRequestsError):
            garmin.get_daily_summary()

    # A 429 writes a sentinel into the session dir so a *future* process (fresh
    # module state) fails fast instead of re-hammering the login endpoints.
    sentinel = tmp_path / garmin._RATE_LIMIT_SENTINEL
    assert sentinel.exists()
    assert float(sentinel.read_text().strip()) > garmin.time.time()


def test_failed_login_cloudflare_403_persists_cooldown(monkeypatch, tmp_path):
    monkeypatch.setenv("GARMIN_CONNECT_USERNAME", "user")
    monkeypatch.setenv("GARMIN_CONNECT_PASSWORD", "pass")
    monkeypatch.setattr(garmin, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(garmin, "RATE_LIMIT_COOLDOWN_SECONDS", 3600)
    monkeypatch.setattr(garmin, "_client", None)
    monkeypatch.setattr(garmin, "_auth_failed", None)

    # Garmin's block can surface as a Cloudflare bot-challenge 403 (the error the
    # Trainer sub-agent reported) instead of a typed 429 — treat it the same way.
    client = MagicMock()
    client.login.side_effect = GarminConnectConnectionError(
        "Portal login: HTTP 403 (Cloudflare bot challenge)"
    )
    with patch("nikitai.tools.garmin.Garmin", return_value=client):
        with pytest.raises(GarminConnectConnectionError, match="403"):
            garmin.get_daily_summary()

    sentinel = tmp_path / garmin._RATE_LIMIT_SENTINEL
    assert sentinel.exists()
    assert float(sentinel.read_text().strip()) > garmin.time.time()


def test_failed_login_401_does_not_persist_cooldown(monkeypatch, tmp_path):
    monkeypatch.setenv("GARMIN_CONNECT_USERNAME", "user")
    monkeypatch.setenv("GARMIN_CONNECT_PASSWORD", "pass")
    monkeypatch.setattr(garmin, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(garmin, "RATE_LIMIT_COOLDOWN_SECONDS", 3600)
    monkeypatch.setattr(garmin, "_client", None)
    monkeypatch.setattr(garmin, "_auth_failed", None)

    # A 401 can mean genuinely bad credentials rather than a block — do NOT lock
    # the account out for a full cooldown on an ambiguous auth failure.
    client = MagicMock()
    client.login.side_effect = GarminConnectAuthenticationError(
        "401 Unauthorized (Invalid Username or Password)"
    )
    with patch("nikitai.tools.garmin.Garmin", return_value=client):
        with pytest.raises(GarminConnectAuthenticationError, match="401"):
            garmin.get_daily_summary()

    assert not (tmp_path / garmin._RATE_LIMIT_SENTINEL).exists()


def test_unexpired_cooldown_fails_fast_without_network(monkeypatch, tmp_path):
    monkeypatch.setenv("GARMIN_CONNECT_USERNAME", "user")
    monkeypatch.setenv("GARMIN_CONNECT_PASSWORD", "pass")
    monkeypatch.setattr(garmin, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(garmin, "_client", None)
    monkeypatch.setattr(garmin, "_auth_failed", None)

    future = garmin.time.time() + 600
    (tmp_path / garmin._RATE_LIMIT_SENTINEL).write_text(str(future))

    # No Garmin client is ever constructed and no login attempted while the
    # cooldown is still active — the sentinel alone short-circuits.
    with patch("nikitai.tools.garmin.Garmin") as mock_garmin:
        with pytest.raises(GarminConnectTooManyRequestsError, match="blocking SSO logins"):
            garmin.get_daily_summary()
        with pytest.raises(GarminConnectTooManyRequestsError, match="blocking SSO logins"):
            garmin.get_recent_activities()

    mock_garmin.assert_not_called()


def test_expired_cooldown_allows_login_and_clears_sentinel(monkeypatch, tmp_path):
    monkeypatch.setenv("GARMIN_CONNECT_USERNAME", "user")
    monkeypatch.setenv("GARMIN_CONNECT_PASSWORD", "pass")
    monkeypatch.setattr(garmin, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(garmin, "_client", None)
    monkeypatch.setattr(garmin, "_auth_failed", None)

    past = garmin.time.time() - 60
    (tmp_path / garmin._RATE_LIMIT_SENTINEL).write_text(str(past))

    client = MagicMock()
    client.get_stats.return_value = {"steps": 9000}
    with patch("nikitai.tools.garmin.Garmin", return_value=client):
        result = garmin.get_daily_summary()

    # Login proceeded and the sentinel was cleared so it can't gate future runs.
    client.login.assert_called_once_with(str(tmp_path))
    assert not (tmp_path / garmin._RATE_LIMIT_SENTINEL).exists()
    assert result == {"steps": 9000}


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


def test_get_profile_condenses_relevant_fields(monkeypatch):
    client = MagicMock()
    client.get_user_profile.return_value = {
        "height": 1.83,
        "weight": 80.5,
        "gender": "MALE",
        "birthDate": "1990-01-01",
        "unitSystem": "metric",
        "firstName": "Ewan",
        "displayName": "Ewan",
    }
    with patch.object(garmin, "_get_client", return_value=client):
        result = garmin.get_profile()

    client.get_user_profile.assert_called_once_with()
    assert result == {
        "height": 1.83,
        "weight": 80.5,
        "gender": "MALE",
        "birth_date": "1990-01-01",
        "unit_system": "metric",
    }


def test_get_profile_omits_missing_fields_and_non_dict(monkeypatch):
    client = MagicMock()
    client.get_user_profile.return_value = {"height": 1.8, "unitOfMeasure": "statute"}
    with patch.object(garmin, "_get_client", return_value=client):
        assert garmin.get_profile() == {"height": 1.8, "unit_of_measure": "statute"}

    client.get_user_profile.return_value = None
    with patch.object(garmin, "_get_client", return_value=client):
        assert garmin.get_profile() == {}


def test_get_body_composition_defaults_to_today(monkeypatch):
    client = MagicMock()
    client.get_body_composition.return_value = {"dateWeight": 80.5, "totalWeight": 80.5}
    with patch.object(garmin, "_get_client", return_value=client):
        result = garmin.get_body_composition()

    client.get_body_composition.assert_called_once_with(TODAY)
    assert result["dateWeight"] == 80.5


def test_get_body_composition_passes_explicit_date(monkeypatch):
    client = MagicMock()
    client.get_body_composition.return_value = {"dateWeight": 79.0}
    with patch.object(garmin, "_get_client", return_value=client):
        result = garmin.get_body_composition("2026-08-01")

    client.get_body_composition.assert_called_once_with("2026-08-01")
    assert result == {"dateWeight": 79.0}


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
