"""Persistance des utilisateurs."""

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.modules.users.schemas import User, UserStatus

USERS = "users"


def _now() -> datetime:
    return datetime.now(tz=UTC)


def to_user(document: dict[str, Any]) -> User:
    return User(
        id=str(document["_id"]),
        phone=document["phone"],
        whatsapp_name=document.get("whatsapp_name"),
        status=UserStatus(document.get("status", UserStatus.ACTIVE.value)),
        created_at=document["created_at"],
        updated_at=document["updated_at"],
    )


class UserRepository:
    def __init__(self, database: AsyncDatabase[dict[str, Any]]) -> None:
        self._db = database

    async def get_or_create(self, *, phone: str, whatsapp_name: str | None) -> tuple[User, bool]:
        """Récupère l'utilisateur, ou le crée. Renvoie ``(user, créé)``.

        Sûr en concurrence : on tente l'insertion et on relit en cas de
        collision sur l'index unique. Un ``find`` suivi d'un ``insert``
        laisserait deux webhooks simultanés créer deux utilisateurs.
        """
        now = _now()
        document: dict[str, Any] = {
            "phone": phone,
            "whatsapp_name": whatsapp_name,
            "status": UserStatus.ACTIVE.value,
            "created_at": now,
            "updated_at": now,
        }
        try:
            result = await self._db[USERS].insert_one(document)
        except DuplicateKeyError:
            existing = await self._db[USERS].find_one({"phone": phone})
            if existing is None:  # pragma: no cover - incohérence de base
                raise
            return to_user(existing), False

        document["_id"] = result.inserted_id
        return to_user(document), True

    async def get_by_id(self, user_id: str) -> User | None:
        document = await self._db[USERS].find_one({"_id": ObjectId(user_id)})
        return to_user(document) if document else None
