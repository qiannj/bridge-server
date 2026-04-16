#!/usr/bin/env python3
"""Compatibility wrapper for the canonical async runtime."""

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from bridge_server.runtime import app


__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "bridge_server.runtime:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
        workers=1,
        access_log=False,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
