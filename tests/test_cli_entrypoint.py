from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.conftest import REPO_ROOT, load_module


cli = load_module("bridge_cli", REPO_ROOT / "cli" / "bridge-server.py")


def test_cmd_start_uses_canonical_runtime_entrypoint(monkeypatch, tmp_path):
    popen_calls = []

    class DummyPopen:
        def __init__(self, args, **kwargs):
            popen_calls.append((args, kwargs))

    class DummyCompleted:
        def __init__(self, returncode=1):
            self.returncode = returncode
            self.stdout = ""
            self.stderr = ""

    monkeypatch.setattr(cli, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(cli, "LOG_DIR", tmp_path)
    monkeypatch.setattr(cli, "LOG_FILE", tmp_path / "bridge-server.log")
    monkeypatch.setattr(cli.os, "chdir", lambda path: None)
    monkeypatch.setattr(cli, "get_default_port", lambda: 19377)

    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: DummyCompleted(1))
    monkeypatch.setattr(subprocess, "Popen", DummyPopen)

    cli.cmd_start()

    assert popen_calls, "expected subprocess.Popen to be called"
    args, kwargs = popen_calls[0]
    assert "bridge_server.runtime:app" in args
    assert "--app-dir" in args
    assert "src" in args
    assert "19377" in args


def test_cmd_status_reports_running_when_health_check_is_unreachable(
    monkeypatch, tmp_path, capsys
):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("server:\n  port: 19377\n", encoding="utf-8")
    monkeypatch.setattr(cli, "CONFIG_FILE", config_file)
    monkeypatch.setattr(cli, "get_default_port", lambda: 19377)
    monkeypatch.setattr(
        cli,
        "get_service_runtime_status",
        lambda timeout=2: {
            "api_ok": False,
            "api_error": "timed out",
            "process_running": True,
            "port_listening": True,
            "server_version": None,
            "running": True,
        },
    )

    cli.cmd_status()

    out = capsys.readouterr().out
    assert "服务状态：运行中（本地健康检查不可达）" in out
    assert "进程：已检测到 Bridge Server 运行进程" in out
    assert "端口 19377：已监听" in out
    assert "本地 /health 检查失败：timed out" in out


def test_cmd_test_falls_back_to_secondary_server_url_when_primary_times_out(
    monkeypatch, capsys
):
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        calls.append(("GET", url))
        if url.startswith("http://localhost:19377"):
            raise TimeoutError("timed out")
        if url.endswith("/health"):
            return FakeResponse(200, {"status": "healthy"})
        if url.endswith("/v1/models"):
            return FakeResponse(200, {"data": []})
        if url.endswith("/api/routing"):
            return FakeResponse(200, {"strategy": "fallback"})
        raise AssertionError(url)

    monkeypatch.setattr(
        cli,
        "_iter_server_urls",
        lambda: ["http://localhost:19377", "http://203.0.113.10:19377"],
    )
    monkeypatch.setattr(cli.httpx, "get", fake_get)
    monkeypatch.setattr(cli.httpx, "post", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("POST should not be used")))

    cli.cmd_test()

    out = capsys.readouterr().out
    assert "健康检查..." in out and "OK" in out
    assert "API 测试..." in out and "OK" in out
    assert "路由配置..." in out and "OK" in out
    assert ("GET", "http://localhost:19377/health") in calls
    assert ("GET", "http://203.0.113.10:19377/health") in calls


def test_cmd_providers_list_reads_api_models_catalog(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_iter_server_urls", lambda: ["http://203.0.113.10:19377"])
    monkeypatch.setattr(
        cli,
        "_request_with_fallback",
        lambda method, path, **kwargs: SimpleNamespace(
            status_code=200,
            json=lambda: {
                "models": [
                    {"id": "smart", "provider": "bridge-server", "owned_by": "bridge-server"},
                    {"id": "scnet/Qwen3-235B-A22B", "provider": "scnet", "owned_by": "scnet"},
                    {"id": "scnet/MiniMax-M2.5", "provider": "scnet", "owned_by": "scnet"},
                ]
            },
        ),
    )

    cli.cmd_providers_list()

    out = capsys.readouterr().out
    assert "bridge-server" in out
    assert "scnet" in out
    assert "scnet/Qwen3-235B-A22B" in out


def test_cmd_routing_strategy_reads_api_routing(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_iter_server_urls", lambda: ["http://203.0.113.10:19377"])
    monkeypatch.setattr(
        cli,
        "_request_with_fallback",
        lambda method, path, **kwargs: SimpleNamespace(
            status_code=200,
            json=lambda: {
                "strategy": "fallback",
                "effective_strategy": "manual",
                "model_mapping": {"chat": "scnet/MiniMax-M2.5"},
            },
        ),
    )

    cli.cmd_routing_strategy()

    out = capsys.readouterr().out
    assert "策略：fallback" in out
    assert "chat" in out
    assert "scnet/MiniMax-M2.5" in out


def test_cmd_routing_strategy_falls_back_to_legacy_endpoint_on_404(monkeypatch, capsys):
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append(path)
        if path == "/api/routing":
            return SimpleNamespace(status_code=404, json=lambda: {})
        if path == "/api/v1/routing/strategy":
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"strategy": "legacy", "model_mapping": {"chat": "legacy-model"}},
            )
        raise AssertionError(path)

    monkeypatch.setattr(cli, "_request_with_fallback", fake_request)

    cli.cmd_routing_strategy()

    out = capsys.readouterr().out
    assert calls == ["/api/routing", "/api/v1/routing/strategy"]
    assert "策略：legacy" in out


def test_cmd_providers_list_falls_back_to_legacy_endpoint_on_404(monkeypatch, capsys):
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append(path)
        if path == "/api/models":
            return SimpleNamespace(status_code=404, json=lambda: {})
        if path == "/api/v1/providers/list":
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "providers": [
                        {"name": "legacy-provider", "models": [{"id": "legacy-model", "cost": 0.12}]}
                    ]
                },
            )
        raise AssertionError(path)

    monkeypatch.setattr(cli, "_request_with_fallback", fake_request)

    cli.cmd_providers_list()

    out = capsys.readouterr().out
    assert calls == ["/api/models", "/api/v1/providers/list"]
    assert "legacy-provider" in out
    assert "legacy-model" in out
