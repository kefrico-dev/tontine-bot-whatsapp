"""Traitement métier des événements WhatsApp.

Phase 1 : aucun routage d'intention, aucune logique tontine. Tout message
texte entrant et nouveau reçoit la même réponse d'accueil.
"""

from app.core.logging import get_logger, mask_phone
from app.infrastructure.whatsapp.client import WhatsAppClient
from app.infrastructure.whatsapp.exceptions import (
    WhatsAppApiError,
    WhatsAppError,
    WhatsAppNotConfigured,
)
from app.modules.messaging.repository import MessagingRepository
from app.modules.messaging.schemas import (
    InboundWhatsAppMessage,
    ParsedEvent,
    ProcessingResult,
    WebhookEventStatus,
    WhatsAppMessageType,
)

logger = get_logger(__name__)

WELCOME_MESSAGE = (
    "Bienvenue sur KEFRICO Tontine 👋\n\n"
    "Je suis votre assistant pour gérer vos tontines directement depuis WhatsApp."
)


class MessagingService:
    """Orchestre idempotence, persistance et réponse."""

    def __init__(
        self,
        repository: MessagingRepository,
        whatsapp_client: WhatsAppClient,
        *,
        business_phone: str | None = None,
    ) -> None:
        self._repository = repository
        self._whatsapp = whatsapp_client
        self._business_phone = business_phone

    async def handle_events(
        self, events: list[ParsedEvent], *, correlation_id: str | None
    ) -> ProcessingResult:
        result = ProcessingResult()
        for event in events:
            await self._handle_event(event, result=result, correlation_id=correlation_id)
        return result

    async def _handle_event(
        self,
        event: ParsedEvent,
        *,
        result: ProcessingResult,
        correlation_id: str | None,
    ) -> None:
        message_type = event.message_type if isinstance(event, InboundWhatsAppMessage) else None

        # Verrou d'idempotence : posé AVANT tout traitement et surtout avant
        # l'appel sortant. Un rejeu de Meta pendant que nous répondons encore
        # est donc absorbé ici, sans second envoi.
        claimed = await self._repository.claim_event(
            external_id=event.external_id,
            event_type=event.event_type,
            message_type=message_type,
            correlation_id=correlation_id,
        )
        if not claimed:
            result.duplicates += 1
            logger.info(
                "webhook_event_duplicate",
                event_type=event.event_type.value,
                external_id=event.external_id,
            )
            return

        result.received += 1

        if not isinstance(event, InboundWhatsAppMessage):
            await self._ignore(event.external_id, reason=event.event_type.value, result=result)
            return

        if event.message_type is not WhatsAppMessageType.TEXT or not event.text:
            # Type reconnu mais non traité en Phase 1 : on trace, on n'échoue pas.
            await self._ignore(
                event.external_id,
                reason=f"unsupported_type:{event.message_type.value}",
                result=result,
            )
            return

        await self._handle_text_message(event, result=result, correlation_id=correlation_id)

    async def _ignore(self, external_id: str, *, reason: str, result: ProcessingResult) -> None:
        await self._repository.mark_event(
            external_id=external_id,
            status=WebhookEventStatus.IGNORED,
            error=None,
        )
        result.ignored += 1
        logger.info("webhook_event_ignored", external_id=external_id, reason=reason)

    async def _handle_text_message(
        self,
        message: InboundWhatsAppMessage,
        *,
        result: ProcessingResult,
        correlation_id: str | None,
    ) -> None:
        await self._repository.store_inbound_message(
            message,
            recipient=self._business_phone,
            correlation_id=correlation_id,
        )

        try:
            sent = await self._whatsapp.send_text_message(
                to=message.sender_phone, text=WELCOME_MESSAGE
            )
        except (WhatsAppError, WhatsAppNotConfigured) as exc:
            # Le message entrant est enregistré ; seul l'envoi a échoué.
            # L'événement reste en REPLY_FAILED : une reprise ultérieure pourra
            # renvoyer la réponse sans retraiter l'entrant.
            await self._repository.mark_event(
                external_id=message.external_id,
                status=WebhookEventStatus.REPLY_FAILED,
                error=_error_label(exc),
            )
            result.reply_failed += 1
            logger.warning(
                "whatsapp_reply_failed",
                message_id=message.external_message_id,
                sender=mask_phone(message.sender_phone),
                error=_error_label(exc),
            )
            return

        await self._repository.store_outbound_message(
            sent,
            text=WELCOME_MESSAGE,
            sender=self._business_phone,
            correlation_id=correlation_id,
        )
        await self._repository.mark_event(
            external_id=message.external_id,
            status=WebhookEventStatus.REPLIED,
        )
        result.replied += 1
        logger.info(
            "whatsapp_replied",
            message_id=message.external_message_id,
            reply_id=sent.external_message_id,
            sender=mask_phone(message.sender_phone),
        )


def _error_label(exc: Exception) -> str:
    """Étiquette d'erreur courte et non sensible, destinée au stockage."""
    if isinstance(exc, WhatsAppApiError):
        return f"WhatsAppApiError:{exc.status_code}:{exc.meta_code}"
    return type(exc).__name__
