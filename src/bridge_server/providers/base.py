#!/usr/bin/env python3
"""
Provider 抽象基类 - Bridge Server v2.0
统一各AI平台的接口规范和性能优化
"""

import asyncio
import httpx
import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ProviderStatus(Enum):
    """Provider状态枚举"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"  
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ModelInfo:
    """模型信息"""
    id: str
    name: str
    max_tokens: int
    input_cost_per_1k: float
    output_cost_per_1k: float
    supports_streaming: bool = True
    context_window: int = 4096


@dataclass
class ProviderMetrics:
    """Provider性能指标"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency: float = 0.0
    last_request_time: float = 0.0
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests
    
    @property
    def average_latency(self) -> float:
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency / self.successful_requests


class BaseProvider(ABC):
    """AI平台Provider抽象基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.provider_id = config.get("id", self.__class__.__name__)
        self.models = self._load_models()
        self.client = self._create_http_client()
        self.metrics = ProviderMetrics()
        
        logger.info(f"初始化 Provider: {self.provider_id}, 支持 {len(self.models)} 个模型")
    
    def _create_http_client(self) -> httpx.AsyncClient:
        """创建优化的HTTP客户端"""
        self._uses_shared_http_client = True
        from ..utils.connection_pools import get_provider_http_client

        return get_provider_http_client(
            self.provider_id,
            base_url=self.config.get("base_url", ""),
            headers=self._get_headers(),
            timeout=self.config.get("timeout", 30.0),
            http2=self.config.get("http2", True),
            max_connections=self.config.get("max_connections", 50),
            max_keepalive_connections=self.config.get("max_keepalive_connections", 20),
            follow_redirects=True,
            event_hooks={"request": [self._inject_observability_headers]},
        )

    async def _inject_observability_headers(self, request: httpx.Request) -> None:
        """Inject request correlation headers into outbound provider calls."""
        from ..observability.tracing import get_trace_headers

        for header, value in get_trace_headers().items():
            request.headers[header] = value
    
    @abstractmethod
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头（子类实现认证逻辑）"""
        pass
    
    @abstractmethod
    def _load_models(self) -> Dict[str, ModelInfo]:
        """加载模型列表（子类实现）"""
        pass
    
    @abstractmethod
    async def _make_request(self, messages: list, model: str, **kwargs) -> Dict[str, Any]:
        """发起实际请求（子类实现）"""
        pass
    
    @abstractmethod
    async def _make_stream_request(self, messages: list, model: str, **kwargs) -> AsyncGenerator[str, None]:
        """发起流式请求（子类实现）"""
        pass
    
    async def chat_completion(self, messages: list, model: str = None, **kwargs) -> Dict[str, Any]:
        """统一的聊天完成接口"""
        start_time = time.perf_counter()
        
        try:
            # 模型验证
            if model and model not in self.models:
                raise ValueError(f"不支持的模型: {model}")
            
            # 执行请求
            result = await self._make_request(messages, model, **kwargs)
            
            # 记录成功指标
            latency = (time.perf_counter() - start_time) * 1000
            self._record_success(latency)
            
            logger.info(f"请求成功 | Provider: {self.provider_id} | 模型: {model} | 延迟: {latency:.2f}ms")
            
            return result
            
        except Exception as e:
            # 记录失败指标
            self._record_failure()
            logger.error(f"请求失败 | Provider: {self.provider_id} | 错误: {str(e)}")
            raise
    
    async def chat_completion_stream(self, messages: list, model: str = None, **kwargs) -> AsyncGenerator[str, None]:
        """统一的流式聊天完成接口"""
        start_time = time.perf_counter()
        
        try:
            # 模型验证
            if model and model not in self.models:
                raise ValueError(f"不支持的模型: {model}")
            
            # 检查流式支持
            if model and not self.models[model].supports_streaming:
                raise ValueError(f"模型 {model} 不支持流式输出")
            
            # 执行流式请求
            async for chunk in self._make_stream_request(messages, model, **kwargs):
                yield chunk
            
            # 记录成功指标
            latency = (time.perf_counter() - start_time) * 1000
            self._record_success(latency)
            
        except Exception as e:
            # 记录失败指标  
            self._record_failure()
            logger.error(f"流式请求失败 | Provider: {self.provider_id} | 错误: {str(e)}")
            raise
    
    async def health_check(self) -> ProviderStatus:
        """健康检查"""
        try:
            # 发起轻量级测试请求
            test_messages = [{"role": "user", "content": "hello"}]
            await asyncio.wait_for(
                self._make_request(test_messages, list(self.models.keys())[0]),
                timeout=10.0
            )
            
            # 根据成功率判断状态
            if self.metrics.success_rate >= 0.95:
                return ProviderStatus.HEALTHY
            elif self.metrics.success_rate >= 0.8:
                return ProviderStatus.DEGRADED
            else:
                return ProviderStatus.UNHEALTHY
                
        except Exception as e:
            logger.warning(f"健康检查失败 | Provider: {self.provider_id} | 错误: {str(e)}")
            return ProviderStatus.UNHEALTHY
    
    def get_supported_models(self) -> list:
        """获取支持的模型列表"""
        return list(self.models.keys())
    
    def get_model_info(self, model: str) -> Optional[ModelInfo]:
        """获取模型信息"""
        return self.models.get(model)
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取性能指标"""
        return {
            "provider_id": self.provider_id,
            "total_requests": self.metrics.total_requests,
            "success_rate": round(self.metrics.success_rate, 3),
            "average_latency": round(self.metrics.average_latency, 2),
            "last_request_time": self.metrics.last_request_time
        }
    
    def _record_success(self, latency_ms: float):
        """记录成功请求指标"""
        self.metrics.total_requests += 1
        self.metrics.successful_requests += 1
        self.metrics.total_latency += latency_ms
        self.metrics.last_request_time = time.time()
    
    def _record_failure(self):
        """记录失败请求指标"""
        self.metrics.total_requests += 1
        self.metrics.failed_requests += 1
        self.metrics.last_request_time = time.time()
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.client and not getattr(self, "_uses_shared_http_client", False):
            await self.client.aclose()


class ProviderFactory:
    """Provider工厂类"""
    
    _providers = {}
    
    @classmethod
    def register(cls, provider_type: str, provider_class: type):
        """注册Provider类"""
        cls._providers[provider_type] = provider_class
        logger.info(f"注册 Provider: {provider_type}")
    
    @classmethod
    def create(cls, provider_type: str, config: Dict[str, Any]) -> BaseProvider:
        """创建Provider实例"""
        if provider_type not in cls._providers:
            raise ValueError(f"未知的 Provider 类型: {provider_type}")
        
        provider_class = cls._providers[provider_type]
        return provider_class(config)
    
    @classmethod
    def get_supported_types(cls) -> list:
        """获取支持的Provider类型"""
        return list(cls._providers.keys())
