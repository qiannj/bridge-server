#!/usr/bin/env python3
"""Bridge Server - FastAPI 入口 v1.0.0"""

from fastapi import FastAPI, Request, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
import asyncio
import json
import time
import httpx
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import logging
import time
import os
from typing import Optional
import yaml
from pathlib import Path

from app.auth import verify_token, get_current_user
from app.router import route_model, call_llm
from services.usage import record_usage, get_tracker

# 🔒 安全：日志级别（从环境变量读取，默认 INFO）
log_level = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# 🔒 安全：警告 DEBUG 模式
if log_level == "DEBUG":
    logger.warning("⚠️  生产环境不建议使用 DEBUG 日志级别")


# 加载配置
def load_config() -> dict:
    config_file = Path.home() / ".bridge-server" / "config.yaml"
    if not config_file.exists():
        logger.warning(f"配置文件不存在：{config_file}")
        return {}

    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


config = load_config()

# 创建 FastAPI 应用
app = FastAPI(
    title="Bridge Server",
    description="LLM Model Router & API Gateway - v1.0.0 Community Edition",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 🔒 安全：全局异常处理器 - 返回详细错误信息（仅 DEBUG 模式）
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """全局 HTTP 异常处理器"""
    logger.warning(f"HTTP 错误 | {exc.status_code} | {exc.detail}")
    
    # 返回详细错误信息（包括 status code）
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.detail,
                "status_code": exc.status_code,
                "type": "http_error"
            }
        }
    )

# 🔒 安全：CORS 配置（默认禁止所有）
server_config = config.get("server", {})
allowed_origins = server_config.get("cors_origins", [])

if not allowed_origins:
    logger.warning("未配置 CORS，默认禁止所有跨域请求")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # 空列表 = 禁止所有
    allow_credentials=False,        # 🔒 安全：默认不允许携带凭证
    allow_methods=["POST"],         # 🔒 安全：仅允许 POST
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=[],
    max_age=600,
)

# 🔒 安全：速率限制（更严格）
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["30/minute", "500/hour", "10/second"],
    storage_uri="memory://"
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ============ 健康检查 ============


@app.get("/")
async def root():
    """根路径"""
    return {"service": "bridge-server", "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": time.time(), "version": "1.0.0"}


@app.get("/ready")
async def readiness_check():
    """就绪检查 - 验证所有依赖是否可用"""
    checks = {
        "database": True,
        "cache": True,
        "providers": []
    }
    
    # 检查 Provider 配置（支持 list 和 dict 两种格式）
    providers_raw = config.get("providers", {})
    providers = {}
    if isinstance(providers_raw, list):
        for p in providers_raw:
            name = p.get("name", "unknown")
            providers[name] = p
    else:
        providers = providers_raw
    
    for name, prov_config in providers.items():
        if prov_config.get("enabled", False):
            checks["providers"].append({
                "name": name,
                "status": "configured" if prov_config.get("api_key") or prov_config.get("api_key_env") else "missing_key"
            })
    
    all_healthy = all(p.get("status") == "configured" for p in checks["providers"])
    
    return {
        "status": "ready" if all_healthy else "degraded",
        "checks": checks,
        "timestamp": time.time()
    }


# ============ 核心代理接口 ============


