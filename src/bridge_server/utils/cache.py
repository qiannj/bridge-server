#!/usr/bin/env python3
"""
智能缓存系统 - Bridge Server v2.0
L1(内存) + L2(Redis) 二级缓存，提升响应速度
"""

import asyncio
import json
import logging
import time
from typing import Any, Optional, Dict, Union
from dataclasses import dataclass
from cachetools import TTLCache
import redis.asyncio as redis

logger = logging.getLogger(__name__)


@dataclass
class CacheMetrics:
    """缓存指标"""
    l1_hits: int = 0
    l2_hits: int = 0
    misses: int = 0
    writes: int = 0
    errors: int = 0
    
    @property
    def total_requests(self) -> int:
        return self.l1_hits + self.l2_hits + self.misses
    
    @property
    def hit_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return (self.l1_hits + self.l2_hits) / self.total_requests
    
    @property
    def l1_hit_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.l1_hits / self.total_requests


class HybridCache:
    """二级混合缓存"""
    
    def __init__(self, 
                 redis_url: Optional[str] = None,
                 l1_maxsize: int = 2000,
                 l1_ttl: int = 300,
                 l2_ttl: int = 1800,
                 key_prefix: str = "bridge:cache:"):
        
        # L1 内存缓存
        self.l1_cache = TTLCache(maxsize=l1_maxsize, ttl=l1_ttl)
        
        # L2 Redis缓存
        self.l2_cache = None
        self.redis_url = redis_url
        self.l2_ttl = l2_ttl
        
        # 缓存配置
        self.key_prefix = key_prefix
        
        # 指标统计
        self.metrics = CacheMetrics()
        
        # 初始化Redis连接
        if redis_url:
            asyncio.create_task(self._init_redis())
        
        logger.info(f"混合缓存初始化 | L1容量: {l1_maxsize} | L1TTL: {l1_ttl}s | L2TTL: {l2_ttl}s")
    
    async def _init_redis(self):
        """初始化Redis连接"""
        try:
            self.l2_cache = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=10
            )
            
            # 测试连接
            await self.l2_cache.ping()
            logger.info("Redis缓存连接成功")
            
        except Exception as e:
            logger.warning(f"Redis连接失败，仅使用内存缓存: {str(e)}")
            self.l2_cache = None
    
    def _make_key(self, key: str) -> str:
        """生成带前缀的缓存键"""
        return f"{self.key_prefix}{key}"
    
    async def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        try:
            # L1 缓存查找
            if key in self.l1_cache:
                self.metrics.l1_hits += 1
                logger.debug(f"L1缓存命中: {key}")
                return self.l1_cache[key]
            
            # L2 缓存查找
            if self.l2_cache:
                redis_key = self._make_key(key)
                cached_value = await self.l2_cache.get(redis_key)
                
                if cached_value is not None:
                    # 反序列化
                    try:
                        value = json.loads(cached_value)
                        
                        # 回写到L1缓存
                        self.l1_cache[key] = value
                        
                        self.metrics.l2_hits += 1
                        logger.debug(f"L2缓存命中: {key}")
                        return value
                        
                    except json.JSONDecodeError as e:
                        logger.warning(f"缓存反序列化失败: {key}, 错误: {str(e)}")
                        # 删除损坏的缓存
                        await self.l2_cache.delete(redis_key)
            
            # 缓存未命中
            self.metrics.misses += 1
            logger.debug(f"缓存未命中: {key}")
            return None
            
        except Exception as e:
            self.metrics.errors += 1
            logger.error(f"缓存读取错误: {key}, 错误: {str(e)}")
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置缓存值"""
        try:
            # L1 缓存写入
            self.l1_cache[key] = value
            
            # L2 缓存写入
            if self.l2_cache:
                redis_key = self._make_key(key)
                
                try:
                    # 序列化
                    serialized_value = json.dumps(value, ensure_ascii=False)
                    
                    # 设置TTL
                    cache_ttl = ttl or self.l2_ttl
                    
                    await self.l2_cache.setex(redis_key, cache_ttl, serialized_value)
                    
                except (json.JSONEncodeError, TypeError) as e:
                    logger.warning(f"缓存序列化失败: {key}, 错误: {str(e)}")
                    return False
            
            self.metrics.writes += 1
            logger.debug(f"缓存写入成功: {key}")
            return True
            
        except Exception as e:
            self.metrics.errors += 1
            logger.error(f"缓存写入错误: {key}, 错误: {str(e)}")
            return False
    
    async def delete(self, key: str) -> bool:
        """删除缓存"""
        try:
            # 删除L1缓存
            if key in self.l1_cache:
                del self.l1_cache[key]
            
            # 删除L2缓存
            if self.l2_cache:
                redis_key = self._make_key(key)
                await self.l2_cache.delete(redis_key)
            
            logger.debug(f"缓存删除成功: {key}")
            return True
            
        except Exception as e:
            self.metrics.errors += 1
            logger.error(f"缓存删除错误: {key}, 错误: {str(e)}")
            return False
    
    async def exists(self, key: str) -> bool:
        """检查缓存是否存在"""
        try:
            # 检查L1缓存
            if key in self.l1_cache:
                return True
            
            # 检查L2缓存
            if self.l2_cache:
                redis_key = self._make_key(key)
                return await self.l2_cache.exists(redis_key) > 0
            
            return False
            
        except Exception as e:
            logger.error(f"缓存存在性检查错误: {key}, 错误: {str(e)}")
            return False
    
    async def clear(self, pattern: Optional[str] = None) -> int:
        """清空缓存"""
        cleared = 0
        
        try:
            # 清空L1缓存
            if pattern:
                # 模式匹配清理（简单实现）
                keys_to_delete = [k for k in self.l1_cache.keys() if pattern in k]
                for k in keys_to_delete:
                    del self.l1_cache[k]
                    cleared += 1
            else:
                cleared += len(self.l1_cache)
                self.l1_cache.clear()
            
            # 清空L2缓存
            if self.l2_cache:
                if pattern:
                    # Redis模式匹配删除
                    redis_pattern = f"{self.key_prefix}*{pattern}*"
                    keys = await self.l2_cache.keys(redis_pattern)
                    if keys:
                        deleted = await self.l2_cache.delete(*keys)
                        cleared += deleted
                else:
                    # 删除所有带前缀的键
                    redis_pattern = f"{self.key_prefix}*"
                    keys = await self.l2_cache.keys(redis_pattern)
                    if keys:
                        deleted = await self.l2_cache.delete(*keys)
                        cleared += deleted
            
            logger.info(f"缓存清理完成，删除 {cleared} 个条目")
            return cleared
            
        except Exception as e:
            logger.error(f"缓存清理错误: {str(e)}")
            return cleared
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取缓存指标"""
        return {
            "l1_size": len(self.l1_cache),
            "l1_maxsize": self.l1_cache.maxsize,
            "l1_ttl": self.l1_cache.ttl,
            "l2_enabled": self.l2_cache is not None,
            "l2_ttl": self.l2_ttl,
            "metrics": {
                "total_requests": self.metrics.total_requests,
                "l1_hits": self.metrics.l1_hits,
                "l2_hits": self.metrics.l2_hits,
                "misses": self.metrics.misses,
                "writes": self.metrics.writes,
                "errors": self.metrics.errors,
                "hit_rate": round(self.metrics.hit_rate, 3),
                "l1_hit_rate": round(self.metrics.l1_hit_rate, 3)
            }
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        health = {
            "l1_cache": True,
            "l2_cache": False,
            "overall": False
        }
        
        try:
            # L1缓存健康检查（写入测试值）
            test_key = f"health_check_{int(time.time())}"
            self.l1_cache[test_key] = "test"
            
            if test_key in self.l1_cache:
                health["l1_cache"] = True
                del self.l1_cache[test_key]
            
            # L2缓存健康检查
            if self.l2_cache:
                await self.l2_cache.ping()
                health["l2_cache"] = True
            
            health["overall"] = health["l1_cache"]
            
        except Exception as e:
            logger.error(f"缓存健康检查失败: {str(e)}")
            health["error"] = str(e)
        
        return health
    
    async def close(self):
        """关闭缓存连接"""
        try:
            if self.l2_cache:
                await self.l2_cache.close()
                logger.info("Redis缓存连接已关闭")
        except Exception as e:
            logger.error(f"关闭缓存连接失败: {str(e)}")


class CacheManager:
    """缓存管理器 - 管理多个缓存实例"""
    
    def __init__(self):
        self.caches: Dict[str, HybridCache] = {}
        logger.info("缓存管理器初始化完成")
    
    def create_cache(self, name: str, **kwargs) -> HybridCache:
        """创建缓存实例"""
        cache = HybridCache(**kwargs)
        self.caches[name] = cache
        logger.info(f"创建缓存实例: {name}")
        return cache
    
    def get_cache(self, name: str) -> Optional[HybridCache]:
        """获取缓存实例"""
        return self.caches.get(name)
    
    async def close_all(self):
        """关闭所有缓存连接"""
        for name, cache in self.caches.items():
            try:
                await cache.close()
                logger.info(f"缓存实例已关闭: {name}")
            except Exception as e:
                logger.error(f"关闭缓存实例失败: {name}, 错误: {str(e)}")
        
        self.caches.clear()
    
    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """获取所有缓存的指标"""
        metrics = {}
        for name, cache in self.caches.items():
            metrics[name] = cache.get_metrics()
        return metrics