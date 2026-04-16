# Bridge Server 完整优化计划

## 项目现状诊断

### 技术债务清单
1. **架构问题** - 494行单体main.py，耦合严重
2. **性能瓶颈** - 同步阻塞，单进程10req/s上限  
3. **依赖混乱** - 22个库功能重叠，存储方案分散
4. **监控缺失** - Prometheus配置未实现，日志系统落后
5. **可维护性差** - 缺乏测试，代码结构混乱

## 优化策略总览

### 三阶段改造路径
```
阶段1: 核心架构重构 (2周) → 阶段2: 性能深度优化 (2周) → 阶段3: 可观测性建设 (1周)
```

---

## 阶段1：核心架构重构 (2周)

### 1.1 目录结构重组
```
bridge-server/
├── src/                    # 核心代码
│   ├── gateway/           # API网关层
│   ├── services/          # 业务服务层
│   ├── providers/         # AI平台适配器
│   ├── models/           # 数据模型
│   └── utils/            # 工具函数
├── observability/         # 可观测性
│   ├── logging/          # 日志配置
│   ├── metrics/          # 指标采集
│   └── tracing/          # 链路追踪
├── tests/                # 测试代码
├── config/               # 配置文件
└── docker/              # 容器配置
```

### 1.2 Provider抽象层
```python
# src/providers/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, AsyncGenerator
import httpx

class BaseProvider(ABC):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client = self._create_optimized_client()
        self.metrics = MetricsCollector(self.__class__.__name__)
    
    def _create_optimized_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.config["base_url"],
            headers=self._get_headers(),
            limits=httpx.Limits(
                max_connections=50,      # 单provider连接池
                max_keepalive_connections=20
            ),
            timeout=httpx.Timeout(30.0, connect=5.0),
            http2=True,                 # 启用HTTP/2
        )
    
    @abstractmethod
    async def chat_completion(self, messages: list) -> Dict[str, Any]:
        pass
    
    async def _request_with_retry(self, *args, **kwargs):
        # 内置重试机制 + 指标采集
        pass
```

### 1.3 服务层解耦
```python
# src/services/routing/router.py
class SmartRouter:
    def __init__(self, cache: HybridCache, config: RouterConfig):
        self.cache = cache
        self.config = config
        self.task_detector = TaskDetector()
    
    async def route(self, message: str, user_context: Dict) -> RouteResult:
        # 缓存优先 + 智能路由 + 负载均衡
        pass

# src/services/proxy/proxy.py  
class ProxyService:
    async def forward_request(self, provider: str, data: Dict) -> Dict:
        # 统一代理层 + 熔断机制
        pass
```

---

## 阶段2：性能深度优化 (2周)

### 2.1 HTTP客户端优化
```python
# src/utils/http_client.py
class OptimizedHttpManager:
    def __init__(self):
        self.clients = {
            'dashscope': self._create_client({
                'max_connections': 100,
                'base_url': 'https://dashscope.aliyuncs.com'
            }),
            'openai': self._create_client({
                'max_connections': 80, 
                'base_url': 'https://api.openai.com'
            }),
            'moonshot': self._create_client({
                'max_connections': 60,
                'base_url': 'https://api.moonshot.cn'  
            })
        }
    
    def _create_client(self, config: Dict) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=config['max_connections'],
                max_keepalive_connections=20
            ),
            timeout=httpx.Timeout(30.0, connect=5.0),
            http2=True,
            retries=3  # 自动重试
        )
```

