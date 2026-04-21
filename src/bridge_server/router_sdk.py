"""
Bridge Server 开放路由 SDK
================================
用户通过继承 BaseRouter 实现自定义路由逻辑并一键导入 Bridge Server。

使用流程：
  1. 继承 BaseRouter，实现 route(ctx) 方法
  2. 在项目根目录创建 manifest.json
  3. 运行 bridge-server router import <目录>  或上传 .bspkg 包

安全约束（自动强制）：
  - 不可 import os / subprocess / socket / sys 等危险模块
  - route() 硬超时 300ms，超时后系统自动 fallback 到内置路由
  - RoutingDecision 中 provider/model 必须在 ctx.models 已知列表中
  - RoutingContext 永不包含 api_key / oauth_token / 完整对话内容
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


# ── 模型信息 ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModelCapabilities:
    """
    模型能力评分（0.0 ~ 1.0），数据来自 cli/model-benchmark.py 的测试结果。
    若尚未运行 benchmark，所有字段默认为 0.0。
    """
    coding: float = 0.0         # 代码生成 / 调试能力
    reasoning: float = 0.0      # 逻辑推理 / 数学能力
    creative: float = 0.0       # 创意写作 / 内容生成
    tool_use: float = 0.0       # 函数调用 / 工具使用
    context_length: int = 4096  # 最大上下文长度（tokens）


@dataclass(frozen=True)
class ModelMetrics:
    """运行时动态指标（过去 5 分钟滚动窗口）。首次启动或无请求时为默认值。"""
    latency_p50_ms: float = 0.0     # 中位延迟
    latency_p99_ms: float = 0.0     # 99 分位延迟
    error_rate: float = 0.0          # 错误率 0.0~1.0
    is_rate_limited: bool = False    # 当前是否触发限流


@dataclass(frozen=True)
class ModelInfo:
    """单个模型的完整信息快照（只读）。"""
    provider: str
    model_id: str
    display_name: str
    health: Literal["healthy", "degraded", "down", "unknown"]
    input_cost_per_1k: float    # ¥/1K input tokens（来自 config.yaml）
    output_cost_per_1k: float   # ¥/1K output tokens
    capabilities: ModelCapabilities
    metrics: ModelMetrics
    tags: List[str] = field(default_factory=list)

    @property
    def cost_per_1k(self) -> float:
        """总综合成本（输入+输出 ¥/1K tokens）"""
        return self.input_cost_per_1k + self.output_cost_per_1k

    @property
    def full_name(self) -> str:
        """'provider/model_id' 格式，用于 RoutingDecision 校验"""
        return f"{self.provider}/{self.model_id}"


# ── 路由上下文（只读，传给自定义路由器）────────────────────────────────────

@dataclass(frozen=True)
class RoutingContext:
    """
    传给自定义路由器的只读上下文。

    ⚠️  永远不包含：api_key、oauth_token、完整历史消息内容。
    路由器只能看到 last_user_message、消息轮数、模型列表和 session 元数据。
    """
    last_user_message: str
    messages_count: int
    models: List[ModelInfo]
    session_metadata: Dict[str, Any] = field(default_factory=dict)

    # ── 内置便利方法（减少样板代码）─────────────────────────────────────────

    def healthy(self) -> List[ModelInfo]:
        """返回所有 health='healthy' 的模型。"""
        return [m for m in self.models if m.health == "healthy"]

    def cheapest(
        self,
        min_capability: Optional[str] = None,
        min_score: float = 0.0,
    ) -> Optional[ModelInfo]:
        """
        健康节点中综合成本最低的模型。

        Args:
            min_capability: 'coding' | 'reasoning' | 'creative' | 'tool_use'
            min_score:      对应能力的最低分数门槛（0.0~1.0）
        """
        pool = self.healthy()
        if min_capability:
            pool = [
                m for m in pool
                if getattr(m.capabilities, min_capability, 0.0) >= min_score
            ]
        return min(pool, key=lambda m: m.cost_per_1k, default=None)

    def best(self, capability: str = "reasoning") -> Optional[ModelInfo]:
        """健康节点中指定能力最强的模型。"""
        return max(
            self.healthy(),
            key=lambda m: getattr(m.capabilities, capability, 0.0),
            default=None,
        )

    def under_latency(self, max_p99_ms: float) -> List[ModelInfo]:
        """健康节点中 p99 延迟低于阈值的模型列表。"""
        return [
            m for m in self.healthy()
            if m.metrics.latency_p99_ms <= max_p99_ms
        ]

    def by_tag(self, tag: str) -> List[ModelInfo]:
        """按 tag 过滤健康节点（tag 在 config.yaml model.tags 中定义）。"""
        return [m for m in self.healthy() if tag in m.tags]


# ── 路由决策 ────────────────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    """路由器 route() 方法必须返回的结构。"""
    provider: str
    model: str
    confidence: float   # 0.0 ~ 1.0，路由置信度
    reason: str         # 人类可读的路由原因，写入请求日志

    def validate(self, ctx: RoutingContext) -> Optional[str]:
        """
        校验决策合法性。
        返回 None 表示合法；返回字符串表示错误信息（系统将拒绝该决策并 fallback）。
        """
        valid_names = {m.full_name for m in ctx.models}
        full = f"{self.provider}/{self.model}"
        if full not in valid_names:
            return (
                f"路由目标 '{full}' 不在可用模型列表中。"
                f"可用: {sorted(valid_names)}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            return f"confidence 必须在 0.0~1.0 之间，实际值: {self.confidence}"
        if not self.reason:
            return "reason 不能为空"
        return None


# ── 基类 ─────────────────────────────────────────────────────────────────────

class BaseRouter(ABC):
    """
    自定义路由器基类。

    最小实现示例::

        from bridge_server.router_sdk import BaseRouter, RoutingContext, RoutingDecision

        class MyRouter(BaseRouter):
            async def route(self, ctx: RoutingContext) -> RoutingDecision:
                m = ctx.cheapest('coding', min_score=0.7) or ctx.healthy()[0]
                return RoutingDecision(
                    provider=m.provider,
                    model=m.model_id,
                    confidence=0.8,
                    reason='默认最便宜编码模型',
                )

    manifest.json 最小示例::

        {
            "name": "my-router",
            "version": "1.0.0",
            "entrypoint": "router.py",
            "class": "MyRouter"
        }
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: 来自 router_config.yaml 的用户自定义参数字典。
        """
        self.config = config

    def on_load(self) -> bool:
        """
        加载时健康检查（可选重写）。
        返回 False 或抛出异常 → 拒绝激活该路由器。
        可在此处加载模型文件、预热缓存等。
        """
        return True

    @abstractmethod
    async def route(self, ctx: RoutingContext) -> RoutingDecision:
        """
        核心路由逻辑。

        约束：
          - 严禁阻塞调用（数据库查询、网络请求等）
          - 硬超时 300ms，超时后系统自动 fallback 到内置路由
          - 必须返回 RoutingDecision，provider/model 必须在 ctx.models 中
        """
        ...
