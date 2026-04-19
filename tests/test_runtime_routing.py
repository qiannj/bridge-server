from __future__ import annotations

from types import SimpleNamespace
import importlib
import sys

import pytest

from conftest import REPO_ROOT, SRC_DIR

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

runtime = importlib.import_module("bridge_server.runtime")


def test_runtime_routing_strategy_mapping():
    assert runtime._resolve_provider_routing_strategy({"routing": {"strategy": "fallback"}}).value == "manual"
    assert runtime._resolve_provider_routing_strategy({"routing": {"strategy": "round_robin"}}).value == "round_robin"
    assert runtime._resolve_provider_routing_strategy({"routing": {"strategy": "load_balance"}}).value == "lowest_latency"
    assert runtime._resolve_provider_routing_strategy({"routing": {"strategy": "cost_optimized"}}).value == "cost_optimized"


@pytest.mark.asyncio
async def test_api_routing_exposes_configured_and_effective_strategy():
    runtime.runtime_config = {"routing": {"strategy": "fallback", "model_mapping": {"coding": "demo/alpha"}}}
    runtime.provider_manager = SimpleNamespace(routing_strategy=SimpleNamespace(value="manual"))

    data = await runtime.get_routing_config()

    assert data["strategy"] == "fallback"
    assert data["effective_strategy"] == "manual"
    assert data["model_mapping"] == {"coding": "demo/alpha"}
