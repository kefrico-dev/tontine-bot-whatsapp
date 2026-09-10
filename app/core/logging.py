"""Logging structuré minimal : timestamp, level, event, correlation_id."""

import logging
import sys

import structlog
from structlog.typing import Processor


def configure_logging(*, level: str = "INFO", json_logs: bool = False) -> None:
    """Configure structlog. JSON en production, rendu lisible en développement."""
    log_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    # Les logs stdlib (uvicorn) partent sur le même flux.
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # injecte correlation_id
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.typing.FilteringBoundLogger:
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(name)
    return logger
