from __future__ import annotations

from pathlib import Path

from conftest import REPO_ROOT


def test_legacy_parallel_files_removed():
    removed = [
        REPO_ROOT / "main_v2.py",
        REPO_ROOT / "main_v2_async.py",
        REPO_ROOT / "requirements-v2.txt",
        REPO_ROOT / "setup-wizard.py",
        REPO_ROOT / "app" / "main.py",
        REPO_ROOT / "src" / "bridge_server" / "providers" / "base_v2.py",
        REPO_ROOT / "src" / "bridge_server" / "providers" / "base_simple.py",
    ]
    assert all(not path.exists() for path in removed)
