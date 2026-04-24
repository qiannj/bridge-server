"""
Bridge Server Router SDK
========================
供自定义路由器插件使用的公开 API。

用户路由器示例：
    from bridge_server.router_sdk import BaseRouter, RoutingContext, RoutingDecision

    class MyRouter(BaseRouter):
        def on_load(self) -> bool:
            return True

        async def route(self, ctx: RoutingContext) -> RoutingDecision:
            if "代码" in ctx.last_user_message:
                return RoutingDecision(provider="openai", model="gpt-4o", confidence=0.9, reason="编程任务")
            return RoutingDecision(provider="dashscope", model="qwen3.5-plus", confidence=0.7, reason="通用任务")
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── 模型元信息（只读） ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModelCapabilities:
    """模型能力评分（0-1 浮点数，来自 benchmark 数据）。"""
    coding: float = 0.0
    reasoning: float = 0.0
    creative: float = 0.0
    tool_use: float = 0.0
    context_length: int = 4096


@dataclass(frozen=True)
class ModelMetrics:
    """模型近期运行指标（5 分钟滚动窗口）。"""
    latency_p50_ms: float = 0.0
    latency_p99_ms: float = 0.0
    error_rate: float = 0.0
    is_rate_limited: bool = False


@dataclass(frozen=True)
class ModelInfo:
    """
    单个模型的完整信息快照。
    由 ModelInfoAggregator 每 30 秒刷新，作为只读数据传给路由器。
    """
    provider: str
    model_id: str
    display_name: str = ""
    health: str = "unknown"        # "healthy" | "degraded" | "down" | "unknown"
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    metrics: ModelMetrics = field(default_factory=ModelMetrics)
    tags: List[str] = field(default_factory=list)

    @property
    def full_id(self) -> str:
        """返回 'provider/model_id' 格式的完整标识符。"""
        return f"{self.provider}/{self.model_id}"

    @property
    def is_healthy(self) -> bool:
        return self.health == "healthy"


# ── 路由上下文（传给路由器的只读输入） ─────────────────────────────────────────

@dataclass(frozen=True)
class RoutingContext:
    """
    路由决策的输入上下文。
    所有字段均为只读，不包含任何系统内部对象（provider_manager、token 等）。
    """
    last_user_message: str
    messages_count: int = 1
    models: List[ModelInfo] = field(default_factory=list)
    session_metadata: Dict[str, Any] = field(default_factory=dict)

    def get_healthy_models(self) -> List[ModelInfo]:
        """返回当前健康的模型列表。"""
        return [m for m in self.models if m.is_healthy]

    def find_model(self, provider: str, model_id: str) -> Optional[ModelInfo]:
        """按 provider + model_id 查找模型信息。"""
        for m in self.models:
            if m.provider == provider and m.model_id == model_id:
                return m
        return None


# ── 路由决策（路由器的输出） ──────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    """路由器返回的决策结果。"""
    provider: str
    model: str
    confidence: float = 0.5      # 0-1，置信度
    reason: str = ""

    def validate(self, ctx: RoutingContext) -> Optional[str]:
        """
        校验决策是否合法。
        返回 None 表示校验通过；返回字符串表示错误信息。
        """
        if not self.provider or not self.model:
            return "provider 和 model 字段不能为空"
        if not (0.0 <= self.confidence <= 1.0):
            return f"confidence 必须在 0-1 范围内，当前值: {self.confidence}"

        # 检查 provider/model 是否在可用模型列表中
        available = {(m.provider, m.model_id) for m in ctx.models}
        if available and (self.provider, self.model) not in available:
            return (
                f"模型 '{self.provider}/{self.model}' 不在可用模型列表中。"
                f"可用: {sorted(f'{p}/{m}' for p, m in available)}"
            )
        return None


# ── 基础路由器抽象类 ──────────────────────────────────────────────────────────

class BaseRouter(abc.ABC):
    """
    自定义路由器必须继承此类。

    合约：
    - __init__(config: dict)  — 接收 router_config.yaml 中的配置
    - on_load() -> bool       — 健康检查，返回 False 则拒绝激活
    - route(ctx) -> RoutingDecision  — 异步路由决策，必须在 300ms 内返回
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config: Dict[str, Any] = config or {}

    def on_load(self) -> bool:
        """路由器激活前的健康检查。返回 False 则激活失败。"""
        return True

    @abc.abstractmethod
    async def route(self, ctx: RoutingContext) -> RoutingDecision:
        """
        核心路由逻辑。
        - 必须是 async 方法
        - 必须在 300ms 内返回
        - 只能使用 ctx 中的只读数据，禁止访问文件系统或网络
        """
        ...
