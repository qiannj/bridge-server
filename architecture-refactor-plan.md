# Bridge Server 重构计划

## 1. 目录结构重组

```
bridge-server/
├── src/                    # 核心代码
│   ├── gateway/           # API网关层
│   │   ├── middleware/    # 中间件
│   │   ├── handlers/      # 请求处理
│   │   └── validators/    # 参数验证
│   ├── services/          # 业务服务层
│   │   ├── auth/         # 认证服务
│   │   ├── routing/      # 路由决策
│   │   ├── proxy/        # 上游代理
│   │   └── usage/        # 用量统计
│   ├── providers/         # AI平台适配器
│   │   ├── base.py       # 基础接口
│   │   ├── dashscope.py  # 阿里云
│   │   ├── openai.py     # OpenAI
│   │   └── moonshot.py   # Moonshot
│   ├── models/           # 数据模型
│   │   ├── requests.py   # 请求模型
│   │   ├── responses.py  # 响应模型
│   │   └── config.py     # 配置模型
│   └── utils/            # 工具函数
│       ├── cache.py      # 缓存工具
│       ├── metrics.py    # 监控指标
│       └── helpers.py    # 通用工具
├── tests/                 # 测试代码
├── config/               # 配置文件
├── docker/              # 容器配置
└── docs/               # 文档
```

## 2. 核心模块重构

### 2.1 抽象Provider基类
```python
# src/providers/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, AsyncGenerator

class BaseProvider(ABC):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client = self._create_client()
    
    @abstractmethod
    async def chat_completion(self, messages: list) -> Dict[str, Any]:
        pass
    
    @abstractmethod  
    async def chat_completion_stream(self, messages: list) -> AsyncGenerator:
        pass
    
    def _create_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.config["base_url"],
            headers=self._get_headers(),
            limits=httpx.Limits(max_connections=20)
        )
```

### 2.2 路由服务解耦
```python
# src/services/routing/router.py
class RouterService:
    def __init__(self, config: RouterConfig, cache: Cache):
        self.config = config
        self.cache = cache
        self.task_detector = TaskDetector()
    
    async def route(self, message: str, user_context: Dict) -> RouteResult:
        cache_key = self._generate_cache_key(message)
        
        # 尝试缓存
        if cached := await self.cache.get(cache_key):
            return RouteResult.from_cache(cached)
        
        # 任务检测
        task_type = self.task_detector.detect(message)
        
        # 模型选择
        selected_model = self._select_model(task_type, user_context)
        
        result = RouteResult(
            model=selected_model,
            task_type=task_type,
            reason=f"智能路由: {task_type}"
        )
        
        # 缓存结果
        await self.cache.set(cache_key, result, ttl=300)
        
        return result
```

### 2.3 用量统计异步化
```python
# src/services/usage/tracker.py
class UsageTracker:
    def __init__(self, writer: BatchWriter):
        self.writer = writer
        self.buffer = []
        
    async def record(self, usage_data: UsageRecord):
        # 非阻塞写入
        await self.writer.write_async(usage_data)
        
    async def get_stats(self, period: str, user_id: str) -> UsageStats:
        # 并发查询多个数据源
        tasks = [
            self._query_database(period, user_id),
            self._query_cache(period, user_id)  
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return self._merge_results(results)
```

## 3. 性能优化方案

### 3.1 连接池优化
```python
# src/utils/http_client.py
class OptimizedHttpClient:
    def __init__(self):
        self.clients = {
            'dashscope': httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=50,
                    max_keepalive_connections=20
                ),
                timeout=httpx.Timeout(30.0, connect=5.0)
            ),
            'openai': httpx.AsyncClient(...),
            # 每个provider独立连接池
        }
    
    async def request(self, provider: str, **kwargs):
        client = self.clients[provider]
        return await client.request(**kwargs)
```

### 3.2 智能缓存策略
```python
# src/utils/cache.py
class SmartCache:
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.memory_cache = TTLCache(maxsize=1000, ttl=300)
        
    async def get(self, key: str):
        # L1: 内存缓存
        if value := self.memory_cache.get(key):
            return value
            
        # L2: Redis缓存 
        if self.redis:
            if value := await self.redis.get(key):
                self.memory_cache[key] = value
                return value
        
        return None
```

### 3.3 批量写入器
```python
# src/utils/batch_writer.py
class BatchWriter:
    def __init__(self, batch_size=100, flush_interval=5):
        self.buffer = []
        self.batch_size = batch_size
        self._start_flush_timer(flush_interval)
    
    async def write_async(self, data: dict):
        self.buffer.append(data)
        
        if len(self.buffer) >= self.batch_size:
            await self._flush()
    
    async def _flush(self):
        if not self.buffer:
            return
            
        batch = self.buffer.copy()
        self.buffer.clear()
        
        # 批量写入数据库
        await self._bulk_insert(batch)
```

## 4. 技术选型调整

### 4.1 依赖精简
```python
# 当前22个依赖 -> 优化到12个核心依赖
core_dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0", 
    "httpx>=0.25.0",
    "pydantic>=2.0.0",
    "pyyaml>=6.0",
    "redis>=5.0.0",       # 缓存
    "sqlalchemy>=2.0.0",  # 数据库ORM
    "prometheus-client",   # 监控指标
    "structlog",          # 结构化日志
    "tenacity",           # 重试机制
    "click",              # CLI工具
    "pytest"              # 测试
]
```

### 4.2 配置统一
```python
# src/models/config.py
from pydantic import BaseSettings

class BridgeServerConfig(BaseSettings):
    # 服务配置
    host: str = "127.0.0.1"
    port: int = 19377
    workers: int = 4
    
    # 性能配置
    max_connections: int = 100
    request_timeout: int = 30
    batch_size: int = 100
    cache_ttl: int = 300
    
    # 数据库配置
    database_url: str = "sqlite:///bridge_server.db"
    redis_url: Optional[str] = None
    
    # 监控配置
    enable_metrics: bool = True
    metrics_port: int = 9090
    
    class Config:
        env_file = ".env"
        env_prefix = "BRIDGE_"
```

## 5. 实施计划

### 阶段1：核心重构（1周）
1. Provider抽象层 - 统一上游接口
2. 路由服务解耦 - 独立路由决策
3. 异步改造 - 消除同步阻塞

### 阶段2：性能优化（1周）  
1. 连接池优化 - 提升并发能力
2. 智能缓存 - 减少重复计算
3. 批量写入 - 降低I/O开销

### 阶段3：架构升级（2周）
1. 微服务拆分 - 解耦核心模块
2. 监控完善 - 性能指标采集
3. 容错机制 - 提升系统稳定性

## 6. 预期收益

| 指标 | 现状 | 目标 | 提升 |
|------|------|------|------|
| 并发请求 | 10 req/s | 100+ req/s | 10x |
| 响应延迟 | 2-10s | 50-200ms | 20-50x |
| 内存使用 | 200MB | 150MB | 25% ↓ |
| 代码复杂度 | 高耦合 | 模块化 | 可维护性大幅提升 |
| 错误率 | 5% | <1% | 5x稳定性提升 |

这个重构计划可以根据你的时间安排分阶段实施，优先解决最严重的性能瓶颈。