### 2.2 二级缓存体系
```python
# src/utils/cache.py
class HybridCache:
    def __init__(self, redis_client=None):
        self.l1_cache = TTLCache(maxsize=2000, ttl=300)  # 内存缓存
        self.l2_cache = redis_client                      # Redis缓存
        self.metrics = CacheMetrics()
    
    async def get(self, key: str) -> Optional[Any]:
        # L1命中
        if value := self.l1_cache.get(key):
            self.metrics.record_hit('l1')
            return value
            
        # L2命中  
        if self.l2_cache and (value := await self.l2_cache.get(key)):
            self.l1_cache[key] = value  # 回写L1
            self.metrics.record_hit('l2')
            return value
        
        self.metrics.record_miss()
        return None
    
    async def set(self, key: str, value: Any, ttl: int = 300):
        # 双写策略
        self.l1_cache[key] = value
        if self.l2_cache:
            await self.l2_cache.setex(key, ttl, value)
```

### 2.3 批量写入优化
```python
# src/utils/batch_writer.py
class HighPerformanceWriter:
    def __init__(self, batch_size=200, flush_interval=3):
        self.buffer = []
        self.batch_size = batch_size
        self.lock = asyncio.Lock()
        self._start_flush_timer(flush_interval)
        
    async def write_async(self, data: UsageRecord):
        async with self.lock:
            self.buffer.append(data)
            
            if len(self.buffer) >= self.batch_size:
                await self._flush_batch()
    
    async def _flush_batch(self):
        if not self.buffer:
            return
            
        batch = self.buffer.copy()
        self.buffer.clear()
        
        # 并行写入多个存储
        tasks = [
            self._write_to_sqlite(batch),
            self._write_to_redis_stats(batch),
            self._update_prometheus_metrics(batch)
        ]
        
        await asyncio.gather(*tasks, return_exceptions=True)
```

---

## 阶段3：可观测性建设 (1周)

### 3.1 结构化日志系统
```python
# observability/logging/setup.py
import structlog
from pythonjsonlogger import jsonlogger

def setup_structured_logging():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="ISO"),
            add_correlation_id,  # 请求追踪ID
            add_service_context, # 服务上下文
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(30),  # INFO级别
        logger_factory=structlog.WriteLoggerFactory(),
        cache_logger_on_first_use=True,
    )

# 使用示例
logger = structlog.get_logger()

# 替换原有的字符串拼接
# logger.info(f"收到请求 | user={username} | text={text[:50]}...")
logger.info("request_received", 
    user_id=user_id,
    request_id=request_id, 
    text_preview=text[:50],
    route_mode="smart_routing",
    processing_time_ms=duration
)
```

### 3.2 请求追踪机制
```python
# observability/tracing/middleware.py
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar('request_id')

class RequestTracingMiddleware:
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # 生成请求ID
            request_id = str(uuid.uuid4())[:8]
            request_id_var.set(request_id)
            
            # 注入响应头
            scope["headers"].append((b"x-request-id", request_id.encode()))
        
        await self.app(scope, receive, send)

def add_correlation_id(logger, method_name, event_dict):
    """为日志添加关联ID"""
    request_id = request_id_var.get(None)
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict
```

### 3.3 Prometheus指标完善
```python
# observability/metrics/collector.py
from prometheus_client import Counter, Histogram, Gauge

class BridgeServerMetrics:
    def __init__(self):
        # 请求指标
        self.request_total = Counter(
            'bridge_requests_total', 
            'Total requests', 
            ['method', 'endpoint', 'status', 'provider']
        )
        
        self.request_duration = Histogram(
            'bridge_request_duration_seconds',
            'Request duration',
            ['endpoint', 'provider'],
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        )
        
        # 业务指标
        self.llm_calls = Counter(
            'bridge_llm_calls_total',
            'LLM API calls',
            ['provider', 'model', 'status']
        )
        
        self.token_usage = Counter(
            'bridge_tokens_total', 
            'Token usage',
            ['provider', 'model', 'type']  # type: prompt/completion
        )
        
        # 系统指标
        self.active_connections = Gauge(
            'bridge_active_connections',
            'Active HTTP connections',
            ['provider']
        )
        
        self.cache_operations = Counter(
            'bridge_cache_operations_total',
            'Cache operations', 
            ['operation', 'result']  # operation: get/set, result: hit/miss
        )

    def record_request(self, method: str, endpoint: str, status: int, 
                      provider: str, duration: float):
        self.request_total.labels(
            method=method, endpoint=endpoint, 
            status=status, provider=provider
        ).inc()
        
        self.request_duration.labels(
            endpoint=endpoint, provider=provider
        ).observe(duration)
```

