#!/usr/bin/env python3
"""
智能路由服务 - Bridge Server v2.0
基于任务类型和上下文的智能模型选择 (简化版本，无外部依赖)
"""

import re
import json
import logging
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass
import time

logger = logging.getLogger(__name__)


# 简化的TTL缓存实现
class SimpleTTLCache:
    def __init__(self, maxsize: int = 1000, ttl: int = 300):
        self.maxsize = maxsize
        self.ttl = ttl
        self.cache = {}
        self.timestamps = {}
    
    def __contains__(self, key):
        if key not in self.cache:
            return False
        
        # 检查是否过期
        if time.time() - self.timestamps[key] > self.ttl:
            del self.cache[key]
            del self.timestamps[key]
            return False
        
        return True
    
    def __getitem__(self, key):
        if key in self:
            return self.cache[key]
        raise KeyError(key)
    
    def __setitem__(self, key, value):
        # 清理过期项
        current_time = time.time()
        expired_keys = [k for k, t in self.timestamps.items() if current_time - t > self.ttl]
        for k in expired_keys:
            self.cache.pop(k, None)
            self.timestamps.pop(k, None)
        
        # 如果达到最大容量，删除最旧的项
        if len(self.cache) >= self.maxsize:
            oldest_key = min(self.timestamps.keys(), key=lambda k: self.timestamps[k])
            del self.cache[oldest_key]
            del self.timestamps[oldest_key]
        
        self.cache[key] = value
        self.timestamps[key] = current_time
    
    def __len__(self):
        # 清理过期项并返回当前大小
        current_time = time.time()
        expired_keys = [k for k, t in self.timestamps.items() if current_time - t > self.ttl]
        for k in expired_keys:
            self.cache.pop(k, None)
            self.timestamps.pop(k, None)
        return len(self.cache)
    
    def clear(self):
        self.cache.clear()
        self.timestamps.clear()


class TaskType(Enum):
    """任务类型枚举"""
    SIMPLE = "simple"           # 简单对话
    COMPLEX = "complex"         # 复杂分析
    CODING = "coding"           # 编程任务
    CREATIVE = "creative"       # 创意写作
    TRANSLATION = "translation" # 翻译任务
    UNKNOWN = "unknown"         # 未知类型


@dataclass
class RoutingDecision:
    """路由决策结果"""
    selected_model: str
    provider: str
    task_type: TaskType
    confidence: float
    reason: str
    estimated_cost: float
    estimated_tokens: int
    from_cache: bool = False


@dataclass 
class ModelCapability:
    """模型能力定义"""
    model_id: str
    provider: str
    strengths: List[TaskType]
    cost_per_1k: float
    context_window: int
    quality_score: float  # 1-10分


