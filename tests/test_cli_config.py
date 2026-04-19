from __future__ import annotations

from pathlib import Path

from conftest import REPO_ROOT, load_module


def load_cli_config_module(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_SERVER_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("BRIDGE_SERVER_PORT", raising=False)
    return load_module("bridge_cli_config", REPO_ROOT / "cli" / "config.py")


def test_get_default_port_prefers_port_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PORT", "24444")
    monkeypatch.setenv("BRIDGE_SERVER_PORT", "25555")
    monkeypatch.setenv("BRIDGE_SERVER_CONFIG_DIR", str(tmp_path))
    module = load_module("bridge_cli_config_env", REPO_ROOT / "cli" / "config.py")
    assert module.get_default_port() == 24444


def test_get_default_port_falls_back_to_bridge_server_port(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_SERVER_PORT", "25555")
    module = load_cli_config_module(monkeypatch, tmp_path)
    monkeypatch.setenv("BRIDGE_SERVER_PORT", "25555")
    assert module.get_default_port() == 25555


def test_get_default_port_reads_config_file(monkeypatch, tmp_path):
    config_dir = tmp_path
    config_dir.mkdir(exist_ok=True)
    (config_dir / "config.yaml").write_text("server:\n  port: 26666\n", encoding="utf-8")
    module = load_cli_config_module(monkeypatch, config_dir)
    assert module.get_default_port() == 26666


def test_get_default_port_defaults_to_19377(monkeypatch, tmp_path):
    module = load_cli_config_module(monkeypatch, tmp_path)
    assert module.get_default_port() == 19377
