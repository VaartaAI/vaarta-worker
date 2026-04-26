"""
Exponential backoff retry decorator.

Usage:
    @with_retry(max_attempts=3, backoff_base=2.0, exceptions=(RateLimitError,))
    def call_api(...):
        ...

Delay schedule: 2^1=2s, 2^2=4s, 2^3=8s, ...
"""
from __future__ import annotations
import time
import functools
from typing import Tuple, Type
import structlog

logger = structlog.get_logger(__name__)


def with_retry(
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """
    Decorator that retries the wrapped function with exponential backoff.

    Args:
        max_attempts: Total attempts including the first try.
        backoff_base:  Base for exponent — delay = backoff_base ** attempt_number.
        exceptions:    Only retry on these exception types.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == max_attempts:
                        logger.error(
                            "retry_exhausted",
                            func=func.__qualname__,
                            max_attempts=max_attempts,
                            error=str(exc),
                        )
                        raise
                    delay = backoff_base ** attempt
                    logger.warning(
                        "retry_backoff",
                        func=func.__qualname__,
                        attempt=attempt,
                        retry_in_seconds=delay,
                        error=str(exc),
                    )
                    time.sleep(delay)
        return wrapper
    return decorator
