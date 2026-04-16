#!/usr/bin/env python3
"""Compatibility wrapper for the CLI setup wizard."""

from pathlib import Path
import runpy


if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).resolve().parent / "cli" / "setup-wizard.py"),
        run_name="__main__",
    )
