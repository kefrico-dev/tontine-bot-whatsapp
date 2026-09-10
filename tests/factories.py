"""Payloads Meta et doublures utilisées par les tests.

Les payloads reproduisent la structure réellement observée sur le numéro de
test Meta, champs non documentés compris (``from_user_id``, ``country_code``,
``internal_1p_only_data``…), afin que le parser soit éprouvé sur du vrai.
"""

import json
from typing import Any

from app.infrastructure.whatsapp.client import SentMessage
from app.infrastructure.whatsapp.security import compute_signature
from app.modules.messaging.schemas import (
    InboundWhatsAppMessage,
    WebhookEventStatus,
    WebhookEventType,
    WhatsAppMessageType,
)

APP_SECRET = "0123456789abcdef0123456789abcdef"
VERIFY_TOKEN = "kefrico-verify-token-de-test"
PHONE_NUMBER_ID = "100000000000001"
WABA_ID = "200000000000002"
SENDER = "22900000000"  # numero fictif
WAMID = "wamid.TEST0000000000000000000000000000001"


def text_message_payload(
    *,
    message_id: str = WAMID,
    sender: str = SENDER,
    text: str = "Bonjour",
    message_type: str = "text",
    profile_name: str | None = "kefrico",
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "from": sender,
        "from_user_id": "BJ.0000000000000001",
        "id": message_id,
        "timestamp": "1789075498",
        "type": message_type,
        "from_logical_id": "1000000000001",
        "internal_1p_only_data": {"account_context": {"cs_id": PHONE_NUMBER_ID}},
    }
    if message_type == "text":
        message["text"] = {"body": text}

    contacts: list[dict[str, Any]] = []
    if profile_name is not None:
        contacts.append(
            {
                "profile": {"name": profile_name},
                "wa_id": sender,
                "user_id": "BJ.0000000000000001",
                "country_code": "BJ",
            }
        )

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA_ID,
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "10000000000",
                                "phone_number_id": PHONE_NUMBER_ID,
                            },
                            "contacts": contacts,
                            "messages": [message],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def status_payload(*, message_id: str = WAMID, status: str = "delivered") -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA_ID,
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                            "statuses": [
                                {
                                    "id": message_id,
                                    "status": status,
                                    "timestamp": "1789075500",
                                    "recipient_id": SENDER,
                                    "conversation": {"id": "abc"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def signed_headers(body: bytes, *, secret: str = APP_SECRET) -> dict[str, str]:
    return {
        "X-Hub-Signature-256": compute_signature(secret=secret, payload=body),
        "Content-Type": "application/json",
    }


class FakeMessagingRepository:
    """Repository en mémoire reproduisant le comportement du verrou unique."""

    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}
        self.inbound: list[InboundWhatsAppMessage] = []
        self.outbound: list[SentMessage] = []

    async def claim_event(
        self,
        *,
        external_id: str,
        event_type: WebhookEventType,
        message_type: WhatsAppMessageType | None,
        correlation_id: str | None,
    ) -> bool:
        if external_id in self.events:
            return False
        self.events[external_id] = {
            "event_type": event_type,
            "message_type": message_type,
            "status": WebhookEventStatus.RECEIVED,
            "correlation_id": correlation_id,
            "error": None,
        }
        return True

    async def mark_event(
        self, *, external_id: str, status: WebhookEventStatus, error: str | None = None
    ) -> None:
        self.events[external_id]["status"] = status
        self.events[external_id]["error"] = error

    async def store_inbound_message(
        self,
        message: InboundWhatsAppMessage,
        *,
        recipient: str | None,
        correlation_id: str | None,
    ) -> bool:
        if any(m.external_message_id == message.external_message_id for m in self.inbound):
            return False
        self.inbound.append(message)
        return True

    async def store_outbound_message(
        self,
        sent: SentMessage,
        *,
        text: str,
        sender: str | None,
        correlation_id: str | None,
    ) -> bool:
        self.outbound.append(sent)
        return True

    def status_of(self, external_id: str) -> WebhookEventStatus:
        status: WebhookEventStatus = self.events[external_id]["status"]
        return status


class FakeWhatsAppClient:
    """Client sortant simulé : compte les envois, peut échouer à la demande."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[tuple[str, str]] = []

    async def send_text_message(self, *, to: str, text: str) -> SentMessage:
        if self.error is not None:
            raise self.error
        self.sent.append((to, text))
        return SentMessage(
            external_message_id=f"wamid.OUT{len(self.sent)}",
            recipient=to,
        )
