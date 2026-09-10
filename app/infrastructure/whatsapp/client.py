"""Client sortant vers l'API Meta WhatsApp Cloud."""

from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import Settings
from app.core.logging import get_logger, mask_phone
from app.infrastructure.whatsapp.exceptions import (
    WhatsAppApiError,
    WhatsAppNotConfigured,
    WhatsAppTransportError,
)

logger = get_logger(__name__)


class SentMessage(BaseModel):
    """Résultat d'un envoi accepté par Meta."""

    external_message_id: str
    recipient: str


class WhatsAppClient:
    """Envoie des messages via l'API Graph.

    Le client HTTP est fourni par l'appelant et partagé pour toute la durée de
    vie de l'application : ouvrir une connexion par message gaspillerait un
    handshake TLS à chaque appel.
    """

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http_client

    def _authorization(self) -> str:
        token = self._settings.whatsapp_access_token
        if not token or not self._settings.whatsapp_phone_number_id:
            raise WhatsAppNotConfigured
        return f"Bearer {token}"

    async def send_text_message(self, *, to: str, text: str) -> SentMessage:
        """Envoie un message texte. Lève en cas d'échec, ne renvoie jamais None."""
        headers = {
            # Jamais logué : cet en-tête porte le jeton d'accès.
            "Authorization": self._authorization(),
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }

        try:
            response = await self._http.post(
                self._settings.whatsapp_messages_url,
                json=body,
                headers=headers,
                timeout=self._settings.whatsapp_timeout_s,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "whatsapp_send_transport_error",
                to=mask_phone(to),
                error=type(exc).__name__,
            )
            raise WhatsAppTransportError(type(exc).__name__) from exc

        if response.status_code >= 400:
            meta_code, meta_message = _extract_meta_error(response)
            logger.warning(
                "whatsapp_send_rejected",
                to=mask_phone(to),
                status_code=response.status_code,
                meta_code=meta_code,
                meta_message=meta_message,
            )
            raise WhatsAppApiError(
                status_code=response.status_code,
                meta_code=meta_code,
                meta_message=meta_message,
            )

        message_id = _extract_message_id(response)
        if message_id is None:
            logger.warning("whatsapp_send_unexpected_response", to=mask_phone(to))
            raise WhatsAppApiError(
                status_code=response.status_code,
                meta_message="Réponse Meta sans identifiant de message.",
            )

        logger.info("whatsapp_send_ok", to=mask_phone(to), message_id=message_id)
        return SentMessage(external_message_id=message_id, recipient=to)


def _payload(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _extract_meta_error(response: httpx.Response) -> tuple[int | None, str | None]:
    error = _payload(response).get("error")
    if not isinstance(error, dict):
        return None, None
    code = error.get("code")
    message = error.get("message")
    return (
        code if isinstance(code, int) else None,
        message if isinstance(message, str) else None,
    )


def _extract_message_id(response: httpx.Response) -> str | None:
    messages = _payload(response).get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    first = messages[0]
    if not isinstance(first, dict):
        return None
    message_id = first.get("id")
    return message_id if isinstance(message_id, str) and message_id else None
