#!/usr/bin/env python3
"""
Bridge Server v2.0 - 异步化FastAPI入口
性能目标：10 req/s → 200+ req/s
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any
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
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from providers import ProviderManager, ProviderConfig, RoutingStrategy
from services.routing.router import SmartRouter, RouterConfig
from utils.cache import HybridCache

# 原有模块（异步化改造）
from app.auth_async import verify_token_async, get_current_user_async
from app.usage_async import UsageTrackerAsync, record_usage_async

# 配置日志
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

if log_level == "DEBUG":
    logger.warning("⚠️  生产环境不建议使用 DEBUG 日志级别")


# 全局变量（应用启动时初始化）
provider_manager: Optional[ProviderManager] = None
smart_router: Optional[SmartRouter] = None
cache_system: Optional[HybridCache] = None
usage_tracker: Optional[UsageTrackerAsync] = None


async def load_config() -> Dict[str, Any]:
    """异步加载配置"""
    config_file = Path.home() / ".bridge-server" / "config.yaml"
    if not config_file.exists():
        logger.warning(f"配置文件不存在：{config_file}")
        return {}

    # 异步读取文件
    def _read_config():
        with open(config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    
    # 在线程池中执行I/O操作
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _read_config)


async def init_provider_system() -> None:
    """初始化Provider系统"""
    global provider_manager, smart_router, cache_system
    
    logger.info("🚀 初始化 Provider 系统...")
    
    # 1. 初始化缓存
    redis_url = os.getenv("REDIS_URL")
    cache_system = HybridCache(
        redis_url=redis_url,
        l1_maxsize=2000,
        l1_ttl=300,  # 5分钟
        l2_ttl=1800,  # 30分钟
        key_prefix="bridge:v2:"
    )
    
    # 2. 创建Provider管理器
    provider_manager = ProviderManager(routing_strategy=RoutingStrategy.COST_OPTIMIZED)
    
    # 3. 添加可用的Providers
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
        else:
            logger.info(f"- Provider {config.config['id']} 跳过（无API密钥）")
    
    if added_count == 0:
        logger.error("❌ 没有可用的 Provider！请设置 API 密钥")
    else:
        logger.info(f"✅ Provider 系统初始化完成，{added_count} 个可用")
    
    # 4. 初始化智能路由器
    router_config = RouterConfig()
    smart_router = SmartRouter(router_config, cache_system)
    
    logger.info("🎯 智能路由器初始化完成")


async def init_usage_tracker() -> None:
    """初始化异步用量跟踪器"""
    global usage_tracker
    
    logger.info("📊 初始化用量跟踪器...")
    usage_tracker = UsageTrackerAsync()
    await usage_tracker.initialize()
    logger.info("✅ 用量跟踪器初始化完成")


# FastAPI 应用初始化
app = FastAPI(
    title="Bridge Server v2.0",
    description="高性能AI Gateway - 异步架构",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 限流器
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.info("🚀 Bridge Server v2.0 启动中...")
    
    # 初始化Provider系统
    await init_provider_system()
    
    # 初始化用量跟踪器
    await init_usage_tracker()
    
    # 健康检查
    if provider_manager:
        health_results = await provider_manager.health_check_all()
        healthy_count = sum(1 for status in health_results.values() if status.value == "healthy")
        logger.info(f"🏥 健康检查完成，{healthy_count}/{len(health_results)} 个 Provider 健康")
    
    logger.info("✅ Bridge Server v2.0 启动完成")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    logger.info("🛑 Bridge Server v2.0 关闭中...")
    
    # 清理Provider资源
    if provider_manager:
        await provider_manager.cleanup()
    
    # 关闭缓存连接
    if cache_system:
        await cache_system.close()
    
    # 关闭用量跟踪器
    if usage_tracker:
        await usage_tracker.close()
    
    logger.info("✅ Bridge Server v2.0 关闭完成")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP异常处理器"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.detail,
                "type": "http_exception",
                "code": exc.status_code
            }
        }
    )


@app.get("/")
async def root():
    """根路径"""
    return {"message": "Bridge Server v2.0 - 高性能AI Gateway", "version": "2.0.0"}


@app.get("/health")
async def health_check():
    """健康检查"""
    health_data = {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "2.0.0"
    }
    
    # Provider健康检查
    if provider_manager:
        provider_health = await provider_manager.health_check_all()
        health_data["providers"] = {
            pid: status.value for pid, status in provider_health.items()
        }
    
    # 缓存健康检查
    if cache_system:
        cache_health = await cache_system.health_check()
        health_data["cache"] = cache_health
    
    return health_data


@app.get("/metrics")
async def get_metrics():
    """获取系统指标"""
    metrics = {
        "timestamp": time.time(),
        "providers": {},
        "cache": {},
        "routing": {}
    }
    
    # Provider指标
    if provider_manager:
        metrics["providers"] = provider_manager.get_stats()
    
    # 缓存指标
    if cache_system:
        metrics["cache"] = cache_system.get_metrics()
    
    # 路由指标
    if smart_router:
        metrics["routing"] = smart_router.get_stats()
    
    return metrics


@app.post("/v1/chat/completions")
@limiter.limit("60/minute")
async def chat_completions(
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """
    OpenAI兼容的聊天完成接口 - v2.0异步版本
    
    性能优化：
    - 全异步处理
    - 智能缓存
    - 智能路由
    - 故障转移
    """
    perf_start = time.perf_counter()
    
    try:
        # 1. 异步解析请求
        perf_parse = time.perf_counter()
        req_dict = await request.json()
        logger.debug(f"⏱️  请求解析: {(time.perf_counter() - perf_parse) * 1000:.2f}ms")
        
        # 2. 验证输入
        if "messages" not in req_dict or not req_dict["messages"]:
            raise HTTPException(status_code=400, detail="缺少 messages 字段")
        
        messages = req_dict["messages"]
        
        # 3. 异步身份验证
        perf_auth = time.perf_counter()
        current_user = await get_current_user_async(authorization)
        logger.debug(f"⏱️  身份验证: {(time.perf_counter() - perf_auth) * 1000:.2f}ms")
        
        # 4. 智能路由决策
        perf_route = time.perf_counter()
        if not smart_router:
            raise HTTPException(status_code=500, detail="路由器未初始化")
        
        user_context = {
            "user_id": current_user.get("user_id"),
            "user_domain": current_user.get("domain", "general")
        }
        
        route_result = await smart_router.route(
            messages=messages,
            user_context=user_context,
            provider_manager=provider_manager
        )
        
        logger.info(f"⏱️  路由决策: {(time.perf_counter() - perf_route) * 1000:.2f}ms | "
                   f"{route_result.provider_id}/{route_result.model} | "
                   f"{route_result.task_type.value}({route_result.confidence:.2f})")
        
        # 5. 执行模型调用
        perf_llm = time.perf_counter()
        
        # 检查流式响应
        stream = req_dict.get("stream", False)
        
        if stream:
            # 流式响应
            return StreamingResponse(
                stream_chat_completion(
                    messages=messages,
                    provider_id=route_result.provider_id,
                    model=route_result.model,
                    current_user=current_user,
                    route_result=route_result,
                    **req_dict
                ),
                media_type="text/plain"
            )
        else:
            # 普通响应
            if not provider_manager:
                raise HTTPException(status_code=500, detail="Provider管理器未初始化")
            
            response = await provider_manager.chat_completion(
                messages=messages,
                model=route_result.model,
                provider_id=route_result.provider_id,
                max_tokens=req_dict.get("max_tokens", 4000),
                temperature=req_dict.get("temperature", 0.7),
                stream=False
            )
            
            llm_duration = (time.perf_counter() - perf_llm) * 1000
            
            # 6. 异步记录用量
            if usage_tracker and "usage" in response:
                usage_info = response["usage"]
                asyncio.create_task(record_usage_async(
                    model=route_result.model,
                    provider=route_result.provider_id,
                    input_tokens=usage_info.get("prompt_tokens", 0),
                    output_tokens=usage_info.get("completion_tokens", 0),
                    user_id=current_user.get("user_id", "unknown"),
                    task_type=route_result.task_type.value,
                    duration_ms=llm_duration
                ))
            
            # 7. 增强响应
            response["usage"]["routing"] = {
                "task_type": route_result.task_type.value,
                "selected_model": route_result.model,
                "provider": route_result.provider_id,
                "reason": route_result.reason,
                "from_cache": route_result.from_cache,
                "confidence": route_result.confidence
            }
            
            # 8. 性能日志
            total_duration = (time.perf_counter() - perf_start) * 1000
            logger.info(f"⏱️  总耗时: {total_duration:.2f}ms | "
                       f"LLM: {llm_duration:.2f}ms | "
                       f"其他: {total_duration - llm_duration:.2f}ms")
            
            return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"请求处理失败: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


async def stream_chat_completion(messages, provider_id, model, current_user, route_result, **kwargs):
    """流式聊天完成"""
    try:
        if not provider_manager:
            raise RuntimeError("Provider管理器未初始化")
        
        async for chunk in provider_manager.chat_completion_stream(
            messages=messages,
            model=model,
            provider_id=provider_id,
            **kwargs
        ):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        error_chunk = {
            "error": {
                "message": str(e),
                "type": "stream_error"
            }
        }
        yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"


@app.get("/v1/models")
async def list_models():
    """列出可用模型"""
    if not provider_manager:
        return {"data": []}
    
    models_data = []
    provider_models = provider_manager.get_provider_models()
    
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


if __name__ == "__main__":
    import uvicorn
    
    # 高性能配置
    uvicorn.run(
        "main_v2:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # 生产环境禁用热重载
        workers=1,     # 异步架构，单进程即可
        loop="uvloop", # 使用高性能事件循环
        http="httptools",  # 使用高性能HTTP解析器
        access_log=False,  # 禁用访问日志提升性能
        log_level="info"
    )