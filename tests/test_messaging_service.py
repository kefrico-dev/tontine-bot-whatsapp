"""Service de messagerie : idempotence, statuts, échec d'envoi."""

from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from app.infrastructure.whatsapp.exceptions import (
    WhatsAppApiError,
    WhatsAppNotConfigured,
    WhatsAppTransportError,
)
from app.infrastructure.whatsapp.parser import parse_webhook_payload
from app.modules.messaging.repository import MessagingRepository
from app.modules.messaging.schemas import ParsedEvent, WebhookEventStatus, WebhookEventType
from app.modules.messaging.service import MessagingService

#: La Phase 2 remplace la constante par un composeur : on fige le texte ici.
WELCOME_MESSAGE = "Bienvenue sur KEFRICO Tontine"

from tests.factories import (  # noqa: E402
    SENDER,
    WAMID,
    FakeMessagingRepository,
    FakeWhatsAppClient,
    StaticReplyComposer,
    encode,
    status_payload,
    text_message_payload,
)


def events_of(payload: dict[str, Any]) -> list[ParsedEvent]:
    return parse_webhook_payload(payload, raw_body=encode(payload))


def build(repository: FakeMessagingRepository, client: FakeWhatsAppClient) -> MessagingService:
    return MessagingService(
        repository,
        client,  # type: ignore[arg-type]
        StaticReplyComposer(WELCOME_MESSAGE),
        business_phone="100000000000001",
    )


async def test_text_message_is_stored_and_answered() -> None:
    repository, client = FakeMessagingRepository(), FakeWhatsAppClient()
    service = build(repository, client)

    result = await service.handle_events(events_of(text_message_payload()), correlation_id="c1")

    assert result.received == 1
    assert result.replied == 1
    assert len(repository.inbound) == 1
    assert len(repository.outbound) == 1
    assert client.sent == [(SENDER, WELCOME_MESSAGE)]
    assert repository.status_of(WAMID) is WebhookEventStatus.REPLIED


async def test_duplicate_delivery_stores_and_answers_once() -> None:
    """Le scénario obligatoire : webhook A, puis webhook A à nouveau."""
    repository, client = FakeMessagingRepository(), FakeWhatsAppClient()
    service = build(repository, client)
    events = events_of(text_message_payload())

    first = await service.handle_events(events, correlation_id="c1")
    second = await service.handle_events(events, correlation_id="c2")

    assert first.replied == 1
    assert second.duplicates == 1
    assert second.replied == 0
    assert len(repository.inbound) == 1, "message entrant enregistré une seule fois"
    assert len(client.sent) == 1, "une seule réponse WhatsApp"
    assert repository.status_of(WAMID) is WebhookEventStatus.REPLIED


async def test_status_events_are_ignored_not_answered() -> None:
    repository, client = FakeMessagingRepository(), FakeWhatsAppClient()
    service = build(repository, client)

    result = await service.handle_events(events_of(status_payload()), correlation_id="c1")

    assert result.ignored == 1
    assert result.replied == 0
    assert client.sent == []
    assert repository.status_of(f"{WAMID}:delivered") is WebhookEventStatus.IGNORED


async def test_unsupported_type_is_ignored_without_error() -> None:
    repository, client = FakeMessagingRepository(), FakeWhatsAppClient()
    service = build(repository, client)

    result = await service.handle_events(
        events_of(text_message_payload(message_type="image")), correlation_id="c1"
    )

    assert result.ignored == 1
    assert client.sent == []
    assert repository.inbound == []


async def test_unknown_payload_is_traced_and_ignored() -> None:
    repository, client = FakeMessagingRepository(), FakeWhatsAppClient()
    service = build(repository, client)

    result = await service.handle_events(events_of({"object": "x"}), correlation_id="c1")

    assert result.ignored == 1
    assert client.sent == []
    key = next(iter(repository.events))
    assert repository.events[key]["event_type"] is WebhookEventType.UNKNOWN


@pytest.mark.parametrize(
    "error",
    [
        WhatsAppApiError(status_code=400, meta_code=131030),
        WhatsAppApiError(status_code=401, meta_code=190),
        WhatsAppApiError(status_code=429, meta_code=80007),
        WhatsAppApiError(status_code=500, meta_code=1),
        WhatsAppTransportError("ReadTimeout"),
        WhatsAppNotConfigured(),
    ],
)
async def test_outbound_failure_keeps_the_inbound_message(error: Exception) -> None:
    """Le message entrant reste enregistré ; l'événement passe en REPLY_FAILED."""
    repository, client = FakeMessagingRepository(), FakeWhatsAppClient(error=error)
    service = build(repository, client)

    result = await service.handle_events(events_of(text_message_payload()), correlation_id="c1")

    assert result.reply_failed == 1
    assert result.replied == 0
    assert len(repository.inbound) == 1, "l'entrant ne doit pas être perdu"
    assert repository.outbound == []
    assert repository.status_of(WAMID) is WebhookEventStatus.REPLY_FAILED
    assert repository.events[WAMID]["error"] is not None


async def test_a_retry_after_outbound_failure_does_not_reprocess_the_inbound() -> None:
    """Meta rejoue après un échec d'envoi : aucun retraitement, aucun doublon."""
    repository = FakeMessagingRepository()
    failing = FakeWhatsAppClient(error=WhatsAppTransportError("ReadTimeout"))
    events = events_of(text_message_payload())

    await build(repository, failing).handle_events(events, correlation_id="c1")
    second = await build(repository, FakeWhatsAppClient()).handle_events(
        events, correlation_id="c2"
    )

    assert second.duplicates == 1
    assert len(repository.inbound) == 1
    # L'événement reste en REPLY_FAILED : c'est lui que la reprise ciblera.
    assert repository.status_of(WAMID) is WebhookEventStatus.REPLY_FAILED


# --- Repository : traduction réelle de DuplicateKeyError ----------------------


class RaisingCollection:
    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.inserted: list[dict[str, Any]] = []

    async def insert_one(self, document: dict[str, Any]) -> None:
        if self.error is not None:
            raise self.error
        self.inserted.append(document)

    async def update_one(self, *args: Any, **kwargs: Any) -> None:
        return None


class FakeDatabase:
    def __init__(self, error: Exception | None = None) -> None:
        self.collections: dict[str, RaisingCollection] = {}
        self._error = error

    def __getitem__(self, name: str) -> RaisingCollection:
        return self.collections.setdefault(name, RaisingCollection(self._error))


async def test_repository_translates_duplicate_key_error_into_false() -> None:
    database = FakeDatabase(DuplicateKeyError("index unique violé"))
    repository = MessagingRepository(database)  # type: ignore[arg-type]

    claimed = await repository.claim_event(
        external_id=WAMID,
        event_type=WebhookEventType.INBOUND_MESSAGE,
        message_type=None,
        correlation_id="c1",
    )

    assert claimed is False


async def test_repository_claims_a_new_event() -> None:
    database = FakeDatabase()
    repository = MessagingRepository(database)  # type: ignore[arg-type]

    claimed = await repository.claim_event(
        external_id=WAMID,
        event_type=WebhookEventType.INBOUND_MESSAGE,
        message_type=None,
        correlation_id="c1",
    )

    assert claimed is True
    document = database["webhook_events"].inserted[0]
    assert document["external_id"] == WAMID
    assert document["status"] == WebhookEventStatus.RECEIVED.value
    assert document["processed_at"] is None
