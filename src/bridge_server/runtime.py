#!/usr/bin/env python3
"""
Bridge Server v2.0 - 阶段2异步优化版本
目标：30-50 QPS (Step 1)
"""

import asyncio
import inspect
import json
import logging
import os
import time
import importlib.util
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import yaml

# 启动时加载 .env 文件（~/.bridge-server/.env）
try:
    from dotenv import load_dotenv
    _env_file = Path.home() / ".bridge-server" / ".env"
    if _env_file.exists():
        load_dotenv(_env_file, override=False)
except ImportError:
    pass

from fastapi import FastAPI, Request, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# 核心系统
from .providers import (
    ProviderManager, ProviderConfig, RoutingStrategy,
    DashScopeProvider, OpenAIProvider, MoonshotProvider
)
from .observability import (
    PROMETHEUS_MEDIA_TYPE,
    PerformanceMonitor,
    attach_response_context,
    bind_llm_context,
    bind_request_context,
    bind_user_context,
    build_runtime_snapshot,
    clear_request_context,
    extract_request_context,
    get_logger,
    get_metrics_collector,
    render_prometheus_metrics,
    setup_structured_logging,
)
from .services.routing import RouteResult, SmartRouter
from .services.savings import estimate_baseline_cost_rmb, estimate_model_cost_usd, resolve_baseline_model
from .services.model_info import ModelInfoAggregator, set_model_info_aggregator, get_model_info_aggregator
from .services.router_registry import RouterRegistry, set_router_registry, get_router_registry
from .router_sdk import RoutingContext, RoutingDecision
from .utils.cache import HybridCache
from .utils.connection_pools import close_connection_pool_manager, get_connection_pool_manager
from .services.bypass_router import BypassRouter, get_bypass_router, set_bypass_router

# 异步模块
from .auth import get_auth_manager, get_current_user_async, AsyncAuthManager
from .usage import UsageTrackerAsync, record_usage_async

# 配置日志
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
setup_structured_logging(service_name="bridge-server", version="2.1.0-async", level=log_level)
logger = get_logger(__name__)


# 全局组件
provider_manager: Optional[ProviderManager] = None
smart_router: Optional[SmartRouter] = None
cache_system: Optional[HybridCache] = None
usage_tracker: Optional[UsageTrackerAsync] = None
auth_manager: Optional[AsyncAuthManager] = None
runtime_config: Dict[str, Any] = {}
model_info_aggregator: Optional[ModelInfoAggregator] = None
router_registry_instance: Optional[RouterRegistry] = None


def _resolve_config_dir() -> Path:
    """Resolve config dir from env vars with backward compatibility."""
    for env_name in ("BRIDGE_SERVER_CONFIG_DIR", "BRIDGE_CONFIG_DIR"):
        env_value = os.getenv(env_name)
        if env_value:
            return Path(env_value)
    return Path.home() / ".bridge-server"


def _resolve_provider_routing_strategy(config: Dict[str, Any]) -> RoutingStrategy:
    """Map user-facing routing config to ProviderManager strategies."""
    configured = str(config.get("routing", {}).get("strategy", "fallback")).strip().lower()
    mapping = {
        "fallback": RoutingStrategy.MANUAL,
        "priority": RoutingStrategy.MANUAL,
        "manual": RoutingStrategy.MANUAL,
        "round_robin": RoutingStrategy.ROUND_ROBIN,
        "load_balance": RoutingStrategy.LOWEST_LATENCY,
        "lowest_latency": RoutingStrategy.LOWEST_LATENCY,
        "cost_optimized": RoutingStrategy.COST_OPTIMIZED,
    }
    return mapping.get(configured, RoutingStrategy.MANUAL)


# provider name → provider_type 映射（已知的专用 provider）
_PROVIDER_TYPE_MAP = {
    "dashscope": "dashscope",
    "moonshot": "moonshot",
}

_OPENAI_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"

def _build_providers_config(config: Dict[str, Any]) -> List[ProviderConfig]:
    """从 config.yaml 的 providers 列表动态构建 ProviderConfig。

    每条 provider 配置格式：
      name: dashscope
      base_url: https://...
      api_key_env: DASHSCOPE_API_KEY   # 从环境变量读取
      api_key: sk-xxx                  # 或直接内嵌（自定义 provider）
      models: [...]
    """
    yaml_providers = config.get("providers", [])

    # 若 config.yaml 中没有 providers 段，回退到环境变量兜底
    if not yaml_providers:
        logger.info("config.yaml 中无 providers 配置，回退到环境变量兜底")
        return _fallback_providers_config()

    result: List[ProviderConfig] = []
    for idx, p in enumerate(yaml_providers):
        name = p.get("name", f"provider_{idx}")
        base_url = p.get("base_url", "")
        auth_type = p.get("auth_type", "api_key")

        if auth_type == "oauth":
            oauth_cfg = dict(p.get("oauth") or {})
            is_codex_oauth = oauth_cfg.get("provider") == "openai_codex"
            if is_codex_oauth and not oauth_cfg.get("auth_store_key"):
                oauth_cfg["auth_store_key"] = name
            resolved_base_url = base_url
            if is_codex_oauth and (not resolved_base_url or resolved_base_url.rstrip("/") == "https://api.openai.com/v1"):
                resolved_base_url = str(oauth_cfg.get("base_url") or _OPENAI_CODEX_BASE_URL)
            if is_codex_oauth:
                enabled = bool(
                    oauth_cfg.get("token_url")
                    and oauth_cfg.get("client_id")
                    and oauth_cfg.get("auth_store_key")
                )
            else:
                enabled = bool(
                    oauth_cfg.get("token_url")
                    and oauth_cfg.get("client_id")
                    and oauth_cfg.get("client_secret")
                )
            if not enabled:
                logger.debug(f"Provider '{name}' OAuth 配置不完整，跳过")
                continue

            provider_type = _PROVIDER_TYPE_MAP.get(name, "openai")
            result.append(ProviderConfig(
                provider_type=provider_type,
                config={
                    "id": name,
                    "base_url": resolved_base_url,
                    "auth_type": "oauth",
                    "oauth": oauth_cfg,
                    "models": [m.get("id") for m in p.get("models", []) if m.get("id")],
                    "timeout": p.get("timeout", 120.0),
                },
                weight=max(1, len(yaml_providers) - idx),
                priority=idx + 1,
                enabled=True,
            ))
            logger.info(f"✓ 从 config.yaml 读取 OAuth Provider: {name} ({provider_type})")
            continue

        # Standard api_key provider
        # 解析 API Key：优先 api_key_env，其次 api_key 直接值
        api_key_env = p.get("api_key_env", "")
        api_key = os.getenv(api_key_env) if api_key_env else None
        if not api_key:
            api_key = p.get("api_key", "")

        provider_type = _PROVIDER_TYPE_MAP.get(name, "openai")
        enabled = bool(api_key)

        if not enabled:
            logger.debug(f"Provider '{name}' 未配置 API Key，跳过")
            continue

        result.append(ProviderConfig(
            provider_type=provider_type,
            config={
                "id": name,
                "api_key": api_key,
                "base_url": base_url,
                "models": [m.get("id") for m in p.get("models", []) if m.get("id")],
                "timeout": p.get("timeout", 120.0),  # 默认 120s，支持 thinking 类模型
            },
            weight=max(1, len(yaml_providers) - idx),
            priority=idx + 1,
            enabled=True,
        ))
        logger.info(f"✓ 从 config.yaml 读取 Provider: {name} ({provider_type})")

    return result


