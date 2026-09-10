"""Webhook WhatsApp — couche HTTP uniquement.

Cette route valide, délègue, et traduit le résultat en code HTTP. Aucune
logique métier n'y figure.
"""

import json
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import JSONResponse, PlainTextResponse

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.middleware import get_correlation_id
from app.infrastructure.whatsapp.exceptions import (
    InvalidWebhookSignature,
    MalformedWebhookPayload,
    WebhookNotReady,
    WhatsAppNotConfigured,
)
from app.infrastructure.whatsapp.parser import parse_webhook_payload
from app.infrastructure.whatsapp.security import (
    SIGNATURE_HEADER,
    verify_signature,
    verify_token_matches,
)
from app.modules.messaging.repository import MessagingRepository
from app.modules.messaging.service import MessagingService

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def get_settings_from_state(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_messaging_service(request: Request) -> MessagingService:
    """Assemble le service à partir des ressources partagées de l'application."""
    settings: Settings = request.app.state.settings
    database = request.app.state.mongo_client[settings.mongodb_database]
    return MessagingService(
        MessagingRepository(database),
        request.app.state.whatsapp_client,
        business_phone=settings.whatsapp_phone_number_id,
    )


@router.get("/whatsapp", summary="Vérification du webhook Meta")
async def verify_webhook(
    settings: Annotated[Settings, Depends(get_settings_from_state)],
    hub_mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    hub_verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    hub_challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> PlainTextResponse:
    """Renvoie le challenge de Meta si le verify token correspond.

    Le token n'est jamais logué, ni en cas de succès ni en cas d'échec.
    """
    expected = settings.meta_verify_token
    if not expected:
        raise WhatsAppNotConfigured

    valid = hub_mode == "subscribe" and verify_token_matches(
        provided=hub_verify_token, expected=expected
    )
    if not valid or not hub_challenge:
        logger.warning("webhook_verification_refused", mode=hub_mode)
        return PlainTextResponse("Forbidden", status_code=403)

    logger.info("webhook_verification_ok")
    return PlainTextResponse(hub_challenge, status_code=200)


@router.post("/whatsapp", summary="Réception des événements Meta")
async def receive_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings_from_state)],
    service: Annotated[MessagingService, Depends(get_messaging_service)],
) -> JSONResponse:
    """Reçoit un événement Meta, le trace, y répond si c'est un texte nouveau."""
    started = time.perf_counter()

    secret = settings.meta_app_secret
    if not secret:
        raise WhatsAppNotConfigured

    # Sans index unique, l'idempotence n'est pas garantie : mieux vaut refuser
    # et laisser Meta rejouer que traiter deux fois le même message.
    if not getattr(request.app.state, "indexes_ready", False):
        raise WebhookNotReady

    # 1. Corps BRUT : la signature porte sur ces octets exacts.
    raw_body = await request.body()

    # 2. Signature, avant toute interprétation du contenu.
    if not verify_signature(
        secret=secret, payload=raw_body, header=request.headers.get(SIGNATURE_HEADER)
    ):
        logger.warning("webhook_signature_refused", body_bytes=len(raw_body))
        raise InvalidWebhookSignature

    # 3. Décodage seulement maintenant.
    try:
        payload: Any = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("webhook_payload_malformed", error=type(exc).__name__)
        raise MalformedWebhookPayload from exc

    # 4. Normalisation puis traitement.
    events = parse_webhook_payload(payload, raw_body=raw_body)
    result = await service.handle_events(events, correlation_id=get_correlation_id(request))

    logger.info(
        "webhook_processed",
        events=len(events),
        received=result.received,
        duplicates=result.duplicates,
        replied=result.replied,
        reply_failed=result.reply_failed,
        ignored=result.ignored,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return JSONResponse(status_code=200, content={"status": "received"})
