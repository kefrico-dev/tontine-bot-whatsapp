"""Parcours complet du webhook, de la requête HTTP à la réponse WhatsApp."""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.webhooks.whatsapp import get_messaging_service
from app.core.middleware import CORRELATION_ID_HEADER
from app.infrastructure.whatsapp.exceptions import WhatsAppTransportError
from app.modules.messaging.schemas import (
    MessageDirection,
    WebhookEventStatus,
    WhatsAppMessageType,
)
from app.modules.messaging.service import MessagingService
from tests.factories import (
    SENDER,
    WAMID,
    FakeMessagingRepository,
    FakeWhatsAppClient,
    StaticReplyComposer,
    encode,
    signed_headers,
    status_payload,
    text_message_payload,
)

PATH = "/webhooks/whatsapp"


async def test_complete_flow_stores_and_replies(
    whatsapp_http: AsyncClient,
    repository: FakeMessagingRepository,
    whatsapp_client: FakeWhatsAppClient,
    reply_composer: StaticReplyComposer,
) -> None:
    body = encode(text_message_payload())

    response = await whatsapp_http.post(PATH, content=body, headers=signed_headers(body))

    assert response.status_code == 200
    assert response.json() == {"status": "received"}

    # message entrant enregistré
    assert len(repository.inbound) == 1
    stored = repository.inbound[0]
    assert stored.external_message_id == WAMID
    assert stored.sender_phone == SENDER
    assert stored.text == "Bonjour"
    assert stored.message_type is WhatsAppMessageType.TEXT

    # réponse envoyée : celle produite par le composeur, quel qu'il soit
    assert whatsapp_client.sent == [(SENDER, reply_composer.reply)]

    # message sortant enregistré
    assert len(repository.outbound) == 1
    assert repository.outbound[0].recipient == SENDER

    # événement clos
    assert repository.status_of(WAMID) is WebhookEventStatus.REPLIED


async def test_duplicate_delivery_over_http_replies_only_once(
    whatsapp_http: AsyncClient,
    repository: FakeMessagingRepository,
    whatsapp_client: FakeWhatsAppClient,
) -> None:
    body = encode(text_message_payload())
    headers = signed_headers(body)

    first = await whatsapp_http.post(PATH, content=body, headers=headers)
    second = await whatsapp_http.post(PATH, content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200, "un doublon s'acquitte, il ne provoque pas de 500"
    assert len(repository.inbound) == 1
    assert len(whatsapp_client.sent) == 1


async def test_status_event_returns_200_without_reply(
    whatsapp_http: AsyncClient, whatsapp_client: FakeWhatsAppClient
) -> None:
    body = encode(status_payload())

    response = await whatsapp_http.post(PATH, content=body, headers=signed_headers(body))

    assert response.status_code == 200
    assert whatsapp_client.sent == []


async def test_irrelevant_payload_returns_200_without_error(
    whatsapp_http: AsyncClient, whatsapp_client: FakeWhatsAppClient
) -> None:
    body = encode({"object": "whatsapp_business_account", "entry": [{"changes": [{}]}]})

    response = await whatsapp_http.post(PATH, content=body, headers=signed_headers(body))

    assert response.status_code == 200
    assert whatsapp_client.sent == []


async def test_outbound_failure_still_acknowledges_meta(
    whatsapp_app: FastAPI, repository: FakeMessagingRepository
) -> None:
    """Rejouer le webhook ne réparerait pas l'envoi : on acquitte quand même."""
    failing = FakeWhatsAppClient(error=WhatsAppTransportError("ReadTimeout"))
    service = MessagingService(repository, failing, StaticReplyComposer())  # type: ignore[arg-type]
    whatsapp_app.dependency_overrides[get_messaging_service] = lambda: service

    body = encode(text_message_payload())
    transport = ASGITransport(app=whatsapp_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(PATH, content=body, headers=signed_headers(body))

    assert response.status_code == 200
    assert len(repository.inbound) == 1
    assert repository.status_of(WAMID) is WebhookEventStatus.REPLY_FAILED


async def test_correlation_id_is_propagated(whatsapp_http: AsyncClient) -> None:
    body = encode(text_message_payload())
    headers = signed_headers(body) | {CORRELATION_ID_HEADER: "corr-webhook-1"}

    response = await whatsapp_http.post(PATH, content=body, headers=headers)

    assert response.headers[CORRELATION_ID_HEADER] == "corr-webhook-1"


async def test_directions_are_distinct(
    whatsapp_http: AsyncClient, repository: FakeMessagingRepository
) -> None:
    body = encode(text_message_payload())
    await whatsapp_http.post(PATH, content=body, headers=signed_headers(body))

    assert MessageDirection.INBOUND != MessageDirection.OUTBOUND
    assert len(repository.inbound) == 1
    assert len(repository.outbound) == 1
