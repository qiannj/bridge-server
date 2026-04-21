from __future__ import annotations

import importlib
import sqlite3
import sys

import aiosqlite
import pytest

from conftest import SRC_DIR

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

usage = importlib.import_module("bridge_server.usage")


@pytest.mark.asyncio
async def test_init_database_adds_savings_columns_for_existing_usage_table(monkeypatch, tmp_path):
    db_path = tmp_path / "usage.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE usage_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            date TEXT NOT NULL,
            user_id TEXT NOT NULL,
            model TEXT NOT NULL,
            provider TEXT NOT NULL,
            task_type TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            cost_rmb REAL DEFAULT 0.0,
            duration_ms REAL DEFAULT 0.0,
            success BOOLEAN DEFAULT TRUE,
            created_at REAL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

    tracker = usage.UsageTrackerAsync(config_dir=tmp_path)
    tracker.db_file = db_path

    async def fake_get_db_connection():
        return aiosqlite.connect(str(db_path))

    async def fake_get_connection_pool_manager():
        return None

    monkeypatch.setattr(usage, "get_db_connection", fake_get_db_connection)
    monkeypatch.setattr(usage, "get_connection_pool_manager", fake_get_connection_pool_manager)

    await tracker._init_database()

    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(usage_records)").fetchall()}
    conn.close()

    assert "baseline_model" in columns
    assert "baseline_cost_rmb" in columns
    assert "savings_rmb" in columns
    assert "baseline_source" in columns


@pytest.mark.asyncio
async def test_flush_batch_persists_savings_fields(monkeypatch, tmp_path):
    db_path = tmp_path / "usage.db"
    tracker = usage.UsageTrackerAsync(config_dir=tmp_path)
    tracker.db_file = db_path

    async def fake_get_db_connection():
        return aiosqlite.connect(str(db_path))

    async def fake_get_connection_pool_manager():
        return None

    monkeypatch.setattr(usage, "get_db_connection", fake_get_db_connection)
    monkeypatch.setattr(usage, "get_connection_pool_manager", fake_get_connection_pool_manager)

    await tracker._init_database()
    await tracker._flush_batch(
        [
            {
                "timestamp": 123.0,
                "date": "2026-04-20",
                "user_id": "admin",
                "model": "MiniMax-M2.5",
                "provider": "scnet-coding",
                "task_type": "coding",
                "input_tokens": 1000,
                "output_tokens": 500,
                "total_tokens": 1500,
                "cost_usd": 0.1,
                "cost_rmb": 0.72,
                "duration_ms": 800.0,
                "success": True,
                "baseline_model": "scnet-coding/Qwen3-235B-A22B",
                "baseline_cost_rmb": 2.16,
                "savings_rmb": 1.44,
                "baseline_source": "scenario_override",
            }
        ]
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT baseline_model, baseline_cost_rmb, savings_rmb, baseline_source FROM usage_records"
    ).fetchone()
    conn.close()

    assert row == (
        "scnet-coding/Qwen3-235B-A22B",
        2.16,
        1.44,
        "scenario_override",
    )
