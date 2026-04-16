#!/usr/bin/env python3
"""Compatibility entrypoint that re-exports the canonical async application."""

from pathlib import Path
import sys
from typing import Any, Dict

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from bridge_server.runtime import app


def load_config() -> Dict[str, Any]:
    """Load the Bridge Server config from the canonical config locations."""
    config_paths = [
        Path.home() / ".bridge-server" / "config.yaml",
        REPO_ROOT / "config.yaml.example",
    ]

    for config_path in config_paths:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as handle:
                return yaml.safe_load(handle) or {}

    return {}


__all__ = ["app", "load_config"]
