#!/usr/bin/env python3
"""
RESTful API v1 路由模块
提供标准化的 API 接口
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Body
from typing import List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["v1"])


@router.get("/info")
async def get_api_info():
    """获取 API 信息"""
    return {
        "name": "Bridge Server API",
        "version": "1.6.0",
        "description": "RESTful API for Bridge Server",
        "endpoints": [
            "/api/v1/auth/token",
            "/api/v1/routing/strategy",
            "/api/v1/routing/providers",
            "/api/v1/routing/test",
            "/api/v1/usage/summary",
            "/api/v1/usage/records",
            "/api/v1/providers/list",
        ]
    }


# ============ 认证相关 ============

@router.post("/auth/token")
async def create_api_token(
    username: str = Body(..., embed=True),
    password: str = Body(..., embed=True)
):
    """
    创建 API Token（简易实现，生产环境应使用数据库存储）
    
    注意：此为简化实现，实际部署应配置 auth_tokens
    """
    from app.auth import load_config
    
    config = load_config()
    auth_config = config.get("auth", {})
    
    # 简易验证（生产环境应使用数据库）
    if username == "admin" and password == auth_config.get("admin_password", "admin"):
        import jwt
        from datetime import timedelta
        
        expire = datetime.utcnow() + timedelta(days=30)
        to_encode = {
            "sub": username,
            "exp": expire,
            "iat": datetime.utcnow(),
            "type": "access"
        }
        
        secret_key = auth_config.get("jwt_secret", "bridge-server-secret-key-change-me")
        token = jwt.encode(to_encode, secret_key, algorithm="HS256")
        
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": 30 * 24 * 60 * 60
        }
    
    raise HTTPException(status_code=401, detail="用户名或密码错误")


# ============ 路由管理 ============

@router.get("/routing/strategy")
async def get_routing_strategy():
    """获取当前路由策略"""
    from app.auth import load_config
    
    config = load_config()
    routing_config = config.get("routing", {})
    
    return {
        "strategy": routing_config.get("strategy", "balanced"),
        "model_mapping": routing_config.get("model_mapping", {}),
        "custom_rules": routing_config.get("custom_rules", [])
    }


@router.get("/routing/providers")
async def get_routing_providers():
    """获取可用 Provider 列表"""
    from app.auth import load_config
    
    config = load_config()
    providers = config.get("providers", {})
    
    provider_list = []
    for name, prov_config in providers.items():
        if prov_config.get("enabled", False):
            provider_list.append({
                "name": name,
                "base_url": prov_config.get("base_url", ""),
                "models": list(prov_config.get("models", {}).keys()),
                "status": "active"
            })
    
    return {"providers": provider_list}


@router.post("/routing/test")
async def test_routing(
    message: str = Body(..., embed=True),
    config_override: Optional[dict] = Body(None)
):
    """
    测试路由决策
    
    返回路由选择结果和原因
    """
    from app.auth import load_config
    from app.router import route_model
    
    config = load_config()
    
    # 合并配置（如果有覆盖）
    if config_override:
        config.update(config_override)
    
    selected_model, task_type, reason = route_model(message, config)
    
    return {
        "message": message[:100],
        "task_type": task_type,
        "selected_model": selected_model,
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat()
    }


# ============ 用量统计 ============

@router.get("/usage/summary")
async def get_usage_summary(
    period: str = Query("today", pattern="^(today|yesterday|week|month|all)$")
):
    """获取用量统计摘要"""
    from services.usage import get_tracker
    
    tracker = get_tracker()
    usage = tracker.get_usage(period)
    
    return {
        "period": period,
        "total_requests": usage["total_requests"],
        "total_tokens": usage["total_tokens_in"] + usage["total_tokens_out"],
        "total_cost": round(usage["total_cost"], 4),
        "success_rate": round(
            usage["total_requests_success"] / max(usage["total_requests"], 1) * 100, 2
        ),
        "models": usage["models"],
        "providers": usage["providers"]
    }


@router.get("/usage/records")
async def get_usage_records(
    date: Optional[str] = Query(None, pattern="^\\d{4}-\\d{2}-\\d{2}$"),
    limit: int = Query(100, ge=1, le=1000)
):
    """
    获取用量记录（从数据库或文件）
    
    注意：v1.6.0 支持 MySQL 后，这里会从数据库查询
    """
    from services.usage import get_tracker
    
    tracker = get_tracker()
    period = "today" if not date else "all"
    usage = tracker.get_usage(period)
    
    # 返回每日明细（简化实现）
    return {
        "records": usage.get("daily_breakdown", [])[:limit],
        "total": len(usage.get("daily_breakdown", []))
    }


@router.get("/usage/export")
async def export_usage(
    period: str = Query("month", pattern="^(today|week|month|all)$"),
    format: str = Query("json", pattern="^(json|csv)$")
):
    """导出用量报告"""
    from services.usage import get_tracker
    
    tracker = get_tracker()
    report = tracker.export_report(period, format)
    
    return {
        "format": format,
        "content": report,
        "generated_at": datetime.utcnow().isoformat()
    }


# ============ Provider 管理 ============

@router.get("/providers/list")
async def list_providers():
    """列出所有配置的 Provider"""
    from app.auth import load_config
    
    config = load_config()
    providers = config.get("providers", {})
    
    result = []
    for name, prov_config in providers.items():
        models_info = []
        for model_name, model_info in prov_config.get("models", {}).items():
            models_info.append({
                "id": model_name,
                "cost": model_info.get("cost", 0),
                "use_case": model_info.get("use_case", "通用")
            })
        
        result.append({
            "name": name,
            "enabled": prov_config.get("enabled", False),
            "base_url": prov_config.get("base_url", ""),
            "models": models_info
        })
    
    return {"providers": result}


@router.post("/providers/{provider_name}/test")
async def test_provider(
    provider_name: str,
    message: str = Body("Hello", embed=True)
):
    """
    测试 Provider 连接
    
    发送简单请求验证 Provider 是否可用
    """
    from app.auth import load_config
    import httpx
    
    config = load_config()
    providers = config.get("providers", {})
    
    if provider_name not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")
    
    prov_config = providers[provider_name]
    
    if not prov_config.get("enabled", False):
        raise HTTPException(status_code=400, detail=f"Provider '{provider_name}' 未启用")
    
    # 获取 API Key
    api_key = prov_config.get("api_key", "")
    if "api_key_env" in prov_config:
        import os
        api_key = os.getenv(prov_config["api_key_env"], "")
    
    if not api_key:
        raise HTTPException(status_code=400, detail="Provider 缺少 API Key")
    
    base_url = prov_config.get("base_url", "")
    models = prov_config.get("models", {})
    
    if not models:
        raise HTTPException(status_code=400, detail="Provider 没有配置模型")
    
    # 使用第一个模型测试
    test_model = list(models.keys())[0]
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                json={
                    "model": test_model,
                    "messages": [{"role": "user", "content": message}]
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code == 200:
                return {
                    "provider": provider_name,
                    "model": test_model,
                    "status": "success",
                    "response_time_ms": response.elapsed.total_seconds() * 1000
                }
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Provider 返回错误：{response.text[:200]}"
                )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Provider 请求超时")
    except httpx.ConnectError as e:
        raise HTTPException(status_code=503, detail=f"无法连接 Provider: {str(e)[:100]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试失败：{str(e)[:100]}")
