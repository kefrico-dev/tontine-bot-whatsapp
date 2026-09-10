from httpx import AsyncClient

from app.core.middleware import CORRELATION_ID_HEADER


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_sets_a_correlation_id(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.headers[CORRELATION_ID_HEADER]


async def test_health_reuses_incoming_correlation_id(client: AsyncClient) -> None:
    response = await client.get("/health", headers={CORRELATION_ID_HEADER: "abc-123"})

    assert response.headers[CORRELATION_ID_HEADER] == "abc-123"
