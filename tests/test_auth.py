"""Unit tests for nikitai.auth."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nikitai import auth


@pytest.fixture(autouse=True)
def token_cache_path(tmp_path, monkeypatch):
    """Redirect the token cache to a temp file so tests never touch the real home dir."""
    cache_path = tmp_path / ".nikitai_token_cache.json"
    monkeypatch.setattr(auth, "_TOKEN_CACHE_PATH", cache_path)
    return cache_path


@pytest.fixture(autouse=True)
def azure_client_id(monkeypatch):
    monkeypatch.setenv("AZURE_CLIENT_ID", "test-client-id")


# ── _load_cache / _save_cache ───────────────────────────────────────────────


def test_load_cache_returns_empty_cache_when_file_missing(token_cache_path):
    assert not token_cache_path.exists()

    cache = auth._load_cache()

    assert isinstance(cache, auth.msal.SerializableTokenCache)


def test_load_cache_deserializes_existing_file(token_cache_path):
    seed = auth.msal.SerializableTokenCache()
    token_cache_path.write_text(seed.serialize())

    with patch.object(auth.msal.SerializableTokenCache, "deserialize") as mock_deserialize:
        auth._load_cache()
        mock_deserialize.assert_called_once_with(seed.serialize())


def test_save_cache_writes_when_state_changed(token_cache_path):
    cache = MagicMock()
    cache.has_state_changed = True
    cache.serialize.return_value = "serialized-data"

    auth._save_cache(cache)

    assert token_cache_path.read_text() == "serialized-data"


def test_save_cache_does_not_write_when_state_unchanged(token_cache_path):
    cache = MagicMock()
    cache.has_state_changed = False

    auth._save_cache(cache)

    assert not token_cache_path.exists()


# ── get_access_token ─────────────────────────────────────────────────────────


def test_get_access_token_missing_client_id_raises(monkeypatch):
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)

    with pytest.raises(KeyError):
        auth.get_access_token()


@patch("nikitai.auth.msal.PublicClientApplication")
def test_get_access_token_uses_silent_flow_when_account_cached(mock_app_cls):
    mock_app = MagicMock()
    mock_app.get_accounts.return_value = [{"username": "user@example.com"}]
    mock_app.acquire_token_silent.return_value = {"access_token": "silent-token"}
    mock_app_cls.return_value = mock_app

    token = auth.get_access_token()

    assert token == "silent-token"
    mock_app.acquire_token_silent.assert_called_once_with(
        auth.SCOPES, account={"username": "user@example.com"}
    )
    mock_app.initiate_device_flow.assert_not_called()


@patch("nikitai.auth.msal.PublicClientApplication")
def test_get_access_token_falls_back_to_device_flow_when_silent_fails(mock_app_cls):
    mock_app = MagicMock()
    mock_app.get_accounts.return_value = [{"username": "user@example.com"}]
    mock_app.acquire_token_silent.return_value = None
    mock_app.initiate_device_flow.return_value = {
        "user_code": "ABC123",
        "message": "Go to https://microsoft.com/devicelogin and enter code ABC123",
    }
    mock_app.acquire_token_by_device_flow.return_value = {"access_token": "device-token"}
    mock_app_cls.return_value = mock_app

    token = auth.get_access_token()

    assert token == "device-token"


@patch("nikitai.auth.msal.PublicClientApplication")
def test_get_access_token_no_accounts_uses_device_flow(mock_app_cls):
    mock_app = MagicMock()
    mock_app.get_accounts.return_value = []
    mock_app.initiate_device_flow.return_value = {
        "user_code": "XYZ789",
        "message": "Go to https://microsoft.com/devicelogin and enter code XYZ789",
    }
    mock_app.acquire_token_by_device_flow.return_value = {"access_token": "device-token-2"}
    mock_app_cls.return_value = mock_app

    token = auth.get_access_token()

    assert token == "device-token-2"
    mock_app.acquire_token_silent.assert_not_called()


@patch("nikitai.auth.msal.PublicClientApplication")
def test_get_access_token_raises_when_device_flow_creation_fails(mock_app_cls):
    mock_app = MagicMock()
    mock_app.get_accounts.return_value = []
    mock_app.initiate_device_flow.return_value = {"error": "bad_request"}
    mock_app_cls.return_value = mock_app

    with pytest.raises(RuntimeError, match="Failed to create device flow"):
        auth.get_access_token()


@patch("nikitai.auth.msal.PublicClientApplication")
def test_get_access_token_raises_when_device_flow_auth_fails(mock_app_cls):
    mock_app = MagicMock()
    mock_app.get_accounts.return_value = []
    mock_app.initiate_device_flow.return_value = {
        "user_code": "ABC123",
        "message": "Go to https://microsoft.com/devicelogin and enter code ABC123",
    }
    mock_app.acquire_token_by_device_flow.return_value = {"error_description": "user declined"}
    mock_app_cls.return_value = mock_app

    with pytest.raises(RuntimeError, match="user declined"):
        auth.get_access_token()
