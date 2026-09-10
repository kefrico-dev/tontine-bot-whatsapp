"""Test d'intégration sur une vraie instance MongoDB.

Il s'exécute si la configuration locale (.env) pointe vers une base joignable —
MongoDB Atlas ou le conteneur du docker-compose — et se saute sinon. La CI n'a
donc besoin d'aucun service.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.infrastructure.database.mongodb import create_mongo_client, ping
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
async def live_settings() -> Settings:
    # Connexion à froid : la résolution SRV d'Atlas peut dépasser le timeout
    # par défaut, on laisse plus de marge au test d'intégration.
    settings = Settings().model_copy(update={"mongodb_timeout_ms": 15000})
    client = create_mongo_client(settings)
    try:
        if not await ping(client):
            pytest.skip("aucune instance MongoDB joignable — test d'intégration ignoré")
    finally:
        await client.close()
    return settings


async def test_ping_reaches_a_real_server(live_settings: Settings) -> None:
    client = create_mongo_client(live_settings)
    try:
        assert await ping(client) is True
    finally:
        await client.close()


async def test_ready_reports_up_against_a_real_server(live_settings: Settings) -> None:
    app: FastAPI = create_app(live_settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/ready")

    await app.state.mongo_client.close()

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "services": {"mongodb": "up"}}
