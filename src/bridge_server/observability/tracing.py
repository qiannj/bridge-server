"""Request tracing helpers and correlation propagation."""

from __future__ import annotations

import secrets
from typing import Any, Dict, Mapping, Optional

import structlog


REQUEST_ID_HEADER = "X-Request-ID"
TRACE_ID_HEADER = "X-Trace-ID"
TRACEPARENT_HEADER = "traceparent"


def _generate_request_id() -> str:
    return secrets.token_hex(8)


def _generate_trace_id() -> str:
    return secrets.token_hex(16)


def _generate_span_id() -> str:
    return secrets.token_hex(8)


def _normalize_trace_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    candidate = "".join(ch for ch in value.strip().lower() if ch.isalnum())
    if len(candidate) == 32:
        return candidate
    return None


def _parse_traceparent(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    parts = value.split("-")
    if len(parts) != 4:
        return None
    return _normalize_trace_id(parts[1])


def extract_request_context(headers: Mapping[str, str]) -> Dict[str, str]:
    """Build request and trace identifiers from incoming headers."""
    request_id = headers.get(REQUEST_ID_HEADER, "") or headers.get(REQUEST_ID_HEADER.lower(), "")
    trace_id = (
        _normalize_trace_id(headers.get(TRACE_ID_HEADER))
        or _normalize_trace_id(headers.get(TRACE_ID_HEADER.lower()))
        or _parse_traceparent(headers.get(TRACEPARENT_HEADER))
        or _parse_traceparent(headers.get(TRACEPARENT_HEADER.lower()))
    )

    return {
        "request_id": request_id or _generate_request_id(),
        "trace_id": trace_id or _generate_trace_id(),
    }


def bind_request_context(
    *,
    request_id: str,
    trace_id: str,
    method: str,
    path: str,
    client_ip: Optional[str] = None,
) -> None:
    structlog.contextvars.clear_contextvars()
    context = {
        "request_id": request_id,
        "trace_id": trace_id,
        "http_method": method,
        "http_path": path,
    }
    if client_ip:
        context["client_ip"] = client_ip
    structlog.contextvars.bind_contextvars(**context)


def bind_user_context(*, user_id: Optional[str] = None, user_domain: Optional[str] = None) -> None:
    updates = {}
    if user_id:
        updates["user_id"] = user_id
    if user_domain:
        updates["user_domain"] = user_domain
    if updates:
        structlog.contextvars.bind_contextvars(**updates)


def bind_llm_context(*, provider_id: Optional[str] = None, model: Optional[str] = None) -> None:
    updates = {}
    if provider_id:
        updates["provider_id"] = provider_id
    if model:
        updates["model"] = model
    if updates:
        structlog.contextvars.bind_contextvars(**updates)


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()


def get_context() -> Dict[str, Any]:
    return dict(structlog.contextvars.get_contextvars())


def get_trace_headers() -> Dict[str, str]:
    """Return outbound headers that propagate the current trace context."""
    context = get_context()
    trace_id = _normalize_trace_id(context.get("trace_id"))
    request_id = context.get("request_id")

    if not trace_id:
        return {}

    headers = {
        TRACE_ID_HEADER: trace_id,
        TRACEPARENT_HEADER: f"00-{trace_id}-{_generate_span_id()}-01",
    }
    if request_id:
        headers[REQUEST_ID_HEADER] = str(request_id)
    return headers


def attach_response_context(response: Any, request_context: Mapping[str, str]) -> None:
    response.headers[REQUEST_ID_HEADER] = request_context["request_id"]
    response.headers[TRACE_ID_HEADER] = request_context["trace_id"]
