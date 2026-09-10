"""Création des index MongoDB.

``create_index`` est idempotent : réexécuter cette fonction à chaque démarrage
ne recrée rien et ne coûte qu'un aller-retour.
"""

from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.core.logging import get_logger
from app.modules.messaging.repository import MESSAGES, WEBHOOK_EVENTS

logger = get_logger(__name__)


async def ensure_indexes(database: AsyncDatabase[dict[str, Any]]) -> None:
    """Pose les contraintes dont dépend l'idempotence.

    ``webhook_events.external_id`` est le verrou fonctionnel : il empêche de
    répondre deux fois au même message. ``messages.external_message_id`` est un
    garde-fou de données : il garantit l'unicité de l'historique même si un
    futur chemin de code oubliait de passer par le verrou.
    """
    await database[WEBHOOK_EVENTS].create_index(
        "external_id", unique=True, name="uniq_webhook_event_external_id"
    )
    await database[MESSAGES].create_index(
        "external_message_id", unique=True, name="uniq_message_external_id"
    )
    logger.info("mongodb_indexes_ready", collections=[WEBHOOK_EVENTS, MESSAGES])
