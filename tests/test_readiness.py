from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.conftest import FakeMongoClient


async def test_ready_when_mongodb_is_up(client: AsyncClient) -> None:
    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "services": {"mongodb": "up"}}


async def test_not_ready_when_mongodb_is_down(app: FastAPI) -> None:
    app.state.mongo_client = FakeMongoClient(reachable=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "services": {"mongodb": "down"}}


async def test_readiness_does_not_mention_other_services(client: AsyncClient) -> None:
    """La Phase 0 ne dépend que de MongoDB : rien d'autre ne doit apparaître."""
    services = (await client.get("/ready")).json()["services"]

    assert list(services) == ["mongodb"]
