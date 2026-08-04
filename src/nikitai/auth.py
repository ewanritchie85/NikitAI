"""Microsoft Graph authentication via MSAL device-code flow."""

import json
import os
from pathlib import Path

import msal

_TOKEN_CACHE_PATH = Path.home() / ".nikitai_token_cache.json"

SCOPES = [
    "Mail.Read",
    "Mail.Send",
    "Calendars.ReadWrite",
]


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if _TOKEN_CACHE_PATH.exists():
        cache.deserialize(_TOKEN_CACHE_PATH.read_text())
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        _TOKEN_CACHE_PATH.write_text(cache.serialize())


def get_access_token() -> str:
    client_id = os.environ["AZURE_CLIENT_ID"]
    tenant_id = os.environ.get("AZURE_TENANT_ID", "consumers")

    cache = _load_cache()
    app = msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )

    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(cache)
            return result["access_token"]

    # Device-code flow — prints a URL + code the user visits once
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Failed to create device flow: {json.dumps(flow, indent=2)}")

    print(flow["message"])  # e.g. "Go to https://microsoft.com/devicelogin and enter code XXXXXXXX"
    result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise RuntimeError(f"Authentication failed: {result.get('error_description')}")

    _save_cache(cache)
    return result["access_token"]
