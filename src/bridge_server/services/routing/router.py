#!/usr/bin/env python3
"""
智能路由服务 - Bridge Server v2.0
基于任务类型和上下文的智能模型选择
"""

import re
import logging
import hashlib
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """任务类型枚举"""
    COMPLEX = "complex"        # 复杂推理
    CODING = "coding"          # 编程任务
    WRITING = "writing"        # 写作任务
    ANALYSIS = "analysis"      # 分析任务
    CREATIVE = "creative"      # 创意任务
    SIMPLE = "simple"         # 简单对话
    GENERAL = "general"       # 通用任务


@dataclass
class RouteResult:
    """路由结果"""
    provider_id: str
    model: str
    task_type: TaskType
    confidence: float
    reason: str
    from_cache: bool = False
    
    @classmethod
    def from_cache(cls, cached_data: Dict) -> 'RouteResult':
        """从缓存数据创建路由结果"""
        return cls(
            provider_id=cached_data["provider_id"],
            model=cached_data["model"],
            task_type=TaskType(cached_data["task_type"]),
            confidence=cached_data["confidence"],
            reason=cached_data["reason"],
            from_cache=True
        )
    
    def to_cache(self) -> Dict:
        """转换为缓存数据"""
        return {
            "provider_id": self.provider_id,
            "model": self.model,
            "task_type": self.task_type.value,
            "confidence": self.confidence,
            "reason": self.reason
        }


class TaskDetector:
    """任务类型检测器"""
    
    def __init__(self):
        # 任务关键词模式
        self.patterns = {
            TaskType.COMPLEX: [
                r"推理|证明|推导|复杂|深入分析|数学|逻辑|算法复杂度",
                r"prove|reasoning|complex|mathematical|logic",
            ],
            TaskType.CODING: [
                r"代码|编程|函数|debug|bug|算法|程序|脚本|API",
                r"code|python|javascript|java|cpp|programming|function|debug|algorithm",
            ],
            TaskType.WRITING: [
                r"写|文章|邮件|报告|文档|文案|润色|改写|翻译",
                r"write|article|email|report|document|translate|rewrite",
            ],
            TaskType.ANALYSIS: [
                r"分析|总结|数据|解释|为什么|如何|对比|评估|原因",
                r"analyze|analysis|summarize|explain|why|how|compare|evaluate",
            ],
            TaskType.CREATIVE: [
                r"创意|故事|头脑风暴|想象|设计|诗歌|小说|创作",
                r"creative|story|brainstorm|imagine|design|poetry|novel|create",
            ],
            TaskType.SIMPLE: [
                r"你好|hi|hello|谢谢|再见|在吗|早上好|晚上好|怎么样",
                r"hello|hi|thanks|bye|good morning|good evening|how are you",
            ]
        }
        
        # 编译正则表达式
        self.compiled_patterns = {}
        for task_type, patterns in self.patterns.items():
            self.compiled_patterns[task_type] = [
                re.compile(pattern, re.IGNORECASE) for pattern in patterns
            ]
    
    def detect(self, message: str, context: Dict = None) -> Tuple[TaskType, float]:
        """
        检测任务类型
        
        Args:
            message: 用户消息
            context: 上下文信息（可选）
            
        Returns:
            (TaskType, confidence_score)
        """
        if not message:
            return TaskType.GENERAL, 0.5
        
        # 提取消息内容
        content = self._extract_content(message)
        if not content:
            return TaskType.GENERAL, 0.5
        
        # 计算各任务类型的匹配分数
        scores = {}
        
        for task_type, patterns in self.compiled_patterns.items():
            score = 0.0
            matches = 0
            
            for pattern in patterns:
                pattern_matches = len(pattern.findall(content))
                if pattern_matches > 0:
                    matches += 1
                    score += pattern_matches * 0.2  # 每个匹配0.2分
            
            # 如果有匹配，基础分数为0.3，每个模式匹配额外加0.1
            if matches > 0:
                scores[task_type] = 0.3 + matches * 0.1 + score
            else:
                scores[task_type] = 0.0
        
        # 上下文加权
        if context:
            self._apply_context_weights(scores, context)
        
        # 文本长度影响
        self._apply_length_weights(scores, content)
        
        # 找到最高分数的任务类型
        if scores:
            best_task = max(scores, key=scores.get)
            confidence = min(scores[best_task], 1.0)
            
            # 如果置信度太低，返回通用任务
            if confidence < 0.3:
                return TaskType.GENERAL, 0.5
            
            return best_task, confidence
        
        return TaskType.GENERAL, 0.5
    
    def _extract_content(self, message) -> str:
        """提取消息内容"""
        if isinstance(message, str):
            return message
        elif isinstance(message, list) and len(message) > 0:
            # 取最后一条消息
            last_msg = message[-1]
            if isinstance(last_msg, dict):
                return last_msg.get("content", "")
        elif isinstance(message, dict):
            return message.get("content", "")
        
        return str(message)
    
    def _apply_context_weights(self, scores: Dict[TaskType, float], context: Dict):
        """应用上下文权重"""
        # 历史任务类型加权
        if "last_task_type" in context:
            last_task = TaskType(context["last_task_type"])
            if last_task in scores:
                scores[last_task] += 0.1  # 连续性加权
        
        # 用户专业领域加权
        user_domain = context.get("user_domain", "")
        if user_domain == "developer":
            scores[TaskType.CODING] += 0.15
        elif user_domain == "writer":
            scores[TaskType.WRITING] += 0.15
        elif user_domain == "analyst":
            scores[TaskType.ANALYSIS] += 0.15
    
    def _apply_length_weights(self, scores: Dict[TaskType, float], content: str):
        """应用文本长度权重"""
        length = len(content)
        
        if length < 20:
            # 短文本更可能是简单对话
            scores[TaskType.SIMPLE] += 0.2
        elif length > 200:
            # 长文本更可能是复杂任务
            scores[TaskType.COMPLEX] += 0.1
            scores[TaskType.ANALYSIS] += 0.1
            scores[TaskType.WRITING] += 0.1


