"""Modèles de l'état conversationnel."""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

#: Durée de vie d'une conversation inachevée. Assez long pour une discussion
#: WhatsApp entrecoupée, assez court pour qu'un brouillon de la veille ne
#: resurgisse pas au milieu d'un nouvel échange.
STATE_TTL = timedelta(minutes=30)


class ConversationStep(StrEnum):
    IDLE = "IDLE"

    CREATE_NAME = "CREATE_TONTINE_NAME"
    CREATE_AMOUNT = "CREATE_TONTINE_AMOUNT"
    CREATE_FREQUENCY = "CREATE_TONTINE_FREQUENCY"
    CREATE_MEMBERS = "CREATE_TONTINE_MEMBERS"
    CREATE_CONFIRM = "CREATE_TONTINE_CONFIRM"

    JOIN_CODE = "JOIN_TONTINE_CODE"
    JOIN_CONFIRM = "JOIN_TONTINE_CONFIRM"


class ConversationState(BaseModel):
    """État courant d'une conversation.

    ``version`` porte le contrôle de concurrence optimiste : toute transition
    est conditionnée à la version lue, si bien que deux messages traités en
    parallèle ne peuvent pas s'écraser mutuellement.
    """

    id: str
    user_id: str
    step: ConversationStep
    version: int = Field(ge=1)
    data: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime
    expires_at: datetime

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at <= now
