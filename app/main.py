"""Point d'entrée de l'application KEFRICO Tontine."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from pymongo.errors import PyMongoError

from app.api import health
from app.api.webhooks import whatsapp as whatsapp_webhook
from app.core.config import Settings, get_settings
from app.core.error_handlers import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.infrastructure.database.indexes import ensure_indexes
from app.infrastructure.database.mongodb import create_mongo_client, get_database, ping
from app.infrastructure.whatsapp.client import WhatsAppClient

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    # Préchauffage : la première connexion (résolution SRV puis TLS) coûte
    # plusieurs secondes. On la paie au démarrage plutôt que sur le premier
    # /ready. Une base injoignable ne bloque pas le démarrage : c'est le rôle
    # du readiness check de le signaler.
    reachable = await ping(app.state.mongo_client)

    if reachable:
        try:
            await ensure_indexes(get_database(app.state.mongo_client, settings))
            app.state.indexes_ready = True
        except PyMongoError as exc:
            # Sans index unique, l'idempotence n'est pas garantie : le webhook
            # refusera de traiter plutôt que de risquer une double réponse.
            logger.error("mongodb_indexes_failed", error=type(exc).__name__)

    logger.info(
        "application_started",
        environment=settings.environment,
        database=settings.mongodb_database,
        mongodb="up" if reachable else "down",
        indexes_ready=app.state.indexes_ready,
        whatsapp_configured=settings.whatsapp_configured,
    )
    try:
        yield
    finally:
        await app.state.http_client.aclose()
        await app.state.mongo_client.close()
        logger.info("application_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.is_production)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.mongo_client = create_mongo_client(settings)
    app.state.indexes_ready = False

    # Un seul client HTTP pour toute la durée de vie de l'application :
    # les connexions vers Meta sont ainsi réutilisées.
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.whatsapp_timeout_s, connect=5.0)
    )
    app.state.whatsapp_client = WhatsAppClient(settings, app.state.http_client)

    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(whatsapp_webhook.router)

    return app


app = create_app()
