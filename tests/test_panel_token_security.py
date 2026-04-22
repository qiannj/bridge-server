from __future__ import annotations

import pytest

from conftest import REPO_ROOT, load_module


admin_api = load_module("bridge_admin_api", REPO_ROOT / "src" / "bridge_server" / "admin_api.py")


def test_require_panel_auth_only_accepts_header_token(monkeypatch):
    import asyncio
    import inspect

    monkeypatch.setattr(admin_api, "get_panel_token", lambda: "pt-secret")

    assert "token" not in inspect.signature(admin_api.require_panel_auth).parameters

    with pytest.raises(admin_api.HTTPException) as exc_info:
        asyncio.run(admin_api.require_panel_auth(x_panel_token=None))

    assert exc_info.value.status_code == 401


def test_web_ui_uses_session_storage_for_panel_token_only():
    html = (REPO_ROOT / "web" / "index.html").read_text(encoding="utf-8")

    assert "sessionStorage.getItem('panel_token')" in html
    assert "sessionStorage.setItem('panel_token'" in html
    assert "sessionStorage.removeItem('panel_token')" in html
    assert "localStorage.getItem('panel_token')" not in html
    assert "localStorage.setItem('panel_token'" not in html
    assert "localStorage.removeItem('panel_token')" not in html


def test_web_ui_rehydrates_panel_token_from_session_storage():
    html = (REPO_ROOT / "web" / "index.html").read_text(encoding="utf-8")

    assert "token: sessionStorage.getItem('panel_token') || ''" in html
    assert "await this.login(true);" in html


def test_external_api_key_create_update_and_deactivate(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_SERVER_CONFIG_DIR", str(tmp_path))
    now = 1000.0
    monkeypatch.setattr(admin_api.time, "time", lambda: now)

    created = admin_api.create_external_api_key(
        name="openlaw",
        model_permissions=["scnet/Qwen3-235B-A22B"],
        expires_at=now + 3600,
    )
    assert created["token"].startswith("sk-")
    assert created["name"] == "openlaw"
    assert created["model_permissions"] == ["scnet/Qwen3-235B-A22B"]
    assert created["expires_at"] == now + 3600

    listed = admin_api.list_external_api_keys()
    assert len(listed) == 1
    assert listed[0]["key_preview"].startswith("sk-")

    updated = admin_api.update_external_api_key(
        listed[0]["id"],
        name="openlaw-prod",
        model_permissions=["*"],
        expires_at=None,
    )
    assert updated["name"] == "openlaw-prod"
    assert updated["model_permissions"] == ["*"]
    assert updated["expires_at"] is None

    admin_api.delete_external_api_key(listed[0]["id"])
    assert admin_api.list_external_api_keys()[0]["active"] is False
