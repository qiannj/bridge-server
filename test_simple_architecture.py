#!/usr/bin/env python3
"""
简化版本测试 - 验证核心架构逻辑
"""

import asyncio
import logging
import sys
from pathlib import Path

# 直接在本文件中定义简化版的类，避免import问题

import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass
from enum import Enum

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
    """AI平台Provider抽象基类 - 简化版"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.provider_id = config.get("id", self.__class__.__name__)
        self.models = self._load_models()
        self.metrics = ProviderMetrics()
        
        logger.info(f"初始化 Provider: {self.provider_id}, 支持 {len(self.models)} 个模型")
    
    @abstractmethod
    def _load_models(self) -> Dict[str, ModelInfo]:
        """加载模型列表（子类实现）"""
        pass
    
    async def chat_completion(self, messages: list, model: str = None, **kwargs) -> Dict[str, Any]:
        """统一的聊天完成接口 - 简化版（模拟）"""
        start_time = time.perf_counter()
        
        try:
            # 模型验证
            if model and model not in self.models:
                raise ValueError(f"不支持的模型: {model}")
            
            # 模拟请求延迟
            await asyncio.sleep(0.1)
            
            # 模拟响应
            result = {
                "id": f"sim-{int(time.time())}",
                "model": model or list(self.models.keys())[0],
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": f"[模拟响应] 来自 {self.provider_id}"
                    },
                    "index": 0
                }],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30
                },
                "provider": self.provider_id
            }
            
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
    
    async def health_check(self) -> ProviderStatus:
        """健康检查 - 简化版"""
        try:
            # 简化的健康检查
            await asyncio.sleep(0.05)  # 模拟检查延迟
            
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


# 简化版DashScope Provider
class SimpleDashScopeProvider(BaseProvider):
    """简化版DashScope Provider"""
    
    def _load_models(self):
        return {
            "qwen3-max": ModelInfo(
                id="qwen3-max",
                name="Qwen3 Max",
                max_tokens=8192,
                input_cost_per_1k=2.5,
                output_cost_per_1k=10.0,
                supports_streaming=True,
                context_window=256000
            ),
            "qwen3.5-flash": ModelInfo(
                id="qwen3.5-flash", 
                name="Qwen3.5 Flash",
                max_tokens=8192,
                input_cost_per_1k=0.5,
                output_cost_per_1k=1.5,
                supports_streaming=True,
                context_window=256000
            ),
        }


# 简化版OpenAI Provider
class SimpleOpenAIProvider(BaseProvider):
    """简化版OpenAI Provider"""
    
    def _load_models(self):
        return {
            "gpt-4": ModelInfo(
                id="gpt-4",
                name="GPT-4", 
                max_tokens=4096,
                input_cost_per_1k=30.0,
                output_cost_per_1k=60.0,
                supports_streaming=True,
                context_window=8192
            ),
            "gpt-3.5-turbo": ModelInfo(
                id="gpt-3.5-turbo",
                name="GPT-3.5 Turbo",
                max_tokens=4096,
                input_cost_per_1k=0.5,
                output_cost_per_1k=1.5,
                supports_streaming=True,
                context_window=16385
            )
        }


async def test_simple_architecture():
    """测试简化版架构"""
    
    print("=" * 60)
    print("Bridge Server v2.0 - 简化架构测试")
    print("=" * 60)
    
    # 1. 注册Provider
    print("\n1. 注册Provider类...")
    ProviderFactory.register("dashscope", SimpleDashScopeProvider)
    ProviderFactory.register("openai", SimpleOpenAIProvider)
    
    supported_types = ProviderFactory.get_supported_types()
    print(f"   支持的Provider类型: {supported_types}")
    
    # 2. 创建Provider实例
    print("\n2. 创建Provider实例...")
    providers = {}
    
    # DashScope
    dashscope_config = {"id": "dashscope"}
    dashscope_provider = ProviderFactory.create("dashscope", dashscope_config)
    providers["dashscope"] = dashscope_provider
    print(f"   ✓ 创建 {dashscope_provider.provider_id}")
    print(f"     支持模型: {dashscope_provider.get_supported_models()}")
    
    # OpenAI
    openai_config = {"id": "openai"}
    openai_provider = ProviderFactory.create("openai", openai_config)
    providers["openai"] = openai_provider
    print(f"   ✓ 创建 {openai_provider.provider_id}")
    print(f"     支持模型: {openai_provider.get_supported_models()}")
    
    # 3. 健康检查
    print("\n3. 健康检查...")
    for provider_id, provider in providers.items():
        health_status = await provider.health_check()
        print(f"   {provider_id}: {health_status.value}")
    
    # 4. 测试请求
    print("\n4. 测试模拟请求...")
    test_messages = [
        {"role": "user", "content": "你好，今天天气怎么样？"}
    ]
    
    for provider_id, provider in providers.items():
        print(f"\n   测试 {provider_id}:")
        
        # 使用默认模型
        models = provider.get_supported_models()
        test_model = models[0] if models else None
        
        try:
            response = await provider.chat_completion(
                messages=test_messages,
                model=test_model,
                max_tokens=100
            )
            
            print(f"     ✓ 请求成功")
            print(f"       模型: {response['model']}")
            print(f"       响应: {response['choices'][0]['message']['content']}")
            
        except Exception as e:
            print(f"     ✗ 请求失败: {str(e)}")
    
    # 5. 成本对比
    print("\n5. 模型成本对比...")
    print("   模型名称           | Provider  | 输入成本/1K | 输出成本/1K | 上下文长度")
    print("   " + "-" * 70)
    
    for provider_id, provider in providers.items():
        for model_id in provider.get_supported_models():
            model_info = provider.get_model_info(model_id)
            print(f"   {model_info.name:<18} | {provider_id:<8} | ¥{model_info.input_cost_per_1k:>7.2f} | ¥{model_info.output_cost_per_1k:>8.2f} | {model_info.context_window:>8}")
    
    # 6. 性能指标
    print("\n6. 性能指标...")
    for provider_id, provider in providers.items():
        metrics = provider.get_metrics()
        print(f"   {provider_id}:")
        print(f"     总请求数: {metrics['total_requests']}")
        print(f"     成功率: {metrics['success_rate']:.3f}")
        print(f"     平均延迟: {metrics['average_latency']:.2f}ms")
    
    print("\n✓ 简化架构测试完成！")
    print("=" * 60)
    
    return providers


async def main():
    """主函数"""
    try:
        providers = await test_simple_architecture()
        
        # 额外测试：路由逻辑演示
        print("\n" + "=" * 60)
        print("智能路由演示 (简化版)")
        print("=" * 60)
        
        # 简单的成本优化路由
        def cost_optimized_route(task_content: str):
            """根据任务内容选择最优Provider"""
            
            # 简单任务 -> 使用最便宜的模型
            simple_keywords = ["你好", "天气", "简单", "问候"]
            if any(keyword in task_content for keyword in simple_keywords):
                return "dashscope", "qwen3.5-flash"  # 成本：0.5+1.5=2.0
            
            # 复杂任务 -> 使用性能最好的模型
            complex_keywords = ["分析", "编程", "复杂", "深入"]
            if any(keyword in task_content for keyword in complex_keywords):
                return "dashscope", "qwen3-max"  # 成本：2.5+10.0=12.5 但性能最好
            
            # 默认平衡选择
            return "openai", "gpt-3.5-turbo"  # 成本：0.5+1.5=2.0
        
        # 测试路由案例
        test_cases = [
            "你好，今天天气怎么样？",
            "帮我分析一下这个复杂的技术架构",
            "写一个Python快速排序算法",
            "普通的聊天对话"
        ]
        
        print("\n路由决策演示:")
        for i, content in enumerate(test_cases, 1):
            provider_id, model = cost_optimized_route(content)
            provider = providers[provider_id]
            model_info = provider.get_model_info(model)
            
            print(f"\n{i}. 任务: {content}")
            print(f"   → 路由到: {provider_id}/{model}")
            print(f"   → 成本: 输入¥{model_info.input_cost_per_1k:.2f}/1K + 输出¥{model_info.output_cost_per_1k:.2f}/1K")
            print(f"   → 上下文: {model_info.context_window:,} tokens")
        
        print("\n✓ 路由演示完成！")
        
    except KeyboardInterrupt:
        print("\n\n中断测试...")
    except Exception as e:
        logger.error(f"测试异常: {str(e)}", exc_info=True)


if __name__ == "__main__":
    # 运行测试
    asyncio.run(main())