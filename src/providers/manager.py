#!/usr/bin/env python3
"""
Provider Manager - 统一管理所有AI Provider
支持负载均衡、健康检查、故障转移
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass

from .base import BaseProvider, ProviderStatus, ProviderFactory

logger = logging.getLogger(__name__)


class RoutingStrategy(Enum):
    """路由策略"""
    ROUND_ROBIN = "round_robin"      # 轮询
    LOWEST_LATENCY = "lowest_latency"  # 最低延迟
    COST_OPTIMIZED = "cost_optimized"  # 成本优化
    MANUAL = "manual"                # 手动指定


@dataclass
class ProviderConfig:
    """Provider配置"""
    provider_type: str
    config: Dict[str, Any]
    weight: int = 1
    priority: int = 1  # 1=高优先级, 2=中优先级, 3=低优先级
    enabled: bool = True


class ProviderManager:
    """Provider统一管理器"""
    
    def __init__(self, routing_strategy: RoutingStrategy = RoutingStrategy.ROUND_ROBIN):
        self.providers: Dict[str, BaseProvider] = {}
        self.provider_configs: Dict[str, ProviderConfig] = {}
        self.routing_strategy = routing_strategy
        self.round_robin_index = 0
        self.health_check_interval = 60  # 健康检查间隔（秒）
        self.last_health_check = 0
        
        # 导入所有Provider实现
        self._import_providers()
    
    def _import_providers(self):
        """导入所有Provider实现"""
        try:
            from . import dashscope, openai, moonshot
            logger.info("成功导入所有 Provider 实现")
        except ImportError as e:
            logger.warning(f"导入 Provider 实现时出错: {e}")
    
    async def add_provider(self, provider_config: ProviderConfig) -> bool:
        """添加Provider"""
        try:
            provider_id = provider_config.config.get("id", provider_config.provider_type)
            
            # 创建Provider实例
            provider = ProviderFactory.create(provider_config.provider_type, provider_config.config)
            
            # 健康检查
            health_status = await provider.health_check()
            if health_status == ProviderStatus.UNHEALTHY:
                logger.warning(f"Provider {provider_id} 健康检查失败，跳过添加")
                return False
            
            # 添加到管理器
            self.providers[provider_id] = provider
            self.provider_configs[provider_id] = provider_config
            
            logger.info(f"成功添加 Provider: {provider_id}, 状态: {health_status.value}")
            return True
            
        except Exception as e:
            logger.error(f"添加 Provider 失败: {provider_config.provider_type}, 错误: {str(e)}")
            return False
    
    async def remove_provider(self, provider_id: str) -> bool:
        """移除Provider"""
        try:
            if provider_id in self.providers:
                provider = self.providers[provider_id]
                await provider.__aexit__(None, None, None)  # 清理资源
                
                del self.providers[provider_id]
                del self.provider_configs[provider_id]
                
                logger.info(f"成功移除 Provider: {provider_id}")
                return True
            else:
                logger.warning(f"Provider 不存在: {provider_id}")
                return False
                
        except Exception as e:
            logger.error(f"移除 Provider 失败: {provider_id}, 错误: {str(e)}")
            return False
    
    def get_available_providers(self) -> List[str]:
        """获取可用的Provider列表"""
        available = []
        for provider_id, config in self.provider_configs.items():
            if config.enabled and provider_id in self.providers:
                available.append(provider_id)
        return available
    
    def get_provider_models(self, provider_id: str = None) -> Dict[str, List[str]]:
        """获取Provider支持的模型列表"""
        if provider_id:
            if provider_id in self.providers:
                return {provider_id: self.providers[provider_id].get_supported_models()}
            else:
                return {}
        else:
            # 返回所有Provider的模型
            all_models = {}
            for pid, provider in self.providers.items():
                all_models[pid] = provider.get_supported_models()
            return all_models
    
    async def select_provider(self, model: str = None, **kwargs) -> Optional[str]:
        """根据路由策略选择Provider"""
        available_providers = self.get_available_providers()
        
        if not available_providers:
            logger.error("没有可用的 Provider")
            return None
        
        # 如果指定了模型，筛选支持该模型的Provider
        if model:
            supporting_providers = []
            for provider_id in available_providers:
                if model in self.providers[provider_id].get_supported_models():
                    supporting_providers.append(provider_id)
            
            if not supporting_providers:
                logger.warning(f"没有Provider支持模型: {model}")
                return None
            
            available_providers = supporting_providers
        
        # 根据策略选择
        if self.routing_strategy == RoutingStrategy.ROUND_ROBIN:
            return self._round_robin_select(available_providers)
        
        elif self.routing_strategy == RoutingStrategy.LOWEST_LATENCY:
            return await self._lowest_latency_select(available_providers)
        
        elif self.routing_strategy == RoutingStrategy.COST_OPTIMIZED:
            return self._cost_optimized_select(available_providers, model)
        
        else:  # 默认返回第一个
            return available_providers[0]
    
    def _round_robin_select(self, providers: List[str]) -> str:
        """轮询选择"""
        if not providers:
            return None
        
        selected = providers[self.round_robin_index % len(providers)]
        self.round_robin_index += 1
        return selected
    
    async def _lowest_latency_select(self, providers: List[str]) -> str:
        """最低延迟选择"""
        best_provider = None
        best_latency = float('inf')
        
        for provider_id in providers:
            provider = self.providers[provider_id]
            metrics = provider.get_metrics()
            avg_latency = metrics.get("average_latency", float('inf'))
            
            if avg_latency < best_latency:
                best_latency = avg_latency
                best_provider = provider_id
        
        return best_provider or providers[0]
    
    def _cost_optimized_select(self, providers: List[str], model: str = None) -> str:
        """成本优化选择"""
        if not model:
            return providers[0]
        
        best_provider = None
        best_cost = float('inf')
        
        for provider_id in providers:
            provider = self.providers[provider_id]
            model_info = provider.get_model_info(model)
            
            if model_info:
                # 简单成本估算：输入+输出费用的平均值
                avg_cost = (model_info.input_cost_per_1k + model_info.output_cost_per_1k) / 2
                
                if avg_cost < best_cost:
                    best_cost = avg_cost
                    best_provider = provider_id
        
        return best_provider or providers[0]
    
    async def chat_completion(self, messages: list, model: str = None, 
                            provider_id: str = None, **kwargs) -> Dict[str, Any]:
        """统一聊天完成接口"""
        # 如果没有指定provider，自动选择
        if not provider_id:
            provider_id = await self.select_provider(model, **kwargs)
        
        if not provider_id or provider_id not in self.providers:
            raise ValueError(f"无法找到合适的 Provider")
        
        provider = self.providers[provider_id]
        
        try:
            result = await provider.chat_completion(messages, model, **kwargs)
            return result
            
        except Exception as e:
            # 尝试故障转移
            logger.warning(f"Provider {provider_id} 请求失败: {str(e)}, 尝试故障转移")
            
            # 获取备用Provider
            backup_providers = [pid for pid in self.get_available_providers() 
                              if pid != provider_id]
            
            if backup_providers:
                backup_id = await self.select_provider(model, **kwargs)
                if backup_id and backup_id != provider_id:
                    logger.info(f"故障转移到 Provider: {backup_id}")
                    backup_provider = self.providers[backup_id]
                    return await backup_provider.chat_completion(messages, model, **kwargs)
            
            # 故障转移失败，抛出原始异常
            raise e
    
    async def chat_completion_stream(self, messages: list, model: str = None,
                                   provider_id: str = None, **kwargs):
        """统一流式聊天完成接口"""
        # 如果没有指定provider，自动选择
        if not provider_id:
            provider_id = await self.select_provider(model, **kwargs)
        
        if not provider_id or provider_id not in self.providers:
            raise ValueError(f"无法找到合适的 Provider")
        
        provider = self.providers[provider_id]
        
        async for chunk in provider.chat_completion_stream(messages, model, **kwargs):
            yield chunk
    
    async def health_check_all(self) -> Dict[str, ProviderStatus]:
        """检查所有Provider健康状态"""
        current_time = time.time()
        
        # 跳过频繁的健康检查
        if current_time - self.last_health_check < self.health_check_interval:
            return {}
        
        results = {}
        tasks = []
        
        for provider_id, provider in self.providers.items():
            tasks.append(self._check_single_provider(provider_id, provider))
        
        if tasks:
            health_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(health_results):
                provider_id = list(self.providers.keys())[i]
                if isinstance(result, Exception):
                    results[provider_id] = ProviderStatus.UNHEALTHY
                else:
                    results[provider_id] = result
        
        self.last_health_check = current_time
        return results
    
    async def _check_single_provider(self, provider_id: str, provider: BaseProvider) -> ProviderStatus:
        """检查单个Provider健康状态"""
        try:
            status = await provider.health_check()
            
            # 如果Provider不健康，禁用它
            if status == ProviderStatus.UNHEALTHY:
                self.provider_configs[provider_id].enabled = False
                logger.warning(f"Provider {provider_id} 不健康，已禁用")
            else:
                self.provider_configs[provider_id].enabled = True
            
            return status
            
        except Exception as e:
            logger.error(f"健康检查失败: {provider_id}, 错误: {str(e)}")
            self.provider_configs[provider_id].enabled = False
            return ProviderStatus.UNHEALTHY
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {
            "total_providers": len(self.providers),
            "available_providers": len(self.get_available_providers()),
            "routing_strategy": self.routing_strategy.value,
            "providers": {}
        }
        
        for provider_id, provider in self.providers.items():
            config = self.provider_configs[provider_id]
            stats["providers"][provider_id] = {
                "enabled": config.enabled,
                "weight": config.weight,
                "priority": config.priority,
                "models": provider.get_supported_models(),
                "metrics": provider.get_metrics()
            }
        
        return stats
    
    async def cleanup(self):
        """清理所有Provider资源"""
        for provider in self.providers.values():
            try:
                await provider.__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"清理 Provider 资源失败: {str(e)}")
        
        self.providers.clear()
        self.provider_configs.clear()
        logger.info("Provider Manager 清理完成")