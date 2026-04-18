"""Unit tests for UsageTrackerAsync — queue, budget config, and cost calculation."""

import sys
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest
from unittest.mock import AsyncMock

from bridge_server.usage import UsageTrackerAsync


class TestBudgetConfig:
    @pytest.mark.asyncio
    async def test_default_config_created_when_no_file(self, tmp_path):
        tracker = UsageTrackerAsync(config_dir=tmp_path)
        await tracker._load_budget_config()
        assert tracker._budget_cache["daily_limit_rmb"] == pytest.approx(100.0)
        assert tracker._budget_cache["monthly_limit_rmb"] == pytest.approx(2000.0)

    @pytest.mark.asyncio
    async def test_existing_file_loaded_correctly(self, tmp_path):
        budget_data = {"daily_limit_rmb": 50.0, "monthly_limit_rmb": 500.0}
        (tmp_path / "budget.json").write_text(json.dumps(budget_data))
        tracker = UsageTrackerAsync(config_dir=tmp_path)
        await tracker._load_budget_config()
        assert tracker._budget_cache["daily_limit_rmb"] == pytest.approx(50.0)
        assert tracker._budget_cache["monthly_limit_rmb"] == pytest.approx(500.0)


class TestRecordUsage:
    @pytest.mark.asyncio
    async def test_record_usage_enqueues_item(self, tmp_path):
        tracker = UsageTrackerAsync(config_dir=tmp_path)
        assert tracker._write_queue.empty()
        await tracker.record_usage(
            model="gpt-4",
            provider="openai",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.01,
        )
        assert not tracker._write_queue.empty()

    @pytest.mark.asyncio
    async def test_cost_rmb_calculation(self, tmp_path):
        tracker = UsageTrackerAsync(config_dir=tmp_path)
        await tracker.record_usage(
            model="gpt-4",
            provider="openai",
            input_tokens=100,
            output_tokens=50,
            cost_usd=1.0,
        )
        record = tracker._write_queue.get_nowait()
        assert record["cost_rmb"] == pytest.approx(7.2)

    @pytest.mark.asyncio
    async def test_total_tokens_calculation(self, tmp_path):
        tracker = UsageTrackerAsync(config_dir=tmp_path)
        await tracker.record_usage(
            model="claude-3",
            provider="anthropic",
            input_tokens=200,
            output_tokens=300,
            cost_usd=0.05,
        )
        record = tracker._write_queue.get_nowait()
        assert record["total_tokens"] == 500


class TestGetBudgetStatus:
    @pytest.mark.asyncio
    async def test_budget_status_structure(self, tmp_path):
        tracker = UsageTrackerAsync(config_dir=tmp_path)
        tracker._budget_cache = {
            "daily_limit_rmb": 100.0,
            "monthly_limit_rmb": 2000.0,
            "alerts": {
                "daily_threshold": 0.8,
                "monthly_threshold": 0.9,
            },
        }
        tracker.get_usage_stats = AsyncMock(return_value={"total_cost_rmb": 0})
        status = await tracker.get_budget_status()
        assert "today" in status
        assert "month" in status
        for section in ("today", "month"):
            for key in ("used_rmb", "limit_rmb", "usage_rate", "alert", "exceeded"):
                assert key in status[section], f"Missing '{key}' in status['{section}']"
