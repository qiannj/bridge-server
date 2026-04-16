#!/usr/bin/env python3
"""
异步认证模块 - v2.0
优化用户认证和授权流程
"""

import asyncio
import json
import logging
import time
from typing import Optional, Dict, Any
from pathlib import Path
import aiofiles
import hashlib

logger = logging.getLogger(__name__)


class AsyncAuthManager:
    """异步认证管理器"""
    
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path.home() / ".bridge-server"
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
        # 默认用户配置
        default_users = {
            "admin": {
                "user_id": "admin",
                "username": "admin", 
                "domain": "admin",
                "permissions": ["read", "write", "admin"],
                "created_at": time.time(),
                "active": True
            },
            "guest": {
                "user_id": "guest",
                "username": "guest",
                "domain": "general", 
                "permissions": ["read"],
                "created_at": time.time(),
                "active": True
            }
        }
        
        # 默认令牌配置
        default_tokens = {
            "bridge-admin-token": {
                "user_id": "admin",
                "created_at": time.time(),
                "expires_at": None,  # 永不过期
                "active": True
            },
            "bridge-guest-token": {
                "user_id": "guest", 
                "created_at": time.time(),
                "expires_at": None,
                "active": True
            }
        }
        
        # 异步写入文件
        if not self.users_file.exists():
            async with aiofiles.open(self.users_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(default_users, indent=2, ensure_ascii=False))
        
        if not self.tokens_file.exists():
            async with aiofiles.open(self.tokens_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(default_tokens, indent=2, ensure_ascii=False))
    
    async def _preload_cache(self) -> None:
        """预加载缓存"""
        try:
            # 加载用户数据
            async with aiofiles.open(self.users_file, 'r', encoding='utf-8') as f:
                users_data = json.loads(await f.read())
                for user_id, user_info in users_data.items():
                    cache_key = f"user:{user_id}"
                    self._user_cache[cache_key] = {
                        "data": user_info,
                        "timestamp": time.time()
                    }
            
            # 加载令牌数据
            async with aiofiles.open(self.tokens_file, 'r', encoding='utf-8') as f:
                tokens_data = json.loads(await f.read())
                for token, token_info in tokens_data.items():
                    cache_key = f"token:{token}"
                    self._token_cache[cache_key] = {
                        "data": token_info,
                        "timestamp": time.time()
                    }
            
            logger.info(f"缓存预加载完成: {len(self._user_cache)} 用户, {len(self._token_cache)} 令牌")
        
        except Exception as e:
            logger.warning(f"缓存预加载失败: {str(e)}")
    
    async def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """验证令牌"""
        if not token:
            return None
        
        # 清理Bearer前缀
        if token.startswith("Bearer "):
            token = token[7:]
        
        # 检查缓存
        cache_key = f"token:{token}"
        if cache_key in self._token_cache:
            cached_item = self._token_cache[cache_key]
            if time.time() - cached_item["timestamp"] < self._cache_ttl:
                return cached_item["data"]
        
        # 从文件加载
        try:
            async with aiofiles.open(self.tokens_file, 'r', encoding='utf-8') as f:
                tokens_data = json.loads(await f.read())
                
                token_info = tokens_data.get(token)
                if token_info and token_info.get("active", True):
                    # 检查过期时间
                    expires_at = token_info.get("expires_at")
                    if expires_at and time.time() > expires_at:
                        return None
                    
                    # 更新缓存
                    self._token_cache[cache_key] = {
                        "data": token_info,
                        "timestamp": time.time()
                    }
                    
                    return token_info
        
        except Exception as e:
            logger.error(f"令牌验证失败: {str(e)}")
        
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


async def get_current_user_async(authorization: Optional[str] = None) -> Dict[str, Any]:
    """异步获取当前用户信息"""
    if not authorization:
        # 返回默认guest用户
        return {
            "user_id": "guest",
            "username": "guest",
            "domain": "general",
            "permissions": ["read"]
        }
    
    auth_mgr = await get_auth_manager()
    
    # 验证令牌
    token_info = await auth_mgr.verify_token(authorization)
    if not token_info:
        # 返回默认guest用户
        return {
            "user_id": "guest",
            "username": "guest", 
            "domain": "general",
            "permissions": ["read"]
        }
    
    # 获取用户信息
    user_id = token_info.get("user_id")
    if user_id:
        user_info = await auth_mgr.get_user_by_id(user_id)
        if user_info:
            return user_info
    
    # 默认返回基础用户信息
    return {
        "user_id": user_id or "unknown",
        "username": user_id or "unknown",
        "domain": "general",
        "permissions": ["read"]
    }


# 兼容性函数（用于依赖注入）
async def verify_token_dependency(authorization: Optional[str] = None) -> bool:
    """FastAPI依赖注入用的令牌验证"""
    return await verify_token_async(authorization)


async def get_current_user_dependency(authorization: Optional[str] = None) -> Dict[str, Any]:
    """FastAPI依赖注入用的用户获取"""
    return await get_current_user_async(authorization)