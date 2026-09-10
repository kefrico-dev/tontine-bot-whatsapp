"""Endpoints de supervision : liveness et readiness."""

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from app.infrastructure.database.mongodb import MongoClient, ping
from app.schemas.common import HealthResponse, ReadinessResponse

router = APIRouter(tags=["monitoring"])


@router.get("/health", response_model=HealthResponse, summary="Liveness")
async def health() -> HealthResponse:
    """Liveness pure : aucune I/O, aucune dépendance."""
    return HealthResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness",
    responses={503: {"model": ReadinessResponse}},
)
async def ready(request: Request) -> JSONResponse:
    """Readiness : l'application ne se déclare prête que si MongoDB répond."""
    client: MongoClient = request.app.state.mongo_client
    mongodb_up = await ping(client)

    payload = ReadinessResponse(
        status="ready" if mongodb_up else "not_ready",
        services={"mongodb": "up" if mongodb_up else "down"},
    )
    return JSONResponse(
        status_code=200 if mongodb_up else 503,
        content=payload.model_dump(),
    )
