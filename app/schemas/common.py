"""Schémas partagés."""

from typing import Literal

from pydantic import BaseModel

ServiceStatus = Literal["up", "down"]


class HealthResponse(BaseModel):
    """Liveness : le processus répond."""

    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    """Readiness : l'application peut réellement servir du trafic."""

    status: Literal["ready", "not_ready"]
    services: dict[str, ServiceStatus]


class ErrorResponse(BaseModel):
    """Réponse d'erreur : aucun détail interne n'est exposé."""

    code: str
    message: str
    correlation_id: str | None = None
