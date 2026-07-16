"""Safety helpers for persisting US broker order metadata."""

import re
from typing import Any, Dict, Mapping, Optional


BROKER_ORDER_PAYLOAD_FIELDS = (
    "order_no",
    "order_date",
    "response_code",
    "message",
    "ticker",
    "exchange",
    "requested_quantity",
    "requested_price",
    "filled_quantity",
    "remaining_quantity",
    "average_fill_price",
)

_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+\-/]+=*"),
    re.compile(
        r"(?i)[\"']?\b(authorization|access[_-]?token|refresh[_-]?token|"
        r"app[_-]?secret|appsecret|api[_-]?key|appkey|client[_-]?secret|"
        r"password|passwd|my[_-]?sec|paper[_-]?sec|htsid|"
        r"account(?:[_-]?(?:number|no))?|cano)[\"']?\s*[:=]\s*"
        r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
    ),
    re.compile(r"\b\d{4}(?:-\d{2,4}){2,3}\b"),
    re.compile(r"\b\d{8,12}\b"),
)


def sanitize_order_payload(payload: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return only explicitly approved, non-secret broker order fields."""
    if payload is None:
        return None
    sanitized = {}
    for field in BROKER_ORDER_PAYLOAD_FIELDS:
        if field not in payload:
            continue
        value = payload[field]
        if field == "message" and value is not None:
            value = sanitize_reason(str(value))
        sanitized[field] = value
    return sanitized


def sanitize_reason(reason: Optional[str], max_length: int = 500) -> Optional[str]:
    """Bound and mask free-form broker/exception text before persistence."""
    if reason is None:
        return None
    sanitized = str(reason)
    for pattern in _SENSITIVE_TEXT_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized[:max_length]
