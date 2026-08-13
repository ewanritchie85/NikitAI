"""Garmin Connect health/fitness data tools for the NikitAI Trainer sub-agent.

Thin, read-only wrappers around Cyberjunky's ``garminconnect`` library (the
standard unofficial Python client for the Garmin Connect web API — it is NOT an
official Garmin API, and it uses real account credentials rather than an OAuth
app). Only reads are exposed here; there is no write-back to Garmin (no workout
logging, no weigh-ins) in this v1.

A module-level authenticated :class:`garminconnect.Garmin` client is created
lazily on first use from the ``GARMIN_CONNECT_USERNAME`` /
``GARMIN_CONNECT_PASSWORD`` environment variables. The Garmin session is
persisted to disk (via the library's built-in token store at
``~/.nikitai_garmin_session``) so later runs resume the session instead of
logging in from scratch — the same spirit as the MSAL token cache in
:mod:`nikitai.auth`. The client is created exactly once per process and shared
by every tool function, and authentication is attempted at most once: a failed
attempt is remembered so later calls fail fast instead of re-attempting a login.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from garminconnect import Garmin

# Session/token store, outside the repository (matches auth._TOKEN_CACHE_PATH).
SESSION_DIR = Path.home() / ".nikitai_garmin_session"

_client: Garmin | None = None
# A failed authentication (resume or fresh login) is cached here so subsequent
# calls re-raise it immediately rather than hammering Garmin with a new login on
# every tool call within the process.
_auth_failed: Exception | None = None


def _get_client() -> Garmin:
    """Return the module-level Garmin client, created lazily and exactly once.

    The client is built once per process on first use and cached in ``_client``,
    so all five tool functions share a single authenticated instance — never
    re-instantiated per call and never logged in again within the process.

    Authentication ordering (happens at most once): ``Garmin.login(SESSION_DIR)``
    first attempts to resume the cached session from ``~/.nikitai_garmin_session``
    via the library's built-in token store, refreshing the token if it is nearing
    expiry, and only falls back to a fresh username/password login when no valid
    cached session exists to resume (missing, corrupt, or missing-token store).
    If auth still fails, the error is cached in ``_auth_failed`` and re-raised on
    every later call so we never retry a login merely because one attempt failed.
    """
    global _client, _auth_failed
    if _client is not None:
        return _client
    if _auth_failed is not None:
        raise _auth_failed

    username = os.environ.get("GARMIN_CONNECT_USERNAME")
    password = os.environ.get("GARMIN_CONNECT_PASSWORD")
    if not username or not password:
        _auth_failed = RuntimeError(
            "GARMIN_CONNECT_USERNAME and GARMIN_CONNECT_PASSWORD must both be set "
            "to access Garmin Connect."
        )
        raise _auth_failed

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    client = Garmin(username, password)
    try:
        client.login(str(SESSION_DIR))
    except Exception as exc:  # noqa: BLE001
        _auth_failed = exc
        raise
    _client = client
    return _client


def _date_arg(date: str | None) -> str:
    """Normalize an optional date to ``%Y-%m-%d``, defaulting to today."""
    return date or datetime.now().strftime("%Y-%m-%d")


def _summarise_activity(activity: dict[str, Any]) -> dict[str, Any]:
    """Condense one raw Garmin activity into the fields a coach needs.

    Raw activity payloads are large; this keeps the model's token budget small
    while preserving the id so ``get_activity_details`` can fetch full detail.
    """
    activity_type = activity.get("activityType")
    if isinstance(activity_type, dict):
        activity_type = activity_type.get("typeKey") or activity_type.get("typeId")
    return {
        "id": activity.get("activityId"),
        "name": activity.get("activityName"),
        "type": activity_type,
        "start_time": activity.get("startTimeLocal"),
        "duration_seconds": activity.get("duration"),
        "distance_meters": activity.get("distance"),
        "calories": activity.get("calories"),
        "average_heart_rate": activity.get("averageHR"),
        "max_heart_rate": activity.get("maxHR"),
    }


def get_recent_activities(limit: int = 10) -> list[dict]:
    """Return the most recent ``limit`` workouts/activities as condensed dicts.

    Each entry carries the type, start time/date, duration, distance, and key
    stats (calories, heart rate), plus the activity ``id`` for
    :func:`get_activity_details`.
    """
    activities = _get_client().get_activities(0, limit)
    if not isinstance(activities, list):
        return []
    return [_summarise_activity(a) for a in activities if isinstance(a, dict)]


def get_activity_details(activity_id: str) -> dict:
    """Return the full Garmin record for a single activity by its id."""
    return _get_client().get_activity(activity_id)


def get_daily_summary(date: str | None = None) -> dict:
    """Return daily stats (steps, calories, resting heart rate, etc.) for ``date``."""
    return _get_client().get_stats(_date_arg(date))


def get_sleep_data(date: str | None = None) -> dict:
    """Return sleep stages and duration for ``date``."""
    return _get_client().get_sleep_data(_date_arg(date))


def get_body_battery(date: str | None = None) -> dict:
    """Return Garmin's body battery (energy) readings for ``date``.

    The API returns one entry per day; for a single date that is a one-element
    list, so the day's entry is unwrapped to keep the return type a flat dict.
    """
    data = _get_client().get_body_battery(_date_arg(date))
    if isinstance(data, list):
        if len(data) == 1:
            return data[0]
        return {"body_battery": data}
    return data