@app.post("/v1/chat/completions")
@limiter.limit("60/minute")
async def chat_completions(
    request: Request,
    authorized: bool = Depends(verify_token),
    current_user: dict = Depends(get_current_user)
):
    """
    OpenAI 兼容的聊天完成接口

    支持的任务类型自动识别：
    - simple: 简单问候
    - coding: 代码任务
    - writing: 写作
    - analysis: 分析
    - creative: 创意
    - complex: 复杂推理
    - general: 默认
    """
    try:
        # 🔒 安全：输入验证
        if not hasattr(request, "json"):
            req_dict = request if isinstance(request, dict) else {}
        else:
            req_dict = await request.json() if hasattr(request, "json") else {}

        # 验证 messages 字段
        if "messages" not in req_dict or not req_dict["messages"]:
            raise HTTPException(status_code=400, detail="缺少 messages 字段")

        messages = req_dict["messages"]

        # 🔒 安全：验证消息数量
        MAX_MESSAGES = 50
        if len(messages) > MAX_MESSAGES:
            raise HTTPException(
                status_code=400, detail=f"消息数量超过限制 ({MAX_MESSAGES})"
            )

        # 🔒 安全：验证消息内容
        MAX_MESSAGE_LENGTH = 100000  # v2.1.1: 增加长度限制以支持长推理
        for i, msg in enumerate(messages):
            content = msg.get("content") or ""  # 处理 None 的情况
            if len(content) > MAX_MESSAGE_LENGTH:
                raise HTTPException(
                    status_code=400,
                    detail=f"消息 {i} 长度超过限制 ({MAX_MESSAGE_LENGTH})",
                )

        # 获取最后一条消息
        last_message = messages[-1]
        text = last_message.get("content", "")

        if not text:
            raise HTTPException(status_code=400, detail="消息内容为空")
        
        # 🚀 v2.1.1: 支持任意 model 参数，都使用智能路由
        requested_model = req_dict.get("model", None)
        
        # 检查是否启用 stream 模式
        stream = req_dict.get("stream", False)
        
        # 路由到合适的模型
        if requested_model == "smart":
            logger.info(f"收到请求 | user={current_user.get('username', 'unknown')} | text={text[:50]}... | 模式=智能路由")
        else:
            logger.info(f"收到请求 | user={current_user.get('username', 'unknown')} | text={text[:50]}... | 模式=默认")

        selected_model, task_type, reason = route_model(text, config, requested_model)

        logger.info(
            f"路由决策 | 任务类型={task_type} | 模型={selected_model} | 原因={reason}"
        )

        # 🚀 v2.1.1: 处理 stream 模式
        if stream:
            return await chat_completions_stream(
                selected_model, messages, config,
                current_user, task_type, reason
            )

        # 调用模型
        response = await call_llm(selected_model, req_dict["messages"], config)

        # 添加路由信息到响应
        if "usage" not in response:
            response["usage"] = {}
        response["usage"]["routing"] = {
            "task_type": task_type,
            "selected_model": selected_model,
            "reason": reason,
        }
        response["usage"]["user"] = current_user.get("username", "unknown")

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理请求失败：{type(e).__name__}", exc_info=True)
        # 🔒 安全：错误信息脱敏，不泄露内部细节
        error_str = str(e).lower()
        if "timeout" in error_str:
            safe_msg = "请求超时，请稍后重试"
        elif "connection" in error_str or "connect" in error_str:
            safe_msg = "无法连接到服务，请稍后重试"
        elif "auth" in error_str or "token" in error_str:
            safe_msg = "认证失败，请检查配置"
        else:
            safe_msg = "服务器内部错误，请稍后重试"
        raise HTTPException(status_code=500, detail=safe_msg)


@app.post("/v1/completions")
async def completions(
    request: dict,
    authorized: bool = Depends(verify_token)
):
    """OpenAI 兼容的完成接口（旧版本）"""
    # 转换为 chat completions 格式
    prompt = request.get("prompt", "")
    chat_request = {"messages": [{"role": "user", "content": prompt}]}

    return await chat_completions(chat_request, authorized)


# ============ 管理接口 ============


@app.get("/v1/models")
async def list_models_v1():
    """OpenAI 兼容的模型列表接口"""
    return await list_models()

@app.get("/api/models")
async def list_models():
    """列出所有可用模型"""
    providers_raw = config.get("providers", {})
    providers = {}
    if isinstance(providers_raw, list):
        for p in providers_raw:
            name = p.get("name", "unknown")
            providers[name] = p
    else:
        providers = providers_raw

    models = []
    for provider_name, provider_config in providers.items():
        if not provider_config.get("enabled", False):
            continue

        provider_models = provider_config.get("models", {})
        for model_name, model_info in provider_models.items():
            models.append(
                {
                    "id": model_name,
                    "provider": provider_name,
                    "cost": model_info.get("cost", 0),
                    "use_case": model_info.get("use_case", "通用"),
                }
            )

    return {"models": models}


