from __future__ import annotations

from pathlib import Path

from conftest import REPO_ROOT, load_module


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
