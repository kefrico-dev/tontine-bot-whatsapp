"""Accès MongoDB (PyMongo async)."""

from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

MongoClient = AsyncMongoClient[dict[str, Any]]


def create_mongo_client(settings: Settings) -> MongoClient:
    """Crée le client MongoDB. La connexion réelle est établie paresseusement."""
    return AsyncMongoClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
        connectTimeoutMS=settings.mongodb_timeout_ms,
        tz_aware=True,
        uuidRepresentation="standard",
    )


def get_database(client: MongoClient, settings: Settings) -> AsyncDatabase[dict[str, Any]]:
    return client[settings.mongodb_database]


async def ping(client: MongoClient) -> bool:
    """Vrai si MongoDB répond. Ne lève jamais : destiné au readiness check."""
    try:
        await client.admin.command("ping")
    except PyMongoError as exc:
        logger.warning("mongodb_ping_failed", error=str(exc))
        return False
    return True
