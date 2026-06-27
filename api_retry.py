"""Exponential-backoff retry for transient Anthropic API errors.

Wrap any callable that makes a single API call (``client.messages.create`` /
``client.messages.stream`` acquisition) in ``with_retries(...)``. Only *transient*
errors are retried — rate limits (429), overloaded / 5xx server errors (500/502/
503/504/529), timeouts, and connection drops. Permanent errors (400 invalid
request, model refusals surfaced as 4xx, etc.) are re-raised immediately so we
fail fast instead of burning the retry budget on a request that can never succeed.

This composes with the per-stage budget caps: a transient error that never billed
costs nothing, so retrying it is free; once a call finally succeeds it records
usage and the caller's ``check_budget`` fires. The cap remains the runaway ceiling.

Version-tolerant: exception classes are resolved by name via ``getattr`` so the
module imports cleanly even if a future/older SDK drops one of them.
"""

from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

import anthropic

T = TypeVar("T")


class _NeverMatch(Exception):
    """Sentinel used when an SDK version lacks a named exception class."""


def _exc(name: str):
    return getattr(anthropic, name, _NeverMatch)


# Named transient exception classes (resolved defensively).
_TRANSIENT_TYPES = tuple(
    _exc(n)
    for n in ("RateLimitError", "APITimeoutError", "APIConnectionError", "InternalServerError")
)

# HTTP status codes treated as transient when surfaced via APIStatusError.
_TRANSIENT_STATUS = {500, 502, 503, 504, 529}

_APIStatusError = _exc("APIStatusError")


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, _TRANSIENT_TYPES):
        return True
    if _APIStatusError is not _NeverMatch and isinstance(exc, _APIStatusError):
        if getattr(exc, "status_code", None) in _TRANSIENT_STATUS:
            return True
    return False


def with_retries(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay: float = 2.0,
    on_retry: Callable[[int, float, Exception], None] | None = None,
) -> T:
    """Call ``fn()``; on a transient error wait and retry, up to ``max_attempts``.

    Backoff is exponential (``base_delay * 2**attempt``) plus jitter. Non-transient
    errors raise immediately. After the final attempt the last error is re-raised.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — we re-raise non-transient below
            if not _is_transient(exc) or attempt == max_attempts - 1:
                raise
            last_exc = exc
            delay = base_delay * (2 ** attempt) + random.uniform(0.0, base_delay * 0.25)
            if on_retry is not None:
                on_retry(attempt + 1, delay, exc)
            time.sleep(delay)
    # Unreachable in practice (final attempt either returns or raises), but keeps
    # the type checker and runtime honest.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("with_retries: no attempts were made.")
