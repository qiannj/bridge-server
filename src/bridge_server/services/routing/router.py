#!/usr/bin/env python3
"""
场景化路由服务 - Bridge Server v2.1
基于可配置正则表达式的场景匹配和模型选择
"""

import re
import logging
import hashlib
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default patterns for known scenario names (used when config has no patterns)
DEFAULT_PATTERNS: Dict[str, List[str]] = {
    'coding': [
        r'代码|编程|函数|debug|bug|算法|程序|脚本|API|接口|实现|报错|错误|exception|syntax',
        r'code|python|javascript|typescript|java|golang|cpp|rust|programming|function|debug|algorithm|script',
    ],
    'writing': [
        r'写|文章|邮件|报告|文档|文案|润色|改写|撰写|起草|文稿|作文|创作',
        r'write|article|email|report|document|essay|draft|rewrite|proofread|compose',
    ],
    'search': [
        r'搜索|查找|查询|检索|找一下|查一下|哪里有|在哪|怎么找|有没有',
        r'search|find|lookup|query|retrieve|where is|how to find|locate',
    ],
    'summary': [
        r'总结|摘要|归纳|概括|提炼|压缩|简化|要点|精华|缩写',
        r'summarize|summary|abstract|condense|brief|key points|tldr|recap',
    ],
    'translation': [
        r'翻译|译成|译为|中译英|英译中|用.*语说|怎么说|转换语言|多语言',
        r'translate|translation|in english|in chinese|in japanese|how do you say|language',
    ],
    'chat': [
        r'你好|hi|hello|谢谢|再见|在吗|聊天|说说|讲讲|介绍一下|是什么|怎么样',
        r'hello|hi|hey|thanks|bye|chat|tell me|what is|who is|explain|how are you',
    ],
}



@dataclass
class RouteResult:
    """路由结果"""
    provider_id: str
    model: str
    task_type: str          # scenario name, e.g. "coding", "writing", "general"
    confidence: float
    reason: str
    from_cache: bool = False

    @classmethod
    def from_cached_data(cls, cached_data: Dict) -> 'RouteResult':
        return cls(
            provider_id=cached_data['provider_id'],
            model=cached_data['model'],
            task_type=cached_data['task_type'],
            confidence=cached_data['confidence'],
            reason=cached_data['reason'],
            from_cache=True,
        )

    def to_cache(self) -> Dict:
        return {
            'provider_id': self.provider_id,
            'model': self.model,
            'task_type': self.task_type,
            'confidence': self.confidence,
            'reason': self.reason,
        }


