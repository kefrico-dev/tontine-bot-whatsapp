"""Modèles internes du canal de messagerie.

Ces modèles sont volontairement indépendants du format Meta : le payload brut
ne circule pas dans l'application, il est traduit une fois pour toutes par le
parser puis oublié.
"""

from datetime import datetime
from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, Field

PROVIDER_WHATSAPP: Final[Literal["WHATSAPP"]] = "WHATSAPP"


class MessageDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class MessageStatus(StrEnum):
    RECEIVED = "RECEIVED"
    SENT = "SENT"
    FAILED = "FAILED"


class WhatsAppMessageType(StrEnum):
    """Types Meta connus. Seul TEXT est traité en Phase 1."""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"
    LOCATION = "location"
    CONTACTS = "contacts"
    INTERACTIVE = "interactive"
    BUTTON = "button"
    REACTION = "reaction"
    ORDER = "order"
    SYSTEM = "system"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value: object) -> "WhatsAppMessageType":
        """Ne lève jamais : un type inconnu de Meta devient UNKNOWN."""
        if isinstance(value, str):
            try:
                return cls(value)
            except ValueError:
                return cls.UNKNOWN
        return cls.UNKNOWN


class WebhookEventType(StrEnum):
    INBOUND_MESSAGE = "INBOUND_MESSAGE"
    MESSAGE_STATUS = "MESSAGE_STATUS"
    UNKNOWN = "UNKNOWN"


class WebhookEventStatus(StrEnum):
    """Cycle de vie d'un événement webhook.

    ``REPLY_FAILED`` est la clé de la reprise : l'événement a été reçu, le
    message entrant est enregistré, seul l'envoi de la réponse a échoué. Un
    futur mécanisme de reprise pourra donc renvoyer la réponse sans retraiter
    le message entrant, en sélectionnant simplement les événements dans cet
    état.
    """

    RECEIVED = "RECEIVED"
    IGNORED = "IGNORED"
    REPLIED = "REPLIED"
    REPLY_FAILED = "REPLY_FAILED"
    FAILED = "FAILED"


class InboundWhatsAppMessage(BaseModel):
    """Message entrant normalisé."""

    provider: Literal["WHATSAPP"] = PROVIDER_WHATSAPP
    external_message_id: str
    sender_phone: str
    sender_name: str | None = None
    message_type: WhatsAppMessageType
    text: str | None = None
    timestamp: datetime

    @property
    def event_type(self) -> WebhookEventType:
        return WebhookEventType.INBOUND_MESSAGE

    @property
    def external_id(self) -> str:
        """Clé de déduplication : l'identifiant Meta du message est unique."""
        return self.external_message_id


class WhatsAppStatusEvent(BaseModel):
    """Accusé de livraison d'un message sortant (sent / delivered / read / failed)."""

    provider: Literal["WHATSAPP"] = PROVIDER_WHATSAPP
    external_message_id: str
    status: str
    recipient: str | None = None
    timestamp: datetime

    @property
    def event_type(self) -> WebhookEventType:
        return WebhookEventType.MESSAGE_STATUS

    @property
    def external_id(self) -> str:
        """Un même message produit plusieurs statuts : la clé les distingue."""
        return f"{self.external_message_id}:{self.status}"


class UnknownWebhookEvent(BaseModel):
    """Événement légitime mais non reconnu : on le trace sans le comprendre."""

    provider: Literal["WHATSAPP"] = PROVIDER_WHATSAPP
    #: Empreinte du corps brut — jamais le corps lui-même.
    fingerprint: str = Field(min_length=8)

    @property
    def event_type(self) -> WebhookEventType:
        return WebhookEventType.UNKNOWN

    @property
    def external_id(self) -> str:
        """Un rejeu à l'identique reste dédupliqué grâce à l'empreinte."""
        return f"sha256:{self.fingerprint}"


ParsedEvent = InboundWhatsAppMessage | WhatsAppStatusEvent | UnknownWebhookEvent


class ProcessingResult(BaseModel):
    """Résumé du traitement d'un webhook, destiné aux logs."""

    received: int = 0
    duplicates: int = 0
    replied: int = 0
    reply_failed: int = 0
    ignored: int = 0
