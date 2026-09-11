"""Persistance des tontines et de leurs membres.

Deux invariants sont défendus ici, et ils le sont **par MongoDB**, pas par du
code applicatif :

1. une tontine ne dépasse jamais ``expected_members`` membres actifs ;
2. un utilisateur n'est jamais deux fois membre de la même tontine.

``active_members_count`` est un compteur dénormalisé. La source de vérité
reste ``tontine_members`` : le compteur n'existe que parce qu'une condition de
capacité doit être évaluée **atomiquement**, ce qu'un comptage ne permet pas.
Invariant à tenir dans toute évolution future :

    active_members_count == count(tontine_members où status == ACTIVE)

Toute écriture qui fait passer un membership vers ou depuis ``ACTIVE`` doit
donc ajuster le compteur **dans la même transaction**. La Phase 2 ne gère pas
encore ``LEFT``/``REMOVED`` : le décrément n'existe pas, et c'est volontaire.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.core.logging import get_logger
from app.modules.tontines.exceptions import (
    AlreadyMember,
    InviteCodeGenerationFailed,
    TontineClosed,
    TontineFull,
    TontineNotFound,
)
from app.modules.tontines.invite_code import MAX_GENERATION_ATTEMPTS, generate_invite_code
from app.modules.tontines.schemas import (
    Currency,
    Frequency,
    MemberRole,
    Membership,
    MemberStatus,
    Tontine,
    TontineDraft,
    TontineMembership,
    TontineStatus,
)

logger = get_logger(__name__)

TONTINES = "tontines"
TONTINE_MEMBERS = "tontine_members"

INVITE_CODE_INDEX = "uniq_tontine_invite_code"
MEMBER_INDEX = "uniq_tontine_member"

T = TypeVar("T")


def _now() -> datetime:
    return datetime.now(tz=UTC)


def conflicting_fields(error: DuplicateKeyError) -> set[str]:
    """Champs de l'index à l'origine du conflit.

    Permet de distinguer une collision de code d'invitation d'une double
    adhésion : les traiter pareillement masquerait un bug.
    """
    details = error.details or {}
    key_pattern = details.get("keyPattern")
    if isinstance(key_pattern, dict):
        return set(key_pattern)
    # Repli : certaines versions ne renseignent que le message.
    message = str(error)
    return {name for name in ("invite_code", "tontine_id", "user_id") if name in message}


def _to_tontine(document: dict[str, Any]) -> Tontine:
    return Tontine(
        id=str(document["_id"]),
        name=document["name"],
        description=document.get("description"),
        currency=Currency(document["currency"]),
        contribution_amount=document["contribution_amount"],
        frequency=Frequency(document["frequency"]),
        expected_members=document["expected_members"],
        active_members_count=document["active_members_count"],
        start_date=document.get("start_date"),
        status=TontineStatus(document["status"]),
        invite_code=document["invite_code"],
        created_by=str(document["created_by"]),
        created_at=document["created_at"],
        updated_at=document["updated_at"],
    )


def _to_membership(document: dict[str, Any]) -> Membership:
    return Membership(
        id=str(document["_id"]),
        tontine_id=str(document["tontine_id"]),
        user_id=str(document["user_id"]),
        role=MemberRole(document["role"]),
        status=MemberStatus(document["status"]),
        position=document.get("position"),
        joined_at=document["joined_at"],
        created_at=document["created_at"],
        updated_at=document["updated_at"],
    )


class TontineRepository:
    def __init__(self, database: AsyncDatabase[dict[str, Any]]) -> None:
        self._db = database

    async def _in_transaction(self, callback: Callable[[AsyncClientSession], Awaitable[T]]) -> T:
        """Exécute ``callback`` dans une transaction, avec retry borné.

        ``with_transaction`` de PyMongo rejoue automatiquement les conflits
        transitoires (``TransientTransactionError``) et les commits au
        résultat inconnu, dans une fenêtre de 120 s. Nos erreurs métier ne
        portent pas ces labels : elles provoquent l'abandon de la transaction
        et remontent telles quelles, sans nouvelle tentative.
        """
        async with self._db.client.start_session() as session:
            return await session.with_transaction(callback)

    # --- Création ------------------------------------------------------------

    async def create_with_owner(self, *, draft: TontineDraft, owner_id: str) -> Tontine:
        """Crée la tontine et le membership OWNER, ou rien du tout."""
        owner = ObjectId(owner_id)

        for _ in range(MAX_GENERATION_ATTEMPTS):
            invite_code = generate_invite_code()
            try:
                return await self._in_transaction(
                    lambda session, code=invite_code: self._create_once(  # type: ignore[misc]
                        session, draft=draft, owner=owner, invite_code=code
                    )
                )
            except DuplicateKeyError as error:
                if "invite_code" not in conflicting_fields(error):
                    # Un autre index a sauté : ce n'est pas une collision de
                    # code, c'est un bug. On ne le masque pas par un retry.
                    raise
                logger.warning("invite_code_collision")
                continue

        raise InviteCodeGenerationFailed

    async def _create_once(
        self,
        session: AsyncClientSession,
        *,
        draft: TontineDraft,
        owner: ObjectId,
        invite_code: str,
    ) -> Tontine:
        now = _now()
        tontine_document: dict[str, Any] = {
            "name": draft.name,
            "description": None,
            "currency": draft.currency.value,
            "contribution_amount": draft.contribution_amount,
            "frequency": draft.frequency.value,
            "expected_members": draft.expected_members,
            "active_members_count": 1,  # le créateur, inséré juste après
            "start_date": None,
            "status": TontineStatus.OPEN.value,
            "invite_code": invite_code,
            "created_by": owner,
            "created_at": now,
            "updated_at": now,
        }
        result = await self._db[TONTINES].insert_one(tontine_document, session=session)
        tontine_document["_id"] = result.inserted_id

        await self._db[TONTINE_MEMBERS].insert_one(
            {
                "tontine_id": result.inserted_id,
                "user_id": owner,
                "role": MemberRole.OWNER.value,
                "status": MemberStatus.ACTIVE.value,
                "position": None,
                "joined_at": now,
                "created_at": now,
                "updated_at": now,
            },
            session=session,
        )
        return _to_tontine(tontine_document)

    # --- Adhésion ------------------------------------------------------------

    async def join_by_code(self, *, invite_code: str, user_id: str) -> Tontine:
        """Réserve une place puis crée le membership, atomiquement."""
        user = ObjectId(user_id)
        return await self._in_transaction(
            lambda session: self._join_once(session, invite_code=invite_code, user=user)
        )

    async def _join_once(
        self, session: AsyncClientSession, *, invite_code: str, user: ObjectId
    ) -> Tontine:
        now = _now()

        # Réservation de place. La capacité est comparée par MongoDB entre deux
        # champs du même document ($expr) : la valeur de référence n'est jamais
        # lue au préalable côté application, donc jamais périmée.
        reserved = await self._db[TONTINES].find_one_and_update(
            {
                "invite_code": invite_code,
                "status": TontineStatus.OPEN.value,
                "$expr": {"$lt": ["$active_members_count", "$expected_members"]},
            },
            {"$inc": {"active_members_count": 1}, "$set": {"updated_at": now}},
            return_document=ReturnDocument.AFTER,
            session=session,
        )

        if reserved is None:
            # Aucune place réservée : il faut distinguer les trois causes.
            existing = await self._db[TONTINES].find_one(
                {"invite_code": invite_code}, session=session
            )
            if existing is None:
                raise TontineNotFound
            if existing["status"] != TontineStatus.OPEN.value:
                raise TontineClosed
            raise TontineFull

        try:
            await self._db[TONTINE_MEMBERS].insert_one(
                {
                    "tontine_id": reserved["_id"],
                    "user_id": user,
                    "role": MemberRole.MEMBER.value,
                    "status": MemberStatus.ACTIVE.value,
                    "position": None,
                    "joined_at": now,
                    "created_at": now,
                    "updated_at": now,
                },
                session=session,
            )
        except DuplicateKeyError as error:
            if "user_id" in conflicting_fields(error):
                # L'abandon de la transaction annule aussi la réservation :
                # le compteur n'est pas incrémenté pour rien.
                raise AlreadyMember from error
            raise

        return _to_tontine(reserved)

    # --- Lecture -------------------------------------------------------------

    async def find_by_invite_code(self, invite_code: str) -> Tontine | None:
        document = await self._db[TONTINES].find_one({"invite_code": invite_code})
        return _to_tontine(document) if document else None

    async def list_for_user(self, user_id: str) -> list[TontineMembership]:
        """Tontines dont l'utilisateur est membre actif, plus anciennes d'abord."""
        memberships: dict[ObjectId, MemberRole] = {}
        cursor = self._db[TONTINE_MEMBERS].find(
            {"user_id": ObjectId(user_id), "status": MemberStatus.ACTIVE.value}
        )
        async for document in cursor:
            memberships[document["tontine_id"]] = MemberRole(document["role"])

        if not memberships:
            return []

        results: list[TontineMembership] = []
        cursor = self._db[TONTINES].find({"_id": {"$in": list(memberships)}}).sort("created_at", 1)
        async for document in cursor:
            results.append(
                TontineMembership(
                    tontine=_to_tontine(document),
                    role=memberships[document["_id"]],
                )
            )
        return results

    async def count_active_members(self, tontine_id: str) -> int:
        """Comptage réel, utilisé pour vérifier l'invariant du compteur."""
        return await self._db[TONTINE_MEMBERS].count_documents(
            {"tontine_id": ObjectId(tontine_id), "status": MemberStatus.ACTIVE.value}
        )
