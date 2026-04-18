#!/usr/bin/env python3
"""
异步认证模块 - v2.0
优化用户认证和授权流程
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Optional, Dict, Any
from pathlib import Path
import aiofiles

logger = logging.getLogger(__name__)

# Sentinel used to mark that tokens.json stores hashed keys (SHA-256 hex).
_HASHED_FORMAT_MARKER = "_format"
_HASHED_FORMAT_VALUE = "hashed_v1"


def _hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a token for safe at-rest storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _tokens_are_hashed(data: dict) -> bool:
    return data.get(_HASHED_FORMAT_MARKER) == _HASHED_FORMAT_VALUE


def _default_config_dir() -> Path:
    """Return config dir: BRIDGE_CONFIG_DIR env var, else ~/.bridge-server."""
    env = os.getenv("BRIDGE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".bridge-server"


class AsyncAuthManager:
    """异步认证管理器"""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or _default_config_dir()
        self.users_file = self.config_dir / "users.json"
        self.tokens_file = self.config_dir / "tokens.json"

        # 内存缓存（TTL: 5分钟）
        self._user_cache = {}
        self._token_cache = {}
        self._cache_ttl = 300
    
    async def initialize(self) -> None:
        """初始化认证管理器"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # 确保配置文件存在
        await self._ensure_config_files()
        
        # 预加载用户数据到缓存
        await self._preload_cache()
        
        logger.info("✅ 异步认证管理器初始化完成")
    
    async def _ensure_config_files(self) -> None:
        """确保配置文件存在"""
        default_users = {
            "admin": {
                "user_id": "admin",
                "username": "admin",
                "domain": "admin",
                "permissions": ["read", "write", "admin"],
                "created_at": time.time(),
                "active": True,
            },
        }

        if not self.users_file.exists():
            async with aiofiles.open(self.users_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(default_users, indent=2, ensure_ascii=False))

        if not self.tokens_file.exists():
            # Generate a cryptographically random admin token and show it once.
            admin_token = secrets.token_hex(32)

            separator = "=" * 60
            logger.warning(
                "\n%s\n"
                "IMPORTANT: New admin token generated — save it now.\n"
                "It will NOT be shown again.\n"
                "  Admin token : %s\n"
                "%s",
                separator,
                admin_token,
                separator,
            )

            # Store only the SHA-256 hash on disk — never the plaintext token.
            default_tokens: Dict[str, Any] = {
                _HASHED_FORMAT_MARKER: _HASHED_FORMAT_VALUE,
                _hash_token(admin_token): {
                    "user_id": "admin",
                    "created_at": time.time(),
                    "expires_at": None,
                    "active": True,
                },
            }

            async with aiofiles.open(self.tokens_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(default_tokens, indent=2, ensure_ascii=False))
        else:
            # Migrate existing plaintext-keyed tokens to hashed format.
            await self._migrate_tokens_to_hashed()

    async def _migrate_tokens_to_hashed(self) -> None:
        """One-time migration: re-key tokens.json using SHA-256 hashes."""
        try:
            async with aiofiles.open(self.tokens_file, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())

            if _tokens_are_hashed(data):
                return  # Already migrated.

            migrated: Dict[str, Any] = {_HASHED_FORMAT_MARKER: _HASHED_FORMAT_VALUE}
            for key, value in data.items():
                if not key.startswith("_"):
                    migrated[_hash_token(key)] = value

            async with aiofiles.open(self.tokens_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(migrated, indent=2, ensure_ascii=False))

            logger.info("tokens.json migrated to hashed-key format (hashed_v1)")
        except Exception as exc:
            logger.error("Token migration failed: %s", exc)

    async def _preload_cache(self) -> None:
        """预加载缓存"""
        try:
            async with aiofiles.open(self.users_file, "r", encoding="utf-8") as f:
                users_data = json.loads(await f.read())
                for user_id, user_info in users_data.items():
                    cache_key = f"user:{user_id}"
                    self._user_cache[cache_key] = {
                        "data": user_info,
                        "timestamp": time.time(),
                    }

            async with aiofiles.open(self.tokens_file, "r", encoding="utf-8") as f:
                tokens_data = json.loads(await f.read())
                for token_hash, token_info in tokens_data.items():
                    # Skip the format marker and any metadata keys.
                    if token_hash.startswith("_"):
                        continue
                    # Cache key uses the hash so plaintext tokens never enter memory.
                    cache_key = f"token:{token_hash}"
                    self._token_cache[cache_key] = {
                        "data": token_info,
                        "timestamp": time.time(),
                    }

            logger.info("缓存预加载完成: %d 用户, %d 令牌", len(self._user_cache), len(self._token_cache))

        except Exception as e:
            logger.warning("缓存预加载失败: %s", e)

    async def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """验证令牌"""
        if not token:
            return None

        if token.startswith("Bearer "):
            token = token[7:]

        token_hash = _hash_token(token)

        # Check in-memory cache (keyed by hash, not plaintext).
        cache_key = f"token:{token_hash}"
        if cache_key in self._token_cache:
            cached_item = self._token_cache[cache_key]
            if time.time() - cached_item["timestamp"] < self._cache_ttl:
                return cached_item["data"]

        try:
            async with aiofiles.open(self.tokens_file, "r", encoding="utf-8") as f:
                tokens_data = json.loads(await f.read())

            token_info = tokens_data.get(token_hash)
            if token_info and token_info.get("active", True):
                expires_at = token_info.get("expires_at")
                if expires_at and time.time() > expires_at:
                    return None

                self._token_cache[cache_key] = {
                    "data": token_info,
                    "timestamp": time.time(),
                }
                return token_info

        except Exception as e:
            logger.error("令牌验证失败: %s", e)

        return None
    
    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """根据用户ID获取用户信息"""
        if not user_id:
            return None
        
        # 检查缓存
        cache_key = f"user:{user_id}"
        if cache_key in self._user_cache:
            cached_item = self._user_cache[cache_key]
            if time.time() - cached_item["timestamp"] < self._cache_ttl:
                return cached_item["data"]
        
        # 从文件加载
        try:
            async with aiofiles.open(self.users_file, 'r', encoding='utf-8') as f:
                users_data = json.loads(await f.read())
                
                user_info = users_data.get(user_id)
                if user_info and user_info.get("active", True):
                    # 更新缓存
                    self._user_cache[cache_key] = {
                        "data": user_info,
                        "timestamp": time.time()
                    }
                    
                    return user_info
        
        except Exception as e:
            logger.error(f"用户查询失败: {str(e)}")
        
        return None
    
    def clear_cache(self) -> None:
        """清理缓存"""
        self._user_cache.clear()
        self._token_cache.clear()
        logger.info("认证缓存已清理")


