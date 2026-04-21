from __future__ import annotations

from types import SimpleNamespace
import importlib
import sys

import pytest

from conftest import SRC_DIR

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

runtime = importlib.import_module("bridge_server.runtime")


def _provider_with_prices(price_map):
    return SimpleNamespace(
        get_model_info=lambda model: (
            SimpleNamespace(
                input_cost_per_1k=price_map[model][0],
                output_cost_per_1k=price_map[model][1],
            )
            if model in price_map
            else None
        )
    )


@pytest.mark.asyncio
async def test_record_usage_background_enriches_usage_with_savings(monkeypatch):
    captured = {}

    async def fake_record_usage_async(**kwargs):
        captured.update(kwargs)

    runtime.usage_tracker = object()
    runtime.runtime_config = {
        "savings": {
            "baseline": {
                "default_model": "scnet-coding/Qwen3-235B-A22B",
                "scenarios": {"coding": "scnet-coding/Qwen3-235B-A22B"},
            }
        }
    }
    runtime.provider_manager = SimpleNamespace(
        providers={
            "scnet-coding": _provider_with_prices(
                {
                    "MiniMax-M2.5": (0.05, 0.10),
                    "Qwen3-235B-A22B": (0.10, 0.20),
                }
            )
        }
    )
    monkeypatch.setattr(runtime, "record_usage_async", fake_record_usage_async)

    await runtime._record_usage_background(
        route_result=SimpleNamespace(
            provider_id="scnet-coding",
            model="MiniMax-M2.5",
            task_type="coding",
        ),
        usage_info={"prompt_tokens": 1000, "completion_tokens": 500},
        current_user={"user_id": "admin"},
        duration_ms=850.0,
    )

    assert captured["cost_usd"] == pytest.approx(0.1, rel=1e-6)
    assert captured["baseline_model"] == "scnet-coding/Qwen3-235B-A22B"
    assert captured["baseline_cost_rmb"] == pytest.approx(1.44, rel=1e-6)
    assert captured["savings_rmb"] == pytest.approx(0.72, rel=1e-6)
    assert captured["baseline_source"] == "scenario_override"


@pytest.mark.asyncio
async def test_record_usage_background_gracefully_handles_missing_savings_config(monkeypatch):
    captured = {}

    async def fake_record_usage_async(**kwargs):
        captured.update(kwargs)

    runtime.usage_tracker = object()
    runtime.runtime_config = {}
    runtime.provider_manager = SimpleNamespace(
        providers={
            "scnet-coding": _provider_with_prices({"MiniMax-M2.5": (0.05, 0.10)})
        }
    )
    monkeypatch.setattr(runtime, "record_usage_async", fake_record_usage_async)

    await runtime._record_usage_background(
        route_result=SimpleNamespace(
            provider_id="scnet-coding",
            model="MiniMax-M2.5",
            task_type="coding",
        ),
        usage_info={"prompt_tokens": 1000, "completion_tokens": 500},
        current_user={"user_id": "admin"},
        duration_ms=850.0,
    )

    assert captured["cost_usd"] == pytest.approx(0.1, rel=1e-6)
    assert captured["baseline_model"] is None
    assert captured["baseline_cost_rmb"] is None
    assert captured["savings_rmb"] is None
    assert captured["baseline_source"] == "default"
