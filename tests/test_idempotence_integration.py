"""Idempotence prouvée contre une vraie instance MongoDB.

Les tests unitaires vérifient que le service réagit correctement à un doublon ;
ceux-ci vérifient que la base l'empêche réellement, y compris sur deux
livraisons concurrentes. Ils se sautent si aucune base n'est joignable, la CI
n'a donc besoin d'aucun service.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.infrastructure.database.indexes import ensure_indexes
from app.infrastructure.database.mongodb import create_mongo_client, ping
from app.infrastructure.whatsapp.parser import parse_webhook_payload
from app.modules.messaging.repository import MESSAGES, WEBHOOK_EVENTS, MessagingRepository
from app.modules.messaging.schemas import WebhookEventStatus, WebhookEventType
from app.modules.messaging.service import MessagingService
from tests.factories import (
    WAMID,
    FakeWhatsAppClient,
    StaticReplyComposer,
    encode,
    text_message_payload,
)

pytestmark = pytest.mark.integration

TEST_DATABASE = "kefrico_tontine_test"


@pytest.fixture
async def database() -> AsyncIterator[AsyncDatabase[dict[str, Any]]]:
    # .env est volontairement lu ici : il porte l'URI de la base de travail.
    settings = Settings().model_copy(
        update={"mongodb_database": TEST_DATABASE, "mongodb_timeout_ms": 15000}
    )
    client = create_mongo_client(settings)
    if not await ping(client):
        await client.close()
        pytest.skip("aucune instance MongoDB joignable — test d'intégration ignoré")

    db = client[TEST_DATABASE]
    await db[WEBHOOK_EVENTS].delete_many({})
    await db[MESSAGES].delete_many({})
    await ensure_indexes(db)
    try:
        yield db
    finally:
        await client.drop_database(TEST_DATABASE)
        await client.close()


async def test_unique_indexes_exist(database: AsyncDatabase[dict[str, Any]]) -> None:
    events_indexes = await database[WEBHOOK_EVENTS].index_information()
    messages_indexes = await database[MESSAGES].index_information()

    assert events_indexes["uniq_webhook_event_external_id"]["unique"] is True
    assert messages_indexes["uniq_message_external_id"]["unique"] is True


async def test_ensure_indexes_is_idempotent(database: AsyncDatabase[dict[str, Any]]) -> None:
    """Un redémarrage de l'application ne doit rien casser."""
    await ensure_indexes(database)
    await ensure_indexes(database)

    assert "uniq_webhook_event_external_id" in await database[WEBHOOK_EVENTS].index_information()


async def test_second_claim_is_refused_by_mongodb(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    repository = MessagingRepository(database)

    first = await repository.claim_event(
        external_id=WAMID,
        event_type=WebhookEventType.INBOUND_MESSAGE,
        message_type=None,
        correlation_id="c1",
    )
    second = await repository.claim_event(
        external_id=WAMID,
        event_type=WebhookEventType.INBOUND_MESSAGE,
        message_type=None,
        correlation_id="c2",
    )

    assert first is True
    assert second is False
    assert await database[WEBHOOK_EVENTS].count_documents({"external_id": WAMID}) == 1


async def test_concurrent_deliveries_reply_once(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    """Deux livraisons simultanées : une seule doit passer le verrou."""
    client = FakeWhatsAppClient()
    payload = text_message_payload()
    events = parse_webhook_payload(payload, raw_body=encode(payload))

    async def deliver(correlation_id: str) -> Any:
        service = MessagingService(MessagingRepository(database), client, StaticReplyComposer())  # type: ignore[arg-type]
        return await service.handle_events(events, correlation_id=correlation_id)

    first, second = await asyncio.gather(deliver("c1"), deliver("c2"))

    assert first.received + second.received == 1, "un seul traitement"
    assert first.duplicates + second.duplicates == 1, "un seul doublon détecté"
    assert len(client.sent) == 1, "une seule réponse WhatsApp"
    assert await database[WEBHOOK_EVENTS].count_documents({"external_id": WAMID}) == 1
    assert await database[MESSAGES].count_documents({"external_message_id": WAMID}) == 1, (
        "message entrant enregistré une seule fois"
    )


async def test_full_cycle_writes_both_directions(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    client = FakeWhatsAppClient()
    payload = text_message_payload()
    events = parse_webhook_payload(payload, raw_body=encode(payload))
    service = MessagingService(
        MessagingRepository(database),
        client,  # type: ignore[arg-type]
        StaticReplyComposer(),
        business_phone="15556762623",
    )

    await service.handle_events(events, correlation_id="c1")

    event = await database[WEBHOOK_EVENTS].find_one({"external_id": WAMID})
    assert event is not None
    assert event["status"] == WebhookEventStatus.REPLIED.value
    assert event["processed_at"] is not None
    assert event["correlation_id"] == "c1"

    inbound = await database[MESSAGES].find_one({"direction": "INBOUND"})
    outbound = await database[MESSAGES].find_one({"direction": "OUTBOUND"})
    assert inbound is not None and inbound["text"] == "Bonjour"
    assert outbound is not None and outbound["recipient"] == inbound["sender"]

    # Aucun payload Meta brut ne doit avoir été stocké.
    assert "raw" not in event
    assert "internal_1p_only_data" not in str(event)
