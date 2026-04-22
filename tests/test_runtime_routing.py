from __future__ import annotations

from types import SimpleNamespace
import importlib
import sys

import pytest

from conftest import REPO_ROOT, SRC_DIR

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

runtime = importlib.import_module("bridge_server.runtime")


class FakeProvider:
    def __init__(self, models):
        self._models = models

    def get_supported_models(self):
        return list(self._models)

    def get_model_info(self, model):
        return SimpleNamespace(
            input_cost_per_1k=0.1,
            output_cost_per_1k=0.2,
            max_tokens=8192,
            context_window=32768,
        )


class FakeProviderManager:
    def __init__(self, provider_models):
        self.providers = {
            provider_id: FakeProvider(models)
            for provider_id, models in provider_models.items()
        }

    def get_provider_models(self, provider_id=None):
        if provider_id:
            provider = self.providers.get(provider_id)
            return {provider_id: provider.get_supported_models()} if provider else {}
        return {
            provider_id: provider.get_supported_models()
            for provider_id, provider in self.providers.items()
        }


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


def test_external_api_key_model_permissions_are_enforced():
    runtime._ensure_model_allowed(
        {"type": "external_api_key", "model_permissions": ["demo/alpha"]},
        "demo",
        "alpha",
    )
    runtime._ensure_model_allowed(
        {"type": "external_api_key", "model_permissions": ["smart"]},
        "demo",
        "alpha",
        "smart",
    )

    with pytest.raises(runtime.HTTPException) as exc_info:
        runtime._ensure_model_allowed(
            {"type": "external_api_key", "model_permissions": ["demo/beta"]},
            "demo",
            "alpha",
        )

    assert exc_info.value.status_code == 403


def test_model_catalog_includes_smart_canonical_ids_and_unambiguous_aliases(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "provider_manager",
        FakeProviderManager({"demo": ["alpha", "shared"], "other": ["shared"]}),
    )

    catalog = runtime._build_model_catalog()
    by_id = {item["id"]: item for item in catalog}

    assert "smart" in by_id
    assert "demo/alpha" in by_id
    assert "demo/shared" in by_id
    assert "other/shared" in by_id
    assert by_id["smart"]["provider"] == "bridge-server"
    assert by_id["demo/alpha"]["canonical_id"] == "demo/alpha"
    assert by_id["alpha"]["canonical_id"] == "demo/alpha"
    assert by_id["alpha"]["is_alias"] is True
    assert "shared" not in by_id


def test_resolve_requested_model_uses_smart_router_for_smart_or_missing():
    manager = FakeProviderManager({"demo": ["alpha"]})

    assert runtime._resolve_requested_model(None, manager) is None
    assert runtime._resolve_requested_model("smart", manager) is None


def test_resolve_requested_model_accepts_provider_qualified_model():
    manager = FakeProviderManager({"demo": ["alpha"]})

    result = runtime._resolve_requested_model("demo/alpha", manager)

    assert result.provider_id == "demo"
    assert result.model == "alpha"
    assert result.task_type == "direct"


def test_resolve_requested_model_accepts_unambiguous_bare_model():
    manager = FakeProviderManager({"demo": ["alpha"], "other": ["beta"]})

    result = runtime._resolve_requested_model("alpha", manager)

    assert result.provider_id == "demo"
    assert result.model == "alpha"


def test_resolve_requested_model_rejects_unknown_or_ambiguous_models():
    manager = FakeProviderManager({"demo": ["shared"], "other": ["shared"]})

    with pytest.raises(runtime.HTTPException) as unknown:
        runtime._resolve_requested_model("missing", manager)
    assert unknown.value.status_code == 400

    with pytest.raises(runtime.HTTPException) as ambiguous:
        runtime._resolve_requested_model("shared", manager)
    assert ambiguous.value.status_code == 400
