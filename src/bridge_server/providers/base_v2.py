#!/usr/bin/env python3
"""
Provider系统连接池优化版本 - v2.1
集成HTTP连接池，提升并发性能
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, List, Optional, AsyncGenerator
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass
import aiohttp

from ..utils.connection_pools import get_http_session

logger = logging.getLogger(__name__)


class ProviderStatus(Enum):
    """Provider状态"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy" 
    DISABLED = "disabled"
    UNKNOWN = "unknown"


@dataclass
class ModelInfo:
    """模型信息"""
    id: str
    name: str
    input_cost_per_1k: float  # 输入成本/1K tokens
    output_cost_per_1k: float # 输出成本/1K tokens
    context_window: int
    supports_streaming: bool = True
    supports_function_calling: bool = False


@dataclass
class ProviderMetrics:
    """Provider性能指标"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    last_request_time: Optional[float] = None
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests
    
    @property
    def average_latency_ms(self) -> float:
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency_ms / self.successful_requests


class BaseProvider(ABC):
    """Provider基类 - 连接池优化版本"""
    
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        self.provider_id = provider_id
        self.config = config
        self.metrics = ProviderMetrics()
        self.status = ProviderStatus.UNKNOWN
        self._last_health_check = 0.0
        self._health_check_interval = 30.0  # 30秒
        
        # 连接池优化：不再创建独立的HTTP会话
        # 使用全局连接池管理器
        logger.info(f"Provider {provider_id} 初始化，使用共享连接池")
    
    @abstractmethod
    def get_available_models(self) -> List[ModelInfo]:
        """获取可用模型列表"""
        pass
    
    async def get_http_session(self) -> aiohttp.ClientSession:
        """获取HTTP会话（来自连接池）"""
        return await get_http_session()
    
    async def health_check(self) -> ProviderStatus:
        """健康检查（带缓存）"""
        current_time = time.time()
        
        # 检查缓存
        if (current_time - self._last_health_check) < self._health_check_interval:
            return self.status
        
        try:
            session = await self.get_http_session()
            
            # 简单的健康检查请求
            async with session.get(
                f"{self.config['base_url']}/models",
                headers={"Authorization": f"Bearer {self.config['api_key']}"},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    self.status = ProviderStatus.HEALTHY
                else:
                    self.status = ProviderStatus.UNHEALTHY
                    logger.warning(f"Provider {self.provider_id} 健康检查失败: HTTP {response.status}")
        
        except Exception as e:
            self.status = ProviderStatus.UNHEALTHY
            logger.error(f"Provider {self.provider_id} 健康检查异常: {str(e)}")
        
        self._last_health_check = current_time
        return self.status
    
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]], 
        model: str,
        max_tokens: int = 4000,
        temperature: float = 0.7,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """聊天完成（连接池优化）"""
        
        start_time = time.perf_counter()
        
        try:
            self.metrics.total_requests += 1
            
            # 使用连接池中的HTTP会话
            session = await self.get_http_session()
            
            # 准备请求数据
            request_data = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": stream,
                **kwargs
            }
            
            # 发送请求
            async with session.post(
                f"{self.config['base_url']}/chat/completions",
                json=request_data,
                headers={
                    "Authorization": f"Bearer {self.config['api_key']}",
                    "Content-Type": "application/json"
                }
            ) as response:
                
                if response.status == 200:
                    result = await response.json()
                    
                    # 记录性能指标
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    self.metrics.successful_requests += 1
                    self.metrics.total_latency_ms += duration_ms
                    self.metrics.last_request_time = time.time()
                    
                    # 计算成本
                    if "usage" in result:
                        cost = self._calculate_cost(result["usage"], model)
                        self.metrics.total_cost_usd += cost
                    
                    logger.debug(f"Provider {self.provider_id} 请求成功: {duration_ms:.2f}ms")
                    return result
                
                else:
                    error_text = await response.text()
                    self.metrics.failed_requests += 1
                    logger.error(f"Provider {self.provider_id} 请求失败: HTTP {response.status}, {error_text}")
                    
                    raise Exception(f"HTTP {response.status}: {error_text}")
        
        except Exception as e:
            self.metrics.failed_requests += 1
            logger.error(f"Provider {self.provider_id} 请求异常: {str(e)}")
            raise
    
    async def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        max_tokens: int = 4000,
        temperature: float = 0.7,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式聊天完成（连接池优化）"""
        
        start_time = time.perf_counter()
        
        try:
            self.metrics.total_requests += 1
            
            # 使用连接池中的HTTP会话
            session = await self.get_http_session()
            
            request_data = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True,
                **kwargs
            }
            
            async with session.post(
                f"{self.config['base_url']}/chat/completions",
                json=request_data,
                headers={
                    "Authorization": f"Bearer {self.config['api_key']}",
                    "Content-Type": "application/json"
                }
            ) as response:
                
                if response.status != 200:
                    error_text = await response.text()
                    self.metrics.failed_requests += 1
                    raise Exception(f"HTTP {response.status}: {error_text}")
                
                # 处理流式响应
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    
                    if line.startswith('data: '):
                        data = line[6:]  # 去掉 'data: ' 前缀
                        
                        if data == '[DONE]':
                            break
                        
                        try:
                            chunk = json.loads(data)
                            yield chunk
                        except json.JSONDecodeError:
                            continue
                
                # 记录成功的流式请求
                duration_ms = (time.perf_counter() - start_time) * 1000
                self.metrics.successful_requests += 1
                self.metrics.total_latency_ms += duration_ms
                self.metrics.last_request_time = time.time()
                
                logger.debug(f"Provider {self.provider_id} 流式请求完成: {duration_ms:.2f}ms")
        
        except Exception as e:
            self.metrics.failed_requests += 1
            logger.error(f"Provider {self.provider_id} 流式请求异常: {str(e)}")
            raise
    
    def _calculate_cost(self, usage: Dict[str, Any], model: str) -> float:
        """计算请求成本"""
        model_info = self._get_model_info(model)
        if not model_info:
            return 0.0
        
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        
        input_cost = (input_tokens / 1000) * model_info.input_cost_per_1k
        output_cost = (output_tokens / 1000) * model_info.output_cost_per_1k
        
        return input_cost + output_cost
    
    def _get_model_info(self, model: str) -> Optional[ModelInfo]:
        """获取模型信息"""
        models = self.get_available_models()
        for model_info in models:
            if model_info.id == model:
                return model_info
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """获取Provider统计"""
        return {
            "provider_id": self.provider_id,
            "status": self.status.value,
            "metrics": {
                "total_requests": self.metrics.total_requests,
                "successful_requests": self.metrics.successful_requests,
                "failed_requests": self.metrics.failed_requests,
                "success_rate": round(self.metrics.success_rate, 4),
                "average_latency_ms": round(self.metrics.average_latency_ms, 2),
                "total_cost_usd": round(self.metrics.total_cost_usd, 4),
                "last_request_time": self.metrics.last_request_time
            }
        }


