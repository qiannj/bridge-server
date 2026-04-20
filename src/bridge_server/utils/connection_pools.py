#!/usr/bin/env python3
"""
连接池优化配置 - Bridge Server v2.0 阶段2
目标：100-150 QPS (Step 2)
"""

import asyncio
import importlib.util
import logging
import os
from typing import Dict, Any, Optional
import aiohttp
import aiosqlite
import httpx
from pathlib import Path

logger = logging.getLogger(__name__)


def _ssl_verify_disabled() -> bool:
    """当设置环境变量 BRIDGE_DISABLE_SSL_VERIFY=1 时跳过 SSL 验证（用于公司代理环境）。"""
    return os.getenv("BRIDGE_DISABLE_SSL_VERIFY", "").strip() in ("1", "true", "yes")


class ConnectionPoolManager:
    """统一连接池管理器"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or self._default_config()
        self._initialized = False
        self._init_lock = asyncio.Lock()
        
        # HTTP连接池
        self.http_connector: Optional[aiohttp.TCPConnector] = None
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.httpx_clients: Dict[str, httpx.AsyncClient] = {}
        
        # SQLite连接池
        self.db_pool = []
        self.db_pool_size = self.config["database"]["pool_size"]
        self.db_semaphore = asyncio.Semaphore(self.db_pool_size)
        
        # Redis连接池（如果启用）
        self.redis_pool = None
        
        logger.info("连接池管理器初始化")
    
    def _default_config(self) -> Dict[str, Any]:
        """默认连接池配置"""
        return {
            "http": {
                # HTTP连接池配置
                "connector_limit": 100,          # 总连接数限制
                "connector_limit_per_host": 30,  # 单主机连接数限制
                "keepalive_timeout": 60,         # 连接保持时间
                "enable_cleanup_closed": True,   # 自动清理关闭的连接
                "ttl_dns_cache": 300,           # DNS缓存TTL
                "use_dns_cache": True,          # 启用DNS缓存
                
                # 请求超时配置
                "total_timeout": 30,            # 总超时时间
                "connect_timeout": 5,           # 连接超时
                "sock_read_timeout": 10,        # 读取超时
                "sock_connect_timeout": 5,      # Socket连接超时
                
                # 重试配置
                "max_retries": 3,
                "retry_backoff_factor": 0.5
            },
            "database": {
                # SQLite连接池配置
                "pool_size": 10,                # 连接池大小
                "checkout_timeout": 5,          # 获取连接超时
                "recycle_time": 3600,          # 连接回收时间(秒)
                
                # SQLite优化参数
                "journal_mode": "WAL",          # 使用WAL模式
                "synchronous": "NORMAL",        # 平衡性能和安全
                "cache_size": 64000,           # 缓存页数 (64MB)
                "temp_store": "MEMORY",         # 临时数据存储在内存
                "mmap_size": 268435456,        # 内存映射大小 (256MB)
                "page_size": 4096              # 页面大小
            },
            "redis": {
                # Redis连接池配置（如果使用）
                "max_connections": 20,          # 最大连接数
                "retry_on_timeout": True,       # 超时重试
                "health_check_interval": 30,    # 健康检查间隔
                "socket_keepalive": True,       # 保持连接
                "socket_keepalive_options": {}
            }
        }
    
    async def initialize(self):
        """初始化所有连接池"""
        async with self._init_lock:
            if self._initialized:
                return
            
            logger.info("🔄 初始化连接池...")
            
            # 1. 初始化HTTP连接池
            await self._init_http_pool()
            
            # 2. 初始化数据库连接池
            await self._init_database_pool()
            
            # 3. 初始化Redis连接池（可选）
            if self.config.get("redis", {}).get("enabled", False):
                await self._init_redis_pool()
            
            self._initialized = True
            logger.info("✅ 连接池初始化完成")
    
    async def _init_http_pool(self):
        """初始化HTTP连接池"""
        http_config = self.config["http"]
        
        # 创建TCP连接器
        self.http_connector = aiohttp.TCPConnector(
            limit=http_config["connector_limit"],
            limit_per_host=http_config["connector_limit_per_host"],
            keepalive_timeout=http_config["keepalive_timeout"],
            enable_cleanup_closed=http_config["enable_cleanup_closed"],
            ttl_dns_cache=http_config["ttl_dns_cache"],
            use_dns_cache=http_config["use_dns_cache"]
        )
        
        # 创建超时配置
        timeout = aiohttp.ClientTimeout(
            total=http_config["total_timeout"],
            connect=http_config["connect_timeout"],
            sock_read=http_config["sock_read_timeout"],
            sock_connect=http_config["sock_connect_timeout"]
        )
        
        # 创建HTTP会话
        self.http_session = aiohttp.ClientSession(
            connector=self.http_connector,
            timeout=timeout,
            connector_owner=True
        )
        
        logger.info(f"HTTP连接池初始化: {http_config['connector_limit']} 连接")
    
    async def _init_database_pool(self):
        """初始化SQLite连接池"""
        db_config = self.config["database"]
        db_path = Path.home() / ".bridge-server" / "usage.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 预创建连接池
        for i in range(self.db_pool_size):
            try:
                conn = await aiosqlite.connect(str(db_path))
                
                # 应用SQLite优化参数
                await conn.execute(f"PRAGMA journal_mode={db_config['journal_mode']}")
                await conn.execute(f"PRAGMA synchronous={db_config['synchronous']}")
                await conn.execute(f"PRAGMA cache_size={db_config['cache_size']}")
                await conn.execute(f"PRAGMA temp_store={db_config['temp_store']}")
                await conn.execute(f"PRAGMA mmap_size={db_config['mmap_size']}")
                await conn.execute(f"PRAGMA page_size={db_config['page_size']}")
                
                # 启用外键约束
                await conn.execute("PRAGMA foreign_keys=ON")
                
                self.db_pool.append({
                    "connection": conn,
                    "created_at": asyncio.get_event_loop().time(),
                    "in_use": False
                })
                
            except Exception as e:
                logger.error(f"创建数据库连接失败: {str(e)}")
        
        logger.info(f"SQLite连接池初始化: {len(self.db_pool)} 连接")
    
    async def _init_redis_pool(self):
        """初始化Redis连接池"""
        try:
            import redis.asyncio as redis
            redis_config = self.config["redis"]
            
            self.redis_pool = redis.ConnectionPool(
                max_connections=redis_config["max_connections"],
                retry_on_timeout=redis_config["retry_on_timeout"],
                health_check_interval=redis_config["health_check_interval"],
                socket_keepalive=redis_config["socket_keepalive"],
                socket_keepalive_options=redis_config["socket_keepalive_options"]
            )
            
            logger.info(f"Redis连接池初始化: {redis_config['max_connections']} 连接")
            
        except ImportError:
            logger.warning("Redis模块未安装，跳过Redis连接池")
        except Exception as e:
            logger.error(f"Redis连接池初始化失败: {str(e)}")
    
    async def get_http_session(self) -> aiohttp.ClientSession:
        """获取HTTP会话"""
        if self.http_session is None:
            await self._init_http_pool()
        
        return self.http_session
    
    async def get_db_connection(self):
        """获取数据库连接（连接池模式）"""
        await self.db_semaphore.acquire()
        
        try:
            current_time = asyncio.get_event_loop().time()
            recycle_time = self.config["database"]["recycle_time"]
            
            for pool_item in self.db_pool:
                if (
                    not pool_item["in_use"]
                    and current_time - pool_item["created_at"] < recycle_time
                ):
                    pool_item["in_use"] = True
                    return DatabaseConnection(pool_item, self)
            
            logger.warning("连接池耗尽，创建临时连接")
            db_path = Path.home() / ".bridge-server" / "usage.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            temp_conn = await aiosqlite.connect(str(db_path))
            
            db_config = self.config["database"]
            await temp_conn.execute(f"PRAGMA journal_mode={db_config['journal_mode']}")
            await temp_conn.execute(f"PRAGMA synchronous={db_config['synchronous']}")
            await temp_conn.execute(f"PRAGMA cache_size={db_config['cache_size']}")
            await temp_conn.execute(f"PRAGMA temp_store={db_config['temp_store']}")
            
            return DatabaseConnection({
                "connection": temp_conn,
                "created_at": current_time,
                "in_use": True,
                "temporary": True
            }, self)
        except Exception:
            self.db_semaphore.release()
            raise
    
    def release_db_connection(self, pool_item: Dict[str, Any]):
        """释放数据库连接"""
        if pool_item.get("temporary"):
            # 临时连接直接关闭
            asyncio.create_task(pool_item["connection"].close())
        else:
            # 连接池连接标记为可用
            pool_item["in_use"] = False
        self.db_semaphore.release()

    def get_provider_http_client(
        self,
        provider_id: str,
        *,
        base_url: str,
        headers: Dict[str, str],
        timeout: Optional[float] = None,
        http2: bool = True,
        max_connections: Optional[int] = None,
        max_keepalive_connections: Optional[int] = None,
        follow_redirects: bool = True,
        event_hooks: Optional[Dict[str, Any]] = None,
    ) -> httpx.AsyncClient:
        """获取Provider共享HTTP客户端"""
        existing_client = self.httpx_clients.get(provider_id)
        if existing_client and not existing_client.is_closed:
            return existing_client
        
        http_config = self.config["http"]
        http2_enabled = bool(http2 and importlib.util.find_spec("h2"))
        if http2 and not http2_enabled:
            logger.info("未检测到 h2 依赖，Provider HTTP 客户端回退到 HTTP/1.1")
        # 确保 base_url 以 '/' 结尾，避免 httpx 按 RFC 3986 规则丢弃最后一段路径
        normalized_base_url = base_url.rstrip('/') + '/' if base_url else base_url
        client = httpx.AsyncClient(
            base_url=normalized_base_url,
            headers=headers,
            limits=httpx.Limits(
                max_connections=max_connections or http_config["connector_limit"],
                max_keepalive_connections=(
                    max_keepalive_connections or http_config["connector_limit_per_host"]
                ),
            ),
            timeout=httpx.Timeout(
                timeout or http_config["total_timeout"],
                connect=http_config["connect_timeout"],
            ),
            http2=http2_enabled,
            follow_redirects=follow_redirects,
            event_hooks=event_hooks,
            verify=not _ssl_verify_disabled(),
        )
        self.httpx_clients[provider_id] = client
        return client
    
    async def get_stats(self) -> Dict[str, Any]:
        """获取连接池统计"""
        stats = {
            "http": {},
            "database": {},
            "redis": {},
            "provider_http_clients": {}
        }
        
        # HTTP连接池统计
        if self.http_connector:
            stats["http"] = {
                "total_connections": len(self.http_connector._conns),
                "available_connections": sum(len(conns) for conns in self.http_connector._conns.values()),
                "limit": self.http_connector._limit,
                "limit_per_host": self.http_connector._limit_per_host
            }
        
        # 数据库连接池统计
        if self.db_pool:
            in_use_count = sum(1 for item in self.db_pool if item["in_use"])
            stats["database"] = {
                "pool_size": len(self.db_pool),
                "in_use": in_use_count,
                "available": len(self.db_pool) - in_use_count,
                "utilization": round(in_use_count / len(self.db_pool), 3) if self.db_pool else 0
            }
        
        if self.httpx_clients:
            stats["provider_http_clients"] = {
                "count": len(self.httpx_clients),
                "clients": {
                    provider_id: {
                        "base_url": str(client.base_url),
                        "closed": client.is_closed,
                    }
                    for provider_id, client in self.httpx_clients.items()
                },
            }
        
        return stats
    
    async def health_check(self) -> Dict[str, bool]:
        """连接池健康检查"""
        health = {
            "http": False,
            "database": False,
            "redis": False
        }
        
        # HTTP健康检查
        if self.http_session and not self.http_session.closed:
            health["http"] = True
        
        # 数据库健康检查
        try:
            conn_wrapper = await self.get_db_connection()
            async with conn_wrapper as conn:
                await conn.execute("SELECT 1")
                health["database"] = True
        except Exception as e:
            logger.warning(f"数据库健康检查失败: {str(e)}")
        
        # Redis健康检查
        if self.redis_pool:
            try:
                import redis.asyncio as redis
                r = redis.Redis(connection_pool=self.redis_pool)
                await r.ping()
                health["redis"] = True
            except Exception as e:
                logger.warning(f"Redis健康检查失败: {str(e)}")
        
        return health
    
    async def cleanup(self):
        """清理所有连接池"""
        logger.info("🧹 清理连接池...")
        
        cleanup_tasks = []
        
        # 清理HTTP会话
        if self.http_session:
            cleanup_tasks.append(self.http_session.close())
        
        for client in self.httpx_clients.values():
            if not client.is_closed:
                cleanup_tasks.append(client.aclose())
        
        # 清理数据库连接
        for pool_item in self.db_pool:
            cleanup_tasks.append(pool_item["connection"].close())
        
        # 等待所有清理任务完成
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        
        self.db_pool.clear()
        self.httpx_clients.clear()
        self.http_session = None
        self.http_connector = None
        self.redis_pool = None
        self._initialized = False
        logger.info("✅ 连接池清理完成")


class DatabaseConnection:
    """数据库连接包装器"""
    
    def __init__(self, pool_item: Dict[str, Any], pool_manager: ConnectionPoolManager):
        self.pool_item = pool_item
        self.pool_manager = pool_manager
        self.connection = pool_item["connection"]
    
    async def __aenter__(self):
        return self.connection
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.pool_manager.release_db_connection(self.pool_item)


# 全局连接池管理器
connection_pool_manager: Optional[ConnectionPoolManager] = None


def get_connection_pool_manager_sync() -> ConnectionPoolManager:
    """同步获取连接池管理器实例"""
    global connection_pool_manager
    
    if connection_pool_manager is None:
        connection_pool_manager = ConnectionPoolManager()
    
    return connection_pool_manager


async def get_connection_pool_manager() -> ConnectionPoolManager:
    """获取连接池管理器实例"""
    pool_manager = get_connection_pool_manager_sync()
    await pool_manager.initialize()
    return pool_manager


def get_provider_http_client(
    provider_id: str,
    *,
    base_url: str,
    headers: Dict[str, str],
    timeout: Optional[float] = None,
    http2: bool = True,
    max_connections: Optional[int] = None,
    max_keepalive_connections: Optional[int] = None,
    follow_redirects: bool = True,
    event_hooks: Optional[Dict[str, Any]] = None,
) -> httpx.AsyncClient:
    """便捷函数：获取Provider共享HTTP客户端"""
    pool_manager = get_connection_pool_manager_sync()
    return pool_manager.get_provider_http_client(
        provider_id,
        base_url=base_url,
        headers=headers,
        timeout=timeout,
        http2=http2,
        max_connections=max_connections,
        max_keepalive_connections=max_keepalive_connections,
        follow_redirects=follow_redirects,
        event_hooks=event_hooks,
    )


async def get_http_session() -> aiohttp.ClientSession:
    """便捷函数：获取HTTP会话"""
    pool_manager = await get_connection_pool_manager()
    return await pool_manager.get_http_session()


async def get_db_connection():
    """便捷函数：获取数据库连接"""
    pool_manager = await get_connection_pool_manager()
    return await pool_manager.get_db_connection()


async def close_connection_pool_manager():
    """关闭并重置全局连接池管理器"""
    global connection_pool_manager
    
    if connection_pool_manager is not None:
        await connection_pool_manager.cleanup()
        connection_pool_manager = None
