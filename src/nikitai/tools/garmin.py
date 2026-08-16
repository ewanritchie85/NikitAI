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

Since garminconnect 0.3.5, ``Garmin.login()`` is itself self-healing: it clears
stale auth state on entry, discards cached tokens the API rejects and falls
through to a fresh credential login, and raises explicit typed failures
(``GarminConnectAuthenticationError``, ``GarminConnectTooManyRequestsError``,
``GarminConnectConnectionError``) instead of generic exceptions. That behaviour
is fully internal to the single ``login()`` call we make here, so it does not
interact with the ``_auth_failed`` cache: it never re-enters this module and
never causes more than one ``login()`` invocation per process. Per-request 401s
after a successful login trigger only an in-library token refresh, not a
credential re-login.

Garmin also rate-limits SSO logins (HTTP 429) after too many credential
attempts. Community analysis (garminconnect issue #344) shows the block is tied
to the ``clientId`` + account email combination rather than purely the IP, that
*browser* login at connect.garmin.com keeps working while it is active, and that
every failed login attempt resets/extends the block timer — the only confirmed
recovery is roughly 24 hours of zero login attempts. Because ``_auth_failed``
only lives in memory, a *new* process (e.g. a restarted web session) would
immediately re-attempt the full login and extend the lockout. To break that
loop, a login failure that signals a Garmin-side block (HTTP 429, the Cloudflare
bot challenge 403, or a CAPTCHA prompt — not a plain 401, which can equally mean
genuinely bad credentials) is persisted to a sentinel file inside ``SESSION_DIR``
(``rate_limited_until``, an epoch timestamp); while it is unexpired,
``_get_client()`` fails fast with a clear error and makes no network calls. The
sentinel is cleared automatically on a successful login. The cooldown defaults
to 24 hours (Garmin's observed block window) and is tunable via
``NIKITAI_GARMIN_RATE_LIMIT_COOLDOWN`` (seconds; ``0`` disables the persisted
cooldown).
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

# Session/token store, outside the repository (matches auth._TOKEN_CACHE_PATH).
SESSION_DIR = Path.home() / ".nikitai_garmin_session"
# Sentinel file storing an epoch timestamp until which login is paused after a
# Garmin-side block (429 / Cloudflare 403 / CAPTCHA). Distinct from the library's
# token files.
_RATE_LIMIT_SENTINEL = "rate_limited_until"
# Garmin's observed SSO block window is ~24h, and every failed attempt extends
# it, so the persisted cooldown defaults to a full day.
RATE_LIMIT_COOLDOWN_SECONDS = int(os.environ.get("NIKITAI_GARMIN_RATE_LIMIT_COOLDOWN", "86400"))

_client: Garmin | None = None
# A failed authentication (resume or fresh login) is cached here so subsequent
# calls re-raise it immediately rather than hammering Garmin with a new login on
# every tool call within the process.
_auth_failed: Exception | None = None


def _rate_limited_until() -> float:
    """Return the epoch time after which a login attempt is allowed again.

    ``0.0`` means no persisted rate limit (sentinel missing, unreadable, or a
    non-numeric value). This is a *best effort* read: a corrupt sentinel simply
    falls back to allowing a login attempt.
    """
    try:
        return float((SESSION_DIR / _RATE_LIMIT_SENTINEL).read_text().strip())
    except (OSError, ValueError):
        return 0.0


def _write_rate_limit() -> None:
    """Persist a rate-limit cooldown so later processes fail fast."""
    if RATE_LIMIT_COOLDOWN_SECONDS <= 0:
        return
    SESSION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    (SESSION_DIR / _RATE_LIMIT_SENTINEL).write_text(str(time.time() + RATE_LIMIT_COOLDOWN_SECONDS))


def _clear_rate_limit() -> None:
    """Remove any persisted rate-limit sentinel after a successful login."""
    try:
        (SESSION_DIR / _RATE_LIMIT_SENTINEL).unlink()
    except OSError:
        pass


def _is_block_signal(exc: Exception) -> bool:
    """Return True when a login failure indicates a Garmin-side block worth a cooldown.

    Garmin's SSO block surfaces differently per strategy, so we persist the
    sentinel on any of the unambiguous block signals rather than only a typed
    429: the HTTP 429 itself, the Cloudflare bot-challenge 403, or a CAPTCHA
    prompt. A plain 401 (``GarminConnectAuthenticationError``) is deliberately
    *not* treated as a block — it can equally mean genuinely bad credentials,
    and locking the account out for 24h on a typo'd password would be worse.
    """
    if isinstance(exc, GarminConnectTooManyRequestsError):
        return True
    if isinstance(exc, GarminConnectAuthenticationError):
        return False
    msg = str(exc).lower()
    return any(
        hint in msg
        for hint in (
            "403",
            "cloudflare",
            "bot challenge",
            "captcha",
        )
    )


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
    On garminconnect 0.3.5+, ``login()`` also self-heals internally — it discards
    cached tokens the API rejects and retries with credentials within the same
    call — so reaching an exception here means the whole resume + credential
    chain failed. If auth fails, the error is cached in ``_auth_failed`` and
    re-raised on every later call so we never retry a login merely because one
    attempt failed; the library's own retries never escape the single
    ``login()`` call and therefore never undermine that once-per-process
    guarantee.
    """
    global _client, _auth_failed
    if _client is not None:
        return _client
    if _auth_failed is not None:
        raise _auth_failed

    # Fail fast (no network) while a Garmin-side block (429 / Cloudflare 403 /
    # CAPTCHA) is still in effect. Without this, every new process would
    # immediately re-attempt the full 5-strategy login and extend the lockout.
    until = _rate_limited_until()
    if until > time.time():
        hours = max(1, round((until - time.time()) / 3600))
        _auth_failed = GarminConnectTooManyRequestsError(
            "Garmin is blocking SSO logins for this account after too many "
            "login attempts. Login is paused for ~"
            f"{hours} hour(s) and the block timer is NOT being extended — "
            "any login attempt would only reset the cooldown. Please wait. "
            "You can still sign in via the web at connect.garmin.com."
        )
        raise _auth_failed

    username = os.environ.get("GARMIN_CONNECT_USERNAME")
    password = os.environ.get("GARMIN_CONNECT_PASSWORD")
    if not username or not password:
        _auth_failed = RuntimeError(
            "GARMIN_CONNECT_USERNAME and GARMIN_CONNECT_PASSWORD must both be set "
            "to access Garmin Connect."
        )
        raise _auth_failed

    SESSION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    client = Garmin(username, password)
    try:
        client.login(str(SESSION_DIR))
    except GarminConnectTooManyRequestsError as exc:
        _write_rate_limit()
        _auth_failed = exc
        raise
    except GarminConnectConnectionError as exc:
        if _is_block_signal(exc):
            _write_rate_limit()
        _auth_failed = exc
        raise
    except Exception as exc:  # noqa: BLE001
        _auth_failed = exc
        raise
    _clear_rate_limit()
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
