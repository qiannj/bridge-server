"""Prometheus metrics collection for Bridge Server."""

from __future__ import annotations

from typing import Any, Dict, Optional

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)


PROMETHEUS_MEDIA_TYPE = CONTENT_TYPE_LATEST


class BridgeServerMetrics:
    """Collect and render Prometheus metrics for runtime observability."""

    def __init__(self, registry: Optional[CollectorRegistry] = None):
        self.registry = registry or REGISTRY

        self.request_total = Counter(
            "bridge_server_requests_total",
            "Total HTTP requests processed by Bridge Server",
            ["method", "endpoint", "status_code"],
            registry=self.registry,
        )
        self.request_duration = Histogram(
            "bridge_server_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "endpoint"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self.registry,
        )
        self.inflight_requests = Gauge(
            "bridge_server_in_progress_requests",
            "In-flight HTTP requests",
            ["endpoint"],
            registry=self.registry,
        )
        self.llm_calls_total = Counter(
            "bridge_server_llm_calls_total",
            "LLM API calls made by provider and model",
            ["provider", "model", "status"],
            registry=self.registry,
        )
        self.llm_call_duration = Histogram(
            "bridge_server_llm_call_duration_seconds",
            "LLM upstream call duration in seconds",
            ["provider", "model", "status"],
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
            registry=self.registry,
        )
        self.token_usage_total = Counter(
            "bridge_server_tokens_total",
            "Prompt and completion token usage",
            ["provider", "model", "token_type"],
            registry=self.registry,
        )
        self.route_decisions_total = Counter(
            "bridge_server_route_decisions_total",
            "Smart routing decisions",
            ["task_type", "provider", "model", "from_cache"],
            registry=self.registry,
        )
        self.provider_total = Gauge(
            "bridge_server_providers_total",
            "Total configured providers",
            registry=self.registry,
        )
        self.provider_available = Gauge(
            "bridge_server_available_providers",
            "Currently available providers",
            registry=self.registry,
        )
        self.provider_enabled = Gauge(
            "bridge_server_provider_enabled",
            "Whether a provider is enabled",
            ["provider"],
            registry=self.registry,
        )
        self.provider_healthy = Gauge(
            "bridge_server_provider_healthy",
            "Latest provider health status",
            ["provider"],
            registry=self.registry,
        )
        self.cache_hit_rate = Gauge(
            "bridge_server_cache_hit_rate",
            "Current cache hit rate",
            registry=self.registry,
        )
        self.cache_requests = Gauge(
            "bridge_server_cache_requests_total",
            "Observed cache requests",
            registry=self.registry,
        )
        self.cache_writes = Gauge(
            "bridge_server_cache_writes_total",
            "Observed cache writes",
            registry=self.registry,
        )
        self.cache_errors = Gauge(
            "bridge_server_cache_errors_total",
            "Observed cache errors",
            registry=self.registry,
        )
        self.requests_per_second = Gauge(
            "bridge_server_requests_per_second",
            "Runtime requests per second",
            registry=self.registry,
        )
        self.average_latency_ms = Gauge(
            "bridge_server_average_latency_ms",
            "Average request latency in milliseconds",
            registry=self.registry,
        )
        self.error_rate = Gauge(
            "bridge_server_error_rate",
            "Runtime error rate",
            registry=self.registry,
        )
        self.db_connections_in_use = Gauge(
            "bridge_server_db_connections_in_use",
            "Database connections currently in use",
            registry=self.registry,
        )
        self.db_connections_available = Gauge(
            "bridge_server_db_connections_available",
            "Database connections currently available",
            registry=self.registry,
        )
        self.provider_http_clients = Gauge(
            "bridge_server_provider_http_clients",
            "Shared provider HTTP client count",
            registry=self.registry,
        )
        self.budget_remaining_rmb = Gauge(
            "bridge_server_budget_remaining_rmb",
            "Remaining budget in RMB",
            ["period"],
            registry=self.registry,
        )
        self.budget_usage_ratio = Gauge(
            "bridge_server_budget_usage_ratio",
            "Budget usage ratio",
            ["period"],
            registry=self.registry,
        )
        self.budget_alert_active = Gauge(
            "bridge_server_budget_alert_active",
            "Whether a budget alert is active",
            ["period"],
            registry=self.registry,
        )

    def record_http_request(
        self, method: str, endpoint: str, status_code: int, duration_seconds: float
    ) -> None:
        endpoint = endpoint or "unknown"
        self.request_total.labels(
            method=method.upper(),
            endpoint=endpoint,
            status_code=str(status_code),
        ).inc()
        self.request_duration.labels(
            method=method.upper(),
            endpoint=endpoint,
        ).observe(max(duration_seconds, 0.0))

    def increase_inflight(self, endpoint: str) -> None:
        self.inflight_requests.labels(endpoint=endpoint or "unknown").inc()

    def decrease_inflight(self, endpoint: str) -> None:
        self.inflight_requests.labels(endpoint=endpoint or "unknown").dec()

    def record_llm_call(
        self, provider: str, model: str, status: str, duration_seconds: float
    ) -> None:
        provider = provider or "unknown"
        model = model or "unknown"
        status = status or "unknown"
        self.llm_calls_total.labels(provider=provider, model=model, status=status).inc()
        self.llm_call_duration.labels(
            provider=provider,
            model=model,
            status=status,
        ).observe(max(duration_seconds, 0.0))

    def record_token_usage(
        self, provider: str, model: str, prompt_tokens: int = 0, completion_tokens: int = 0
    ) -> None:
        provider = provider or "unknown"
        model = model or "unknown"
        if prompt_tokens:
            self.token_usage_total.labels(
                provider=provider,
                model=model,
                token_type="prompt",
            ).inc(prompt_tokens)
        if completion_tokens:
            self.token_usage_total.labels(
                provider=provider,
                model=model,
                token_type="completion",
            ).inc(completion_tokens)

    def record_route_decision(
        self, task_type: str, provider: str, model: str, from_cache: bool
    ) -> None:
        self.route_decisions_total.labels(
            task_type=task_type or "unknown",
            provider=provider or "unknown",
            model=model or "unknown",
            from_cache=str(bool(from_cache)).lower(),
        ).inc()

    def set_performance_stats(self, stats: Dict[str, Any]) -> None:
        self.requests_per_second.set(stats.get("qps", 0.0) or 0.0)
        self.average_latency_ms.set(stats.get("avg_latency_ms", 0.0) or 0.0)
        self.error_rate.set(stats.get("error_rate", 0.0) or 0.0)

    def set_provider_stats(self, stats: Dict[str, Any]) -> None:
        self.provider_total.set(stats.get("total_providers", 0) or 0)
        self.provider_available.set(stats.get("available_providers", 0) or 0)

        for provider_id, provider_stats in stats.get("providers", {}).items():
            self.provider_enabled.labels(provider=provider_id).set(
                1 if provider_stats.get("enabled") else 0
            )

    def set_provider_health(self, health: Dict[str, Any]) -> None:
        for provider_id, status in health.items():
            normalized = getattr(status, "value", status)
            self.provider_healthy.labels(provider=provider_id).set(
                1 if normalized == "healthy" else 0
            )

    def set_cache_metrics(self, cache_metrics: Dict[str, Any]) -> None:
        metrics = cache_metrics.get("metrics", {})
        self.cache_hit_rate.set(metrics.get("hit_rate", 0.0) or 0.0)
        self.cache_requests.set(metrics.get("total_requests", 0) or 0)
        self.cache_writes.set(metrics.get("writes", 0) or 0)
        self.cache_errors.set(metrics.get("errors", 0) or 0)

    def set_connection_pool_stats(self, connection_stats: Dict[str, Any]) -> None:
        database = connection_stats.get("database", {})
        provider_http = connection_stats.get("provider_http_clients", {})
        self.db_connections_in_use.set(database.get("in_use", 0) or 0)
        self.db_connections_available.set(database.get("available", 0) or 0)
        self.provider_http_clients.set(provider_http.get("count", 0) or 0)

    def set_budget_status(self, budget_status: Dict[str, Any]) -> None:
        for period in ("today", "month"):
            budget = budget_status.get(period, {})
            limit = budget.get("limit_rmb", 0.0) or 0.0
            used = budget.get("used_rmb", 0.0) or 0.0
            remaining = max(limit - used, 0.0)
            self.budget_remaining_rmb.labels(period=period).set(remaining)
            self.budget_usage_ratio.labels(period=period).set(budget.get("usage_rate", 0.0) or 0.0)
            self.budget_alert_active.labels(period=period).set(1 if budget.get("alert") else 0)

    def observe_runtime_snapshot(self, snapshot: Dict[str, Any]) -> None:
        if "performance" in snapshot:
            self.set_performance_stats(snapshot["performance"])
        if "providers" in snapshot:
            self.set_provider_stats(snapshot["providers"])
        if "cache" in snapshot:
            self.set_cache_metrics(snapshot["cache"])
        if "connection_pool" in snapshot:
            self.set_connection_pool_stats(snapshot["connection_pool"])
        if "budget" in snapshot and isinstance(snapshot["budget"], dict) and "error" not in snapshot["budget"]:
            self.set_budget_status(snapshot["budget"])

    def render(self) -> bytes:
        return generate_latest(self.registry)


_metrics_collector: Optional[BridgeServerMetrics] = None


def get_metrics_collector() -> BridgeServerMetrics:
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = BridgeServerMetrics()
    return _metrics_collector


def render_prometheus_metrics(metrics_collector: Optional[BridgeServerMetrics] = None) -> bytes:
    collector = metrics_collector or get_metrics_collector()
    return collector.render()
