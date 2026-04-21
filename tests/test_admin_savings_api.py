from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import pytest
import yaml

from conftest import REPO_ROOT, load_module


admin_api = load_module("bridge_admin_savings_api", REPO_ROOT / "src" / "bridge_server" / "admin_api.py")


@pytest.fixture()
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(admin_api, "_get_config_dir", lambda: tmp_path)
    return tmp_path


def _create_usage_db(config_dir: Path) -> None:
    db_path = config_dir / "usage.db"
    conn = sqlite3.connect(db_path)
    try:
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
                baseline_model TEXT,
                baseline_cost_rmb REAL DEFAULT 0.0,
                savings_rmb REAL DEFAULT 0.0,
                baseline_source TEXT DEFAULT 'default'
            )
            """
        )
        now = time.time()
        rows = [
            (
                now - 120,
                "2026-04-20",
                "u1",
                "MiniMax-M2.5",
                "scnet-coding",
                "coding",
                1000,
                500,
                1500,
                0.10,
                0.72,
                500.0,
                1,
                "scnet-coding/Qwen3-235B-A22B",
                1.44,
                0.72,
                "scenario_override",
            ),
            (
                now - 60,
                "2026-04-20",
                "u2",
                "Qwen3-32B",
                "dashscope",
                "summary",
                800,
                200,
                1000,
                0.05,
                0.36,
                400.0,
                1,
                "scnet-coding/Qwen3-235B-A22B",
                1.08,
                0.72,
                "default",
            ),
            (
                now - 30,
                "2026-04-20",
                "u3",
                "MiniMax-M2.5",
                "scnet-coding",
                "coding",
                600,
                200,
                800,
                0.04,
                0.288,
                320.0,
                1,
                None,
                0.0,
                0.0,
                "default",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO usage_records (
                timestamp, date, user_id, model, provider, task_type,
                input_tokens, output_tokens, total_tokens,
                cost_usd, cost_rmb, duration_ms, success,
                baseline_model, baseline_cost_rmb, savings_rmb, baseline_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_get_savings_aggregates_summary_model_and_task_breakdowns(config_dir: Path):
    _create_usage_db(config_dir)

    result = await admin_api.get_savings(period="today")

    assert result["summary"]["total_requests"] == 3
    assert result["summary"]["covered_requests"] == 2
    assert result["summary"]["uncovered_requests"] == 1
    assert result["summary"]["actual_cost_rmb"] == pytest.approx(1.368, rel=1e-6)
    assert result["summary"]["baseline_cost_rmb"] == pytest.approx(2.52, rel=1e-6)
    assert result["summary"]["savings_rmb"] == pytest.approx(1.44, rel=1e-6)
    assert result["summary"]["savings_rate"] == pytest.approx(1.44 / 2.52, rel=1e-6)

    assert result["by_model"]["MiniMax-M2.5"]["requests"] == 2
    assert result["by_model"]["MiniMax-M2.5"]["savings_rmb"] == pytest.approx(0.72, rel=1e-6)
    assert result["by_task_type"]["coding"]["requests"] == 2
    assert result["by_task_type"]["coding"]["covered_requests"] == 1
    assert list(result["daily"].values())[0]["savings_rmb"] == pytest.approx(1.44, rel=1e-6)
    assert len(result["records"]) == 3


@pytest.mark.asyncio
async def test_get_savings_config_returns_normalized_defaults(config_dir: Path):
    (config_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "savings": {
                    "enabled": True,
                    "baseline": {
                        "default_model": "scnet-coding/Qwen3-235B-A22B",
                        "scenarios": {"coding": "scnet-coding/Qwen3-235B-A22B"},
                    },
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    result = await admin_api.get_savings_config()

    assert result == {
        "enabled": True,
        "baseline": {
            "default_model": "scnet-coding/Qwen3-235B-A22B",
            "scenarios": {"coding": "scnet-coding/Qwen3-235B-A22B"},
        },
    }


@pytest.mark.asyncio
async def test_update_savings_config_persists_and_hot_reloads_runtime(config_dir: Path, monkeypatch: pytest.MonkeyPatch):
    (config_dir / "config.yaml").write_text(yaml.safe_dump({}, allow_unicode=True), encoding="utf-8")

    class RuntimeStub:
        runtime_config = {"routing": {"strategy": "fallback"}}

    monkeypatch.setitem(__import__("sys").modules, "bridge_server.runtime", RuntimeStub)

    req = admin_api.SavingsConfigUpdateRequest(
        enabled=True,
        baseline=admin_api.SavingsBaselineConfig(
            default_model="scnet-coding/Qwen3-235B-A22B",
            scenarios={
                "coding": "scnet-coding/Qwen3-235B-A22B",
                "summary": "  ",
            },
        ),
    )

    result = await admin_api.update_savings_config(req)
    saved = yaml.safe_load((config_dir / "config.yaml").read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["config"] == {
        "enabled": True,
        "baseline": {
            "default_model": "scnet-coding/Qwen3-235B-A22B",
            "scenarios": {"coding": "scnet-coding/Qwen3-235B-A22B"},
        },
    }
    assert saved["savings"] == result["config"]
    assert RuntimeStub.runtime_config["savings"] == result["config"]
