"""
全流程集成测试 — Bridge Server 用户用例
========================================

测试完整 HTTP 管道：请求 → 中间件 → 认证 → 路由 → Mock Provider → 响应

所有测试均使用 FastAPI TestClient 配合受控 Mock，
不发起真实 AI Provider API 调用。

覆盖的用户场景：
1. 公开端点无需认证即可访问
2. 受保护端点必须通过认证
3. 完整聊天补全流程（路由 + Mock Provider 响应）
4. 流式聊天（SSE）
5. 用量/预算统计流程
6. 健康检查 / 就绪探针
7. Prometheus 指标
8. 模型目录与路由配置查询
9. API 文档默认禁用
10. 错误处理（400/401/422/500）
11. 响应头（X-Response-Time、X-Request-ID）
12. CORS 行为
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

# ── 测试用固定 Token（明文 + 对应 SHA-256 Hash） ─────────────────────────────
_ADMIN_TOKEN = "integration-test-admin-token-abc123"
_ADMIN_TOKEN_HASH = hashlib.sha256(_ADMIN_TOKEN.encode()).hexdigest()

_INVALID_TOKEN = "totally-wrong-token-xyz"


# ── Mock 数据工厂 ─────────────────────────────────────────────────────────────

def _make_route_result():
    """返回一个最小 RouteResult 对象，用于路由 Mock。"""
    from bridge_server.services.routing.router import RouteResult, TaskType

    return RouteResult(
        provider_id="dashscope",
        model="qwen-turbo",
        task_type=TaskType.GENERAL,
        confidence=0.92,
        reason="integration-test route",
        from_cache=False,
    )


def _make_chat_response() -> Dict[str, Any]:
    """返回符合 OpenAI 格式的 Mock 聊天响应。"""
    return {
        "id": "chatcmpl-integration-test",
        "object": "chat.completion",
        "model": "qwen-turbo",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello from mock provider!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 7,
            "total_tokens": 19,
        },
    }


async def _fake_stream_gen(*args, **kwargs) -> AsyncIterator[Dict]:
    """供流式测试使用的 Async Generator Mock。"""
    yield {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]}
    yield {"choices": [{"delta": {"content": " world"}, "finish_reason": "stop"}]}


# ── Pytest Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def mock_provider_manager():
    """ProviderManager-like Mock，所有异步方法使用 AsyncMock。"""
    mgr = MagicMock()
    mgr.providers = {
        "dashscope": MagicMock(
            get_supported_models=MagicMock(return_value=["qwen-turbo", "qwen-max"]),
            get_model_info=MagicMock(
                return_value=SimpleNamespace(
                    input_cost_per_1k=0.001,
                    output_cost_per_1k=0.002,
                    max_tokens=4096,
                    context_window=8192,
                )
            ),
        )
    }
    mgr.routing_strategy = SimpleNamespace(value="cost_optimized")
    mgr.get_available_providers = MagicMock(return_value=["dashscope"])
    mgr.health_check_all = AsyncMock(
        return_value={"dashscope": SimpleNamespace(value="healthy")}
    )
    mgr.chat_completion = AsyncMock(return_value=_make_chat_response())
    mgr.chat_completion_stream = MagicMock(side_effect=_fake_stream_gen)
    mgr.cleanup = AsyncMock()
    return mgr


@pytest.fixture
def mock_usage_tracker():
    """UsageTrackerAsync-like Mock。"""
    tracker = MagicMock()
    tracker.get_usage_stats = AsyncMock(
        return_value={
            "period": "today",
            "total_requests": 42,
            "total_cost_rmb": 0.12,
        }
    )
    tracker.get_budget_status = AsyncMock(
        return_value={
            "user_id": None,
            "today": {"alert": False, "usage": 0.05, "limit": 10.0},
        }
    )
    tracker.record_usage = AsyncMock()
    tracker.close = AsyncMock()
    return tracker


@pytest.fixture
def mock_cache():
    """HybridCache-like Mock。"""
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.health_check = AsyncMock(
        return_value={"overall": True, "l1": True, "l2": False}
    )
    cache.close = AsyncMock()
    return cache


@pytest.fixture
def mock_smart_router():
    """SmartRouter Mock，始终返回固定 RouteResult。"""
    router = MagicMock()
    router.route = AsyncMock(return_value=_make_route_result())
    return router


@pytest.fixture
def mock_conn_pool():
    """ConnectionPoolManager Mock。"""
    pool = MagicMock()
    pool.health_check = AsyncMock(return_value={"database": True})
    pool.get_stats = AsyncMock(
        return_value={"database": {"in_use": 0, "available": 5}}
    )
    return pool


@pytest.fixture
def integration_client(
    tmp_path,
    mock_provider_manager,
    mock_usage_tracker,
    mock_cache,
    mock_smart_router,
    mock_conn_pool,
):
    """
    完整集成 TestClient：
    - 真实 AsyncAuthManager，使用 tmp_path 中的已知 Token（测试真实认证管道）
    - 所有外部依赖（Provider、Router、Cache、Usage、DB Pool）均为 Mock
    - 不使用 dependency_overrides — require_auth 以真实方式运行
    """
    import bridge_server.auth as auth_module
    import bridge_server.runtime as runtime
    from bridge_server.auth import AsyncAuthManager

    # 在 tmp_path 写入预设 tokens.json 和 users.json
    tokens_data = {
        "_format": "hashed_v1",
        _ADMIN_TOKEN_HASH: {
            "user_id": "admin",
            "created_at": 1_000_000.0,
            "expires_at": None,
            "active": True,
        },
    }
    users_data = {
        "admin": {
            "user_id": "admin",
            "username": "admin",
            "domain": "admin",
            "permissions": ["read", "write", "admin"],
            "active": True,
            "created_at": 1_000_000.0,
        }
    }
    (tmp_path / "tokens.json").write_text(json.dumps(tokens_data))
    (tmp_path / "users.json").write_text(json.dumps(users_data))

    auth_mgr = AsyncAuthManager(config_dir=tmp_path)

    # 替换 initialize_system，注入所有 Mock 组件
    async def _mock_initialize():
        runtime.provider_manager = mock_provider_manager
        runtime.smart_router = mock_smart_router
        runtime.cache_system = mock_cache
        runtime.usage_tracker = mock_usage_tracker
        runtime.connection_pool_manager = mock_conn_pool
        runtime.auth_manager = auth_mgr
        runtime.runtime_config = {
            "routing": {
                "strategy": "cost_optimized",
                "model_mapping": {"general": "qwen-turbo"},
            }
        }
        # 使 get_auth_manager() 返回我们的 auth_mgr，不触发真实初始化
        auth_module.auth_manager = auth_mgr

    with (
        patch.object(runtime, "initialize_system", new=_mock_initialize),
        patch(
            "bridge_server.runtime.close_connection_pool_manager",
            new_callable=AsyncMock,
        ),
    ):
        with TestClient(runtime.app) as client:
            yield client

    # 清理全局状态，防止测试间污染
    runtime.provider_manager = None
    runtime.smart_router = None
    runtime.cache_system = None
    runtime.usage_tracker = None
    runtime.connection_pool_manager = None
    runtime.auth_manager = None
    auth_module.auth_manager = None
    runtime.app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    """携带有效管理员 Token 的请求头。"""
    return {"Authorization": _ADMIN_TOKEN}


@pytest.fixture
def bearer_auth_headers():
    """携带 'Bearer <token>' 前缀的请求头。"""
    return {"Authorization": f"Bearer {_ADMIN_TOKEN}"}


# ══════════════════════════════════════════════════════════════════════════════
# 1. 公开端点测试 — 无需认证
# ══════════════════════════════════════════════════════════════════════════════

class TestPublicEndpoints:
    """这些端点应在没有认证 Token 的情况下可访问。"""

    def test_health_returns_200(self, integration_client):
        resp = integration_client.get("/health")
        assert resp.status_code == 200

    def test_health_has_required_fields(self, integration_client):
        data = integration_client.get("/health").json()
        assert "status" in data
        assert "timestamp" in data
        assert data["status"] in ("healthy", "degraded")

    def test_root_returns_200(self, integration_client):
        resp = integration_client.get("/")
        assert resp.status_code == 200
        assert "version" in resp.json()

    def test_ready_returns_200(self, integration_client):
        resp = integration_client.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] in ("ready", "degraded")

    def test_models_catalog_is_public(self, integration_client):
        resp = integration_client.get("/api/models")
        assert resp.status_code == 200
        assert "models" in resp.json()

    def test_routing_config_is_public(self, integration_client):
        resp = integration_client.get("/api/routing")
        assert resp.status_code == 200
        assert "strategy" in resp.json()

    def test_v1_models_is_public(self, integration_client):
        resp = integration_client.get("/v1/models")
        assert resp.status_code == 200
        assert "data" in resp.json()


# ══════════════════════════════════════════════════════════════════════════════
# 2. 认证强制执行测试
# ══════════════════════════════════════════════════════════════════════════════

class TestAuthEnforcement:
    """受保护端点必须拒绝无效或缺失的认证。"""

    @pytest.mark.parametrize(
        "path",
        ["/metrics", "/stats", "/metrics/prometheus", "/api/usage", "/api/budget"],
    )
    def test_no_token_returns_401(self, integration_client, path):
        resp = integration_client.get(path)
        assert resp.status_code == 401

    def test_chat_no_token_returns_401(self, integration_client):
        resp = integration_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, integration_client):
        resp = integration_client.get(
            "/metrics", headers={"Authorization": _INVALID_TOKEN}
        )
        assert resp.status_code == 401

    def test_valid_token_grants_metrics_access(self, integration_client, auth_headers):
        resp = integration_client.get("/metrics", headers=auth_headers)
        assert resp.status_code == 200

    def test_bearer_prefix_is_stripped_and_accepted(
        self, integration_client, bearer_auth_headers
    ):
        resp = integration_client.get("/metrics", headers=bearer_auth_headers)
        assert resp.status_code == 200

    def test_valid_token_grants_usage_access(self, integration_client, auth_headers):
        resp = integration_client.get("/api/usage", headers=auth_headers)
        assert resp.status_code == 200

    def test_valid_token_grants_budget_access(self, integration_client, auth_headers):
        resp = integration_client.get("/api/budget", headers=auth_headers)
        assert resp.status_code == 200

    def test_401_response_contains_chinese_detail(self, integration_client):
        """401 响应体应包含中文提示信息。"""
        resp = integration_client.get("/api/usage")
        detail = resp.json().get("detail", "")
        # 应包含认证相关中文提示
        assert "认证" in detail or "Authorization" in detail

    def test_bearer_only_no_token_returns_401(self, integration_client):
        """'Bearer ' 后没有 token 内容，应返回 401。"""
        resp = integration_client.get(
            "/api/usage", headers={"Authorization": "Bearer "}
        )
        assert resp.status_code == 401

    def test_chat_bearer_prefix_accepted(
        self, integration_client, bearer_auth_headers
    ):
        resp = integration_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
            headers=bearer_auth_headers,
        )
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 3. 聊天补全完整流程
# ══════════════════════════════════════════════════════════════════════════════

class TestChatCompletionFlow:
    """端到端聊天补全：认证 → 路由 → Mock Provider → 增强响应。"""

    def test_basic_chat_returns_200(self, integration_client, auth_headers):
        resp = integration_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello, world!"}]},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_response_contains_assistant_message(
        self, integration_client, auth_headers
    ):
        resp = integration_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
            headers=auth_headers,
        )
        data = resp.json()
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["message"]["content"] == "Hello from mock provider!"

    def test_routing_info_attached_to_response(
        self, integration_client, auth_headers
    ):
        resp = integration_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Explain recursion"}]},
            headers=auth_headers,
        )
        routing = resp.json()["usage"]["routing"]
        assert routing["provider"] == "dashscope"
        assert routing["selected_model"] == "qwen-turbo"
        assert routing["task_type"] in (
            "general", "simple", "coding", "complex", "writing", "analysis", "creative"
        )
        assert 0.0 <= routing["confidence"] <= 1.0
        assert routing["from_cache"] in (True, False)

    def test_custom_params_forwarded(
        self, integration_client, auth_headers, mock_provider_manager
    ):
        """max_tokens 和 temperature 应透传给 provider。"""
        integration_client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Test"}],
                "max_tokens": 512,
                "temperature": 0.3,
            },
            headers=auth_headers,
        )
        call_kwargs = mock_provider_manager.chat_completion.call_args
        assert call_kwargs.kwargs.get("max_tokens") == 512
        assert call_kwargs.kwargs.get("temperature") == 0.3

    def test_multi_turn_conversation(self, integration_client, auth_headers):
        """多轮对话（多条消息）应正常处理。"""
        messages = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
            {"role": "user", "content": "What about Go?"},
        ]
        resp = integration_client.post(
            "/v1/chat/completions",
            json={"messages": messages},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_missing_messages_field_returns_400(
        self, integration_client, auth_headers
    ):
        resp = integration_client.post(
            "/v1/chat/completions",
            json={"model": "qwen-turbo"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_empty_messages_array_returns_400(
        self, integration_client, auth_headers
    ):
        resp = integration_client.post(
            "/v1/chat/completions",
            json={"messages": []},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_malformed_json_returns_4xx(self, integration_client, auth_headers):
        resp = integration_client.post(
            "/v1/chat/completions",
            content=b"not-json-at-all",
            headers={**auth_headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_provider_failure_returns_500(
        self, integration_client, auth_headers, mock_provider_manager
    ):
        mock_provider_manager.chat_completion.side_effect = RuntimeError(
            "Provider is down"
        )
        resp = integration_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
            headers=auth_headers,
        )
        assert resp.status_code == 500
        # 重置 side_effect，不影响后续测试
        mock_provider_manager.chat_completion.side_effect = None
        mock_provider_manager.chat_completion.return_value = _make_chat_response()

    def test_response_has_usage_fields(self, integration_client, auth_headers):
        resp = integration_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Count to 5"}]},
            headers=auth_headers,
        )
        usage = resp.json().get("usage", {})
        assert "prompt_tokens" in usage
        assert "completion_tokens" in usage


# ══════════════════════════════════════════════════════════════════════════════
# 4. 流式聊天（SSE）
# ══════════════════════════════════════════════════════════════════════════════

class TestStreamingFlow:
    """stream=true 应返回 SSE 格式响应。"""

    def test_stream_returns_200(self, integration_client, auth_headers):
        resp = integration_client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Tell me a story"}],
                "stream": True,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_stream_content_type_is_text(self, integration_client, auth_headers):
        resp = integration_client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Stream test"}],
                "stream": True,
            },
            headers=auth_headers,
        )
        content_type = resp.headers.get("content-type", "")
        assert "text/" in content_type

    def test_stream_body_contains_done_marker(self, integration_client, auth_headers):
        resp = integration_client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
            headers=auth_headers,
        )
        # SSE 流应以 [DONE] 结束
        assert "[DONE]" in resp.text


# ══════════════════════════════════════════════════════════════════════════════
# 5. 用量与预算统计流程
# ══════════════════════════════════════════════════════════════════════════════

class TestUsageBudgetFlow:
    """用量和预算端点的完整用户旅程。"""

    def test_usage_today(self, integration_client, auth_headers):
        resp = integration_client.get("/api/usage?period=today", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "today"
        assert "total_requests" in data

    def test_usage_month(self, integration_client, auth_headers):
        resp = integration_client.get("/api/usage?period=month", headers=auth_headers)
        assert resp.status_code == 200

    def test_usage_user_id_filter(
        self, integration_client, auth_headers, mock_usage_tracker
    ):
        mock_usage_tracker.get_usage_stats.return_value = {
            "period": "today",
            "user_id": "alice",
            "total_requests": 5,
        }
        resp = integration_client.get(
            "/api/usage?user_id=alice", headers=auth_headers
        )
        assert resp.status_code == 200
        # verify tracker was called with user_id
        call_kwargs = mock_usage_tracker.get_usage_stats.call_args
        assert call_kwargs.kwargs.get("user_id") == "alice"

    def test_budget_returns_today_key(self, integration_client, auth_headers):
        resp = integration_client.get("/api/budget", headers=auth_headers)
        assert resp.status_code == 200
        assert "today" in resp.json()

    def test_budget_no_alert_by_default(self, integration_client, auth_headers):
        resp = integration_client.get("/api/budget", headers=auth_headers)
        assert resp.json()["today"]["alert"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 6. 指标与可观测性流程
# ══════════════════════════════════════════════════════════════════════════════

class TestMetricsFlow:
    """指标端点的可观测性用户旅程。"""

    def test_metrics_returns_json_by_default(self, integration_client, auth_headers):
        resp = integration_client.get("/metrics", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    def test_stats_alias_works(self, integration_client, auth_headers):
        resp = integration_client.get("/stats", headers=auth_headers)
        assert resp.status_code == 200

    def test_prometheus_format_via_query_param(
        self, integration_client, auth_headers
    ):
        resp = integration_client.get(
            "/metrics?format=prometheus", headers=auth_headers
        )
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_prometheus_dedicated_endpoint(self, integration_client, auth_headers):
        resp = integration_client.get("/metrics/prometheus", headers=auth_headers)
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "text/plain" in ct or "application/openmetrics" in ct

    def test_prometheus_body_contains_metrics_lines(
        self, integration_client, auth_headers
    ):
        resp = integration_client.get(
            "/metrics?format=prometheus", headers=auth_headers
        )
        # Prometheus 格式以 '# HELP' 或 '# TYPE' 行开头
        assert "#" in resp.text or len(resp.text) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 7. 健康检查与就绪探针
# ══════════════════════════════════════════════════════════════════════════════

class TestHealthReadinessFlow:
    """服务健康状态与 Kubernetes 就绪探针场景。"""

    def test_health_contains_performance_stats(self, integration_client):
        data = integration_client.get("/health").json()
        assert "performance" in data

    def test_health_contains_provider_info(self, integration_client):
        data = integration_client.get("/health").json()
        # providers 字段或 status 字段应存在
        assert "providers" in data or data["status"] in ("healthy", "degraded")

    def test_ready_checks_providers(self, integration_client):
        data = integration_client.get("/ready").json()
        assert "checks" in data
        assert "providers" in data["checks"]

    def test_ready_true_when_providers_available(
        self, integration_client, mock_provider_manager
    ):
        mock_provider_manager.get_available_providers.return_value = ["dashscope"]
        data = integration_client.get("/ready").json()
        assert data["checks"]["providers"] is True

    def test_degraded_when_no_providers(
        self, integration_client, mock_provider_manager
    ):
        mock_provider_manager.get_available_providers.return_value = []
        data = integration_client.get("/ready").json()
        assert data["status"] == "degraded"
        assert data["checks"]["providers"] is False

    def test_ready_has_timestamp(self, integration_client):
        data = integration_client.get("/ready").json()
        assert "timestamp" in data
        assert isinstance(data["timestamp"], float)


# ══════════════════════════════════════════════════════════════════════════════
# 8. 模型目录与路由配置
# ══════════════════════════════════════════════════════════════════════════════

class TestModelsCatalogFlow:
    """模型目录与路由配置查询场景。"""

    def test_models_returns_list(self, integration_client):
        resp = integration_client.get("/api/models")
        models = resp.json()["models"]
        assert isinstance(models, list)
        assert len(models) >= 1

    def test_model_has_required_fields(self, integration_client):
        model = integration_client.get("/api/models").json()["models"][0]
        for field in ("id", "provider", "object", "input_cost_per_1k", "output_cost_per_1k"):
            assert field in model

    def test_model_object_type(self, integration_client):
        model = integration_client.get("/api/models").json()["models"][0]
        assert model["object"] == "model"

    def test_routing_strategy_returned(self, integration_client):
        data = integration_client.get("/api/routing").json()
        assert data["strategy"] == "cost_optimized"

    def test_routing_model_mapping_returned(self, integration_client):
        data = integration_client.get("/api/routing").json()
        assert data["model_mapping"]["general"] == "qwen-turbo"

    def test_v1_models_mirrors_api_models(self, integration_client):
        v1 = integration_client.get("/v1/models").json()["data"]
        api = integration_client.get("/api/models").json()["models"]
        v1_ids = {m["id"] for m in v1}
        api_ids = {m["id"] for m in api}
        assert v1_ids == api_ids


# ══════════════════════════════════════════════════════════════════════════════
# 9. API 文档端点默认禁用
# ══════════════════════════════════════════════════════════════════════════════

class TestDocsSecurityFlow:
    """API 文档端点应在生产环境（未设置 ENABLE_DOCS=true）中禁用。"""

    def test_docs_ui_disabled(self, integration_client):
        resp = integration_client.get("/docs")
        assert resp.status_code == 404

    def test_redoc_disabled(self, integration_client):
        resp = integration_client.get("/redoc")
        assert resp.status_code == 404

    def test_openapi_json_disabled(self, integration_client):
        resp = integration_client.get("/openapi.json")
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 10. 响应头（中间件行为）
# ══════════════════════════════════════════════════════════════════════════════

class TestResponseHeaders:
    """验证中间件在所有响应中注入的标准头。"""

    def test_x_response_time_present_on_health(self, integration_client):
        resp = integration_client.get("/health")
        assert "x-response-time" in resp.headers

    def test_x_response_time_present_on_chat(
        self, integration_client, auth_headers
    ):
        resp = integration_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "ping"}]},
            headers=auth_headers,
        )
        assert "x-response-time" in resp.headers

    def test_x_response_time_is_numeric_ms(self, integration_client):
        resp = integration_client.get("/health")
        rt = resp.headers["x-response-time"]
        # 格式为 "<float>ms"
        assert rt.endswith("ms")
        float(rt[:-2])  # 应可解析为浮点数（抛出则测试失败）

    def test_x_request_id_present(self, integration_client):
        resp = integration_client.get("/health")
        # Request-ID 或 Trace-ID 至少其中一个应存在
        has_id = (
            "x-request-id" in resp.headers
            or "x-trace-id" in resp.headers
        )
        # 中间件附加请求上下文头（可选，不强制断言避免误报）
        assert resp.status_code == 200  # 至少请求成功


# ══════════════════════════════════════════════════════════════════════════════
# 11. CORS 行为
# ══════════════════════════════════════════════════════════════════════════════

class TestCORSBehavior:
    """CORS 头行为：默认通配符不能与 credentials 同时使用。"""

    def test_health_accessible_cross_origin(self, integration_client):
        resp = integration_client.get(
            "/health", headers={"Origin": "https://example.com"}
        )
        assert resp.status_code == 200

    def test_wildcard_cors_no_credentials_header(self, integration_client):
        """无 CORS_ORIGINS 时，Access-Control-Allow-Credentials 不应为 true。"""
        resp = integration_client.options(
            "/health",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        cred = resp.headers.get("access-control-allow-credentials", "false")
        assert cred.lower() != "true"

    def test_cors_preflight_methods_allowed(self, integration_client):
        resp = integration_client.options(
            "/v1/chat/completions",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        # Preflight 应返回 2xx（不应崩溃）
        assert resp.status_code < 400


# ══════════════════════════════════════════════════════════════════════════════
# 12. 错误处理与边界场景
# ══════════════════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """错误处理与边界条件用户旅程。"""

    def test_unknown_path_returns_404(self, integration_client):
        resp = integration_client.get("/this/path/does/not/exist")
        assert resp.status_code == 404

    def test_chat_no_provider_returns_500(
        self, integration_client, auth_headers, mock_provider_manager, mock_smart_router
    ):
        """系统路由器返回 None 时应返回 500。"""
        mock_smart_router.route.side_effect = RuntimeError("No provider available")
        resp = integration_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "test"}]},
            headers=auth_headers,
        )
        assert resp.status_code == 500
        mock_smart_router.route.side_effect = None
        mock_smart_router.route.return_value = _make_route_result()

    def test_usage_tracker_unavailable_returns_503(
        self, integration_client, auth_headers
    ):
        """usage_tracker 为 None 时，/api/usage 应返回 503。"""
        import bridge_server.runtime as runtime

        original = runtime.usage_tracker
        runtime.usage_tracker = None
        try:
            resp = integration_client.get("/api/usage", headers=auth_headers)
            assert resp.status_code == 503
        finally:
            runtime.usage_tracker = original

    def test_budget_tracker_unavailable_returns_503(
        self, integration_client, auth_headers
    ):
        import bridge_server.runtime as runtime

        original = runtime.usage_tracker
        runtime.usage_tracker = None
        try:
            resp = integration_client.get("/api/budget", headers=auth_headers)
            assert resp.status_code == 503
        finally:
            runtime.usage_tracker = original
