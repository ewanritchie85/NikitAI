"""App-level web authentication for the single-user web UI.

Configuration is read from the environment on every call so tests can flip it:

- ``NIKITAI_WEB_USERNAME`` — the single allowed username.
- ``NIKITAI_WEB_PASSWORD_HASH`` — an argon2id hash of the password, generated with
  ``python -m nikitai.web_auth <password>``. The plaintext password is never stored.
- ``NIKITAI_WEB_SECRET`` — secret signing the session cookie. When unset, a random
  per-process secret is generated, so every restart invalidates sessions.
- ``NIKITAI_WEB_SESSION_TTL`` — session lifetime in seconds (default 43200 = 12h).
- ``NIKITAI_WEB_HTTPS_ONLY`` — set to true behind a TLS-terminating proxy so the
  session cookie is marked ``Secure``.

If ``NIKITAI_WEB_PASSWORD_HASH`` is not configured the app fails closed: login is
enforced but no credential can ever succeed.
"""

from __future__ import annotations

import os
import secrets
import sys
import time
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

SESSION_TTL_DEFAULT = 43200
LOGIN_WINDOW = 900
LOGIN_MAX_ATTEMPTS = 5

_HASHER = PasswordHasher()

_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_LOCK = Lock()


def username() -> str | None:
    return os.environ.get("NIKITAI_WEB_USERNAME") or None


def password_hash() -> str | None:
    return os.environ.get("NIKITAI_WEB_PASSWORD_HASH") or None


def secret_key() -> str:
    return os.environ.get("NIKITAI_WEB_SECRET") or secrets.token_hex(32)


def session_ttl() -> int:
    try:
        return int(os.environ.get("NIKITAI_WEB_SESSION_TTL", SESSION_TTL_DEFAULT))
    except ValueError:
        return SESSION_TTL_DEFAULT


def https_only() -> bool:
    return os.environ.get("NIKITAI_WEB_HTTPS_ONLY", "").lower() in ("1", "true", "yes")


def is_configured() -> bool:
    return bool(username() and password_hash())


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password: str) -> bool:
    stored = password_hash()
    if stored is None:
        return False
    try:
        return _HASHER.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _prune(now: float) -> None:
    for ip in list(_LOGIN_ATTEMPTS):
        _LOGIN_ATTEMPTS[ip] = [t for t in _LOGIN_ATTEMPTS[ip] if now - t < LOGIN_WINDOW]
        if not _LOGIN_ATTEMPTS[ip]:
            del _LOGIN_ATTEMPTS[ip]


def login_blocked(ip: str) -> bool:
    with _LOGIN_LOCK:
        _prune(time.time())
        return len(_LOGIN_ATTEMPTS.get(ip, [])) >= LOGIN_MAX_ATTEMPTS


def record_failed_login(ip: str) -> None:
    with _LOGIN_LOCK:
        now = time.time()
        _prune(now)
        _LOGIN_ATTEMPTS.setdefault(ip, []).append(now)


def clear_failed_logins(ip: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.pop(ip, None)


def is_authenticated(request) -> bool:
    session = request.session
    if not session.get("authenticated"):
        return False
    expires = session.get("expires")
    return bool(expires) and time.time() < expires


def _main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m nikitai.web_auth <password>")
        raise SystemExit(2)
    print(hash_password(args[0]))


if __name__ == "__main__":
    _main()
