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
        # Route through stdlib so additional handlers (e.g. OTel LoggingHandler)
        # see every structlog event too. The JSONRenderer above pre-renders the
        # event, and stdlib's StreamHandler just prints %(message)s — so stdout
        # shows the JSON unchanged, while extra handlers can ship it elsewhere.
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        level=log_level,
        stream=sys.stdout,
        format="%(message)s",
        force=True,
    )
