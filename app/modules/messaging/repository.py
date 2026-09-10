"""Accès MongoDB du module messaging. Aucune logique métier ici."""

from datetime import UTC, datetime
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.core.logging import get_logger
from app.infrastructure.whatsapp.client import SentMessage
from app.modules.messaging.schemas import (
    PROVIDER_WHATSAPP,
    InboundWhatsAppMessage,
    MessageDirection,
    MessageStatus,
    WebhookEventStatus,
    WebhookEventType,
    WhatsAppMessageType,
)

logger = get_logger(__name__)

WEBHOOK_EVENTS = "webhook_events"
MESSAGES = "messages"


def _now() -> datetime:
    return datetime.now(tz=UTC)


class MessagingRepository:
    """Persistance des événements webhook et des messages."""

    def __init__(self, database: AsyncDatabase[dict[str, Any]]) -> None:
        self._db = database

    async def claim_event(
        self,
        *,
        external_id: str,
        event_type: WebhookEventType,
        message_type: WhatsAppMessageType | None,
        correlation_id: str | None,
    ) -> bool:
        """Pose le verrou d'idempotence.

        Renvoie ``True`` si cet événement n'avait jamais été vu, ``False`` s'il
        l'avait déjà été. L'insertion sous contrainte unique est atomique :
        deux livraisons simultanées ne peuvent pas gagner toutes les deux, ce
        qu'un ``find`` suivi d'un ``insert`` ne garantirait pas.
        """
        document = {
            "provider": PROVIDER_WHATSAPP,
            "external_id": external_id,
            "event_type": event_type.value,
            "message_type": message_type.value if message_type else None,
            "status": WebhookEventStatus.RECEIVED.value,
            "received_at": _now(),
            "processed_at": None,
            "correlation_id": correlation_id,
            "error": None,
        }
        try:
            await self._db[WEBHOOK_EVENTS].insert_one(document)
        except DuplicateKeyError:
            return False
        return True

    async def mark_event(
        self,
        *,
        external_id: str,
        status: WebhookEventStatus,
        error: str | None = None,
    ) -> None:
        await self._db[WEBHOOK_EVENTS].update_one(
            {"external_id": external_id},
            {"$set": {"status": status.value, "processed_at": _now(), "error": error}},
        )

    async def store_inbound_message(
        self,
        message: InboundWhatsAppMessage,
        *,
        recipient: str | None,
        correlation_id: str | None,
    ) -> bool:
        """Enregistre un message entrant. ``False`` s'il était déjà stocké."""
        document = {
            "provider": PROVIDER_WHATSAPP,
            "direction": MessageDirection.INBOUND.value,
            "external_message_id": message.external_message_id,
            "sender": message.sender_phone,
            "sender_name": message.sender_name,
            "recipient": recipient,
            "message_type": message.message_type.value,
            "text": message.text,
            "status": MessageStatus.RECEIVED.value,
            "created_at": message.timestamp,
            "correlation_id": correlation_id,
        }
        try:
            await self._db[MESSAGES].insert_one(document)
        except DuplicateKeyError:
            logger.info("inbound_message_already_stored", message_id=message.external_message_id)
            return False
        return True

    async def store_outbound_message(
        self,
        sent: SentMessage,
        *,
        text: str,
        sender: str | None,
        correlation_id: str | None,
    ) -> bool:
        document = {
            "provider": PROVIDER_WHATSAPP,
            "direction": MessageDirection.OUTBOUND.value,
            "external_message_id": sent.external_message_id,
            "sender": sender,
            "recipient": sent.recipient,
            "message_type": WhatsAppMessageType.TEXT.value,
            "text": text,
            "status": MessageStatus.SENT.value,
            "created_at": _now(),
            "correlation_id": correlation_id,
        }
        try:
            await self._db[MESSAGES].insert_one(document)
        except DuplicateKeyError:
            return False
        return True
