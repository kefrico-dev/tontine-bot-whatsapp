"""Doublures en mémoire des repositories de la Phase 2.

Elles reproduisent fidèlement les garanties que MongoDB apporte en vrai —
unicité, compare-and-swap, capacité — afin que les tests unitaires exercent
les mêmes chemins de code que la production. Les invariants eux-mêmes restent
vérifiés contre une vraie base dans les tests d'intégration.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.conversations.schemas import STATE_TTL, ConversationState, ConversationStep
from app.modules.tontines.exceptions import (
    AlreadyMember,
    TontineClosed,
    TontineFull,
    TontineNotFound,
)
from app.modules.tontines.invite_code import generate_invite_code
from app.modules.tontines.schemas import (
    Currency,
    MemberRole,
    Tontine,
    TontineDraft,
    TontineMembership,
    TontineStatus,
)
from app.modules.users.schemas import User, UserStatus


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _oid(counter: int) -> str:
    """Identifiant de 24 caractères hexadécimaux, comme un ObjectId."""
    return f"{counter:024x}"


class FakeUserRepository:
    def __init__(self) -> None:
        self.by_phone: dict[str, User] = {}
        self._counter = 0

    async def get_or_create(self, *, phone: str, whatsapp_name: str | None) -> tuple[User, bool]:
        existing = self.by_phone.get(phone)
        if existing is not None:
            return existing, False
        self._counter += 1
        now = _now()
        user = User(
            id=_oid(self._counter),
            phone=phone,
            whatsapp_name=whatsapp_name,
            status=UserStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        self.by_phone[phone] = user
        return user, True

    async def get_by_id(self, user_id: str) -> User | None:
        return next((u for u in self.by_phone.values() if u.id == user_id), None)


class FakeTontineRepository:
    def __init__(self) -> None:
        self.tontines: dict[str, Tontine] = {}
        self.members: dict[str, set[str]] = {}
        self._counter = 0
        #: Force l'échec de l'insertion du membership OWNER, pour éprouver le rollback.
        self.fail_owner_membership = False

    async def create_with_owner(self, *, draft: TontineDraft, owner_id: str) -> Tontine:
        self._counter += 1
        now = _now()
        tontine = Tontine(
            id=_oid(1000 + self._counter),
            name=draft.name,
            currency=Currency.XOF,
            contribution_amount=draft.contribution_amount,
            frequency=draft.frequency,
            expected_members=draft.expected_members,
            active_members_count=1,
            status=TontineStatus.OPEN,
            invite_code=generate_invite_code(),
            created_by=owner_id,
            created_at=now,
            updated_at=now,
        )
        if self.fail_owner_membership:
            # Transaction annulée : rien ne doit subsister.
            raise RuntimeError("echec d'insertion du membership OWNER")
        self.tontines[tontine.id] = tontine
        self.members[tontine.id] = {owner_id}
        return tontine

    async def join_by_code(self, *, invite_code: str, user_id: str) -> Tontine:
        tontine = next((t for t in self.tontines.values() if t.invite_code == invite_code), None)
        if tontine is None:
            raise TontineNotFound
        if tontine.status is not TontineStatus.OPEN:
            raise TontineClosed
        if user_id in self.members[tontine.id]:
            raise AlreadyMember
        if tontine.active_members_count >= tontine.expected_members:
            raise TontineFull

        updated = tontine.model_copy(
            update={"active_members_count": tontine.active_members_count + 1}
        )
        self.tontines[tontine.id] = updated
        self.members[tontine.id].add(user_id)
        return updated

    async def find_by_invite_code(self, invite_code: str) -> Tontine | None:
        return next((t for t in self.tontines.values() if t.invite_code == invite_code), None)

    async def list_for_user(self, user_id: str) -> list[TontineMembership]:
        resultats: list[TontineMembership] = []
        for tontine_id, membres in self.members.items():
            if user_id not in membres:
                continue
            tontine = self.tontines[tontine_id]
            role = MemberRole.OWNER if tontine.created_by == user_id else MemberRole.MEMBER
            resultats.append(TontineMembership(tontine=tontine, role=role))
        return sorted(resultats, key=lambda item: item.tontine.created_at)

    async def count_active_members(self, tontine_id: str) -> int:
        return len(self.members.get(tontine_id, set()))

    # --- aides de test -------------------------------------------------------

    def close(self, tontine_id: str) -> None:
        self.tontines[tontine_id] = self.tontines[tontine_id].model_copy(
            update={"status": TontineStatus.COMPLETED}
        )

    def fill(self, tontine_id: str) -> None:
        """Remplit la tontine jusqu'à sa capacité, sans membres réels."""
        tontine = self.tontines[tontine_id]
        self.tontines[tontine_id] = tontine.model_copy(
            update={"active_members_count": tontine.expected_members}
        )


class FakeConversationRepository:
    """Reproduit le compare-and-swap sur ``(step, version)``."""

    def __init__(self) -> None:
        self.states: dict[str, ConversationState] = {}
        self._counter = 0

    async def get(self, user_id: str) -> ConversationState | None:
        state = self.states.get(user_id)
        if state is None:
            return None
        return None if state.is_expired(_now()) else state

    async def begin(
        self, *, user_id: str, step: ConversationStep, data: dict[str, Any]
    ) -> ConversationState | None:
        existing = self.states.get(user_id)
        vivant = (
            existing is not None
            and not existing.is_expired(_now())
            and existing.step is not ConversationStep.IDLE
        )
        if vivant:
            return None

        self._counter += 1
        now = _now()
        state = ConversationState(
            id=_oid(2000 + self._counter),
            user_id=user_id,
            step=step,
            version=(existing.version + 1) if existing else 1,
            data=data,
            updated_at=now,
            expires_at=now + STATE_TTL,
        )
        self.states[user_id] = state
        return state

    async def transition(
        self, state: ConversationState, *, step: ConversationStep, data: dict[str, Any]
    ) -> ConversationState | None:
        courant = self.states.get(state.user_id)
        if courant is None or courant.step is not state.step or courant.version != state.version:
            return None

        now = _now()
        mis_a_jour = courant.model_copy(
            update={
                "step": step,
                "data": data,
                "version": courant.version + 1,
                "updated_at": now,
                "expires_at": now + STATE_TTL,
            }
        )
        self.states[state.user_id] = mis_a_jour
        return mis_a_jour

    async def clear(self, user_id: str) -> bool:
        return self.states.pop(user_id, None) is not None

    async def finish(self, state: ConversationState) -> bool:
        courant = self.states.get(state.user_id)
        if courant is None or courant.step is not state.step or courant.version != state.version:
            return False
        del self.states[state.user_id]
        return True

    # --- aides de test -------------------------------------------------------

    def expire(self, user_id: str) -> None:
        state = self.states[user_id]
        self.states[user_id] = state.model_copy(
            update={"expires_at": _now() - timedelta(seconds=1)}
        )
