"""Création des index MongoDB.

``create_index`` est idempotent : réexécuter cette fonction à chaque démarrage
ne recrée rien et ne coûte qu'un aller-retour.
"""

from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.core.logging import get_logger
from app.modules.conversations.repository import CONVERSATION_STATES
from app.modules.messaging.repository import MESSAGES, WEBHOOK_EVENTS
from app.modules.tontines.repository import (
    INVITE_CODE_INDEX,
    MEMBER_INDEX,
    TONTINE_MEMBERS,
    TONTINES,
)
from app.modules.users.repository import USERS

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
    # --- Phase 2 : metier ---------------------------------------------------
    await database[USERS].create_index("phone", unique=True, name="uniq_user_phone")
    await database[TONTINES].create_index("invite_code", unique=True, name=INVITE_CODE_INDEX)
    await database[TONTINE_MEMBERS].create_index(
        [("tontine_id", 1), ("user_id", 1)], unique=True, name=MEMBER_INDEX
    )
    # Non unique : « Mes tontines » liste les adhesions d'un utilisateur.
    await database[TONTINE_MEMBERS].create_index("user_id", name="tontine_member_user")
    await database[CONVERSATION_STATES].create_index(
        "user_id", unique=True, name="uniq_conversation_user"
    )
    # Nettoyage asynchrone des conversations abandonnees. Le service verifie
    # aussi expires_at a la lecture : le demon TTL n'est pas ponctuel.
    await database[CONVERSATION_STATES].create_index(
        "expires_at", expireAfterSeconds=0, name="ttl_conversation_expires"
    )

    logger.info(
        "mongodb_indexes_ready",
        collections=[
            WEBHOOK_EVENTS,
            MESSAGES,
            USERS,
            TONTINES,
            TONTINE_MEMBERS,
            CONVERSATION_STATES,
        ],
    )
