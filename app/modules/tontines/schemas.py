"""Modèles du module tontines."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

#: Bornes métier. Une tontine à un seul membre n'a pas de sens ; 100 est une
#: limite haute raisonnable pour un groupe géré par conversation.
MIN_MEMBERS = 2
MAX_MEMBERS = 100
#: Le franc CFA n'a pas de subdivision : les montants sont des entiers.
MAX_AMOUNT = 100_000_000
MIN_NAME_LENGTH = 2
MAX_NAME_LENGTH = 60


class Currency(StrEnum):
    XOF = "XOF"


class Frequency(StrEnum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class TontineStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MemberRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class MemberStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LEFT = "LEFT"
    REMOVED = "REMOVED"


class TontineDraft(BaseModel):
    """Paramètres validés d'une tontine, avant sa création effective."""

    name: str = Field(min_length=MIN_NAME_LENGTH, max_length=MAX_NAME_LENGTH)
    contribution_amount: int = Field(gt=0, le=MAX_AMOUNT)
    frequency: Frequency
    expected_members: int = Field(ge=MIN_MEMBERS, le=MAX_MEMBERS)
    currency: Currency = Currency.XOF

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < MIN_NAME_LENGTH:
            raise ValueError("Nom trop court.")
        return cleaned

    @field_validator("contribution_amount", mode="before")
    @classmethod
    def _reject_non_integer_amounts(cls, value: object) -> object:
        """Un montant décimal est refusé : le XOF n'a pas de centimes."""
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("Le montant doit être un nombre entier de francs.")
        if isinstance(value, bool):
            raise ValueError("Montant invalide.")
        return value


class Tontine(BaseModel):
    id: str
    name: str
    description: str | None = None
    currency: Currency
    contribution_amount: int
    frequency: Frequency
    expected_members: int
    #: Compteur dénormalisé — voir ``TontineRepository`` pour l'invariant.
    active_members_count: int
    start_date: datetime | None = None
    status: TontineStatus
    invite_code: str
    created_by: str
    created_at: datetime
    updated_at: datetime

    @property
    def is_full(self) -> bool:
        return self.active_members_count >= self.expected_members


class Membership(BaseModel):
    id: str
    tontine_id: str
    user_id: str
    role: MemberRole
    status: MemberStatus
    position: int | None = None
    joined_at: datetime
    created_at: datetime
    updated_at: datetime


class TontineMembership(BaseModel):
    """Une tontine vue par l'un de ses membres."""

    tontine: Tontine
    role: MemberRole
