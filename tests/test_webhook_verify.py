"""GET /webhooks/whatsapp — vérification du webhook Meta."""

import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from tests.factories import VERIFY_TOKEN

PATH = "/webhooks/whatsapp"


async def test_valid_challenge_is_returned_verbatim(whatsapp_http: AsyncClient) -> None:
    response = await whatsapp_http.get(
        PATH,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "1158201444",
        },
    )

    assert response.status_code == 200
    # Meta attend le challenge nu, pas du JSON.
    assert response.text == "1158201444"
    assert response.headers["content-type"].startswith("text/plain")


async def test_wrong_verify_token_is_refused(whatsapp_http: AsyncClient) -> None:
    response = await whatsapp_http.get(
        PATH,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "mauvais-token",
            "hub.challenge": "1158201444",
        },
    )

    assert response.status_code == 403
    assert "1158201444" not in response.text


async def test_wrong_mode_is_refused(whatsapp_http: AsyncClient) -> None:
    response = await whatsapp_http.get(
        PATH,
        params={
            "hub.mode": "unsubscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "1158201444",
        },
    )

    assert response.status_code == 403


async def test_missing_parameters_are_refused(whatsapp_http: AsyncClient) -> None:
    response = await whatsapp_http.get(PATH)

    assert response.status_code == 403


async def test_missing_challenge_is_refused(whatsapp_http: AsyncClient) -> None:
    response = await whatsapp_http.get(
        PATH,
        params={"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN},
    )

    assert response.status_code == 403


async def test_unconfigured_service_never_returns_the_challenge() -> None:
    """Sans META_VERIFY_TOKEN, l'échec doit être franc — jamais un faux succès."""
    app: FastAPI = create_app(Settings(environment="local", _env_file=None))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            PATH,
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "",
                "hub.challenge": "1158201444",
            },
        )

    assert response.status_code == 503
    assert response.json()["code"] == "whatsapp_not_configured"


async def test_verify_token_never_reaches_the_logs(
    whatsapp_http: AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-régression : le log d'accès d'uvicorn imprimait la query string entière."""
    await whatsapp_http.get(
        PATH,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "1158201444",
        },
    )

    captured = capsys.readouterr()
    assert VERIFY_TOKEN not in captured.out + captured.err
    assert logging.getLogger("uvicorn.access").disabled is True
