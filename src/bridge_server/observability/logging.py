"""Structured logging setup for Bridge Server."""

import json
import logging
import os
from typing import Any, Dict

import structlog


_service_context: Dict[str, Any] = {
    "service": "bridge-server",
    "version": "unknown",
    "environment": os.getenv("ENVIRONMENT", "development"),
}


def _json_dumps(payload: Any, **kwargs: Any) -> str:
    kwargs.setdefault("default", str)
    return json.dumps(payload, ensure_ascii=False, **kwargs)


def _add_service_context(
    _logger: logging.Logger, _method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    event_dict.update({key: value for key, value in _service_context.items() if value})
    return event_dict


def setup_structured_logging(
    *, service_name: str = "bridge-server", version: str = "unknown", level: str = "INFO"
) -> None:
    """Configure JSON structured logging for both stdlib logging and structlog."""
    _service_context.update(
        {
            "service": service_name,
            "version": version,
            "environment": os.getenv("ENVIRONMENT", "development"),
        }
    )

    log_level = getattr(logging, str(level).upper(), logging.INFO)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_service_context,
    ]

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(serializer=_json_dumps),
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    logging.captureWarnings(True)

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None):
    """Return a structlog logger."""
    return structlog.get_logger(name)
