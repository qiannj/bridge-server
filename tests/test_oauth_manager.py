from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_codex_oauth_manager_refreshes_token_from_auth_store(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BRIDGE_SERVER_CONFIG_DIR", str(tmp_path))

    from bridge_server.providers.oauth_manager import OAuthTokenManager

    (tmp_path / "auth.json").write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "tokens": {
                            "access_token": "expired-access",
                            "refresh_token": "refresh-123",
                        },
                        "last_refresh": "2026-04-23T12:00:00Z",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class DummyResponse:
        status_code = 200

        def json(self):
            return {"access_token": "fresh-access", "refresh_token": "fresh-refresh"}

        def raise_for_status(self):
            return None

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, data=None):
            assert url == "https://auth.openai.com/oauth/token"
            assert data["grant_type"] == "refresh_token"
            assert data["refresh_token"] == "refresh-123"
            return DummyResponse()

    import bridge_server.providers.oauth_manager as oauth_module

    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", DummyClient)

    manager = OAuthTokenManager(
        token_url="https://auth.openai.com/oauth/token",
        client_id="codex-client-id",
        provider="openai_codex",
        auth_store_key="openai",
    )

    token = asyncio.run(manager.get_token())

    assert token == "fresh-access"
    payload = json.loads((tmp_path / "auth.json").read_text(encoding="utf-8"))
    assert payload["providers"]["openai"]["tokens"]["refresh_token"] == "fresh-refresh"


def test_build_providers_config_accepts_codex_oauth_without_client_secret():
    from bridge_server import runtime

    providers = runtime._build_providers_config(
        {
            "providers": [
                {
                    "name": "openai",
                    "base_url": "https://chatgpt.com/backend-api/codex",
                    "auth_type": "oauth",
                    "oauth": {
                        "provider": "openai_codex",
                        "auth_store_key": "openai",
                        "token_url": "https://auth.openai.com/oauth/token",
                        "client_id": "codex-client-id",
                    },
                    "models": [{"id": "codex-mini-latest", "name": "codex-mini-latest"}],
                }
            ]
        }
    )

    assert len(providers) == 1
    assert providers[0].config["oauth"]["provider"] == "openai_codex"


def test_build_providers_config_repairs_legacy_codex_base_url():
    from bridge_server import runtime

    providers = runtime._build_providers_config(
        {
            "providers": [
                {
                    "name": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "auth_type": "oauth",
                    "oauth": {
                        "provider": "openai_codex",
                        "auth_store_key": "openai",
                        "token_url": "https://auth.openai.com/oauth/token",
                        "client_id": "codex-client-id",
                    },
                    "models": [{"id": "codex-mini-latest", "name": "codex-mini-latest"}],
                }
            ]
        }
    )

    assert providers[0].config["base_url"] == "https://chatgpt.com/backend-api/codex"


def test_build_providers_config_backfills_legacy_codex_auth_store_key():
    from bridge_server import runtime

    providers = runtime._build_providers_config(
        {
            "providers": [
                {
                    "name": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "auth_type": "oauth",
                    "oauth": {
                        "provider": "openai_codex",
                        "token_url": "https://auth.openai.com/oauth/token",
                        "client_id": "codex-client-id",
                    },
                    "models": [{"id": "codex-mini-latest", "name": "codex-mini-latest"}],
                }
            ]
        }
    )

    assert len(providers) == 1
    assert providers[0].config["oauth"]["auth_store_key"] == "openai"


def test_load_auth_store_migrates_legacy_yaml(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BRIDGE_SERVER_CONFIG_DIR", str(tmp_path))
    legacy_path = tmp_path / "auth.json"
    legacy_path.write_text(
        "providers:\n  openai:\n    provider: openai_codex\n    tokens:\n      refresh_token: refresh-123\n",
        encoding="utf-8",
    )

    from bridge_server.providers.oauth_manager import OAuthTokenManager

    manager = OAuthTokenManager(
        token_url="https://auth.openai.com/oauth/token",
        client_id="codex-client-id",
        provider="openai_codex",
        auth_store_key="openai",
    )

    payload = manager._load_auth_store()

    assert payload["providers"]["openai"]["tokens"]["refresh_token"] == "refresh-123"
    assert json.loads(legacy_path.read_text(encoding="utf-8"))["providers"]["openai"]["tokens"]["refresh_token"] == "refresh-123"


def test_oauth_manager_honors_legacy_bridge_config_dir(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("BRIDGE_SERVER_CONFIG_DIR", raising=False)
    monkeypatch.setenv("BRIDGE_CONFIG_DIR", str(tmp_path))

    from bridge_server.providers.oauth_manager import OAuthTokenManager

    manager = OAuthTokenManager(
        token_url="https://auth.openai.com/oauth/token",
        client_id="codex-client-id",
        provider="openai_codex",
        auth_store_key="openai",
    )

    assert manager._auth_store_path() == tmp_path / "auth.json"


def test_oauth_manager_legacy_dict_constructor_compatibility():
    from bridge_server.providers.oauth_manager import OAuthManager

    manager = OAuthManager(
        {
            "token_url": "https://auth.openai.com/oauth/token",
            "client_id": "codex-client-id",
            "provider": "openai_codex",
            "auth_store_key": "openai",
        }
    )

    assert manager.token_url == "https://auth.openai.com/oauth/token"
    assert manager.client_id == "codex-client-id"
    assert manager.provider == "openai_codex"


def test_save_auth_store_sets_private_permissions(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BRIDGE_SERVER_CONFIG_DIR", str(tmp_path))

    from bridge_server.providers.oauth_manager import OAuthTokenManager

    manager = OAuthTokenManager(
        token_url="https://auth.openai.com/oauth/token",
        client_id="codex-client-id",
        provider="openai_codex",
        auth_store_key="openai",
    )
    manager._save_auth_store({"providers": {"openai": {"tokens": {"refresh_token": "refresh-123"}}}})

    if os.name != "nt":
        assert (manager._auth_store_path().stat().st_mode & 0o777) == 0o600
