#!/usr/bin/env python3
"""
认证模块 - v1.6.0 升级
支持 JWT Token 和 API Key 认证
"""

import logging
from fastapi import HTTPException, Header, Depends
from typing import Optional
from datetime import datetime, timedelta
import yaml
from pathlib import Path
import os

logger = logging.getLogger(__name__)


def load_config() -> dict:
    """加载配置文件"""
    config_file = Path.home() / ".bridge-server" / "config.yaml"
    if not config_file.exists():
        return {}

    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def verify_token(authorization: Optional[str] = Header(None)) -> bool:
    """
    验证 API Token（支持 JWT 和 API Key）

    支持三种认证方式：
    1. JWT Bearer Token: Authorization: Bearer <jwt_token>
    2. API Key: Authorization: Bearer <api_key>
    3. 直接 Token: Authorization: <token>
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少认证信息")

    # 提取 Token
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    else:
        token = authorization

    # 加载配置
    config = load_config()
    auth_config = config.get("auth", {})

    # 🔒 安全：JWT 验证 - 强制要求配置密钥
    if token.count('.') >= 2:  # JWT 格式
        try:
            import jwt
            secret_key = auth_config.get("jwt_secret")
            
            # 🔒 安全：如果没有配置密钥，拒绝 JWT 认证
            if not secret_key:
                logger.critical("未配置 jwt_secret，无法使用 JWT 认证")
                raise HTTPException(
                    status_code=503, 
                    detail="服务未配置 jwt_secret，请在 config.yaml 中配置"
                )
            
            payload = jwt.decode(token, secret_key, algorithms=["HS256"])
            
            # 验证 token 类型
            if payload.get("type") == "access":
                logger.info(f"JWT 验证成功 | user={payload.get('sub', 'unknown')}")
                return True
        except jwt.ExpiredSignatureError:
            logger.warning("JWT Token 已过期")
            raise HTTPException(status_code=401, detail="Token 已过期")
        except jwt.InvalidTokenError:
            logger.warning("JWT Token 无效")
            # 继续尝试 API Key 验证
        except Exception:
            logger.warning("JWT 验证失败")
            # 继续尝试 API Key 验证

    # 尝试 API Key 验证
    auth_keys = auth_config.get("api_keys", [])
    
    # 兼容旧配置（server.auth_tokens）
    if not auth_keys:
        auth_keys = config.get("server", {}).get("auth_tokens", [])
    
    # 🔒 安全修复：如果没有配置 Tokens，拒绝所有请求
    if not auth_keys:
        logger.critical("未配置 auth_tokens，拒绝所有请求 - 请在 config.yaml 中配置")
        raise HTTPException(
            status_code=503, detail="服务未配置认证，请联系管理员配置 auth_tokens"
        )
    
    # 提取 API Key 列表（支持新旧格式）
    valid_keys = []
    for key_item in auth_keys:
        if isinstance(key_item, dict):
            # 新格式：{'key': 'sk-xxx', 'name': '...'}
            valid_keys.append(key_item.get('key', ''))
        else:
            # 旧格式：直接是字符串
            valid_keys.append(key_item)
    
    # 验证 API Key
    if token in valid_keys:
        logger.info("API Key 验证成功")
        return True

    # 记录失败的认证尝试
    masked_token = f"***{token[-4:]}" if len(token) > 4 else "***"
    logger.warning(f"认证失败：token={masked_token}")
    raise HTTPException(status_code=401, detail="无效的 Token")


def create_jwt_token(username: str, expires_days: int = 7) -> str:
    """
    创建 JWT Token
    
    🔒 安全改进:
    - Token 过期时间缩短为 7 天（原 30 天）
    - 添加唯一标识（jti），支持吊销
    - 强制要求配置密钥
    
    Args:
        username: 用户名
        expires_days: 过期天数（默认 7 天）
    
    Returns:
        JWT Token 字符串
    """
    import secrets
    
    config = load_config()
    auth_config = config.get("auth", {})
    
    # 🔒 安全：强制要求配置密钥
    secret_key = auth_config.get("jwt_secret")
    if not secret_key:
        logger.critical("未配置 jwt_secret，无法创建 JWT Token")
        raise ValueError("服务未配置 jwt_secret，请在 config.yaml 中配置")
    
    expire = datetime.utcnow() + timedelta(days=expires_days)
    
    # 🔒 安全：生成随机 Token ID（支持吊销）
    jti = secrets.token_hex(16)
    
    to_encode = {
        "sub": username,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access",
        "jti": jti  # 唯一标识
    }
    
    token = jwt.encode(to_encode, secret_key, algorithm="HS256")
    logger.info(f"创建 JWT Token | user={username} | expires={expire.isoformat()}")
    return token


def verify_api_key(x_api_key: Optional[str] = Header(None)) -> bool:
    """
    验证 API Key（通过 X-API-Key 头）
    
    这是另一种认证方式，适用于不支持 Authorization 头的场景
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="缺少 API Key")
    
    config = load_config()
    auth_config = config.get("auth", {})
    
    api_keys = auth_config.get("api_keys", [])
    if not api_keys:
        api_keys = config.get("server", {}).get("auth_tokens", [])
    
    if not api_keys:
        raise HTTPException(status_code=503, detail="服务未配置认证")
    
    if x_api_key in api_keys:
        return True
    
    logger.warning(f"API Key 验证失败：key=***{x_api_key[-4:]}")
    raise HTTPException(status_code=401, detail="无效的 API Key")


# 依赖注入函数
async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """
    获取当前用户信息（用于需要用户上下文的接口）
    
    Returns:
        用户信息字典
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少认证信息")
    
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    else:
        token = authorization
    
    # 尝试 JWT 解析
    if token.count('.') >= 2:
        try:
            import jwt
            config = load_config()
            auth_config = config.get("auth", {})
            secret_key = auth_config.get("jwt_secret", "bridge-server-secret-key-change-me")
            payload = jwt.decode(token, secret_key, algorithms=["HS256"])
            return {
                "username": payload.get("sub", "unknown"),
                "auth_type": "jwt",
                "expires_at": payload.get("exp")
            }
        except Exception:
            pass
    
    # API Key 用户
    return {
        "username": "api_key_user",
        "auth_type": "api_key",
        "expires_at": None
    }