### 3.4 性能监控仪表板
```python
# observability/dashboard.py
from fastapi import APIRouter
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

monitoring = APIRouter()

@monitoring.get("/metrics")
async def prometheus_metrics():
    """Prometheus指标接口"""
    return Response(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )

@monitoring.get("/health")
async def health_check():
    """健康检查接口"""
    checks = {
        "database": await check_database(),
        "redis": await check_redis(),
        "providers": await check_providers()
    }
    
    status = "healthy" if all(checks.values()) else "unhealthy"
    
    return {
        "status": status,
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat()
    }

@monitoring.get("/stats")
async def system_stats():
    """系统统计信息"""
    return {
        "requests_per_second": await get_current_rps(),
        "average_latency": await get_avg_latency(),
        "error_rate": await get_error_rate(),
        "top_providers": await get_provider_usage(),
        "cache_hit_rate": await get_cache_metrics()
    }
```

---

## 技术选型优化

### 依赖精简方案
```python
# 从22个依赖优化到12个核心依赖
core_dependencies = [
    "fastapi>=0.104.0",      # Web框架
    "uvicorn[standard]",     # ASGI服务器  
    "httpx>=0.25.0",        # HTTP客户端
    "pydantic>=2.0.0",      # 数据验证
    "structlog>=23.0.0",    # 结构化日志
    "redis>=5.0.0",         # 缓存
    "sqlalchemy>=2.0.0",    # 数据库ORM
    "prometheus-client",     # 监控指标
    "tenacity>=8.0.0",      # 重试机制
    "cachetools>=5.0.0",    # 内存缓存
    "pyyaml>=6.0",          # 配置解析
    "pytest>=7.0.0"         # 测试框架
]

# 移除的冗余依赖
removed_dependencies = [
    "python-jose",    # 与PyJWT功能重叠
    "mysql-connector", # 统一使用SQLAlchemy
    "aiofiles",       # 使用异步I/O替代
    # ... 其他10个依赖
]
```

---

## 实施计划与里程碑

### 第1-2周：架构重构
- [ ] 目录结构调整
- [ ] Provider抽象层实现
- [ ] 服务层解耦
- [ ] 单元测试补齐

### 第3-4周：性能优化  
- [ ] HTTP连接池优化
- [ ] 二级缓存实现
- [ ] 批量写入机制
- [ ] 压力测试验证

### 第5周：可观测性
- [ ] 结构化日志部署
- [ ] Prometheus指标完善
- [ ] 监控仪表板搭建
- [ ] 告警规则配置

---

## 预期收益对比

| 维度 | 现状 | 目标 | 提升倍数 |
|------|------|------|----------|
| **性能** |
| 并发处理 | 10 req/s | 200+ req/s | 20x |
| 响应延迟 | 2-10s | 100-500ms | 10-50x |
| 内存占用 | 200MB | 120MB | 40%↓ |
| **稳定性** |
| 错误率 | ~5% | <1% | 5x改善 |
| 可用性 | 95% | 99.5% | 提升4.5% |
| **运维** |
| 问题定位 | 小时级 | 分钟级 | 10x提效 |
| 部署速度 | 30分钟 | 5分钟 | 6x提速 |
| **开发** |
| 代码可读性 | 低 | 高 | 质的飞跃 |
| 测试覆盖率 | 0% | 80%+ | 从无到有 |

这个完整方案覆盖了架构、性能、可观测性三个核心维度，可以根据你的资源情况分阶段实施。建议先从阶段1开始，为后续优化打好基础。