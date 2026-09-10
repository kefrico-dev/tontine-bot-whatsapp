"""Traduction des payloads Meta vers les modèles internes.

Règle du module : ne jamais supposer qu'une clé existe. Meta envoie des
messages, des statuts de livraison, des notifications système et des champs
non documentés ; aucun d'eux ne doit provoquer d'erreur.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

from app.modules.messaging.schemas import (
    InboundWhatsAppMessage,
    ParsedEvent,
    UnknownWebhookEvent,
    WhatsAppMessageType,
    WhatsAppStatusEvent,
)


def fingerprint(raw_body: bytes) -> str:
    """Empreinte du corps brut, utilisée comme clé de déduplication de secours."""
    return hashlib.sha256(raw_body).hexdigest()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _parse_timestamp(value: Any) -> datetime:
    """Horodatage Meta (secondes Unix, transmis en chaîne) vers UTC."""
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return datetime.now(tz=UTC)


def _extract_text(message: dict[str, Any]) -> str | None:
    return _as_str(_as_dict(message.get("text")).get("body"))


def _profile_name(contacts: list[Any], wa_id: str) -> str | None:
    """Nom de profil correspondant à l'expéditeur, s'il est fourni."""
    for contact in contacts:
        entry = _as_dict(contact)
        if _as_str(entry.get("wa_id")) == wa_id:
            return _as_str(_as_dict(entry.get("profile")).get("name"))
    return None


def _parse_message(message: Any, contacts: list[Any]) -> InboundWhatsAppMessage | None:
    data = _as_dict(message)
    message_id = _as_str(data.get("id"))
    sender = _as_str(data.get("from"))
    if not message_id or not sender:
        return None

    message_type = WhatsAppMessageType.parse(data.get("type"))
    return InboundWhatsAppMessage(
        external_message_id=message_id,
        sender_phone=sender,
        sender_name=_profile_name(contacts, sender),
        message_type=message_type,
        text=_extract_text(data) if message_type is WhatsAppMessageType.TEXT else None,
        timestamp=_parse_timestamp(data.get("timestamp")),
    )


def _parse_status(status: Any) -> WhatsAppStatusEvent | None:
    data = _as_dict(status)
    message_id = _as_str(data.get("id"))
    state = _as_str(data.get("status"))
    if not message_id or not state:
        return None

    return WhatsAppStatusEvent(
        external_message_id=message_id,
        status=state,
        recipient=_as_str(data.get("recipient_id")),
        timestamp=_parse_timestamp(data.get("timestamp")),
    )


def parse_webhook_payload(payload: Any, *, raw_body: bytes) -> list[ParsedEvent]:
    """Extrait les événements exploitables d'un payload Meta.

    Renvoie toujours au moins un événement : un payload dont rien n'est
    reconnaissable produit un ``UnknownWebhookEvent``, afin qu'il soit tracé et
    dédupliqué comme les autres plutôt que silencieusement perdu.
    """
    events: list[ParsedEvent] = []

    for entry in _as_list(_as_dict(payload).get("entry")):
        for change in _as_list(_as_dict(entry).get("changes")):
            value = _as_dict(_as_dict(change).get("value"))
            contacts = _as_list(value.get("contacts"))

            for message in _as_list(value.get("messages")):
                parsed = _parse_message(message, contacts)
                if parsed is not None:
                    events.append(parsed)

            for status in _as_list(value.get("statuses")):
                parsed_status = _parse_status(status)
                if parsed_status is not None:
                    events.append(parsed_status)

    if not events:
        events.append(UnknownWebhookEvent(fingerprint=fingerprint(raw_body)))

    return events
