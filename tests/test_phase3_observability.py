"""阶段3可观测性测试。"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from bridge_server.observability.metrics import BridgeServerMetrics
from bridge_server.observability.tracing import (
    bind_request_context,
    clear_request_context,
    extract_request_context,
    get_trace_headers,
)


def test_extract_request_context_uses_incoming_trace_headers():
    context = extract_request_context(
        {
            "X-Request-ID": "req-123",
            "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
        }
    )

    assert context["request_id"] == "req-123"
    assert context["trace_id"] == "0123456789abcdef0123456789abcdef"


def test_trace_headers_include_traceparent():
    clear_request_context()
    bind_request_context(
        request_id="req-456",
        trace_id="fedcba9876543210fedcba9876543210",
        method="GET",
        path="/health",
    )

    headers = get_trace_headers()

    assert headers["X-Request-ID"] == "req-456"
    assert headers["X-Trace-ID"] == "fedcba9876543210fedcba9876543210"
    assert headers["traceparent"].startswith("00-fedcba9876543210fedcba9876543210-")
    clear_request_context()


def test_prometheus_collector_renders_runtime_metrics():
    collector = BridgeServerMetrics(registry=CollectorRegistry())
    collector.record_http_request("GET", "/health", 200, 0.12)
    collector.record_llm_call("dashscope", "qwen3.5-flash", "success", 0.42)
    collector.record_token_usage("dashscope", "qwen3.5-flash", 100, 50)
    collector.record_route_decision("general", "dashscope", "qwen3.5-flash", False)
    collector.observe_runtime_snapshot(
        {
            "performance": {"qps": 5.2, "avg_latency_ms": 120.5, "error_rate": 0.01},
            "providers": {
                "total_providers": 2,
                "available_providers": 1,
                "providers": {"dashscope": {"enabled": True}},
            },
            "cache": {"metrics": {"hit_rate": 0.75, "total_requests": 12, "writes": 4, "errors": 0}},
            "connection_pool": {
                "database": {"in_use": 2, "available": 8},
                "provider_http_clients": {"count": 1},
            },
            "budget": {
                "today": {"used_rmb": 10.0, "limit_rmb": 50.0, "usage_rate": 0.2, "alert": False},
                "month": {"used_rmb": 100.0, "limit_rmb": 500.0, "usage_rate": 0.2, "alert": False},
            },
        }
    )

    payload = collector.render().decode("utf-8")

    assert "bridge_server_requests_total" in payload
    assert 'endpoint="/health"' in payload
    assert "bridge_server_llm_calls_total" in payload
    assert "bridge_server_tokens_total" in payload
    assert "bridge_server_budget_usage_ratio" in payload


@pytest.fixture
def observability_client(monkeypatch):
    import bridge_server.runtime as runtime

    async def _noop_initialize():
        return None

    monkeypatch.setattr(runtime, "initialize_system", _noop_initialize)
    runtime.provider_manager = None
    runtime.smart_router = None
    runtime.cache_system = None
    runtime.usage_tracker = None
    runtime.connection_pool_manager = None

    # Bypass require_auth for observability tests.
    runtime.app.dependency_overrides[runtime.require_auth] = lambda: {"user_id": "test", "active": True}

    with TestClient(runtime.app) as client:
        yield client

    runtime.app.dependency_overrides.clear()


def test_main_v2_async_exposes_prometheus_metrics(observability_client):
    response = observability_client.get("/metrics?format=prometheus")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "bridge_server_requests_total" in response.text
    assert "X-Request-ID" in response.headers
    assert "X-Trace-ID" in response.headers


def test_main_v2_async_stats_endpoint_keeps_json(observability_client):
    response = observability_client.get("/stats")

    assert response.status_code == 200
    payload = response.json()
    assert "performance" in payload
    assert "observability" in payload
    assert payload["observability"]["prometheus_endpoint"] == "/metrics/prometheus"