# 全局认证管理器实例
auth_manager: Optional[AsyncAuthManager] = None


async def get_auth_manager() -> AsyncAuthManager:
    """获取认证管理器实例"""
    global auth_manager
    if auth_manager is None:
        auth_manager = AsyncAuthManager()
        await auth_manager.initialize()
    return auth_manager


async def verify_token_async(authorization: Optional[str] = None) -> bool:
    """异步验证令牌"""
    if not authorization:
        return False
    
    auth_mgr = await get_auth_manager()
    token_info = await auth_mgr.verify_token(authorization)
    return token_info is not None


async def get_current_user_async(authorization: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """异步获取当前用户信息；未提供有效 token 时返回 None。"""
    if not authorization:
        return None

    auth_mgr = await get_auth_manager()
    token_info = await auth_mgr.verify_token(authorization)
    if not token_info:
        return None

    user_id = token_info.get("user_id")
    if user_id:
        user_info = await auth_mgr.get_user_by_id(user_id)
        if user_info:
            return user_info

    return {
        "user_id": user_id or "unknown",
        "username": user_id or "unknown",
        "domain": "general",
        "permissions": ["read"],
    }


# 兼容性函数（用于依赖注入）
async def verify_token_dependency(authorization: Optional[str] = None) -> bool:
    """FastAPI依赖注入用的令牌验证"""
    return await verify_token_async(authorization)


async def get_current_user_dependency(authorization: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """FastAPI依赖注入用的用户获取"""
    return await get_current_user_async(authorization)