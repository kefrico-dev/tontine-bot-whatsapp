from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import AppError, ServiceUnavailableError
from app.core.middleware import CORRELATION_ID_HEADER

SECRET_DETAIL = "mongodb://user:tres-secret@cluster.example.net"


class TontineNotFound(AppError):
    status_code = 404
    error_code = "tontine_not_found"
    message = "Tontine introuvable."


def _register_failing_routes(app: FastAPI) -> None:
    async def business_error() -> None:
        raise TontineNotFound

    async def dependency_error() -> None:
        raise ServiceUnavailableError

    async def boom() -> None:
        raise RuntimeError(SECRET_DETAIL)

    app.add_api_route("/_test/business-error", business_error, methods=["GET"])
    app.add_api_route("/_test/dependency-error", dependency_error, methods=["GET"])
    app.add_api_route("/_test/boom", boom, methods=["GET"])


async def test_business_error_is_mapped_to_its_status(app: FastAPI) -> None:
    _register_failing_routes(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/_test/business-error")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "tontine_not_found"
    assert body["message"] == "Tontine introuvable."
    assert body["correlation_id"] == response.headers[CORRELATION_ID_HEADER]


async def test_service_unavailable_error(app: FastAPI) -> None:
    _register_failing_routes(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/_test/dependency-error")

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"


async def test_unhandled_exception_never_leaks_internals(app: FastAPI) -> None:
    _register_failing_routes(app)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/_test/boom")

    assert response.status_code == 500
    body = response.json()
    assert body == {
        "code": "internal_error",
        "message": "Une erreur interne est survenue.",
        "correlation_id": body["correlation_id"],
    }
    assert body["correlation_id"]
    assert SECRET_DETAIL not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text


async def test_unknown_route_uses_the_same_error_shape(client: AsyncClient) -> None:
    response = await client.get("/inconnu")

    assert response.status_code == 404
    assert set(response.json()) == {"code", "message", "correlation_id"}


async def test_validation_error_is_uniform(app: FastAPI) -> None:
    async def with_query(number: int) -> dict[str, int]:
        return {"number": number}

    app.add_api_route("/_test/query", with_query, methods=["GET"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/_test/query", params={"number": "pas-un-entier"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
