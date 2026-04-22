"""Compatibility entrypoint tests."""

from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))


def test_app_main_reexports_canonical_app():
    import app.main
    import bridge_server.runtime as runtime

    assert app.main.app is runtime.app


def test_compatibility_admin_endpoints(monkeypatch):
    import bridge_server.runtime as runtime

    async def _noop_initialize():
        return None

    async def _health_check_all():
        return {"dashscope": "healthy"}

    async def _pool_health_check():
        return {"database": True}

    async def _pool_stats():
        return {"database": {"in_use": 0, "available": 4}}

    class DummyProvider:
        def get_supported_models(self):
            return ["qwen3.5-flash"]

        def get_model_info(self, model_id):
            return SimpleNamespace(
                input_cost_per_1k=0.001,
                output_cost_per_1k=0.002,
                max_tokens=8192,
                context_window=32768,
            )

    class DummyUsageTracker:
        async def get_usage_stats(self, period="today", user_id=None):
            return {"period": period, "user_id": user_id, "total_requests": 1}

        async def get_budget_status(self, user_id=None):
            return {"user_id": user_id, "today": {"alert": False}}

    monkeypatch.setattr(runtime, "initialize_system", _noop_initialize)
    runtime.provider_manager = SimpleNamespace(
        providers={"dashscope": DummyProvider()},
        routing_strategy=SimpleNamespace(value="balanced"),
        get_available_providers=lambda: ["dashscope"],
        health_check_all=_health_check_all,
        cleanup=lambda: None,
    )
    runtime.smart_router = None
    runtime.cache_system = None
    runtime.usage_tracker = DummyUsageTracker()
    runtime.connection_pool_manager = SimpleNamespace(
        health_check=_pool_health_check,
        get_stats=_pool_stats,
    )
    runtime.runtime_config = {
        "routing": {
            "strategy": "balanced",
            "model_mapping": {"general": "qwen3.5-flash"},
        }
    }

    # Bypass require_auth — these tests focus on business logic, not auth.
    runtime.app.dependency_overrides[runtime.require_auth] = lambda: {"user_id": "test", "active": True}

    with TestClient(runtime.app) as client:
        ready = client.get("/ready")
        models = client.get("/api/models")
        routing = client.get("/api/routing")
        usage = client.get("/api/usage?period=month")
        budget = client.get("/api/budget")

    runtime.app.dependency_overrides.clear()

    assert ready.status_code == 200
    assert ready.json()["status"] == "degraded"
    assert models.status_code == 200
    assert models.json()["models"][0]["id"] == "qwen3.5-flash"
    assert routing.json()["strategy"] == "balanced"
    assert routing.json()["model_mapping"]["general"] == "qwen3.5-flash"
    assert usage.json()["period"] == "month"
    assert budget.json()["today"]["alert"] is False
