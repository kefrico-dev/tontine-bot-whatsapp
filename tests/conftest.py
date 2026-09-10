"""Fixtures de test.

MongoDB n'est pas requis : les tests substituent un client factice, ce qui garde
la suite rapide et la CI simple.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pymongo.errors import ServerSelectionTimeoutError

from app.core.config import Settings
from app.main import create_app


class FakeAdmin:
    def __init__(self, *, reachable: bool) -> None:
        self._reachable = reachable

    async def command(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if not self._reachable:
            raise ServerSelectionTimeoutError("mongodb injoignable (test)")
        return {"ok": 1.0}


class FakeMongoClient:
    """Client MongoDB minimal : seul `admin.command("ping")` est utilisé."""

    def __init__(self, *, reachable: bool = True) -> None:
        self.admin = FakeAdmin(reachable=reachable)

    async def close(self) -> None:
        return None


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="local", log_level="INFO", _env_file=None)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    application = create_app(settings)
    application.state.mongo_client = FakeMongoClient(reachable=True)
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
