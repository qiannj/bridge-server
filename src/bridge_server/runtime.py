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
from typing import Optional, Dict, Any, List
import yaml

from fastapi import FastAPI, Request, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response
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
from .services.routing import RouterConfig, SmartRouter
from .utils.cache import HybridCache
from .utils.connection_pools import close_connection_pool_manager, get_connection_pool_manager

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
perf_monitor = PerformanceMonitor()
metrics_collector = get_metrics_collector()
connection_pool_manager = None


async def load_config_async() -> Dict[str, Any]:
    """异步加载配置"""
    config_paths = [
        Path.home() / ".bridge-server" / "config.yaml",
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
    global provider_manager, smart_router, cache_system, usage_tracker, auth_manager, connection_pool_manager, runtime_config
    
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
    provider_manager = ProviderManager(routing_strategy=RoutingStrategy.COST_OPTIMIZED)
    
    # 添加Providers
    providers_config = [
        ProviderConfig(
            provider_type="dashscope",
            config={
                "id": "dashscope",
                "api_key": os.getenv("DASHSCOPE_API_KEY"),
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
            },
            weight=3,
            priority=1,
            enabled=bool(os.getenv("DASHSCOPE_API_KEY"))
        ),
        ProviderConfig(
            provider_type="openai",
            config={
                "id": "openai",
                "api_key": os.getenv("OPENAI_API_KEY"),
                "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
            },
            weight=2,
            priority=2,
            enabled=bool(os.getenv("OPENAI_API_KEY"))
        ),
        ProviderConfig(
            provider_type="moonshot",
            config={
                "id": "moonshot",
                "api_key": os.getenv("MOONSHOT_API_KEY"),
                "base_url": "https://api.moonshot.cn/v1"
            },
            weight=1,
            priority=3,
            enabled=bool(os.getenv("MOONSHOT_API_KEY"))
        )
    ]
    
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
    router_config = RouterConfig()
    smart_router = SmartRouter(router_config, cache_system)
    
    # 6. 系统健康检查
    logger.info("执行系统健康检查...")
    if provider_manager:
        health_results = await provider_manager.health_check_all()
        healthy_count = sum(1 for status in health_results.values() if status.value == "healthy")
        logger.info(f"健康检查完成: {healthy_count}/{len(health_results)} 个Provider健康")
    
    logger.info("✅ 系统初始化完成")


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


async def require_auth(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """FastAPI dependency: reject requests without a valid auth token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="认证必须：请提供 Authorization header")
    auth_mgr = await get_auth_manager()
    token_info = await auth_mgr.verify_token(authorization)
    if not token_info:
        raise HTTPException(status_code=401, detail="无效或已过期的认证令牌")
    return token_info


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
    
    if cleanup_tasks:
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)
    
    await close_connection_pool_manager()
    
    logger.info("✅ 系统关闭完成")


@app.get("/")
async def root():
    """根路径"""
    stats = await perf_monitor.get_stats()
    return {
        "message": "Bridge Server v2.0 - 异步优化版",
        "version": "2.0.0-async",
        "performance": stats
    }


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
        return []

    models: List[Dict[str, Any]] = []
    for provider_id, provider in provider_manager.providers.items():
        for model_id in provider.get_supported_models():
            model_info = provider.get_model_info(model_id)
            models.append(
                {
                    "id": model_id,
                    "provider": provider_id,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": provider_id,
                    "input_cost_per_1k": getattr(model_info, "input_cost_per_1k", None),
                    "output_cost_per_1k": getattr(model_info, "output_cost_per_1k", None),
                    "max_tokens": getattr(model_info, "max_tokens", None),
                    "context_window": getattr(model_info, "context_window", None),
                }
            )

    return models


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
    """Expose the active routing strategy and configured mappings."""
    routing_config = runtime_config.get("routing", {})
    strategy = routing_config.get(
        "strategy",
        provider_manager.routing_strategy.value if provider_manager else "cost_optimized",
    )
    return {
        "strategy": strategy,
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
        req_dict = await request.json()
        
        if "messages" not in req_dict or not req_dict["messages"]:
            raise HTTPException(status_code=400, detail="缺少messages字段")
        
        messages = req_dict["messages"]
        stream = req_dict.get("stream", False)
        
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
            route_result.task_type.value,
            route_result.provider_id,
            route_result.model,
            route_result.from_cache,
        )

        logger.info(
            "route_selected",
            provider=route_result.provider_id,
            model=route_result.model,
            task_type=route_result.task_type.value,
            confidence=round(route_result.confidence, 3),
            from_cache=route_result.from_cache,
            duration_ms=round(route_time, 2),
        )
        
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
                    perf_start=perf_start
                ),
                media_type="text/plain"
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
                    stream=False
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
                "task_type": route_result.task_type.value,
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
    perf_start: float
):
    """流式聊天完成"""
    llm_start = time.perf_counter()

    try:
        if not provider_manager:
            raise RuntimeError("Provider管理器未初始化")
        
        # 开始流式调用
        total_tokens = 0
        
        async for chunk in provider_manager.chat_completion_stream(
            messages=messages,
            model=route_result.model,
            provider_id=route_result.provider_id,
            max_tokens=req_dict.get("max_tokens", 4000),
            temperature=req_dict.get("temperature", 0.7)
        ):
            # 统计token使用
            payload = chunk
            if isinstance(chunk, str):
                try:
                    payload = json.loads(chunk)
                except json.JSONDecodeError:
                    payload = chunk
            
            if isinstance(payload, dict) and "usage" in payload:
                total_tokens += payload["usage"].get("completion_tokens", 0)
            
            if isinstance(payload, dict):
                body = json.dumps(payload, ensure_ascii=False)
            else:
                body = payload
            
            yield f"data: {body}\n\n"
        
        llm_time = (time.perf_counter() - llm_start) * 1000
        metrics_collector.record_llm_call(
            route_result.provider_id,
            route_result.model,
            "success",
            llm_time / 1000,
        )
        if total_tokens:
            metrics_collector.record_token_usage(
                route_result.provider_id,
                route_result.model,
                0,
                total_tokens,
            )
        
        # 异步记录流式请求用量
        asyncio.create_task(_record_usage_background(
            route_result=route_result,
            usage_info={"completion_tokens": total_tokens, "prompt_tokens": 0},
            current_user=current_user,
            duration_ms=llm_time
        ))
        
        # 发送结束标记
        yield "data: [DONE]\n\n"
        
        # 记录性能
        total_time = (time.perf_counter() - perf_start) * 1000
        logger.info(
            "stream_completion_finished",
            provider=route_result.provider_id,
            model=route_result.model,
            total_duration_ms=round(total_time, 2),
            llm_duration_ms=round(llm_time, 2),
        )
        
    except Exception as e:
        metrics_collector.record_llm_call(
            route_result.provider_id,
            route_result.model,
            "error",
            max((time.perf_counter() - llm_start), 0.0),
        )
        error_chunk = {
            "error": {
                "message": str(e),
                "type": "stream_error"
            }
        }
        yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"


async def _record_usage_background(
    route_result,
    usage_info: Dict[str, Any],
    current_user: Dict[str, Any], 
    duration_ms: float
):
    """后台异步记录用量（不阻塞主流程）"""
    
    try:
        if usage_tracker:
            await record_usage_async(
                model=route_result.model,
                provider=route_result.provider_id,
                input_tokens=usage_info.get("prompt_tokens", 0),
                output_tokens=usage_info.get("completion_tokens", 0),
                user_id=current_user.get("user_id", "unknown"),
                task_type=route_result.task_type.value,
                duration_ms=duration_ms
            )
    except Exception as e:
        logger.warning(f"用量记录失败: {str(e)}")


@app.get("/v1/models")
async def list_models():
    """列出可用模型"""
    
    if not provider_manager:
        return {"data": []}
    
    try:
        return {"data": _build_model_catalog()}
        
    except Exception as e:
        logger.error(f"获取模型列表失败: {str(e)}")
        return {"data": [], "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    
    config = {
        "host": "0.0.0.0",
        "port": 8000,
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
