from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any


_REQUEST_ID: ContextVar[str | None] = ContextVar(
    "llmbastion_request_id",
    default=None,
)

_EVENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")

# Explicit allowlist: raw prompts, model responses, headers, query strings,
# client IPs, API keys, exception messages, and arbitrary evidence are never
# serialized by the structured application logger.
_ALLOWED_FIELDS = {
    "action",
    "backend",
    "check",
    "duration_ms",
    "environment",
    "error_type",
    "latency_ms",
    "limit",
    "method",
    "output_action",
    "path",
    "provider",
    "provider_status",
    "redaction_count",
    "remaining",
    "reset_after_seconds",
    "risk_score",
    "semantic_score",
    "status_code",
}


class StructuredJsonFormatter(logging.Formatter):
    """Privacy-first JSON formatter for LLMBastion application events."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(
            record.created,
            tz=timezone.utc,
        ).isoformat().replace("+00:00", "Z")

        event = getattr(record, "event", "application.log")
        if not isinstance(event, str) or not _EVENT_PATTERN.fullmatch(event):
            event = "application.log"

        payload: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "service": "LLMBastion",
            "logger": record.name,
            "event": event,
        }

        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            payload["request_id"] = request_id

        for field in sorted(_ALLOWED_FIELDS):
            if hasattr(record, field):
                payload[field] = getattr(record, field)

        # Exception text/tracebacks may contain provider payloads or secrets.
        # Keep only the exception class for operational diagnosis.
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__

        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )


def configure_logging(level: str = "INFO") -> None:
    """Configure the `app.*` logger tree once with JSON stdout logs."""
    app_logger = logging.getLogger("app")
    normalized_level = level.strip().upper()

    existing = next(
        (
            handler
            for handler in app_logger.handlers
            if getattr(handler, "_llmbastion_json", False)
        ),
        None,
    )

    if existing is None:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredJsonFormatter())
        handler._llmbastion_json = True  # type: ignore[attr-defined]
        app_logger.addHandler(handler)

    app_logger.setLevel(normalized_level)
    app_logger.propagate = False


def bind_request_id(request_id: str) -> Token:
    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Token) -> None:
    _REQUEST_ID.reset(token)


def get_request_id() -> str | None:
    return _REQUEST_ID.get()


def safe_request_path(request) -> str:
    """Return the route template, never a raw user-controlled URL path."""
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    return "<unmatched>"


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    exc_info=None,
    **fields: Any,
) -> None:
    """Emit a structured event after dropping all non-allowlisted fields."""
    safe_event = (
        event
        if isinstance(event, str) and _EVENT_PATTERN.fullmatch(event)
        else "application.log"
    )
    extra = {
        "event": safe_event,
        **{
            key: value
            for key, value in fields.items()
            if key in _ALLOWED_FIELDS
        },
    }
    logger.log(
        level,
        safe_event,
        extra=extra,
        exc_info=exc_info,
    )
