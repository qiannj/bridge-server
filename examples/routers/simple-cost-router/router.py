"""
simple-cost-router — 示例自定义路由器
=====================================
路由逻辑：
  1. 如果消息包含编码关键词 → 在满足 coding_min_score 的模型中选最便宜的
  2. 否则 → 所有健康模型中选最便宜的
  3. 若 max_latency_p99 > 0，在选择前先过滤高延迟模型

安装：
  bridge-server router import ./examples/routers/simple-cost-router
  bridge-server router activate simple-cost-router

测试：
  bridge-server router test simple-cost-router "帮我写一个快速排序"
"""

import re
from bridge_server.router_sdk import BaseRouter, RoutingContext, RoutingDecision

_CODING_PATTERNS = re.compile(
    r"(写代码|编程|函数|算法|debug|修复|报错|代码|script|implement|code|programming)",
    re.IGNORECASE,
)


class SimpleCostRouter(BaseRouter):
    """按能力门槛选最便宜模型的示例路由器。"""

    def __init__(self, config):
        super().__init__(config)
        self._coding_min = float(config.get("coding_min_score", 0.7))
        self._max_p99 = float(config.get("max_latency_p99", 0))

    def on_load(self) -> bool:
        # 参数校验
        assert 0.0 <= self._coding_min <= 1.0, "coding_min_score 必须在 0~1"
        return True

    async def route(self, ctx: RoutingContext) -> RoutingDecision:
        pool = ctx.healthy()

        # 过滤高延迟模型
        if self._max_p99 > 0:
            fast = [m for m in pool if m.metrics.latency_p99_ms <= self._max_p99]
            if fast:
                pool = fast

        if not pool:
            # Fallback: 任何模型（健康检查可能有延迟）
            pool = ctx.models

        is_coding = bool(_CODING_PATTERNS.search(ctx.last_user_message))

        if is_coding:
            # 满足编码能力门槛的模型中选最便宜的
            qualified = [m for m in pool if m.capabilities.coding >= self._coding_min]
            best = min(qualified, key=lambda m: m.cost_per_1k) if qualified else None
            reason = f"编码任务，coding≥{self._coding_min}的最便宜模型"
        else:
            best = None
            reason = "通用任务，最便宜健康模型"

        if best is None:
            best = min(pool, key=lambda m: m.cost_per_1k)

        return RoutingDecision(
            provider=best.provider,
            model=best.model_id,
            confidence=0.85 if is_coding else 0.75,
            reason=f"{reason}: {best.display_name} (¥{best.cost_per_1k:.4f}/K)",
        )
