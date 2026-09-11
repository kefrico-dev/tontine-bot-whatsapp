"""Modèles du module utilisateurs."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class User(BaseModel):
    """Utilisateur identifié par son numéro WhatsApp.

    Le numéro est l'identifiant *fonctionnel* actuel, mais les autres
    documents référencent toujours ``id`` — jamais le numéro — afin qu'un
    changement de numéro reste possible plus tard sans migration massive.
    """

    id: str
    phone: str
    whatsapp_name: str | None = None
    status: UserStatus = UserStatus.ACTIVE
    created_at: datetime
    updated_at: datetime

    @property
    def is_active(self) -> bool:
        return self.status is UserStatus.ACTIVE
