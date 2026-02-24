from __future__ import annotations


def is_embedding_payload_too_large(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "maximum context length" in message
        or "maximum tokens" in message
        or "too many tokens" in message
        or "request too large" in message
        or "payload too large" in message
    )


def is_transient_embedding_error(exc: Exception) -> bool:
    message = str(exc).lower()
    transient_markers = (
        "timeout",
        "timed out",
        "temporarily unavailable",
        "service unavailable",
        "rate limit",
        "try again",
        "connection reset",
        "502",
        "503",
        "504",
    )
    return any(marker in message for marker in transient_markers)