class DashScopeProviderV2(BaseProvider):
    """DashScope Provider - 连接池优化版本"""
    
    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                id="qwen-turbo",
                name="Qwen Turbo",
                input_cost_per_1k=0.0015,  # $0.0015
                output_cost_per_1k=0.0015,
                context_window=8192,
                supports_streaming=True
            ),
            ModelInfo(
                id="qwen-plus",
                name="Qwen Plus", 
                input_cost_per_1k=0.004,   # $0.004
                output_cost_per_1k=0.004,
                context_window=32768,
                supports_streaming=True
            ),
            ModelInfo(
                id="qwen-max",
                name="Qwen Max",
                input_cost_per_1k=0.02,    # $0.02
                output_cost_per_1k=0.02,
                context_window=8192,
                supports_streaming=True
            )
        ]


class OpenAIProviderV2(BaseProvider):
    """OpenAI Provider - 连接池优化版本"""
    
    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                id="gpt-3.5-turbo",
                name="GPT-3.5 Turbo",
                input_cost_per_1k=0.0015,  # $0.0015
                output_cost_per_1k=0.002,  # $0.002
                context_window=4096,
                supports_streaming=True,
                supports_function_calling=True
            ),
            ModelInfo(
                id="gpt-4",
                name="GPT-4",
                input_cost_per_1k=0.03,    # $0.03
                output_cost_per_1k=0.06,   # $0.06
                context_window=8192,
                supports_streaming=True,
                supports_function_calling=True
            )
        ]


class MoonshotProviderV2(BaseProvider):
    """Moonshot Provider - 连接池优化版本"""
    
    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                id="moonshot-v1-8k",
                name="Moonshot v1 8K",
                input_cost_per_1k=0.012,   # $0.012
                output_cost_per_1k=0.012,
                context_window=8192,
                supports_streaming=True
            ),
            ModelInfo(
                id="moonshot-v1-32k", 
                name="Moonshot v1 32K",
                input_cost_per_1k=0.024,   # $0.024
                output_cost_per_1k=0.024,
                context_window=32768,
                supports_streaming=True
            ),
            ModelInfo(
                id="moonshot-v1-128k",
                name="Moonshot v1 128K",
                input_cost_per_1k=0.06,    # $0.06
                output_cost_per_1k=0.06,
                context_window=131072,
                supports_streaming=True
            )
        ]


# Provider工厂（连接池优化版本）
PROVIDER_CLASSES_V2 = {
    "dashscope": DashScopeProviderV2,
    "openai": OpenAIProviderV2,
    "moonshot": MoonshotProviderV2
}


async def create_provider_v2(provider_type: str, provider_id: str, config: Dict[str, Any]) -> Optional[BaseProvider]:
    """创建Provider实例（v2版本，使用连接池）"""
    
    provider_class = PROVIDER_CLASSES_V2.get(provider_type)
    if not provider_class:
        logger.error(f"未知的Provider类型: {provider_type}")
        return None
    
    try:
        provider = provider_class(provider_id, config)
        
        # 执行初始健康检查
        await provider.health_check()
        
        logger.info(f"Provider v2 {provider_id} 创建成功，状态: {provider.status.value}")
        return provider
        
    except Exception as e:
        logger.error(f"创建Provider v2 {provider_id} 失败: {str(e)}")
        return None
