from __future__ import annotations

from pathlib import Path

import pytest

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
