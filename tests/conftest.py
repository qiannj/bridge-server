from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = REPO_ROOT / "cli"
SRC_DIR = REPO_ROOT / "src"


def load_module(module_name: str, file_path: Path):
    if str(CLI_DIR) not in sys.path:
        sys.path.insert(0, str(CLI_DIR))
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module
