"""Observability helpers for Bridge Server."""

from .logging import get_logger, setup_structured_logging
from .metrics import (
    BridgeServerMetrics,
    PROMETHEUS_MEDIA_TYPE,
    get_metrics_collector,
    render_prometheus_metrics,
)
from .runtime import PerformanceMonitor, build_runtime_snapshot
from .tracing import (
    attach_response_context,
    bind_llm_context,
    bind_request_context,
    bind_user_context,
    clear_request_context,
    extract_request_context,
    get_trace_headers,
)

__all__ = [
    "attach_response_context",
    "bind_llm_context",
    "bind_request_context",
    "bind_user_context",
    "BridgeServerMetrics",
    "build_runtime_snapshot",
    "clear_request_context",
    "extract_request_context",
    "get_logger",
    "get_metrics_collector",
    "get_trace_headers",
    "PerformanceMonitor",
    "PROMETHEUS_MEDIA_TYPE",
    "render_prometheus_metrics",
    "setup_structured_logging",
]
