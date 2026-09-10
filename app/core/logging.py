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

    # Le log d'accès d'uvicorn imprime la query string complète, ce qui ferait
    # apparaître hub.verify_token en clair sur GET /webhooks/whatsapp. Notre
    # propre middleware journalise déjà méthode, chemin, statut et durée, sans
    # la query string : cette ligne est à la fois redondante et dangereuse.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    access_logger.disabled = True

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


def mask_phone(phone: str | None) -> str | None:
    """Masque un numéro pour les logs : seuls les 4 derniers chiffres restent."""
    if not phone:
        return None
    digits = "".join(character for character in phone if character.isdigit())
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]
