"""Runtime observability helpers."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional


class PerformanceMonitor:
    """Track coarse application performance metrics."""

    def __init__(self):
        self.request_count = 0
        self.total_latency = 0.0
        self.error_count = 0
        self.start_time = time.time()
        self._lock = asyncio.Lock()

    async def record_request(self, latency_ms: float, success: bool) -> None:
        async with self._lock:
            self.request_count += 1
            if success:
                self.total_latency += latency_ms
            else:
                self.error_count += 1

    async def get_stats(self) -> Dict[str, Any]:
        async with self._lock:
            uptime = time.time() - self.start_time
            successful_requests = max(1, self.request_count - self.error_count)
            qps = self.request_count / uptime if uptime > 0 else 0.0
            error_rate = self.error_count / max(1, self.request_count)

            return {
                "uptime_seconds": round(uptime, 2),
                "total_requests": self.request_count,
                "qps": round(qps, 2),
                "avg_latency_ms": round(self.total_latency / successful_requests, 2),
                "error_count": self.error_count,
                "error_rate": round(error_rate, 4),
                "success_rate": round(1 - error_rate, 4),
            }


async def _resolve_stat_source(source: Any) -> Any:
    if asyncio.iscoroutine(source):
        return await source
    return source


async def build_runtime_snapshot(
    *,
    perf_monitor: Optional[PerformanceMonitor] = None,
    provider_manager: Any = None,
    cache_system: Any = None,
    smart_router: Any = None,
    connection_pool_manager: Any = None,
    usage_tracker: Any = None,
) -> Dict[str, Any]:
    """Collect the current runtime snapshot used by JSON and Prometheus outputs."""
    snapshot: Dict[str, Any] = {
        "timestamp": time.time(),
        "observability": {
            "structured_logging": True,
            "request_tracing": True,
            "prometheus_endpoint": "/metrics/prometheus",
        },
    }

    if perf_monitor:
        snapshot["performance"] = await perf_monitor.get_stats()

    sources = []
    if provider_manager:
        sources.append(("providers", provider_manager.get_stats()))
    if cache_system:
        sources.append(("cache", cache_system.get_metrics()))
    if smart_router:
        sources.append(("routing", smart_router.get_stats()))
    if connection_pool_manager:
        sources.append(("connection_pool", connection_pool_manager.get_stats()))
    if usage_tracker:
        sources.append(("budget", usage_tracker.get_budget_status()))

    for name, source in sources:
        try:
            snapshot[name] = await _resolve_stat_source(source)
        except Exception as exc:
            snapshot[name] = {"error": str(exc)}

    return snapshot