class SmartRouter:
    """智能路由器"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        
        # 路由决策缓存 (5分钟TTL)
        self.decision_cache = SimpleTTLCache(maxsize=1000, ttl=300)
        
        # 任务分类模式
        self.task_patterns = {
            TaskType.CODING: [
                r'(代码|编程|程序|函数|算法|bug|debug|代码优化)',
                r'(python|javascript|java|c\+\+|react|vue|sql)',
                r'(function|class|import|return|if|for|while)',
                r'(API|接口|数据库|框架|library|库)'
            ],
            TaskType.COMPLEX: [
                r'(分析|解释|推理|逻辑|因果|原理|机制)',
                r'(比较|对比|评估|判断|论证|证明)',
                r'(策略|方案|建议|规划|设计|架构)',
                r'(深入|详细|全面|系统|综合|多维度)'
            ],
            TaskType.CREATIVE: [
                r'(写作|创作|故事|小说|诗歌|剧本)',
                r'(创意|想象|虚构|艺术|文学|美学)',
                r'(风格|情感|氛围|意境|表达|修辞)',
                r'(灵感|创新|独特|新颖|有趣|幽默)'
            ],
            TaskType.TRANSLATION: [
                r'(翻译|translate|英文|中文|日文|韩文)',
                r'(中译英|英译中|语言转换|本地化)',
                r'(translation|language|linguistic)'
            ]
        }
        
        # 模型能力配置
        self.model_capabilities = [
            ModelCapability(
                model_id="qwen-turbo",
                provider="dashscope", 
                strengths=[TaskType.SIMPLE, TaskType.TRANSLATION],
                cost_per_1k=0.0015,
                context_window=8192,
                quality_score=7.0
            ),
            ModelCapability(
                model_id="qwen-plus",
                provider="dashscope",
                strengths=[TaskType.COMPLEX, TaskType.CODING],
                cost_per_1k=0.004,
                context_window=32768,
                quality_score=8.5
            ),
            ModelCapability(
                model_id="qwen-max", 
                provider="dashscope",
                strengths=[TaskType.COMPLEX, TaskType.CREATIVE],
                cost_per_1k=0.02,
                context_window=8192,
                quality_score=9.5
            ),
            ModelCapability(
                model_id="gpt-3.5-turbo",
                provider="openai",
                strengths=[TaskType.SIMPLE, TaskType.CODING],
                cost_per_1k=0.0015,
                context_window=4096,
                quality_score=8.0
            ),
            ModelCapability(
                model_id="gpt-4",
                provider="openai",
                strengths=[TaskType.COMPLEX, TaskType.CREATIVE, TaskType.CODING],
                cost_per_1k=0.03,
                context_window=8192,
                quality_score=9.8
            ),
            ModelCapability(
                model_id="moonshot-v1-8k",
                provider="moonshot",
                strengths=[TaskType.SIMPLE, TaskType.TRANSLATION],
                cost_per_1k=0.012,
                context_window=8192,
                quality_score=7.5
            ),
            ModelCapability(
                model_id="moonshot-v1-32k",
                provider="moonshot", 
                strengths=[TaskType.COMPLEX, TaskType.CODING],
                cost_per_1k=0.024,
                context_window=32768,
                quality_score=8.0
            )
        ]
        
        # 路由统计
        self.routing_stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "task_type_distribution": {t.value: 0 for t in TaskType},
            "model_selection_count": {},
            "cost_savings": 0.0
        }
    
    def classify_task(self, messages: List[Dict[str, Any]]) -> Tuple[TaskType, float]:
        """分类任务类型"""
        
        # 提取用户消息文本
        user_text = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_text += msg.get("content", "") + " "
        
        user_text = user_text.lower().strip()
        
        if not user_text:
            return TaskType.UNKNOWN, 0.0
        
        # 按模式匹配各种任务类型
        task_scores = {}
        
        for task_type, patterns in self.task_patterns.items():
            score = 0
            matches = 0
            
            for pattern in patterns:
                if re.search(pattern, user_text):
                    matches += 1
                    # 根据匹配长度调整分数
                    match_obj = re.search(pattern, user_text)
                    if match_obj:
                        score += len(match_obj.group(0)) / len(user_text)
            
            # 综合评分：匹配数量 + 匹配质量
            if matches > 0:
                task_scores[task_type] = matches * 0.3 + score * 0.7
        
        # 简单启发式规则
        if len(user_text) < 20:
            task_scores[TaskType.SIMPLE] = task_scores.get(TaskType.SIMPLE, 0) + 0.5
        elif len(user_text) > 200:
            task_scores[TaskType.COMPLEX] = task_scores.get(TaskType.COMPLEX, 0) + 0.3
        
        # 选择最高分的任务类型
        if task_scores:
            best_task = max(task_scores.items(), key=lambda x: x[1])
            return best_task[0], min(best_task[1], 1.0)
        
        return TaskType.SIMPLE, 0.3  # 默认简单任务
    
    def estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """估算token数量"""
        total_chars = 0
        
        for msg in messages:
            content = msg.get("content", "")
            total_chars += len(content)
        
        # 中英文混合估算: 1.5字符 ≈ 1token
        estimated_tokens = int(total_chars / 1.5)
        return max(estimated_tokens, 10)  # 最少10tokens
    
    def select_model(
        self,
        task_type: TaskType,
        confidence: float,
        estimated_tokens: int,
        strategy: str = "cost_optimized",
        provider_health: Dict[str, bool] = None
    ) -> Tuple[str, str, float, str]:
        """选择最优模型"""
        
        provider_health = provider_health or {}
        
        # 过滤健康的模型
        available_models = []
        for model in self.model_capabilities:
            if provider_health.get(model.provider, True):  # 默认健康
                available_models.append(model)
        
        if not available_models:
            # 降级到默认模型
            logger.warning("所有Provider不健康，使用降级模型")
            return "qwen-turbo", "dashscope", 0.0015, "Provider降级"
        
        # 按策略选择
        if strategy == "cost_optimized":
            return self._select_by_cost(task_type, confidence, available_models)
        elif strategy == "quality_optimized":
            return self._select_by_quality(task_type, confidence, available_models)
        elif strategy == "balanced":
            return self._select_balanced(task_type, confidence, available_models)
        else:
            return self._select_by_cost(task_type, confidence, available_models)
    
    def _select_by_cost(self, task_type: TaskType, confidence: float, models: List[ModelCapability]) -> Tuple[str, str, float, str]:
        """成本优先选择"""
        
        # 筛选适合的模型
        suitable_models = []
        for model in models:
            if task_type in model.strengths or task_type == TaskType.UNKNOWN:
                suitable_models.append(model)
        
        if not suitable_models:
            suitable_models = models  # 降级到所有可用模型
        
        # 高置信度简单任务 → 最便宜模型
        if task_type == TaskType.SIMPLE and confidence > 0.7:
            cheapest = min(suitable_models, key=lambda m: m.cost_per_1k)
            return cheapest.model_id, cheapest.provider, cheapest.cost_per_1k, "简单任务成本优化"
        
        # 复杂任务 → 平衡成本和质量
        if task_type in [TaskType.COMPLEX, TaskType.CODING]:
            # 成本-质量权衡评分
            def cost_quality_score(model):
                cost_score = 1.0 / (model.cost_per_1k * 1000 + 1)  # 成本越低分数越高
                quality_score = model.quality_score / 10.0
                return cost_score * 0.7 + quality_score * 0.3
            
            best_model = max(suitable_models, key=cost_quality_score)
            return best_model.model_id, best_model.provider, best_model.cost_per_1k, "成本-质量平衡"
        
        # 创意任务 → 质量优先，但控制成本
        if task_type == TaskType.CREATIVE:
            creative_models = [m for m in suitable_models if m.quality_score >= 8.0]
            if creative_models:
                best_creative = min(creative_models, key=lambda m: m.cost_per_1k)
                return best_creative.model_id, best_creative.provider, best_creative.cost_per_1k, "创意任务质量优化"
        
        # 默认最便宜
        cheapest = min(suitable_models, key=lambda m: m.cost_per_1k)
        return cheapest.model_id, cheapest.provider, cheapest.cost_per_1k, "默认成本优化"
    
    def _select_by_quality(self, task_type: TaskType, confidence: float, models: List[ModelCapability]) -> Tuple[str, str, float, str]:
        """质量优先选择"""
        
        suitable_models = [m for m in models if task_type in m.strengths or task_type == TaskType.UNKNOWN]
        if not suitable_models:
            suitable_models = models
        
        best_quality = max(suitable_models, key=lambda m: m.quality_score)
        return best_quality.model_id, best_quality.provider, best_quality.cost_per_1k, "质量优先"
    
    def _select_balanced(self, task_type: TaskType, confidence: float, models: List[ModelCapability]) -> Tuple[str, str, float, str]:
        """平衡选择"""
        
        suitable_models = [m for m in models if task_type in m.strengths or task_type == TaskType.UNKNOWN]
        if not suitable_models:
            suitable_models = models
        
        def balanced_score(model):
            cost_score = 1.0 / (model.cost_per_1k * 1000 + 1)
            quality_score = model.quality_score / 10.0
            return cost_score * 0.5 + quality_score * 0.5
        
        best_balanced = max(suitable_models, key=balanced_score)
        return best_balanced.model_id, best_balanced.provider, best_balanced.cost_per_1k, "平衡策略"
    
    async def route_request(
        self,
        messages: List[Dict[str, Any]],
        strategy: str = "cost_optimized",
        provider_health: Dict[str, bool] = None,
        user_context: Dict[str, Any] = None
    ) -> RoutingDecision:
        """路由请求到最佳模型"""
        
        start_time = time.perf_counter()
        
        # 生成缓存键
        messages_hash = hash(str(messages))
        cache_key = f"{messages_hash}_{strategy}"
        
        # 检查缓存
        if cache_key in self.decision_cache:
            decision = self.decision_cache[cache_key]
            decision.from_cache = True
            self.routing_stats["cache_hits"] += 1
            logger.debug(f"路由决策命中缓存: {decision.selected_model}")
            return decision
        
        try:
            # 1. 分类任务
            task_type, confidence = self.classify_task(messages)
            
            # 2. 估算tokens
            estimated_tokens = self.estimate_tokens(messages)
            
            # 3. 选择模型
            model_id, provider, cost_per_1k, reason = self.select_model(
                task_type, confidence, estimated_tokens, strategy, provider_health
            )
            
            # 4. 计算估算成本
            estimated_cost = (estimated_tokens / 1000) * cost_per_1k
            
            # 5. 构建决策
            decision = RoutingDecision(
                selected_model=model_id,
                provider=provider,
                task_type=task_type,
                confidence=confidence,
                reason=reason,
                estimated_cost=estimated_cost,
                estimated_tokens=estimated_tokens,
                from_cache=False
            )
            
            # 6. 缓存决策
            self.decision_cache[cache_key] = decision
            
            # 7. 更新统计
            self.routing_stats["total_requests"] += 1
            self.routing_stats["task_type_distribution"][task_type.value] += 1
            
            model_key = f"{provider}:{model_id}"
            self.routing_stats["model_selection_count"][model_key] = \
                self.routing_stats["model_selection_count"].get(model_key, 0) + 1
            
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(f"路由决策完成: {model_id} ({task_type.value}, {confidence:.2f}, {duration_ms:.1f}ms)")
            
            return decision
        
        except Exception as e:
            logger.error(f"路由决策失败: {str(e)}")
            
            # 降级策略
            return RoutingDecision(
                selected_model="qwen-turbo",
                provider="dashscope", 
                task_type=TaskType.UNKNOWN,
                confidence=0.0,
                reason=f"路由异常降级: {str(e)}",
                estimated_cost=0.0015,
                estimated_tokens=estimated_tokens if 'estimated_tokens' in locals() else 100,
                from_cache=False
            )
    
    def get_routing_stats(self) -> Dict[str, Any]:
        """获取路由统计信息"""
        
        cache_hit_rate = 0.0
        if self.routing_stats["total_requests"] > 0:
            cache_hit_rate = self.routing_stats["cache_hits"] / self.routing_stats["total_requests"]
        
        return {
            "total_requests": self.routing_stats["total_requests"],
            "cache_hits": self.routing_stats["cache_hits"],
            "cache_hit_rate": cache_hit_rate,
            "task_distribution": self.routing_stats["task_type_distribution"],
            "model_usage": self.routing_stats["model_selection_count"],
            "cost_savings_usd": self.routing_stats["cost_savings"],
            "cache_size": len(self.decision_cache)
        }
    
    def clear_cache(self):
        """清空路由缓存"""
        self.decision_cache.clear()
        logger.info("路由决策缓存已清空")


# 全局路由器实例
_global_router: Optional[SmartRouter] = None


def get_smart_router(config: Dict[str, Any] = None) -> SmartRouter:
    """获取全局智能路由器实例"""
    global _global_router
    
    if _global_router is None:
        _global_router = SmartRouter(config)
        logger.info("智能路由器初始化完成")
    
    return _global_router


async def route_to_best_model(
    messages: List[Dict[str, Any]],
    strategy: str = "cost_optimized",
    provider_health: Dict[str, bool] = None,
    user_context: Dict[str, Any] = None
) -> RoutingDecision:
    """便捷函数: 路由到最佳模型"""
    
    router = get_smart_router()
    return await router.route_request(messages, strategy, provider_health, user_context)


if __name__ == "__main__":
    # 测试路由器
    import asyncio
    
    async def test_router():
        router = SmartRouter()
        
        test_cases = [
            [{"role": "user", "content": "你好"}],
            [{"role": "user", "content": "请分析人工智能对社会的深远影响，从技术、经济、伦理三个维度进行系统论述"}],
            [{"role": "user", "content": "写一个Python快速排序算法，要求有详细注释和时间复杂度分析"}],
            [{"role": "user", "content": "写一首关于秋天的现代诗，要富有诗意和画面感"}],
            [{"role": "user", "content": "Please translate this to English: 人工智能正在改变世界"}]
        ]
        
        for i, messages in enumerate(test_cases):
            print(f"\n测试案例 {i+1}: {messages[0]['content'][:30]}...")
            decision = await router.route_request(messages)
            print(f"选择模型: {decision.selected_model}")
            print(f"Provider: {decision.provider}")
            print(f"任务类型: {decision.task_type.value}")
            print(f"置信度: {decision.confidence:.3f}")
            print(f"预估成本: ${decision.estimated_cost:.6f}")
            print(f"选择原因: {decision.reason}")
        
        print(f"\n路由统计:")
        stats = router.get_routing_stats()
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    
    asyncio.run(test_router())