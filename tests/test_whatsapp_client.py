"""Client sortant Meta : succès, erreurs API, erreurs réseau."""

import json
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.infrastructure.whatsapp.client import WhatsAppClient
from app.infrastructure.whatsapp.exceptions import (
    WhatsAppApiError,
    WhatsAppNotConfigured,
    WhatsAppTransportError,
)
from tests.factories import PHONE_NUMBER_ID, SENDER

ACCESS_TOKEN = "EAA-jeton-de-test-tres-secret"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "local",
        "meta_verify_token": "v",
        "meta_app_secret": "s",
        "whatsapp_access_token": ACCESS_TOKEN,
        "whatsapp_phone_number_id": PHONE_NUMBER_ID,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def client_with(handler: Any, settings: Settings | None = None) -> WhatsAppClient:
    settings = settings or make_settings()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WhatsAppClient(settings, http)


def ok_handler(captured: dict[str, Any]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": SENDER, "wa_id": SENDER}],
                "messages": [{"id": "wamid.OUTBOUND1"}],
            },
        )

    return handler


async def test_successful_send_returns_the_meta_message_id() -> None:
    captured: dict[str, Any] = {}
    client = client_with(ok_handler(captured))

    sent = await client.send_text_message(to=SENDER, text="Bienvenue")

    assert sent.external_message_id == "wamid.OUTBOUND1"
    assert sent.recipient == SENDER


async def test_url_is_built_from_the_configured_api_version() -> None:
    captured: dict[str, Any] = {}
    client = client_with(ok_handler(captured), make_settings(whatsapp_api_version="v99.0"))

    await client.send_text_message(to=SENDER, text="Bienvenue")

    assert captured["url"] == f"https://graph.facebook.com/v99.0/{PHONE_NUMBER_ID}/messages"


async def test_default_api_version_is_v25() -> None:
    assert make_settings().whatsapp_api_version == "v25.0"
    assert "/v25.0/" in make_settings().whatsapp_messages_url


async def test_request_shape_matches_the_cloud_api() -> None:
    captured: dict[str, Any] = {}
    client = client_with(ok_handler(captured))

    await client.send_text_message(to=SENDER, text="Bienvenue")

    assert captured["headers"]["authorization"] == f"Bearer {ACCESS_TOKEN}"
    body = json.loads(captured["json"])
    assert body["messaging_product"] == "whatsapp"
    assert body["type"] == "text"
    assert body["to"] == SENDER
    assert body["text"]["body"] == "Bienvenue"


@pytest.mark.parametrize(
    ("status_code", "meta_code"),
    [(400, 131030), (401, 190), (403, 200), (429, 80007), (500, 1), (503, 2)],
)
async def test_meta_errors_are_raised_with_their_code(status_code: int, meta_code: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": {"message": "Erreur Meta", "code": meta_code, "type": "OAuthException"}},
        )

    client = client_with(handler)

    with pytest.raises(WhatsAppApiError) as raised:
        await client.send_text_message(to=SENDER, text="Bienvenue")

    assert raised.value.status_code == status_code
    assert raised.value.meta_code == meta_code
    assert raised.value.is_retryable is (status_code == 429 or status_code >= 500)


async def test_non_json_error_body_is_survived() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>Bad Gateway</html>")

    client = client_with(handler)

    with pytest.raises(WhatsAppApiError) as raised:
        await client.send_text_message(to=SENDER, text="Bienvenue")

    assert raised.value.status_code == 502
    assert raised.value.meta_code is None


async def test_timeout_becomes_a_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("délai dépassé", request=request)

    client = client_with(handler)

    with pytest.raises(WhatsAppTransportError) as raised:
        await client.send_text_message(to=SENDER, text="Bienvenue")

    assert raised.value.cause == "ReadTimeout"
    assert raised.value.is_retryable is True


async def test_network_error_becomes_a_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion impossible", request=request)

    client = client_with(handler)

    with pytest.raises(WhatsAppTransportError) as raised:
        await client.send_text_message(to=SENDER, text="Bienvenue")

    assert raised.value.cause == "ConnectError"


async def test_2xx_without_message_id_is_treated_as_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messaging_product": "whatsapp"})

    client = client_with(handler)

    with pytest.raises(WhatsAppApiError):
        await client.send_text_message(to=SENDER, text="Bienvenue")


async def test_missing_configuration_raises_before_any_call() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal called
        called = True
        return httpx.Response(200, json={"messages": [{"id": "x"}]})

    client = client_with(handler, make_settings(whatsapp_access_token=None))

    with pytest.raises(WhatsAppNotConfigured):
        await client.send_text_message(to=SENDER, text="Bienvenue")

    assert called is False


async def test_the_token_never_reaches_the_logs(capsys: pytest.CaptureFixture[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid token", "code": 190}})

    client = client_with(handler)

    with pytest.raises(WhatsAppApiError):
        await client.send_text_message(to=SENDER, text="Bienvenue")

    output = capsys.readouterr()
    assert ACCESS_TOKEN not in output.out + output.err
    assert "Bearer" not in output.out + output.err
