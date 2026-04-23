from __future__ import annotations

from pathlib import Path

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
