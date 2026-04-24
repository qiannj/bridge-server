from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import REPO_ROOT, load_module


@pytest.fixture()
def setup_module(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_SERVER_CONFIG_DIR", str(tmp_path))
    return load_module("bridge_setup_wizard", REPO_ROOT / "cli" / "setup-wizard.py")


@pytest.fixture()
def wizard(setup_module):
    instance = setup_module.SetupWizard()
    instance.providers = {}
    instance.config["providers"] = []
    return instance


def test_provider_menu_hides_modify_delete_when_empty(wizard, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(RuntimeError("stop")))
    with pytest.raises(RuntimeError, match="stop"):
        wizard._provider_menu()

    output = capsys.readouterr().out
    assert "3. 修改已有 Provider" not in output
    assert "4. 删除已有 Provider" not in output


def test_configure_scenarios_uses_concrete_models_only(wizard, monkeypatch, capsys):
    wizard.config["providers"] = [
        {
            "name": "demo",
            "models": [
                {"id": "alpha", "name": "alpha"},
                {"id": "beta", "name": "beta"},
            ],
        }
    ]

    answers = iter(["y", "", "", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    wizard._configure_scenarios()
    output = capsys.readouterr().out

    assert "smart" not in output.lower()
    assert wizard.config["scenarios"]
    assert {v["model"] for v in wizard.config["scenarios"].values()} == {"demo/alpha"}


def test_select_routing_defaults_to_fallback(wizard, capsys):
    wizard.config["routing"]["strategy"] = "round_robin"
    wizard._select_routing()
    output = capsys.readouterr().out

    assert wizard.config["routing"]["strategy"] == "fallback"
    assert "Fallback" in output


def test_load_existing_legacy_provider_dict_is_normalized(setup_module, monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_SERVER_CONFIG_DIR", str(tmp_path))
    config_dir = tmp_path
    config_dir.mkdir(parents=True, exist_ok=True)
    legacy_config = {
        "providers": {
            "dashscope": {
                "enabled": True,
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key_env": "DASHSCOPE_API_KEY",
                "models": {
                    "qwen3.5-flash": {"use_case": "simple"},
                    "qwen3-coder-plus": {"alias": "coder"},
                },
            }
        }
    }
    (config_dir / "config.yaml").write_text(yaml.safe_dump(legacy_config, allow_unicode=True), encoding="utf-8")

    wizard = setup_module.SetupWizard()

    assert isinstance(wizard.config["providers"], list)
    assert wizard.config["providers"][0]["name"] == "dashscope"
    assert {m["id"] for m in wizard.config["providers"][0]["models"]} == {"qwen3.5-flash", "qwen3-coder-plus"}
    model_names = {m["id"]: m["name"] for m in wizard.config["providers"][0]["models"]}
    assert model_names["qwen3-coder-plus"] == "coder"


def test_choose_auth_type_offers_chatgpt_oauth_for_openai(wizard, monkeypatch):
    openai_provider = type(
        "Provider",
        (),
        {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1"},
    )()

    monkeypatch.setitem(
        wizard._choose_auth_type.__globals__,
        "select_from_list",
        lambda title, options, default_index=0: next(
            option for option in options if "ChatGPT 账号授权" in option
        ),
    )

    assert wizard._choose_auth_type(openai_provider) == "openai_codex"


def test_collect_openai_codex_oauth_config_persists_tokens(wizard, monkeypatch):
    expected = {
        "tokens": {
            "access_token": "access-123",
            "refresh_token": "refresh-456",
        },
        "base_url": "https://chatgpt.com/backend-api/codex",
        "last_refresh": "2026-04-23T12:00:00Z",
    }
    monkeypatch.setattr(wizard, "_run_openai_codex_oauth_login", lambda: expected)

    oauth_cfg = wizard._collect_openai_codex_oauth_config(provider_name="openai")

    assert oauth_cfg["provider"] == "openai_codex"
    assert oauth_cfg["auth_store_key"] == "openai"
    assert oauth_cfg["token_url"] == "https://auth.openai.com/oauth/token"
    assert oauth_cfg["client_id"]
    assert oauth_cfg["base_url"] == expected["base_url"]
    auth_payload = json.loads((wizard.config_dir / "auth.json").read_text(encoding="utf-8"))
    assert auth_payload["providers"]["openai"]["tokens"] == expected["tokens"]


def test_add_preset_openai_codex_provider_uses_codex_runtime_base_url(wizard, monkeypatch):
    provider = type(
        "Provider",
        (),
        {
            "id": "openai",
            "name": "openai",
            "name_en": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "api_key_url": "https://platform.openai.com/api-keys",
            "models": [{"id": "codex-mini-latest", "name": "codex-mini-latest"}],
        },
    )()
    wizard.providers = {"openai": provider}

    monkeypatch.setattr(wizard, "_choose_auth_type", lambda provider=None, base_url="": "openai_codex")
    monkeypatch.setattr(
        wizard,
        "_collect_oauth_config",
        lambda auth_type="oauth", provider_name="": {
            "provider": "openai_codex",
            "auth_store_key": "openai",
            "client_id": "cid",
            "token_url": "https://auth.openai.com/oauth/token",
            "grant_type": "refresh_token",
            "base_url": "https://chatgpt.com/backend-api/codex",
        },
    )
    monkeypatch.setattr(
        wizard,
        "_add_models_loop",
        lambda provider, auth_type="api_key", oauth_cfg=None, api_key=None: [
            {"id": "codex-mini-latest", "name": "codex-mini-latest"}
        ],
    )
    seen = {}
    monkeypatch.setattr(
        wizard,
        "_test_oauth_connection",
        lambda base_url, oauth_cfg, model_id: seen.setdefault("test_base_url", base_url) == base_url,
    )
    monkeypatch.setattr(wizard, "_fetch_oauth_token", lambda oauth_cfg: "token")
    monkeypatch.setitem(wizard._add_preset_provider.__globals__, "_offer_benchmark_after_add", lambda *args, **kwargs: None)

    answers = iter(["1"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    wizard._add_preset_provider()

    provider_cfg = wizard.config["providers"][0]
    assert seen["test_base_url"] == "https://chatgpt.com/backend-api/codex"
    assert provider_cfg["base_url"] == "https://chatgpt.com/backend-api/codex"


def test_add_models_loop_uses_dynamic_codex_models_and_keeps_slug(wizard, monkeypatch, capsys):
    provider = type(
        "Provider",
        (),
        {
            "id": "openai",
            "name": "OpenAI",
            "models": [],
        },
    )()
    dynamic_models = [
        SimpleNamespace(id="gpt-5.4", name="gpt-5.4", pricing=None, context_length=272000),
        SimpleNamespace(id="gpt-5.4-mini", name="gpt-5.4-mini", pricing=None, context_length=400000),
    ]
    monkeypatch.setattr(
        wizard,
        "_resolve_models_for_selection",
        lambda provider, auth_type="api_key", oauth_cfg=None, api_key=None: (dynamic_models, "远端实时返回"),
    )
    answers = iter(["1", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    models = wizard._add_models_loop(
        provider,
        auth_type="openai_codex",
        oauth_cfg={"provider": "openai_codex"},
    )

    output = capsys.readouterr().out
    assert "来源：远端实时返回" in output
    assert models == [{"id": "gpt-5.4", "name": "gpt-5.4", "priority": 1}]


def test_fetch_openai_codex_models_normalizes_response(setup_module, wizard, monkeypatch):
    monkeypatch.setattr(wizard, "_fetch_oauth_token", lambda oauth_cfg: "access-token")

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "models": [
                    {
                        "slug": "gpt-5.4",
                        "display_name": "GPT-5.4",
                        "description": "Coding model",
                        "context_window": 272000,
                        "truncation_policy": {"limit": 10000},
                        "input_modalities": ["text", "image"],
                        "supported_reasoning_levels": [{"effort": "medium"}],
                        "visibility": "list",
                        "supported_in_api": True,
                    },
                    {
                        "slug": "hidden-model",
                        "display_name": "Hidden",
                        "visibility": "internal",
                    },
                ]
            }

    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return Response()

    monkeypatch.setattr(setup_module.httpx, "get", fake_get)

    models = wizard._fetch_openai_codex_models(
        {"provider": "openai_codex", "auth_store_key": "OpenAI"},
        base_url="https://chatgpt.com/backend-api/codex",
    )

    assert captured["url"] == "https://chatgpt.com/backend-api/codex/models"
    assert captured["params"] == {"client_version": setup_module.CODEX_CLIENT_VERSION}
    assert captured["headers"]["Authorization"] == "Bearer access-token"
    assert [m.id for m in models] == ["gpt-5.4"]
    assert models[0].name == "GPT-5.4"
    assert models[0].context_length == 272000
    assert models[0].max_output_tokens == 10000
    assert "reasoning" in models[0].capabilities


def test_resolve_models_for_selection_falls_back_to_registry_when_dynamic_fetch_fails(wizard, monkeypatch):
    provider = type(
        "Provider",
        (),
        {
            "models": [
                SimpleNamespace(id="gpt-4o", name="GPT-4o", pricing=None, context_length=128000),
            ],
            "base_url": "https://api.openai.com/v1",
        },
    )()
    monkeypatch.setattr(wizard, "_fetch_openai_codex_models", lambda oauth_cfg, base_url="": [])

    models, source = wizard._resolve_models_for_selection(
        provider,
        auth_type="openai_codex",
        oauth_cfg={"provider": "openai_codex", "base_url": "https://chatgpt.com/backend-api/codex"},
    )

    assert source == "本地预设（动态拉取失败后回退）"
    assert [m.id for m in models] == ["gpt-4o"]


def test_auth_store_is_written_as_json(wizard):
    wizard._save_oauth_auth_store(
        "openai",
        {
            "provider": "openai_codex",
            "tokens": {"access_token": "access", "refresh_token": "refresh"},
        },
    )

    payload = json.loads((wizard.config_dir / "auth.json").read_text(encoding="utf-8"))
    assert payload["providers"]["openai"]["tokens"]["refresh_token"] == "refresh"
    if os.name != "nt":
        assert ((wizard.config_dir / "auth.json").stat().st_mode & 0o777) == 0o600


def test_auth_store_write_migrates_legacy_yaml_to_json(wizard):
    (wizard.config_dir / "auth.json").write_text(
        "providers:\n  legacy:\n    provider: openai_codex\n    tokens:\n      refresh_token: old-refresh\n",
        encoding="utf-8",
    )

    wizard._save_oauth_auth_store(
        "openai",
        {
            "provider": "openai_codex",
            "tokens": {"access_token": "access", "refresh_token": "refresh"},
        },
    )

    payload = json.loads((wizard.config_dir / "auth.json").read_text(encoding="utf-8"))
    assert payload["providers"]["legacy"]["tokens"]["refresh_token"] == "old-refresh"
    assert payload["providers"]["openai"]["tokens"]["refresh_token"] == "refresh"
