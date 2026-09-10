"""Robustesse du parser : aucun payload Meta légitime ne doit le faire échouer."""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.infrastructure.whatsapp.parser import parse_webhook_payload
from app.modules.messaging.schemas import (
    InboundWhatsAppMessage,
    UnknownWebhookEvent,
    WebhookEventType,
    WhatsAppMessageType,
    WhatsAppStatusEvent,
)
from tests.factories import SENDER, WAMID, encode, status_payload, text_message_payload

RAW = b'{"raw": true}'


def parse(payload: Any) -> list[Any]:
    return parse_webhook_payload(payload, raw_body=encode(payload) if payload else RAW)


def test_text_message_is_normalised() -> None:
    events = parse(text_message_payload())

    assert len(events) == 1
    message = events[0]
    assert isinstance(message, InboundWhatsAppMessage)
    assert message.external_message_id == WAMID
    assert message.sender_phone == SENDER
    assert message.sender_name == "kefrico"
    assert message.message_type is WhatsAppMessageType.TEXT
    assert message.text == "Bonjour"
    assert message.timestamp == datetime.fromtimestamp(1789075498, tz=UTC)
    assert message.timestamp.tzinfo is UTC
    assert message.event_type is WebhookEventType.INBOUND_MESSAGE
    assert message.external_id == WAMID


def test_status_event_is_recognised_and_keyed_per_transition() -> None:
    delivered = parse(status_payload(status="delivered"))[0]
    read = parse(status_payload(status="read"))[0]

    assert isinstance(delivered, WhatsAppStatusEvent)
    assert delivered.event_type is WebhookEventType.MESSAGE_STATUS
    assert delivered.recipient == SENDER
    # Un même message produit plusieurs statuts : leurs clés doivent différer,
    # sinon seule la première transition serait enregistrée.
    assert delivered.external_id != read.external_id
    assert delivered.external_id == f"{WAMID}:delivered"


@pytest.mark.parametrize(
    "message_type",
    ["image", "audio", "video", "document", "location", "interactive", "sticker", "reaction"],
)
def test_unsupported_types_are_recognised_without_error(message_type: str) -> None:
    events = parse(text_message_payload(message_type=message_type))

    assert len(events) == 1
    message = events[0]
    assert isinstance(message, InboundWhatsAppMessage)
    assert message.message_type is WhatsAppMessageType(message_type)
    assert message.text is None


def test_type_unknown_to_us_becomes_unknown() -> None:
    events = parse(text_message_payload(message_type="hologramme"))

    message = events[0]
    assert isinstance(message, InboundWhatsAppMessage)
    assert message.message_type is WhatsAppMessageType.UNKNOWN


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"object": "whatsapp_business_account"},
        {"object": "whatsapp_business_account", "entry": []},
        {"entry": [{}]},
        {"entry": [{"changes": []}]},
        {"entry": [{"changes": [{}]}]},
        {"entry": [{"changes": [{"value": {}}]}]},
        {"entry": [{"changes": [{"value": {"messages": []}}]}]},
        {"entry": "pas-une-liste"},
        {"entry": [{"changes": [{"value": {"messages": ["pas-un-objet"]}}]}]},
        {"entry": [{"changes": [{"value": {"messages": [{"id": "x"}]}}]}]},  # sans « from »
        {"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]},  # sans « status »
        [1, 2, 3],
        "chaine",
        None,
    ],
)
def test_partial_or_irrelevant_payloads_produce_an_unknown_event(payload: Any) -> None:
    """Aucun de ces payloads ne doit lever : ils deviennent des événements inconnus."""
    events = parse_webhook_payload(payload, raw_body=RAW)

    assert len(events) == 1
    assert isinstance(events[0], UnknownWebhookEvent)
    assert events[0].event_type is WebhookEventType.UNKNOWN
    assert events[0].external_id.startswith("sha256:")


def test_unknown_events_dedupe_on_identical_bodies() -> None:
    first = parse_webhook_payload({}, raw_body=b"{}")
    second = parse_webhook_payload({}, raw_body=b"{}")
    third = parse_webhook_payload({}, raw_body=b'{"different": 1}')

    assert first[0].external_id == second[0].external_id
    assert first[0].external_id != third[0].external_id


def test_several_events_in_one_payload() -> None:
    payload = text_message_payload()
    value = payload["entry"][0]["changes"][0]["value"]
    value["messages"].append(
        {"from": SENDER, "id": "wamid.SECOND", "type": "text", "text": {"body": "Deux"}}
    )
    value["statuses"] = [{"id": "wamid.OUT", "status": "sent", "timestamp": "1789075500"}]

    events = parse(payload)

    assert len(events) == 3
    assert sum(isinstance(e, InboundWhatsAppMessage) for e in events) == 2
    assert sum(isinstance(e, WhatsAppStatusEvent) for e in events) == 1


def test_missing_profile_name_is_tolerated() -> None:
    events = parse(text_message_payload(profile_name=None))

    message = events[0]
    assert isinstance(message, InboundWhatsAppMessage)
    assert message.sender_name is None


def test_invalid_timestamp_falls_back_to_now() -> None:
    payload = text_message_payload()
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["timestamp"] = "pas-un-nombre"

    message = parse(payload)[0]

    assert isinstance(message, InboundWhatsAppMessage)
    assert message.timestamp.tzinfo is UTC
