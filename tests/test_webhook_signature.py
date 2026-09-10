"""POST /webhooks/whatsapp — validation de la signature Meta."""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.infrastructure.whatsapp.security import compute_signature, verify_signature
from app.main import create_app
from tests.factories import (
    APP_SECRET,
    FakeMessagingRepository,
    encode,
    signed_headers,
    text_message_payload,
)

PATH = "/webhooks/whatsapp"


async def test_valid_signature_is_accepted(
    whatsapp_http: AsyncClient, repository: FakeMessagingRepository
) -> None:
    body = encode(text_message_payload())

    response = await whatsapp_http.post(PATH, content=body, headers=signed_headers(body))

    assert response.status_code == 200
    assert len(repository.events) == 1


async def test_invalid_signature_is_refused(
    whatsapp_http: AsyncClient, repository: FakeMessagingRepository
) -> None:
    body = encode(text_message_payload())
    headers = {"X-Hub-Signature-256": "sha256=" + "0" * 64}

    response = await whatsapp_http.post(PATH, content=body, headers=headers)

    assert response.status_code == 403
    assert response.json()["code"] == "invalid_signature"
    # Aucune écriture ne doit avoir eu lieu avant la validation.
    assert repository.events == {}


async def test_missing_signature_is_refused(
    whatsapp_http: AsyncClient, repository: FakeMessagingRepository
) -> None:
    body = encode(text_message_payload())

    response = await whatsapp_http.post(
        PATH, content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 403
    assert repository.events == {}


async def test_signature_of_another_secret_is_refused(whatsapp_http: AsyncClient) -> None:
    body = encode(text_message_payload())
    headers = {"X-Hub-Signature-256": compute_signature(secret="autre-secret", payload=body)}

    response = await whatsapp_http.post(PATH, content=body, headers=headers)

    assert response.status_code == 403


async def test_one_altered_byte_invalidates_the_signature(whatsapp_http: AsyncClient) -> None:
    """La signature porte sur le corps brut : un octet modifié doit la casser."""
    body = encode(text_message_payload())
    headers = signed_headers(body)
    altered = body.replace(b"Bonjour", b"BonjouR")
    assert len(altered) == len(body)

    response = await whatsapp_http.post(PATH, content=altered, headers=headers)

    assert response.status_code == 403


async def test_malformed_json_with_valid_signature_returns_400(
    whatsapp_http: AsyncClient, repository: FakeMessagingRepository
) -> None:
    body = b'{"object": "whatsapp_business_account", '

    response = await whatsapp_http.post(PATH, content=body, headers=signed_headers(body))

    assert response.status_code == 400
    assert response.json()["code"] == "malformed_payload"
    assert repository.events == {}


async def test_unconfigured_secret_returns_503() -> None:
    app: FastAPI = create_app(Settings(environment="local", _env_file=None))
    app.state.indexes_ready = True
    body = encode(text_message_payload())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(PATH, content=body, headers=signed_headers(body))

    assert response.status_code == 503
    assert response.json()["code"] == "whatsapp_not_configured"


async def test_webhook_refuses_to_process_without_indexes(
    whatsapp_app: FastAPI, repository: FakeMessagingRepository
) -> None:
    """Sans index unique il n'y a pas d'idempotence : refuser vaut mieux que doubler."""
    whatsapp_app.state.indexes_ready = False
    body = encode(text_message_payload())

    transport = ASGITransport(app=whatsapp_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(PATH, content=body, headers=signed_headers(body))

    assert response.status_code == 503
    assert response.json()["code"] == "webhook_not_ready"
    assert repository.events == {}


def test_verify_signature_is_case_and_prefix_sensitive() -> None:
    body = b'{"a": 1}'
    valid = compute_signature(secret=APP_SECRET, payload=body)

    assert verify_signature(secret=APP_SECRET, payload=body, header=valid) is True
    assert verify_signature(secret=APP_SECRET, payload=body, header=None) is False
    assert verify_signature(secret=APP_SECRET, payload=body, header="") is False
    # Sans le préfixe « sha256= », Meta n'enverrait pas ce format : refus.
    assert (
        verify_signature(secret=APP_SECRET, payload=body, header=valid.removeprefix("sha256="))
        is False
    )