def _fallback_providers_config() -> List[ProviderConfig]:
    """环境变量兜底配置（当 config.yaml 无 providers 时使用）。"""
    return [
        ProviderConfig(
            provider_type="dashscope",
            config={"id": "dashscope", "api_key": os.getenv("DASHSCOPE_API_KEY"),
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
            weight=3, priority=1, enabled=bool(os.getenv("DASHSCOPE_API_KEY"))
        ),
        ProviderConfig(
            provider_type="openai",
            config={"id": "openai", "api_key": os.getenv("OPENAI_API_KEY"),
                    "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")},
            weight=2, priority=2, enabled=bool(os.getenv("OPENAI_API_KEY"))
        ),
        ProviderConfig(
            provider_type="moonshot",
            config={"id": "moonshot", "api_key": os.getenv("MOONSHOT_API_KEY"),
                    "base_url": "https://api.moonshot.cn/v1"},
            weight=1, priority=3, enabled=bool(os.getenv("MOONSHOT_API_KEY"))
        ),
    ]


perf_monitor = PerformanceMonitor()
metrics_collector = get_metrics_collector()
connection_pool_manager = None


async def load_config_async() -> Dict[str, Any]:
    """异步加载配置"""
    config_paths = [
        _resolve_config_dir() / "config.yaml",
        Path(__file__).resolve().parents[2] / "config.yaml.example"
    ]
    
    for config_path in config_paths:
        if config_path.exists():
            def _load():
                with open(config_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _load)
    
    logger.warning("未找到配置文件，使用默认配置")
    return {}


async def initialize_system():
    """初始化系统组件"""
    global provider_manager, smart_router, cache_system, usage_tracker, auth_manager, connection_pool_manager, runtime_config, model_info_aggregator, router_registry_instance
    
    logger.info("🚀 Bridge Server v2.0 系统初始化...")
    runtime_config = await load_config_async()
    
    # 0. 初始化连接池
    logger.info("初始化连接池...")
    connection_pool_manager = await get_connection_pool_manager()
    
    # 1. 初始化缓存系统
    logger.info("初始化缓存系统...")
    redis_url = os.getenv("REDIS_URL")
    cache_system = HybridCache(
        redis_url=redis_url,
        l1_maxsize=2000,
        l1_ttl=300,  # 5分钟
        l2_ttl=1800,  # 30分钟 
        key_prefix="bridge:v2:"
    )
    
    # 2. 初始化认证管理器
    logger.info("初始化认证系统...")
    auth_manager = AsyncAuthManager()
    await auth_manager.initialize()
    
    # 3. 初始化用量跟踪
    logger.info("初始化用量跟踪...")
    usage_tracker = UsageTrackerAsync()
    await usage_tracker.initialize()
    
    # 4. 初始化Provider管理器
    logger.info("初始化Provider系统...")
    provider_manager = ProviderManager(routing_strategy=_resolve_provider_routing_strategy(runtime_config))
    
    # 从 config.yaml 动态加载 providers，兜底使用环境变量硬编码
    providers_config = _build_providers_config(runtime_config)
    
    added_count = 0
    for config in providers_config:
        if config.enabled:
            success = await provider_manager.add_provider(config)
            if success:
                added_count += 1
                logger.info(f"✓ Provider {config.config['id']} 添加成功")
            else:
                logger.warning(f"✗ Provider {config.config['id']} 添加失败")
    
    logger.info(f"Provider系统初始化完成，{added_count} 个可用")
    
    # 5. 初始化智能路由
    logger.info("初始化智能路由...")
    scenarios = runtime_config.get("scenarios", {})
    smart_router = SmartRouter(scenarios, cache_system)
    
    # 6. 系统健康检查
    logger.info("执行系统健康检查...")
    if provider_manager:
        health_results = await provider_manager.health_check_all()
        healthy_count = sum(1 for status in health_results.values() if status.value == "healthy")
        logger.info(f"健康检查完成: {healthy_count}/{len(health_results)} 个Provider健康")
    
    logger.info("✅ 系统初始化完成")

    # 7. 初始化自定义路由框架
    logger.info("初始化自定义路由框架...")
    config_dir = _resolve_config_dir()
    model_info_aggregator = ModelInfoAggregator(config_dir=config_dir)
    set_model_info_aggregator(model_info_aggregator)
    await model_info_aggregator.start()

    router_registry_instance = RouterRegistry(routers_dir=config_dir / "routers")
    set_router_registry(router_registry_instance)

    active = router_registry_instance.get_active()
    if active:
        logger.info(f"自定义路由器 '{active}' 已加载")
    else:
        logger.info("无激活的自定义路由器，使用内置 SmartRouter")

    # 8. 初始化旁路模型路由器
    bypass_cfg = runtime_config.get("bypass_router", {})
    bypass_router_inst = BypassRouter(bypass_cfg)
    set_bypass_router(bypass_router_inst)
    logger.info(
        "旁路模型路由器已初始化",
        enabled=bypass_router_inst.enabled,
        routing_model=bypass_router_inst.routing_model or "(未配置)",
    )


# FastAPI应用
# Disable interactive API docs in production (set ENABLE_DOCS=true only for dev).
_enable_docs = os.getenv("ENABLE_DOCS", "false").lower() == "true"
app = FastAPI(
    title="Bridge Server v2.0",
    description="高性能AI Gateway - 异步优化版",
    version="2.0.0-async",
    docs_url="/docs" if _enable_docs else None,
    redoc_url="/redoc" if _enable_docs else None,
    openapi_url="/openapi.json" if _enable_docs else None,
)

