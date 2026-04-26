"""
Structured JSON logging configuration using structlog.
Call configure_logging() once at process startup before any imports that log.
"""
from __future__ import annotations
import logging
import sys
import structlog


def configure_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
    ]

    structlog.configure(
        processors=shared_processors + [structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (used by third-party libs) through structlog
    logging.basicConfig(
        level=log_level,
        stream=sys.stdout,
        format="%(message)s",
        force=True,
    )