class ScenarioMatcher:
    """基于可配置正则表达式的场景匹配器"""

    def __init__(self, scenarios: Dict[str, Any]):
        self._scenarios: Dict[str, Any] = {}
        self._compiled: Dict[str, List[re.Pattern]] = {}
        self._compiled_exclude: Dict[str, List[re.Pattern]] = {}
        self.load(scenarios)

    def load(self, scenarios: Dict[str, Any]):
        """加载场景配置，支持热更新"""
        self._scenarios = {}
        self._compiled = {}
        self._compiled_exclude = {}
        for name, cfg in scenarios.items():
            if not cfg.get('enabled', True):
                continue
            patterns = cfg.get('patterns') or DEFAULT_PATTERNS.get(name, [])
            exclude_patterns = cfg.get('exclude_patterns') or []
            self._scenarios[name] = cfg
            self._compiled[name] = [
                re.compile(p, re.IGNORECASE) for p in patterns if p
            ]
            self._compiled_exclude[name] = [
                re.compile(p, re.IGNORECASE) for p in exclude_patterns if p
            ]
        logger.info(f"场景匹配器加载完成: {list(self._scenarios.keys())}")

    def match(self, message: str) -> Tuple[str, float]:
        """
        对消息进行场景匹配。
        - conditions 字段（声明式条件）优先于 patterns 匹配
        - exclude_patterns 中任一命中 → 跳过该场景
        - 多场景同时命中 → priority 高者优先，priority 相同时取得分高者
        Returns (scenario_name, confidence) — 无匹配时返回 ('general', 0.5)
        """
        if not message:
            return 'general', 0.5

        scores: Dict[str, float] = {}
        for name, patterns in self._compiled.items():
            cfg = self._scenarios[name]

            # Skip if any exclude pattern matches the message
            if any(p.search(message) for p in self._compiled_exclude.get(name, [])):
                logger.debug(f"场景 '{name}' 被排除规则跳过")
                continue

            # 优先评估 conditions 声明式条件
            conditions = cfg.get('conditions')
            if conditions:
                if self._eval_conditions(conditions, message):
                    # conditions 匹配，赋予高置信度
                    scores[name] = 0.95
                continue  # 有 conditions 字段则不再评估 patterns

            # 原有 patterns 评分逻辑
            score = 0.0
            for pattern in patterns:
                hits = len(pattern.findall(message))
                if hits > 0:
                    score += 0.3 + hits * 0.15
            if score > 0:
                scores[name] = min(score, 1.0)

        if not scores:
            return 'general', 0.5

        # Higher priority wins; break ties by score
        best = max(scores, key=lambda n: (self._scenarios[n].get('priority', 0), scores[n]))
        if scores[best] < 0.3:
            return 'general', 0.5

        return best, scores[best]

    @staticmethod
    def _eval_conditions(conditions: Dict[str, Any], message: str) -> bool:
        """
        求值声明式条件块。

        支持的条件字段：
          message_contains: str | list[str]
          message_length_gt: int
          message_length_lt: int
          time_hour_between: [start_hour, end_hour]   # 含 start，不含 end（跨午夜自动处理）
          weekday_in: list[int]                        # 0=周一 … 6=周日

        支持的逻辑组合：
          all_of: [...]   — 所有条件都满足
          any_of: [...]   — 任一条件满足
          none_of: [...]  — 所有条件都不满足
        """
        from datetime import datetime as _dt
        now = _dt.now()

        def _eval_single(cond: Dict[str, Any]) -> bool:
            # 嵌套逻辑
            if 'all_of' in cond:
                return all(_eval_single(c) for c in cond['all_of'])
            if 'any_of' in cond:
                return any(_eval_single(c) for c in cond['any_of'])
            if 'none_of' in cond:
                return not any(_eval_single(c) for c in cond['none_of'])

            # 叶节点条件
            if 'message_contains' in cond:
                keywords = cond['message_contains']
                if isinstance(keywords, str):
                    keywords = [keywords]
                return any(kw.lower() in message.lower() for kw in keywords)

            if 'message_length_gt' in cond:
                return len(message) > int(cond['message_length_gt'])

            if 'message_length_lt' in cond:
                return len(message) < int(cond['message_length_lt'])

            if 'time_hour_between' in cond:
                bounds = cond['time_hour_between']
                if len(bounds) >= 2:
                    start_h, end_h = int(bounds[0]), int(bounds[1])
                    h = now.hour
                    if start_h <= end_h:
                        return start_h <= h < end_h
                    else:  # 跨午夜，e.g. [22, 8]
                        return h >= start_h or h < end_h
                return False

            if 'weekday_in' in cond:
                return now.weekday() in [int(d) for d in cond['weekday_in']]

            return False

        try:
            return _eval_single(conditions)
        except Exception as e:
            logger.warning(f"条件求值失败: {e}")
            return False

    def get_model(self, scenario: str) -> Optional[str]:
        """获取场景对应的模型字符串 (format: 'provider/model')"""
        cfg = self._scenarios.get(scenario)
        if cfg:
            return cfg.get('model')
        return None


