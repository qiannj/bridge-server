from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import REPO_ROOT, load_module

admin_api = load_module("bridge_admin_benchmark_oauth", REPO_ROOT / "src" / "bridge_server" / "admin_api.py")


@pytest.fixture()
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(admin_api, "_get_config_dir", lambda: tmp_path)
    return tmp_path


class DummyBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, func, *args):
        self.calls.append((func, args))


def test_start_benchmark_repairs_legacy_codex_base_url(config_dir: Path, monkeypatch: pytest.MonkeyPatch):
    (config_dir / "config.yaml").write_text(
        yaml.safe_dump(
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
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    import bridge_server.providers.oauth_manager as oauth_module

    class DummyManager:
        def __init__(self, cfg):
            assert cfg["provider"] == "openai_codex"
            assert cfg["auth_store_key"] == "openai"

        async def get_token(self):
            return "oauth-token"

    monkeypatch.setattr(oauth_module, "OAuthManager", DummyManager)

    background = DummyBackgroundTasks()
    req = admin_api.BenchmarkStartRequest(provider_name="openai")

    result = asyncio.run(admin_api.start_benchmark(req, background))

    assert result["estimated_calls"] > 0
    assert len(background.calls) == 1
    _, args = background.calls[0]
    _, models_tuples, _ = args
    assert models_tuples[0][2] == "https://chatgpt.com/backend-api/codex"
    assert models_tuples[0][3] == "oauth-token"
