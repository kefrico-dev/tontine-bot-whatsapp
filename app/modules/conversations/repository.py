"""Persistance de l'état conversationnel, avec compare-and-swap.

Le document unique par utilisateur ne suffit pas à protéger les transitions :
deux messages peuvent lire la même version et tenter la même transition. Toute
écriture est donc conditionnée à ``(step, version)`` — si la condition ne
correspond plus, l'écriture est refusée plutôt que d'écraser un état plus
récent.
"""

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.modules.conversations.schemas import STATE_TTL, ConversationState, ConversationStep

CONVERSATION_STATES = "conversation_states"


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _to_state(document: dict[str, Any]) -> ConversationState:
    return ConversationState(
        id=str(document["_id"]),
        user_id=str(document["user_id"]),
        step=ConversationStep(document["step"]),
        version=document["version"],
        data=document.get("data", {}),
        updated_at=document["updated_at"],
        expires_at=document["expires_at"],
    )


class ConversationRepository:
    def __init__(self, database: AsyncDatabase[dict[str, Any]]) -> None:
        self._db = database

    async def get(self, user_id: str) -> ConversationState | None:
        """État courant, ou ``None`` s'il n'existe pas — ou s'il est expiré.

        Un état expiré est traité comme inexistant même si le démon TTL de
        MongoDB ne l'a pas encore supprimé : il ne passe qu'environ toutes les
        60 secondes et n'offre aucune garantie de ponctualité.
        """
        document = await self._db[CONVERSATION_STATES].find_one({"user_id": ObjectId(user_id)})
        if document is None:
            return None
        state = _to_state(document)
        return None if state.is_expired(_now()) else state

    async def begin(
        self, *, user_id: str, step: ConversationStep, data: dict[str, Any]
    ) -> ConversationState | None:
        """Démarre un workflow. ``None`` si une conversation vivante existe déjà.

        Le filtre n'accepte que l'absence de document, un état expiré ou un
        état ``IDLE`` : on ne remplace jamais un workflow en cours.
        """
        now = _now()
        try:
            document = await self._db[CONVERSATION_STATES].find_one_and_update(
                {
                    "user_id": ObjectId(user_id),
                    "$or": [
                        {"expires_at": {"$lte": now}},
                        {"step": ConversationStep.IDLE.value},
                    ],
                },
                {
                    "$set": {
                        "step": step.value,
                        "data": data,
                        "updated_at": now,
                        "expires_at": now + STATE_TTL,
                    },
                    "$inc": {"version": 1},
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            # Un état vivant existe : un autre message a pris la main.
            return None
        return _to_state(document) if document else None

    async def transition(
        self,
        state: ConversationState,
        *,
        step: ConversationStep,
        data: dict[str, Any],
    ) -> ConversationState | None:
        """Fait avancer l'état. ``None`` si la version lue n'est plus d'actualité."""
        now = _now()
        document = await self._db[CONVERSATION_STATES].find_one_and_update(
            {
                "user_id": ObjectId(state.user_id),
                "step": state.step.value,
                "version": state.version,
            },
            {
                "$set": {
                    "step": step.value,
                    "data": data,
                    "updated_at": now,
                    "expires_at": now + STATE_TTL,
                },
                "$inc": {"version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        return _to_state(document) if document else None

    async def clear(self, user_id: str) -> bool:
        """Efface l'état. Inconditionnel : seul un ordre explicite l'appelle."""
        result = await self._db[CONVERSATION_STATES].delete_one({"user_id": ObjectId(user_id)})
        return result.deleted_count == 1

    async def finish(self, state: ConversationState) -> bool:
        """Clôt un workflow abouti, sous condition de version."""
        result = await self._db[CONVERSATION_STATES].delete_one(
            {
                "user_id": ObjectId(state.user_id),
                "step": state.step.value,
                "version": state.version,
            }
        )
        return result.deleted_count == 1