class RouterConfig:
    """路由器配置"""
    
    def __init__(self):
        # 模型偏好策略
        self.model_preferences = {
            TaskType.COMPLEX: ["qwen3-max", "gpt-4", "moonshot-v1-128k"],
            TaskType.CODING: ["qwen3.6-plus", "gpt-4-turbo", "moonshot-v1-32k"],
            TaskType.WRITING: ["qwen3.6-plus", "gpt-3.5-turbo", "moonshot-v1-8k"],
            TaskType.ANALYSIS: ["qwen3-max", "gpt-4", "moonshot-v1-32k"],
            TaskType.CREATIVE: ["qwen3.5-flash", "gpt-3.5-turbo", "moonshot-v1-8k"],
            TaskType.SIMPLE: ["qwen3.5-flash", "gpt-3.5-turbo", "moonshot-v1-8k"],
            TaskType.GENERAL: ["qwen3.6-plus", "gpt-3.5-turbo", "moonshot-v1-8k"]
        }
        
        # Provider优先级（基于性价比和可用性）
        self.provider_priority = ["dashscope", "moonshot", "openai"]
        
        # 缓存配置
        self.cache_enabled = True
        self.cache_ttl = 300  # 5分钟


class SmartRouter:
    """智能路由器"""
    
    def __init__(self, config: RouterConfig, cache=None):
        self.config = config
        self.cache = cache
        self.task_detector = TaskDetector()
        
        logger.info("智能路由器初始化完成")
    
    async def route(self, messages: list, user_context: Dict = None, 
                   provider_manager=None) -> RouteResult:
        """
        智能路由决策
        
        Args:
            messages: 对话消息列表
            user_context: 用户上下文信息
            provider_manager: Provider管理器实例
            
        Returns:
            RouteResult: 路由结果
        """
        # 提取最后一条用户消息
        user_message = self._extract_user_message(messages)
        
        # 生成缓存键
        cache_key = self._generate_cache_key(user_message, user_context)
        
        # 尝试从缓存获取
        if self.cache and self.config.cache_enabled:
            cached_result = await self._get_from_cache(cache_key)
            if cached_result:
                logger.info(f"路由缓存命中: {cached_result.model} ({cached_result.task_type.value})")
                return cached_result
        
        # 任务类型检测
        task_type, confidence = self.task_detector.detect(user_message, user_context)
        
        # 模型选择
        selected_model, selected_provider = self._select_model(
            task_type, confidence, provider_manager, user_context
        )
        
        # 创建路由结果
        result = RouteResult(
            provider_id=selected_provider,
            model=selected_model,
            task_type=task_type,
            confidence=confidence,
            reason=f"任务类型: {task_type.value} (置信度: {confidence:.2f})"
        )
        
        # 缓存结果
        if self.cache and self.config.cache_enabled:
            await self._cache_result(cache_key, result)
        
        logger.info(f"路由决策: {selected_provider}/{selected_model} | {result.reason}")
        
        return result
    
    def _extract_user_message(self, messages: list) -> str:
        """提取用户消息"""
        if not messages:
            return ""
        
        # 从后往前找最后一条用户消息
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                return msg.get("content", "")
        
        return ""
    
    def _select_model(self, task_type: TaskType, confidence: float, 
                     provider_manager=None, user_context: Dict = None) -> Tuple[str, str]:
        """选择最适合的模型和Provider"""
        
        # 获取任务类型的首选模型列表
        preferred_models = self.config.model_preferences.get(task_type, [])
        
        if not provider_manager:
            # 没有Provider管理器，返回默认选择
            return preferred_models[0] if preferred_models else "qwen3.5-flash", "dashscope"
        
        # 获取可用模型
        available_models = provider_manager.get_provider_models()
        
        # 按优先级选择
        for provider_id in self.config.provider_priority:
            if provider_id in available_models:
                provider_models = available_models[provider_id]
                
                # 在首选模型中找到第一个可用的
                for preferred_model in preferred_models:
                    if preferred_model in provider_models:
                        return preferred_model, provider_id
                
                # 如果没有首选模型，选择该Provider的第一个模型
                if provider_models:
                    return provider_models[0], provider_id
        
        # 兜底：返回任何可用的模型
        for provider_id, models in available_models.items():
            if models:
                return models[0], provider_id
        
        # 最后的兜底
        return "qwen3.5-flash", "dashscope"
    
    def _generate_cache_key(self, message: str, context: Dict = None) -> str:
        """生成缓存键"""
        # 对消息内容进行哈希，避免缓存键过长（SHA-256，仅用于缓存键，非安全用途）
        message_hash = hashlib.sha256(message.encode(), usedforsecurity=False).hexdigest()[:16]

        # 添加上下文信息
        context_str = ""
        if context:
            context_items = []
            for key in sorted(context.keys()):
                if key in ["user_domain", "last_task_type"]:  # 只包含影响路由的字段
                    context_items.append(f"{key}:{context[key]}")
            context_str = "_".join(context_items)

        cache_key = f"route:{message_hash}"
        if context_str:
            cache_key += f":{hashlib.sha256(context_str.encode(), usedforsecurity=False).hexdigest()[:8]}"
        
        return cache_key
    
    async def _get_from_cache(self, cache_key: str) -> Optional[RouteResult]:
        """从缓存获取路由结果"""
        try:
            cached_data = await self.cache.get(cache_key)
            if cached_data:
                return RouteResult.from_cache(cached_data)
        except Exception as e:
            logger.warning(f"缓存读取失败: {str(e)}")
        
        return None
    
    async def _cache_result(self, cache_key: str, result: RouteResult):
        """缓存路由结果"""
        try:
            await self.cache.set(cache_key, result.to_cache(), ttl=self.config.cache_ttl)
        except Exception as e:
            logger.warning(f"缓存写入失败: {str(e)}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取路由统计信息"""
        return {
            "task_types": [t.value for t in TaskType],
            "model_preferences": {
                t.value: models for t, models in self.config.model_preferences.items()
            },
            "provider_priority": self.config.provider_priority,
            "cache_enabled": self.config.cache_enabled,
            "cache_ttl": self.config.cache_ttl
        }