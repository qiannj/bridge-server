#!/usr/bin/env python3
"""
Bridge Server v2.0 - 阶段2异步优化版本
目标：30-50 QPS (Step 1)
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
import yaml

from fastapi import FastAPI, Request, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# 导入新的Provider系统
import sys
sys.path.insert(0, str(Path(__file__).parent / "src"))

# 核心系统
from providers import (
    ProviderManager, ProviderConfig, RoutingStrategy,
    DashScopeProvider, OpenAIProvider, MoonshotProvider
)
from services.routing import SmartRouter, RouterConfig, TaskType
from utils.cache import HybridCache

# 异步模块
from app.auth_async import get_current_user_async, AsyncAuthManager
from app.usage_async import UsageTrackerAsync, record_usage_async

# 配置日志
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
)
logger = logging.getLogger(__name__)

# 性能监控
class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self):
        self.request_count = 0
        self.total_latency = 0.0
        self.error_count = 0
        self.start_time = time.time()
        self._lock = asyncio.Lock()
    
    async def record_request(self, latency_ms: float, success: bool):
        """记录请求性能"""
        async with self._lock:
            self.request_count += 1
            if success:
                self.total_latency += latency_ms
            else:
                self.error_count += 1
    
    async def get_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        async with self._lock:
            uptime = time.time() - self.start_time
            qps = self.request_count / uptime if uptime > 0 else 0
            avg_latency = self.total_latency / max(1, self.request_count - self.error_count)
            error_rate = self.error_count / max(1, self.request_count)
            
            return {
                "uptime_seconds": uptime,
                "total_requests": self.request_count,
                "qps": round(qps, 2),
                "avg_latency_ms": round(avg_latency, 2),
                "error_count": self.error_count,
                "error_rate": round(error_rate, 4),
                "success_rate": round(1 - error_rate, 4)
            }


# 全局组件
provider_manager: Optional[ProviderManager] = None
smart_router: Optional[SmartRouter] = None
cache_system: Optional[HybridCache] = None
usage_tracker: Optional[UsageTrackerAsync] = None
auth_manager: Optional[AsyncAuthManager] = None
perf_monitor = PerformanceMonitor()


async def load_config_async() -> Dict[str, Any]:
    """异步加载配置"""
    config_paths = [
        Path.home() / ".bridge-server" / "config.yaml",
        Path(__file__).parent / "config.yaml.example"
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
    global provider_manager, smart_router, cache_system, usage_tracker, auth_manager
    
    logger.info("🚀 Bridge Server v2.0 系统初始化...")
    
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
                "api_key": os.getenv("DASHSCOPE_API_KEY", "test-key"),
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
            },
            weight=3,
            priority=1,
            enabled=True  # 测试模式总是启用
        ),
        ProviderConfig(
            provider_type="openai",
            config={
                "id": "openai",
                "api_key": os.getenv("OPENAI_API_KEY", "test-key"),
                "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
            },
            weight=2,
            priority=2,
            enabled=True
        ),
        ProviderConfig(
            provider_type="moonshot",
            config={
                "id": "moonshot",
                "api_key": os.getenv("MOONSHOT_API_KEY", "test-key"),
                "base_url": "https://api.moonshot.cn/v1"
            },
            weight=1,
            priority=3,
            enabled=True
        )
    ]
    
    added_count = 0
    for config in providers_config:
        if config.enabled:
            success = await provider_manager.add_provider(config)
            if success:
                added_count += 1
                logger.info(f"✓ Provider {config.config['id']} 添加成功")
    
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
app = FastAPI(
    title="Bridge Server v2.0",
    description="高性能AI Gateway - 异步优化版",
    version="2.0.0-async",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 限流器（异步优化）
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def performance_middleware(request: Request, call_next):
    """性能监控中间件"""
    start_time = time.perf_counter()
    
    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        # 记录成功请求
        asyncio.create_task(perf_monitor.record_request(duration_ms, True))
        
        # 添加性能头
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
        
        return response
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        # 记录失败请求
        asyncio.create_task(perf_monitor.record_request(duration_ms, False))
        
        raise e


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
    
    if provider_manager:
        cleanup_tasks.append(provider_manager.cleanup())
    
    if cache_system:
        cleanup_tasks.append(cache_system.close())
        
    if usage_tracker:
        cleanup_tasks.append(usage_tracker.close())
    
    if cleanup_tasks:
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)
    
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
    if provider_manager:
        health_tasks.append(provider_manager.health_check_all())
    
    # 缓存健康检查
    if cache_system:
        health_tasks.append(cache_system.health_check())
    
    if health_tasks:
        try:
            results = await asyncio.gather(*health_tasks, return_exceptions=True)
            
            if len(results) >= 1 and not isinstance(results[0], Exception):
                health_data["providers"] = {
                    pid: status.value for pid, status in results[0].items()
                }
            
            if len(results) >= 2 and not isinstance(results[1], Exception):
                health_data["cache"] = results[1]
                
        except Exception as e:
            logger.warning(f"健康检查部分失败: {str(e)}")
    
    # 性能统计
    health_data["performance"] = await perf_monitor.get_stats()
    
    return health_data


@app.get("/metrics")
async def get_metrics():
    """获取系统指标"""
    metrics = {
        "timestamp": time.time(),
        "performance": await perf_monitor.get_stats()
    }
    
    # 并发获取各模块指标
    metric_tasks = []
    
    if provider_manager:
        metric_tasks.append(("providers", provider_manager.get_stats()))
    
    if cache_system:
        metric_tasks.append(("cache", cache_system.get_metrics()))
    
    if smart_router:
        metric_tasks.append(("routing", smart_router.get_stats()))
    
    # 等待所有指标收集完成
    for name, coro_or_value in metric_tasks:
        try:
            if asyncio.iscoroutine(coro_or_value):
                metrics[name] = await coro_or_value
            else:
                metrics[name] = coro_or_value
        except Exception as e:
            logger.warning(f"获取{name}指标失败: {str(e)}")
            metrics[name] = {"error": str(e)}
    
    return metrics


@app.post("/v1/chat/completions")
@limiter.limit("100/minute")  # 提高限流阈值
async def chat_completions(
    request: Request,
    authorization: Optional[str] = Header(None)
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
    
    try:
        # 1. 异步解析请求体
        req_dict = await request.json()
        
        if "messages" not in req_dict or not req_dict["messages"]:
            raise HTTPException(status_code=400, detail="缺少messages字段")
        
        messages = req_dict["messages"]
        stream = req_dict.get("stream", False)
        
        # 2. 并发执行身份验证和路由决策（性能优化）
        perf_parallel_start = time.perf_counter()
        
        auth_task = asyncio.create_task(get_current_user_async(authorization))
        
        # 预处理用户上下文（基于消息内容初步分析）
        user_context_task = asyncio.create_task(_analyze_user_context(messages))
        
        # 等待并发任务完成
        current_user, user_context = await asyncio.gather(
            auth_task,
            user_context_task
        )
        
        parallel_time = (time.perf_counter() - perf_parallel_start) * 1000
        logger.debug(f"并发处理耗时: {parallel_time:.2f}ms")
        
        # 3. 智能路由决策
        perf_route_start = time.perf_counter()
        
        if not smart_router or not provider_manager:
            raise HTTPException(status_code=500, detail="系统组件未初始化")
        
        route_result = await smart_router.route(
            messages=messages,
            user_context={**user_context, "user_id": current_user.get("user_id")},
            provider_manager=provider_manager
        )
        
        route_time = (time.perf_counter() - perf_route_start) * 1000
        
        logger.info(f"路由决策: {route_result.provider_id}/{route_result.model} | "
                   f"类型: {route_result.task_type.value}({route_result.confidence:.2f}) | "
                   f"缓存: {route_result.from_cache} | 耗时: {route_time:.2f}ms")
        
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
            response = await provider_manager.chat_completion(
                messages=messages,
                model=route_result.model,
                provider_id=route_result.provider_id,
                max_tokens=req_dict.get("max_tokens", 4000),
                temperature=req_dict.get("temperature", 0.7),
                stream=False
            )
            
            llm_time = (time.perf_counter() - perf_llm_start) * 1000
            
            # 5. 异步记录用量（不阻塞响应）
            if usage_tracker and "usage" in response:
                usage_info = response["usage"]
                asyncio.create_task(_record_usage_background(
                    route_result=route_result,
                    usage_info=usage_info,
                    current_user=current_user,
                    duration_ms=llm_time
                ))
            
            # 6. 增强响应信息
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
            logger.info(f"请求完成 | 总耗时: {total_time:.2f}ms | "
                       f"LLM: {llm_time:.2f}ms | 路由: {route_time:.2f}ms | "
                       f"并发: {parallel_time:.2f}ms")
            
            return response
    
    except HTTPException:
        raise
    except Exception as e:
        total_time = (time.perf_counter() - perf_start) * 1000
        logger.error(f"请求失败 | 耗时: {total_time:.2f}ms | 错误: {str(e)}", exc_info=True)
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
    
    try:
        if not provider_manager:
            raise RuntimeError("Provider管理器未初始化")
        
        # 开始流式调用
        llm_start = time.perf_counter()
        total_tokens = 0
        
        async for chunk in provider_manager.chat_completion_stream(
            messages=messages,
            model=route_result.model,
            provider_id=route_result.provider_id,
            max_tokens=req_dict.get("max_tokens", 4000),
            temperature=req_dict.get("temperature", 0.7)
        ):
            # 统计token使用
            if "usage" in chunk:
                total_tokens += chunk["usage"].get("completion_tokens", 0)
            
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        
        llm_time = (time.perf_counter() - llm_start) * 1000
        
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
        logger.info(f"流式请求完成 | 总耗时: {total_time:.2f}ms | LLM: {llm_time:.2f}ms")
        
    except Exception as e:
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
        provider_models = provider_manager.get_provider_models()
        models_data = []
        
        for provider_id, models in provider_models.items():
            for model_id in models:
                models_data.append({
                    "id": model_id,
                    "object": "model", 
                    "provider": provider_id,
                    "created": int(time.time()),
                    "owned_by": provider_id
                })
        
        return {"data": models_data}
        
    except Exception as e:
        logger.error(f"获取模型列表失败: {str(e)}")
        return {"data": [], "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    
    # 高性能异步配置
    config = {
        "host": "0.0.0.0",
        "port": 8000,
        "reload": False,
        "workers": 1,
        "loop": "uvloop",  # 高性能事件循环
        "http": "httptools",  # 高性能HTTP解析
        "access_log": False,  # 禁用访问日志提升性能
        "log_level": "info"
    }
    
    logger.info(f"🚀 启动Bridge Server v2.0 - 异步优化版")
    logger.info(f"配置: {config}")
    
    uvicorn.run("main_v2_async:app", **config)