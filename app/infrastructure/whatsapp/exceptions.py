"""Exceptions du canal WhatsApp."""

from app.core.exceptions import AppError


class WhatsAppNotConfigured(AppError):
    """Une opération WhatsApp est demandée sans configuration Meta."""

    status_code = 503
    error_code = "whatsapp_not_configured"
    message = "Le canal WhatsApp n'est pas configuré."


class WebhookNotReady(AppError):
    """Les index d'idempotence ne sont pas en place : traiter serait risqué."""

    status_code = 503
    error_code = "webhook_not_ready"
    message = "Service temporairement indisponible."


class InvalidWebhookSignature(AppError):
    """Signature Meta absente ou invalide.

    403 et non 401 : il ne s'agit pas d'un défi d'authentification auquel
    l'appelant pourrait répondre, mais d'une preuve d'intégrité rejetée.
    """

    status_code = 403
    error_code = "invalid_signature"
    message = "Signature invalide."


class MalformedWebhookPayload(AppError):
    """Le corps reçu n'est pas du JSON exploitable."""

    status_code = 400
    error_code = "malformed_payload"
    message = "Corps de requête invalide."


class WhatsAppError(Exception):
    """Erreur d'un appel sortant vers Meta. Interne : jamais exposée telle quelle."""


class WhatsAppApiError(WhatsAppError):
    """Meta a répondu, mais avec un statut non-2xx."""

    def __init__(
        self,
        *,
        status_code: int,
        meta_code: int | None = None,
        meta_message: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.meta_code = meta_code
        self.meta_message = meta_message
        super().__init__(f"Meta a répondu {status_code} (code={meta_code})")

    @property
    def is_retryable(self) -> bool:
        """429 et 5xx méritent une nouvelle tentative ; 4xx non."""
        return self.status_code == 429 or self.status_code >= 500


class WhatsAppTransportError(WhatsAppError):
    """Meta n'a pas répondu : timeout, DNS, coupure réseau."""

    def __init__(self, cause: str) -> None:
        self.cause = cause
        super().__init__(f"Appel Meta impossible : {cause}")

    @property
    def is_retryable(self) -> bool:
        return True