# CORS middleware: credentials can only be used with explicit origin allowlist.
# Set CORS_ORIGINS env var to a comma-separated list of allowed origins to enable.
_cors_origins_raw = os.getenv("CORS_ORIGINS", "").strip()
_cors_origins: list = (
    [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
    if _cors_origins_raw
    else []
)
# Wildcard origins must not be paired with allow_credentials=True (browser spec).
_allow_credentials = bool(_cors_origins) and "*" not in _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 限流器（异步优化）
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Mount admin API
from .admin_api import router as admin_router
app.include_router(admin_router)

# Mount web UI static files
_web_dir = Path(__file__).parent.parent.parent / "web"
if _web_dir.exists():
    app.mount("/ui", StaticFiles(directory=str(_web_dir), html=True), name="ui")


async def require_auth(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """FastAPI dependency: reject requests without a valid auth token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="认证必须：请提供 Authorization header")
    auth_mgr = await get_auth_manager()
    token_info = await auth_mgr.verify_token(authorization)
    if not token_info:
        raise HTTPException(status_code=401, detail="无效或已过期的认证令牌")
    return token_info


def _ensure_model_allowed(
    token_info: Dict[str, Any],
    provider_id: str,
    model_id: str,
    requested_model: Optional[str] = None,
) -> None:
    """Enforce per-external-api-key model permissions."""
    if token_info.get("type") != "external_api_key":
        return

    permissions = token_info.get("model_permissions") or []
    full_model = f"{provider_id}/{model_id}"
    requested = str(requested_model or "").strip()
    allowed = {"*", full_model, model_id, f"{provider_id}/*"}
    if not requested or requested == "smart":
        allowed.add("smart")
    if not any(str(item).strip() in allowed for item in permissions):
        raise HTTPException(
            status_code=403,
            detail=f"API Key 无权访问模型 {full_model}",
        )


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """Observability middleware for tracing, metrics, and structured request logs."""
    start_time = time.perf_counter()
    request_context = extract_request_context(request.headers)
    endpoint = request.url.path
    status_code = 500
    response = None

    bind_request_context(
        request_id=request_context["request_id"],
        trace_id=request_context["trace_id"],
        method=request.method,
        path=endpoint,
        client_ip=request.client.host if request.client else None,
    )
    metrics_collector.increase_inflight(endpoint)

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception:
        logger.exception("http_request_failed", method=request.method, path=endpoint)
        raise
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000
        await perf_monitor.record_request(duration_ms, status_code < 500)
        metrics_collector.decrease_inflight(endpoint)
        metrics_collector.record_http_request(
            request.method,
            endpoint,
            status_code,
            duration_ms / 1000,
        )

        if response is not None:
            response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
            attach_response_context(response, request_context)

        logger.info(
            "http_request_completed",
            method=request.method,
            path=endpoint,
            status_code=status_code,
            duration_ms=round(duration_ms, 2),
        )
        clear_request_context()


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    await initialize_system()


@app.on_event("shutdown") 
async def shutdown_event():
    """应用关闭事件"""
    logger.info("🛑 Bridge Server v2.0 关闭中...")
    
    # 清理资源
    cleanup_tasks = []
    
    if provider_manager and hasattr(provider_manager, "cleanup"):
        provider_cleanup = provider_manager.cleanup()
        if inspect.isawaitable(provider_cleanup):
            cleanup_tasks.append(provider_cleanup)
    
    if cache_system and hasattr(cache_system, "close"):
        cache_cleanup = cache_system.close()
        if inspect.isawaitable(cache_cleanup):
            cleanup_tasks.append(cache_cleanup)
        
    if usage_tracker and hasattr(usage_tracker, "close"):
        usage_cleanup = usage_tracker.close()
        if inspect.isawaitable(usage_cleanup):
            cleanup_tasks.append(usage_cleanup)

    if model_info_aggregator:
        cleanup_tasks.append(model_info_aggregator.stop())
    
    if cleanup_tasks:
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)
    
    await close_connection_pool_manager()
    
    logger.info("✅ 系统关闭完成")


@app.get("/")
async def root():
    """根路径 - 重定向到管理面板"""
    _web = Path(__file__).parent.parent.parent / "web"
    if _web.exists():
        return RedirectResponse(url="/ui")
    return {"message": "Bridge Server v2.0", "version": "2.0.0-async"}


@app.get("/health")
async def health_check():
    """健康检查"""
    health_data = {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "2.0.0-async"
    }
    
    # 并发健康检查
    health_tasks = []
    
    # Provider健康检查
    if provider_manager and hasattr(provider_manager, "health_check_all"):
        health_tasks.append(provider_manager.health_check_all())
    
    # 缓存健康检查
    if cache_system:
        health_tasks.append(cache_system.health_check())
    
    if connection_pool_manager:
        health_tasks.append(connection_pool_manager.health_check())
    
    if health_tasks:
        try:
            results = await asyncio.gather(*health_tasks, return_exceptions=True)
            
            if len(results) >= 1 and not isinstance(results[0], Exception):
                health_data["providers"] = {
                    pid: status.value if hasattr(status, "value") else status
                    for pid, status in results[0].items()
                }
                metrics_collector.set_provider_health(health_data["providers"])
            
            if len(results) >= 2 and not isinstance(results[1], Exception):
                health_data["cache"] = results[1]
            
            if len(results) >= 3 and not isinstance(results[2], Exception):
                health_data["connection_pool"] = results[2]
                
        except Exception as e:
            logger.warning(f"健康检查部分失败: {str(e)}")
    
    # 性能统计
    health_data["performance"] = await perf_monitor.get_stats()
    
    if provider_manager and not provider_manager.get_available_providers():
        health_data["status"] = "degraded"
    if "connection_pool" in health_data and not health_data["connection_pool"].get("database", False):
        health_data["status"] = "degraded"
    
    return health_data


async def _collect_metrics_snapshot() -> Dict[str, Any]:
    return await build_runtime_snapshot(
        perf_monitor=perf_monitor,
        provider_manager=provider_manager,
        cache_system=cache_system,
        smart_router=smart_router,
        connection_pool_manager=connection_pool_manager,
        usage_tracker=usage_tracker,
    )


def _build_model_catalog() -> List[Dict[str, Any]]:
    """Build a user-facing model catalog from the active providers."""
    if not provider_manager:
        return [
            {
                "id": "smart",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "bridge-server",
                "provider": "bridge-server",
                "canonical_id": "smart",
                "is_alias": False,
            }
        ]

    models: List[Dict[str, Any]] = []
    created = int(time.time())
    bare_name_counts: Dict[str, int] = {}
    provider_models: List[Tuple[str, str, Any]] = []

    for provider_id, provider in provider_manager.providers.items():
        for model_id in provider.get_supported_models():
            bare_name_counts[model_id] = bare_name_counts.get(model_id, 0) + 1
            model_info = provider.get_model_info(model_id)
            provider_models.append((provider_id, model_id, model_info))

    models.append(
        {
            "id": "smart",
            "object": "model",
            "created": created,
            "owned_by": "bridge-server",
            "provider": "bridge-server",
            "canonical_id": "smart",
            "is_alias": False,
            "description": "Bridge Server smart routing pseudo-model",
        }
    )

    for provider_id, model_id, model_info in provider_models:
        canonical_id = f"{provider_id}/{model_id}"
        entry = {
            "id": canonical_id,
            "provider": provider_id,
            "object": "model",
            "created": created,
            "owned_by": provider_id,
            "canonical_id": canonical_id,
            "is_alias": False,
            "input_cost_per_1k": getattr(model_info, "input_cost_per_1k", None),
            "output_cost_per_1k": getattr(model_info, "output_cost_per_1k", None),
            "max_tokens": getattr(model_info, "max_tokens", None),
            "context_window": getattr(model_info, "context_window", None),
        }
        models.append(entry)

        if bare_name_counts.get(model_id) == 1:
            models.append(
                {
                    "id": model_id,
                    "provider": provider_id,
                    "object": "model",
                    "created": created,
                    "owned_by": provider_id,
                    "canonical_id": canonical_id,
                    "is_alias": True,
                    "input_cost_per_1k": getattr(model_info, "input_cost_per_1k", None),
                    "output_cost_per_1k": getattr(model_info, "output_cost_per_1k", None),
                    "max_tokens": getattr(model_info, "max_tokens", None),
                    "context_window": getattr(model_info, "context_window", None),
                }
            )

    return models


def _split_model_ref(model_ref: str) -> Tuple[Optional[str], str]:
    """Split a provider-qualified model ref while preserving slashes inside model IDs."""
    value = (model_ref or "").strip()
    if "/" not in value:
        return None, value
    provider_id, model_id = value.split("/", 1)
    return provider_id.strip() or None, model_id.strip()


# ── 空回合检测与兜底 ────────────────────────────────────────────────────────────

def _detect_empty_non_stream_turn(response: Dict[str, Any]) -> bool:
    """判断非流式响应是否为"空回合"：stop 但无可见内容、无 tool_calls。"""
    choice0 = (response.get("choices") or [{}])[0]
    message = choice0.get("message") or {}
    finish_reason = choice0.get("finish_reason")
    tool_calls = message.get("tool_calls") or []
    function_call = message.get("function_call")
    content = str(message.get("content") or "").strip()
    return (
        finish_reason in {"stop", None}
        and not tool_calls
        and not function_call
        and not content
    )


def _is_tool_followup(messages: List[Dict[str, Any]]) -> bool:
    """判断当前请求是否为工具执行后的 follow-up（最近一条非 system 消息为 tool）。"""
    for m in reversed(messages):
        role = m.get("role", "")
        if role == "system":
            continue
        return role == "tool"
    return False


def _build_empty_turn_retry_messages(
    messages: List[Dict[str, Any]], is_tool_followup: bool
) -> List[Dict[str, Any]]:
    """在原始消息列表末尾追加轻量指导系统提示，用于空回合重试。"""
    if is_tool_followup:
        guidance = (
            "You have already received the tool result. "
            "Now produce a concise user-facing answer based on that result. "
            "Do not call tools again unless absolutely necessary. "
            "Do not return an empty response."
        )
    else:
        guidance = (
            "Your previous response ended without any user-visible content. "
            "Return either: 1. a normal assistant reply, or 2. a structured tool call. "
            "Do not return an empty response."
        )
    return messages + [{"role": "system", "content": guidance}]


def _make_fallback_text(is_tool_followup: bool) -> str:
    """生成最小可见兜底文本。"""
    if is_tool_followup:
        return "工具已执行完成，但模型未生成最终回复。请重试一次。"
    return "上游模型本轮未返回有效内容，请重试一次。"


def _inject_fallback_into_response(response: Dict[str, Any], text: str) -> None:
    """将兜底文本注入非流式响应（就地修改）。"""
    choices = response.setdefault("choices", [{}])
    if not choices:
        choices.append({})
    message = choices[0].setdefault("message", {})
    message["content"] = text
    message["role"] = "assistant"
    choices[0]["finish_reason"] = "stop"


def _resolve_requested_model(model_ref: Optional[str], manager: ProviderManager) -> Optional[RouteResult]:
    """Resolve the OpenAI `model` field into a direct provider/model route.

    Returns None for missing or `smart`, which means the smart router should be used.
    """
    requested_model = str(model_ref or "").strip()
    if not requested_model or requested_model == "smart":
        return None

    provider_id, model_id = _split_model_ref(requested_model)
    all_models = manager.get_provider_models()

    if provider_id:
        if provider_id not in all_models:
            raise HTTPException(status_code=400, detail=f"未知 Provider: {provider_id}")
        if model_id not in all_models.get(provider_id, []):
            raise HTTPException(status_code=400, detail=f"Provider {provider_id} 不支持模型 {model_id}")
        return RouteResult(
            provider_id=provider_id,
            model=model_id,
            task_type="direct",
            confidence=1.0,
            reason=f"客户端指定模型: {provider_id}/{model_id}",
        )

    matches = [(pid, models) for pid, models in all_models.items() if model_id in models]
    if not matches:
        raise HTTPException(status_code=400, detail=f"未知模型: {model_id}")
    if len(matches) > 1:
        candidates = ", ".join(f"{pid}/{model_id}" for pid, _models in matches)
        raise HTTPException(status_code=400, detail=f"模型名不唯一，请使用 provider/model: {candidates}")

    matched_provider = matches[0][0]
    return RouteResult(
        provider_id=matched_provider,
        model=model_id,
        task_type="direct",
        confidence=1.0,
        reason=f"客户端指定裸模型名，匹配为: {matched_provider}/{model_id}",
    )


@app.get("/metrics")
@app.get("/stats")
async def get_metrics(format: str = "json", _auth: Dict[str, Any] = Depends(require_auth)):
    """获取系统指标（JSON 或 Prometheus）。"""
    snapshot = await _collect_metrics_snapshot()
    metrics_collector.observe_runtime_snapshot(snapshot)

    if format.lower() == "prometheus":
        return Response(
            content=render_prometheus_metrics(metrics_collector),
            media_type=PROMETHEUS_MEDIA_TYPE,
        )

    return snapshot


@app.get("/metrics/prometheus")
async def get_prometheus_metrics(_auth: Dict[str, Any] = Depends(require_auth)):
    """Prometheus 指标导出。"""
    snapshot = await _collect_metrics_snapshot()
    metrics_collector.observe_runtime_snapshot(snapshot)
    return Response(
        content=render_prometheus_metrics(metrics_collector),
        media_type=PROMETHEUS_MEDIA_TYPE,
    )


@app.get("/ready")
async def readiness_check():
    """Readiness probe with dependency-level checks."""
    health = await health_check()
    checks = {
        "providers": bool(provider_manager and provider_manager.get_available_providers()),
        "cache": health.get("cache", {}).get("overall", False),
        "database": health.get("connection_pool", {}).get("database", False),
    }

    return {
        "status": "ready" if all(checks.values()) else "degraded",
        "checks": checks,
        "timestamp": time.time(),
    }


@app.get("/api/models")
async def get_models_catalog():
    """Legacy-compatible model catalog endpoint."""
    return {"models": _build_model_catalog()}


@app.get("/api/routing")
async def get_routing_config():
    """Expose configured routing and the effective provider-manager strategy."""
    routing_config = runtime_config.get("routing", {})
    configured_strategy = routing_config.get("strategy", "fallback")
    effective_strategy = provider_manager.routing_strategy.value if provider_manager else _resolve_provider_routing_strategy(runtime_config).value
    return {
        "strategy": configured_strategy,
        "effective_strategy": effective_strategy,
        "model_mapping": routing_config.get("model_mapping", {}),
    }


@app.get("/api/usage")
async def get_usage(
    period: str = "today",
    user_id: Optional[str] = None,
    _auth: Dict[str, Any] = Depends(require_auth),
):
    """Legacy-compatible usage stats endpoint."""
    if not usage_tracker:
        raise HTTPException(status_code=503, detail="用量跟踪器未初始化")
    return await usage_tracker.get_usage_stats(period=period, user_id=user_id)


@app.get("/api/budget")
async def get_budget(
    user_id: Optional[str] = None,
    _auth: Dict[str, Any] = Depends(require_auth),
):
    """Legacy-compatible budget endpoint."""
    if not usage_tracker:
        raise HTTPException(status_code=503, detail="用量跟踪器未初始化")
    return await usage_tracker.get_budget_status(user_id=user_id)


@app.post("/v1/chat/completions")
@limiter.limit("100/minute")
async def chat_completions(
    request: Request,
    authorization: Optional[str] = Header(None),
    _auth: Dict[str, Any] = Depends(require_auth),
):
    """
    OpenAI兼容聊天完成API - v2.0异步优化版
    
    性能优化点：
    1. 全异步处理流程
    2. 并发身份验证和路由决策
    3. 智能缓存命中
    4. 异步用量记录
    5. 故障快速转移
    """
    perf_start = time.perf_counter()
    route_result = None
    
    try:
        # 1. 异步解析请求体
        try:
            req_dict = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="无效的 JSON 请求体")

        if "messages" not in req_dict or not req_dict["messages"]:
            raise HTTPException(status_code=400, detail="缺少messages字段")
        
        messages = req_dict["messages"]
        stream = req_dict.get("stream", False)

        # 提取并转发所有 OpenAI 兼容参数（tools、tool_choice 等）
        # 关键：若不转发 tools，上游模型无法感知可用工具，会退化为 XML 文本格式
        _FORWARDED_KEYS = (
            "tools", "tool_choice", "parallel_tool_calls",
            "stop", "response_format",
            "presence_penalty", "frequency_penalty",
            "top_p", "seed", "n",
        )
        extra_kwargs: Dict[str, Any] = {
            k: req_dict[k] for k in _FORWARDED_KEYS if k in req_dict
        }
        
        # 2. 并发执行用户信息查询和路由决策（性能优化）
        perf_parallel_start = time.perf_counter()
        
        auth_task = asyncio.create_task(get_current_user_async(authorization))
        
        # 预处理用户上下文（基于消息内容初步分析）
        user_context_task = asyncio.create_task(_analyze_user_context(messages))
        
        # 等待并发任务完成
        current_user_opt, user_context = await asyncio.gather(
            auth_task,
            user_context_task
        )
        # _auth dependency already validated the token; use its user_id as fallback.
        current_user: Dict[str, Any] = current_user_opt or {
            "user_id": _auth.get("user_id", "unknown"),
            "domain": "general",
            "permissions": ["read"],
        }
        bind_user_context(
            user_id=current_user.get("user_id"),
            user_domain=current_user.get("domain", "general"),
        )
        
        parallel_time = (time.perf_counter() - perf_parallel_start) * 1000
        logger.debug("parallel_preparation_completed", duration_ms=round(parallel_time, 2))
        
        # 3. 智能路由决策
        perf_route_start = time.perf_counter()
        
        if not smart_router or not provider_manager:
            raise HTTPException(status_code=500, detail="系统组件未初始化")

        # 1) 优先解析用户明确指定的 model（provider/model 或 model_id）
        requested_model = req_dict.get("model")
        route_result = _resolve_requested_model(requested_model, provider_manager)

        # 1.5) 旁路模型路由器（用户配置的 LLM 路由决策 + 可选上下文压缩）
        if route_result is None:
            _br = get_bypass_router()
            if _br and _br.enabled:
                try:
                    _br_result, messages = await _br.route(messages, provider_manager)
                    if _br_result is not None:
                        route_result = _br_result
                        logger.info(
                            "bypass_router_selected",
                            provider=_br_result.provider_id,
                            model=_br_result.model,
                            reason=_br_result.reason,
                        )
                except Exception as _br_exc:
                    logger.warning("bypass_router_error", error=str(_br_exc))

        # 2) 若无直接指定，尝试自定义路由器框架
        if route_result is None:
            _registry = get_router_registry()
            _active_router = _registry.get_active() if _registry else None

            if _active_router and _registry:
                _aggregator = get_model_info_aggregator()
                _model_list = _aggregator.get_snapshot() if _aggregator else []
                _ctx = RoutingContext(
                    last_user_message=next(
                        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
                        "",
                    ),
                    messages_count=len(messages),
                    models=_model_list,
                    session_metadata={
                        "user_id": current_user.get("user_id"),
                        "user_domain": current_user.get("domain", "general"),
                    },
                )
                _ok, _result = await _registry.execute(_active_router, _ctx)
                if _ok and isinstance(_result, RoutingDecision):
                    from .services.routing.router import RouteResult  # local import to avoid circular
                    route_result = RouteResult(
                        provider_id=_result.provider,
                        model=_result.model,
                        task_type="custom",
                        confidence=_result.confidence,
                        reason=_result.reason,
                        from_cache=False,
                    )
                    logger.info(
                        "custom_router_selected",
                        router=_active_router,
                        provider=_result.provider,
                        model=_result.model,
                        confidence=round(_result.confidence, 3),
                        reason=_result.reason,
                    )
                else:
                    logger.warning(
                        "custom_router_fallback",
                        router=_active_router,
                        error=str(_result),
                    )
        if route_result is None:
            route_result = await smart_router.route(
                messages=messages,
                user_context={
                    **user_context,
                    "user_id": current_user.get("user_id"),
                    "user_domain": current_user.get("domain", "general"),
                },
                provider_manager=provider_manager
            )
        
        route_time = (time.perf_counter() - perf_route_start) * 1000
        bind_llm_context(provider_id=route_result.provider_id, model=route_result.model)
        metrics_collector.record_route_decision(
            route_result.task_type,
            route_result.provider_id,
            route_result.model,
            route_result.from_cache,
        )

        logger.info(
            "route_selected",
            provider=route_result.provider_id,
            model=route_result.model,
            task_type=route_result.task_type,
            confidence=round(route_result.confidence, 3),
            from_cache=route_result.from_cache,
            duration_ms=round(route_time, 2),
        )
        _ensure_model_allowed(_auth, route_result.provider_id, route_result.model, requested_model)
        
        # 4. 执行模型调用
        perf_llm_start = time.perf_counter()
        
        if stream:
            # 流式响应
            return StreamingResponse(
                _stream_chat_completion(
                    messages=messages,
                    route_result=route_result,
                    current_user=current_user,
                    req_dict=req_dict,
                    extra_kwargs=extra_kwargs,
                    perf_start=perf_start
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",  # 禁止 nginx 缓冲，确保实时推送
                }
            )
        else:
            # 普通响应
            try:
                response = await provider_manager.chat_completion(
                    messages=messages,
                    model=route_result.model,
                    provider_id=route_result.provider_id,
                    max_tokens=req_dict.get("max_tokens", 4000),
                    temperature=req_dict.get("temperature", 0.7),
                    stream=False,
                    **extra_kwargs,
                )
            except Exception:
                llm_time = (time.perf_counter() - perf_llm_start) * 1000
                metrics_collector.record_llm_call(
                    route_result.provider_id,
                    route_result.model,
                    "error",
                    llm_time / 1000,
                )
                raise
            
            llm_time = (time.perf_counter() - perf_llm_start) * 1000
            metrics_collector.record_llm_call(
                route_result.provider_id,
                route_result.model,
                "success",
                llm_time / 1000,
            )

            # 4b. 空回合检测与兜底（非流式）
            _is_tool_fu = _is_tool_followup(messages)
            if _detect_empty_non_stream_turn(response):
                _orig_reasoning = bool(
                    ((response.get("choices") or [{}])[0].get("message") or {}).get("reasoning_content")
                )
                logger.warning(
                    "empty_turn_detected",
                    provider=route_result.provider_id,
                    model=route_result.model,
                    stream=False,
                    had_reasoning=_orig_reasoning,
                    had_visible_text=False,
                    had_tool_calls=False,
                    last_input_role="tool" if _is_tool_fu else "user",
                    fallback_stage="initial",
                )
                _retry_ok = False
                try:
                    logger.info("empty_turn_retry_started", stream=False)
                    _retry_resp = await provider_manager.chat_completion(
                        messages=_build_empty_turn_retry_messages(messages, _is_tool_fu),
                        model=route_result.model,
                        provider_id=route_result.provider_id,
                        max_tokens=req_dict.get("max_tokens", 4000),
                        temperature=req_dict.get("temperature", 0.7),
                        stream=False,
                        **extra_kwargs,
                    )
                    if not _detect_empty_non_stream_turn(_retry_resp):
                        response = _retry_resp
                        _retry_ok = True
                        logger.info(
                            "empty_turn_retry_succeeded",
                            provider=route_result.provider_id,
                            model=route_result.model,
                        )
                    else:
                        logger.warning("empty_turn_retry_failed_still_empty",
                                       provider=route_result.provider_id, model=route_result.model)
                except Exception as _retry_exc:
                    logger.error("empty_turn_retry_error", error=str(_retry_exc))
                if not _retry_ok:
                    _inject_fallback_into_response(response, _make_fallback_text(_is_tool_fu))
                    logger.info("empty_turn_fallback_emitted",
                                provider=route_result.provider_id, model=route_result.model,
                                is_tool_followup=_is_tool_fu)

            # 5. 异步记录用量（不阻塞响应）
            if usage_tracker and "usage" in response:
                usage_info = response["usage"]
                metrics_collector.record_token_usage(
                    route_result.provider_id,
                    route_result.model,
                    usage_info.get("prompt_tokens", 0),
                    usage_info.get("completion_tokens", 0),
                )
                asyncio.create_task(_record_usage_background(
                    route_result=route_result,
                    usage_info=usage_info,
                    current_user=current_user,
                    duration_ms=llm_time
                ))
            
            # 6. 增强响应信息
            response.setdefault("usage", {})
            response["usage"]["routing"] = {
                "task_type": route_result.task_type,
                "selected_model": route_result.model,
                "provider": route_result.provider_id,
                "reason": route_result.reason,
                "from_cache": route_result.from_cache,
                "confidence": route_result.confidence
            }
            
            # 7. 性能日志
            total_time = (time.perf_counter() - perf_start) * 1000
            logger.info(
                "chat_completion_completed",
                provider=route_result.provider_id,
                model=route_result.model,
                total_duration_ms=round(total_time, 2),
                llm_duration_ms=round(llm_time, 2),
                route_duration_ms=round(route_time, 2),
                preparation_duration_ms=round(parallel_time, 2),
            )
            
            return response
    
    except HTTPException:
        raise
    except Exception as e:
        total_time = (time.perf_counter() - perf_start) * 1000
        logger.exception(
            "chat_completion_failed",
            duration_ms=round(total_time, 2),
            error=str(e),
            provider=getattr(route_result, "provider_id", None),
            model=getattr(route_result, "model", None),
        )
        raise HTTPException(status_code=500, detail="内部服务器错误")


async def _analyze_user_context(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """分析用户上下文（异步）"""
    
    # 简单的消息分析，实际可以更复杂
    last_message = messages[-1] if messages else {}
    content = last_message.get("content", "")
    
    # 消息长度分析
    content_length = len(content)
    
    # 简单的复杂度评估
    complexity_indicators = ["分析", "复杂", "详细", "深入", "比较", "评估"]
    complexity_score = sum(1 for indicator in complexity_indicators if indicator in content)
    
    return {
        "domain": "general",
        "content_length": content_length,
        "complexity_score": complexity_score,
        "message_count": len(messages)
    }


async def _stream_chat_completion(
    messages: List[Dict[str, Any]], 
    route_result, 
    current_user: Dict[str, Any],
    req_dict: Dict[str, Any],
    extra_kwargs: Dict[str, Any],
    perf_start: float
):
    """流式聊天完成，支持 reasoning_content（思维链模型）实时流出。

    失败降级策略：
    - 若流式失败且尚未向客户端发送任何内容，自动降级为非流式请求，
      将结果转成 SSE 格式推出，客户端无感知。
    - 若已发送部分内容后失败，推送 stream_error 事件（无法回滚）。
    """
    llm_start = time.perf_counter()

    routing_info = {
        "task_type": route_result.task_type,
        "selected_model": route_result.model,
        "provider": route_result.provider_id,
        "reason": route_result.reason,
        "from_cache": route_result.from_cache,
        "confidence": route_result.confidence,
    }

    if not provider_manager:
        error_chunk = {"error": {"message": "Provider管理器未初始化", "type": "stream_error"}}
        yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"
        return

    content_chunks_sent = 0  # 记录已发送的含内容 chunk 数量（用于判断是否可降级）
    first_chunk = True
    prompt_tokens = 0
    completion_tokens = 0
    reasoning_chars = 0
    stream_err: Optional[Exception] = None
    seen_visible_chars = 0   # 可见正文字符数（不含 reasoning，用于空回合检测）
    seen_tool_calls = False  # 是否出现过 tool_calls delta
    last_finish_reason: Optional[str] = None

    try:
        async for chunk in provider_manager.chat_completion_stream(
            messages=messages,
            model=route_result.model,
            provider_id=route_result.provider_id,
            max_tokens=req_dict.get("max_tokens", 4000),
            temperature=req_dict.get("temperature", 0.7),
            stream_options={"include_usage": True},
            **extra_kwargs,
        ):
            if isinstance(chunk, str):
                try:
                    payload = json.loads(chunk)
                except json.JSONDecodeError:
                    yield f"data: {chunk}\n\n"
                    content_chunks_sent += 1
                    continue
            else:
                payload = chunk

            if isinstance(payload, dict) and "usage" in payload and payload["usage"]:
                usage = payload["usage"]
                prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                completion_tokens = usage.get("completion_tokens", completion_tokens)

            if isinstance(payload, dict):
                for choice in payload.get("choices", []):
                    delta = choice.get("delta", {})
                    rc = delta.get("reasoning_content") or ""
                    reasoning_chars += len(rc)
                    # 只有携带实际内容的 chunk 才计数
                    if delta.get("content") or delta.get("reasoning_content"):
                        content_chunks_sent += 1
                    # 空回合检测状态跟踪
                    seen_visible_chars += len(delta.get("content") or "")
                    if delta.get("tool_calls"):
                        seen_tool_calls = True
                    fr = choice.get("finish_reason")
                    if fr:
                        last_finish_reason = fr

            if first_chunk and isinstance(payload, dict):
                first_chunk = False
                if not isinstance(payload.get("usage"), dict):
                    payload["usage"] = {}
                payload["usage"]["routing"] = routing_info

            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    except Exception as e:
        stream_err = e

    if stream_err is not None:
        llm_time = (time.perf_counter() - llm_start) * 1000
        metrics_collector.record_llm_call(
            route_result.provider_id, route_result.model, "error", llm_time / 1000,
        )

        if content_chunks_sent == 0:
            # ── 降级到非流式 ──────────────────────────────────────────────
            logger.warning(
                "stream_failed_before_content_fallback_to_non_stream",
                provider=route_result.provider_id,
                model=route_result.model,
                error=str(stream_err),
            )
            try:
                response = await provider_manager.chat_completion(
                    messages=messages,
                    model=route_result.model,
                    provider_id=route_result.provider_id,
                    max_tokens=req_dict.get("max_tokens", 4000),
                    temperature=req_dict.get("temperature", 0.7),
                    stream=False,
                    **extra_kwargs,
                )
                # 将非流式响应转成两个 SSE chunk（content delta + stop）
                resp_id = response.get("id") or f"chatcmpl-fallback-{int(time.time())}"
                resp_created = response.get("created") or int(time.time())
                resp_model = response.get("model") or route_result.model
                choice0 = (response.get("choices") or [{}])[0]
                message = choice0.get("message") or {}
                content = message.get("content") or ""
                reasoning = message.get("reasoning_content") or ""

                usage_info = response.get("usage") or {}
                prompt_tokens = usage_info.get("prompt_tokens", 0)
                completion_tokens = usage_info.get("completion_tokens", 0)

                delta_payload: Dict[str, Any] = {
                    "id": resp_id,
                    "object": "chat.completion.chunk",
                    "created": resp_created,
                    "model": resp_model,
                    "choices": [{
                        "index": 0,
                        "delta": {"role": "assistant", "content": content},
                        "finish_reason": None,
                    }],
                    "usage": {**usage_info, "routing": routing_info, "fallback": True},
                }
                if reasoning:
                    delta_payload["choices"][0]["delta"]["reasoning_content"] = reasoning

                yield f"data: {json.dumps(delta_payload, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'id': resp_id, 'object': 'chat.completion.chunk', 'created': resp_created, 'model': resp_model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

                llm_time = (time.perf_counter() - llm_start) * 1000
                metrics_collector.record_llm_call(
                    route_result.provider_id, route_result.model, "success", llm_time / 1000,
                )
                if completion_tokens:
                    metrics_collector.record_token_usage(
                        route_result.provider_id, route_result.model,
                        prompt_tokens, completion_tokens,
                    )
                asyncio.create_task(_record_usage_background(
                    route_result=route_result,
                    usage_info=usage_info,
                    current_user=current_user,
                    duration_ms=llm_time,
                ))
                logger.info(
                    "stream_fallback_non_stream_success",
                    provider=route_result.provider_id,
                    model=route_result.model,
                    content_len=len(content),
                )
                return

            except Exception as fallback_err:
                logger.error(
                    "stream_and_fallback_both_failed",
                    provider=route_result.provider_id,
                    model=route_result.model,
                    stream_error=str(stream_err),
                    fallback_error=str(fallback_err),
                )
                error_chunk = {
                    "error": {"message": str(stream_err), "type": "stream_error", "fallback_error": str(fallback_err)}
                }
                yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"
                return
        else:
            # 已发出部分内容，无法回滚，直接报错
            error_chunk = {"error": {"message": str(stream_err), "type": "stream_error"}}
            yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"
            return

    # ── 正常流式完成 ─────────────────────────────────────────────────────────
    llm_time = (time.perf_counter() - llm_start) * 1000
    metrics_collector.record_llm_call(
        route_result.provider_id, route_result.model, "success", llm_time / 1000,
    )
    if completion_tokens:
        metrics_collector.record_token_usage(
            route_result.provider_id, route_result.model, prompt_tokens, completion_tokens,
        )
    asyncio.create_task(_record_usage_background(
        route_result=route_result,
        usage_info={"completion_tokens": completion_tokens, "prompt_tokens": prompt_tokens},
        current_user=current_user,
        duration_ms=llm_time,
    ))

    # ── 空回合检测（流式）────────────────────────────────────────────────────
    if last_finish_reason == "stop" and seen_visible_chars == 0 and not seen_tool_calls:
        _is_tool_fu = _is_tool_followup(messages)
        logger.warning(
            "empty_turn_detected",
            provider=route_result.provider_id,
            model=route_result.model,
            stream=True,
            had_reasoning=reasoning_chars > 0,
            had_visible_text=False,
            had_tool_calls=False,
            last_input_role="tool" if _is_tool_fu else "user",
            fallback_stage="initial",
        )
        _et_id = f"chatcmpl-et-{int(time.time())}"
        _et_created = int(time.time())
        _fallback_text: Optional[str] = None

        try:
            logger.info("empty_turn_retry_started", stream=True,
                        provider=route_result.provider_id, model=route_result.model)
            _retry_resp = await provider_manager.chat_completion(
                messages=_build_empty_turn_retry_messages(messages, _is_tool_fu),
                model=route_result.model,
                provider_id=route_result.provider_id,
                max_tokens=req_dict.get("max_tokens", 4000),
                temperature=req_dict.get("temperature", 0.7),
                stream=False,
                **extra_kwargs,
            )
            _retry_choice = (_retry_resp.get("choices") or [{}])[0]
            _retry_content = str((_retry_choice.get("message") or {}).get("content") or "").strip()
            if _retry_content:
                logger.info("empty_turn_retry_succeeded", provider=route_result.provider_id,
                            model=route_result.model, content_len=len(_retry_content))
                _fallback_text = _retry_content
                _et_id = _retry_resp.get("id") or _et_id
                _et_created = _retry_resp.get("created") or _et_created
                # Update token counters
                _ru = _retry_resp.get("usage") or {}
                prompt_tokens = _ru.get("prompt_tokens", prompt_tokens)
                completion_tokens = _ru.get("completion_tokens", completion_tokens)
            else:
                logger.warning("empty_turn_retry_failed_still_empty",
                               provider=route_result.provider_id, model=route_result.model)
        except Exception as _et_exc:
            logger.error("empty_turn_retry_error", error=str(_et_exc))

        if _fallback_text is None:
            _fallback_text = _make_fallback_text(_is_tool_fu)
            logger.info("empty_turn_fallback_emitted", provider=route_result.provider_id,
                        model=route_result.model, is_tool_followup=_is_tool_fu)

        _delta_chunk: Dict[str, Any] = {
            "id": _et_id,
            "object": "chat.completion.chunk",
            "created": _et_created,
            "model": route_result.model,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": _fallback_text}, "finish_reason": None}],
            "usage": {"routing": routing_info, "empty_turn_fallback": True},
        }
        _stop_chunk: Dict[str, Any] = {
            "id": _et_id,
            "object": "chat.completion.chunk",
            "created": _et_created,
            "model": route_result.model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(_delta_chunk, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps(_stop_chunk, ensure_ascii=False)}\n\n"

    yield "data: [DONE]\n\n"

    total_time = (time.perf_counter() - perf_start) * 1000
    logger.info(
        "stream_completion_finished",
        provider=route_result.provider_id,
        model=route_result.model,
        total_duration_ms=round(total_time, 2),
        llm_duration_ms=round(llm_time, 2),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_chars=reasoning_chars,
    )


async def _record_usage_background(
    route_result,
    usage_info: Dict[str, Any],
    current_user: Dict[str, Any], 
    duration_ms: float
):
    """后台异步记录用量（不阻塞主流程）"""
    
    try:
        if usage_tracker:
            prompt_tokens = usage_info.get("prompt_tokens", 0)
            completion_tokens = usage_info.get("completion_tokens", 0)
            actual_model_ref = f"{route_result.provider_id}/{route_result.model}"
            cost_usd = estimate_model_cost_usd(
                model_ref=actual_model_ref,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                provider_manager=provider_manager,
            )

            savings_config = runtime_config.get("savings") or {}
            baseline_model, baseline_source = resolve_baseline_model(route_result.task_type, savings_config)
            baseline_cost_rmb = None
            savings_rmb = None
            if baseline_model:
                baseline_cost_rmb = estimate_baseline_cost_rmb(
                    baseline_model=baseline_model,
                    input_tokens=prompt_tokens,
                    output_tokens=completion_tokens,
                    provider_manager=provider_manager,
                )
                if baseline_cost_rmb is not None and cost_usd is not None:
                    savings_rmb = baseline_cost_rmb - (cost_usd * 7.2)

            await record_usage_async(
                model=route_result.model,
                provider=route_result.provider_id,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                user_id=current_user.get("user_id", "unknown"),
                task_type=route_result.task_type,
                duration_ms=duration_ms,
                cost_usd=cost_usd or 0.0,
                baseline_model=baseline_model,
                baseline_cost_rmb=baseline_cost_rmb,
                savings_rmb=savings_rmb,
                baseline_source=baseline_source,
            )
    except Exception as e:
        logger.warning(f"用量记录失败: {str(e)}")


@app.get("/v1/models")
async def list_models(
    _auth: Dict[str, Any] = Depends(require_auth),
):
    """列出可用模型（需要认证；外部 API Key 仅返回其有权限的模型）"""

    if not provider_manager:
        return {"data": []}

    try:
        all_models = _build_model_catalog()

        # External API keys only see models they are permitted to use.
        if _auth.get("type") == "external_api_key":
            permissions = _auth.get("model_permissions") or []
            if "*" not in permissions:
                def _allowed(entry: Dict[str, Any]) -> bool:
                    mid = entry.get("id", "")
                    cid = entry.get("canonical_id", mid)
                    pid = entry.get("provider", "")
                    return (
                        mid == "smart"
                        or mid in permissions
                        or cid in permissions
                        or f"{pid}/*" in permissions
                    )
                all_models = [m for m in all_models if _allowed(m)]

        return {"data": all_models}

    except Exception as e:
        logger.error(f"获取模型列表失败: {str(e)}")
        return {"data": [], "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    
    config = {
        "host": os.getenv("HOST", "0.0.0.0"),  # nosec B104 — intentional server bind; restrict via HOST env var in production
        "port": int(os.getenv("PORT", "19377")),
        "reload": False,
        "workers": 1,
        "access_log": False,  # 禁用访问日志提升性能
        "log_level": "info"
    }
    
    if os.name != "nt" and importlib.util.find_spec("uvloop"):
        config["loop"] = "uvloop"
    else:
        config["loop"] = "asyncio"
    
    if importlib.util.find_spec("httptools"):
        config["http"] = "httptools"
    else:
        config["http"] = "h11"
    
    logger.info(f"🚀 启动Bridge Server v2.0 - 异步优化版")
    logger.info(f"配置: {config}")
    
    uvicorn.run("bridge_server.runtime:app", **config)