class SmartRouter:
    """智能路由器（配置驱动版）"""

    def __init__(self, scenarios: Dict[str, Any], cache=None):
        self.cache = cache
        self.matcher = ScenarioMatcher(scenarios)
        self._scenarios = scenarios
        logger.info("智能路由器初始化完成（配置驱动模式）")

    def reload(self, scenarios: Dict[str, Any]):
        """热更新路由配置（无需重启服务）"""
        self._scenarios = scenarios
        self.matcher.load(scenarios)
        logger.info(f"路由配置热更新完成，场景数: {len(scenarios)}")

    async def route(self, messages: list, user_context: Dict = None,
                    provider_manager=None) -> RouteResult:
        """执行路由决策"""
        user_message = self._extract_user_message(messages)
        cache_key = self._generate_cache_key(user_message, user_context)

        if self.cache:
            cached = await self._get_from_cache(cache_key)
            if cached:
                logger.debug(f"路由缓存命中: {cached.model} ({cached.task_type})")
                return cached

        scenario, confidence = self.matcher.match(user_message)

        model_str = self.matcher.get_model(scenario)

        # Fallback: pick first available model
        if not model_str and provider_manager:
            avail = provider_manager.get_provider_models()
            for pid, models in avail.items():
                if models:
                    first = models[0]
                    model_str = f"{pid}/{first}"
                    break

        provider_id, model = self._parse_model_str(model_str or '')

        result = RouteResult(
            provider_id=provider_id,
            model=model,
            task_type=scenario,
            confidence=confidence,
            reason=f"场景: {scenario} (置信度: {confidence:.2f})",
        )

        if self.cache:
            await self._cache_result(cache_key, result)

        logger.info(f"路由决策: {provider_id}/{model} | {result.reason}")
        return result

    @staticmethod
    def _parse_model_str(model_str: str) -> Tuple[str, str]:
        """
        解析 'provider/model' 格式字符串。
        支持 'nvidia/z-ai/glm4.7' → provider='nvidia', model='z-ai/glm4.7'
        """
        if not model_str:
            return 'unknown', 'unknown'
        idx = model_str.find('/')
        if idx == -1:
            return model_str, model_str
        return model_str[:idx], model_str[idx + 1:]

    @staticmethod
    def _extract_user_message(messages: list) -> str:
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get('role') == 'user':
                content = msg.get('content', '')
                if isinstance(content, list):
                    return ' '.join(
                        p.get('text', '') for p in content
                        if isinstance(p, dict) and p.get('type') == 'text'
                    )
                return str(content)
        return ''

    @staticmethod
    def _generate_cache_key(message: str, context: Dict = None) -> str:
        msg_hash = hashlib.sha256(message.encode(), usedforsecurity=False).hexdigest()[:16]
        key = f"route:{msg_hash}"
        if context:
            ctx = "_".join(
                f"{k}:{context[k]}" for k in sorted(context)
                if k in ('user_domain', 'last_task_type')
            )
            if ctx:
                key += ":" + hashlib.sha256(ctx.encode(), usedforsecurity=False).hexdigest()[:8]
        return key

    async def _get_from_cache(self, key: str) -> Optional[RouteResult]:
        try:
            data = await self.cache.get(key)
            if data:
                return RouteResult.from_cached_data(data)
        except Exception as e:
            logger.warning(f"缓存读取失败: {e}")
        return None

    async def _cache_result(self, key: str, result: RouteResult):
        try:
            await self.cache.set(key, result.to_cache(), ttl=300)
        except Exception as e:
            logger.warning(f"缓存写入失败: {e}")

    def get_stats(self) -> Dict[str, Any]:
        return {
            'scenarios': list(self._scenarios.keys()),
            'cache_enabled': self.cache is not None,
        }


# ── Backward-compatibility shims ─────────────────────────────────────────────

class TaskType:
    """Backward-compatibility stub. task_type is now a plain string."""
    pass


class RouterConfig:
    """Backward-compatibility stub. Config is now loaded from scenarios dict."""
    pass


class TaskDetector:
    """Backward-compatibility stub."""
    pass