@app.get("/api/routing")
async def get_routing_config():
    """查看当前路由配置"""
    return {
        "strategy": config.get("routing", {}).get("strategy", "balanced"),
        "model_mapping": config.get("routing", {}).get("model_mapping", {}),
    }


@app.get("/api/usage")
async def get_usage(period: str = "today"):
    """查看用量统计"""
    tracker = get_tracker()
    return tracker.get_usage(period)


@app.get("/api/budget")
async def get_budget():
    """查看预算状态"""
    tracker = get_tracker()
    return tracker.check_budget(config)


@app.get("/api/export/usage")
async def export_usage(period: str = "month", format: str = "json"):
    """导出用量报告"""
    tracker = get_tracker()
    return tracker.export_report(period, format)


# ============ 启动服务 ============

if __name__ == "__main__":
    import uvicorn

    server_config = config.get("server", {})
    host = server_config.get("host", "127.0.0.1")
    port = server_config.get("port", 8080)

    uvicorn.run(app, host=host, port=port, workers=1)


# ============ Stream 模式支持 (v2.1.1) ============

async def chat_completions_stream(
    model: str,
    messages: list,
    config: dict,
    current_user: dict,
    task_type: str,
    reason: str
):
    """
    🚀 v2.1.1: Stream 模式，支持心跳防止超时
    
    使用 SSE (Server-Sent Events) 保持连接活跃，
    定期发送注释行 : 来防止代理/负载均衡超时
    """
    
    async def generate():
        """SSE 流生成器，包含心跳机制"""
        
        # 获取 provider 配置
        if "/" in model:
            provider, model_name = model.split("/", 1)
        else:
            provider = None
            model_name = model
        
        providers = config.get("providers", [])
        provider_config = None
        
        if isinstance(providers, list):
            for p in providers:
                p_name = p.get("name", "")
                if provider and p_name == provider:
                    provider_config = p
                    break
                elif not provider:
                    models = p.get("models", [])
                    if isinstance(models, list):
                        for m in models:
                            m_id = m.get("id", "") if isinstance(m, dict) else str(m)
                            if m_id == model_name:
                                provider_config = p
                                provider = p_name
                                break
                    if provider_config:
                        break
        elif isinstance(providers, dict):
            provider_config = providers.get(provider, {})
        
        if not provider_config:
            yield 'data: {"error":"Provider not found"}\n\n'
            return
        
        api_key = provider_config.get("api_key", "")
        if "api_key_env" in provider_config:
            env_var = provider_config["api_key_env"]
            api_key = os.getenv(env_var, "")
        
        if not api_key:
            yield 'data: {"error":"API key not found"}\n\n'
            return
        
        base_url = provider_config.get("base_url", "")
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # 构建 payload，确保 stream=True
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": True
        }
        
        heartbeat_interval = 20  # 每 20 秒发送一次心跳
        last_heartbeat = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
                async with client.stream(
                    "POST",
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers=headers
                ) as response:
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]  # Remove "data: " prefix
                            
                            # 定期发送心跳（SSE 注释行）
                            current_time = time.time()
                            if current_time - last_heartbeat > heartbeat_interval:
                                yield ": heartbeat\n\n"  # SSE 注释，保持连接
                                last_heartbeat = current_time
                            
                            if data.strip() == "[DONE]":
                                yield "data: [DONE]\n\n"
                                break
                            
                            yield f"data: {data}\n\n"
                            
        except Exception as e:
            logger.error(f"Stream 错误: {e}")
            yield f'data: {{"error":"{str(e)}"}}\n\n'
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 Nginx 缓冲
        }
    )
