"""Invariants de la Phase 2 prouvés contre une vraie instance MongoDB.

Les doublures des tests unitaires *reproduisent* les garanties ; ici on les
*vérifie*. Transactions, contraintes uniques et compare-and-swap ne peuvent
être éprouvés nulle part ailleurs. Ces tests se sautent sans base joignable,
la CI n'a donc besoin d'aucun service.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.infrastructure.database.indexes import ensure_indexes
from app.infrastructure.database.mongodb import create_mongo_client, ping
from app.modules.conversations.repository import CONVERSATION_STATES, ConversationRepository
from app.modules.conversations.schemas import ConversationStep
from app.modules.tontines.exceptions import (
    AlreadyMember,
    InviteCodeGenerationFailed,
    TontineClosed,
    TontineFull,
    TontineNotFound,
)
from app.modules.tontines.repository import (
    TONTINE_MEMBERS,
    TONTINES,
    TontineRepository,
    conflicting_fields,
)
from app.modules.tontines.schemas import Frequency, TontineDraft, TontineStatus
from app.modules.users.repository import USERS, UserRepository

pytestmark = pytest.mark.integration

TEST_DATABASE = "kefrico_tontine_test_phase2"
COLLECTIONS = (USERS, TONTINES, TONTINE_MEMBERS, CONVERSATION_STATES)


def draft(**overrides: Any) -> TontineDraft:
    values: dict[str, Any] = {
        "name": "Famille 2026",
        "contribution_amount": 10000,
        "frequency": Frequency.WEEKLY,
        "expected_members": 10,
    }
    values.update(overrides)
    return TontineDraft(**values)


@pytest.fixture
async def database() -> AsyncIterator[AsyncDatabase[dict[str, Any]]]:
    settings = Settings().model_copy(
        update={"mongodb_database": TEST_DATABASE, "mongodb_timeout_ms": 15000}
    )
    client = create_mongo_client(settings)
    if not await ping(client):
        await client.close()
        pytest.skip("aucune instance MongoDB joignable — test d'intégration ignoré")

    db = client[TEST_DATABASE]
    for collection in COLLECTIONS:
        await db[collection].delete_many({})
    await ensure_indexes(db)
    try:
        yield db
    finally:
        await client.drop_database(TEST_DATABASE)
        await client.close()


async def make_user(database: AsyncDatabase[dict[str, Any]], phone: str) -> str:
    user, _ = await UserRepository(database).get_or_create(phone=phone, whatsapp_name=None)
    return user.id


# --- Index -------------------------------------------------------------------


async def test_phase2_indexes_exist(database: AsyncDatabase[dict[str, Any]]) -> None:
    users = await database[USERS].index_information()
    tontines = await database[TONTINES].index_information()
    members = await database[TONTINE_MEMBERS].index_information()
    states = await database[CONVERSATION_STATES].index_information()

    assert users["uniq_user_phone"]["unique"] is True
    assert tontines["uniq_tontine_invite_code"]["unique"] is True
    assert members["uniq_tontine_member"]["unique"] is True
    assert "tontine_member_user" in members
    assert states["uniq_conversation_user"]["unique"] is True
    assert states["ttl_conversation_expires"]["expireAfterSeconds"] == 0


# --- Utilisateurs ------------------------------------------------------------


async def test_same_number_yields_one_user(database: AsyncDatabase[dict[str, Any]]) -> None:
    repository = UserRepository(database)

    premier, cree1 = await repository.get_or_create(phone="+22900000001", whatsapp_name="A")
    second, cree2 = await repository.get_or_create(phone="+22900000001", whatsapp_name="B")

    assert cree1 is True
    assert cree2 is False
    assert premier.id == second.id
    assert await database[USERS].count_documents({}) == 1


async def test_concurrent_first_messages_create_one_user(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    """Cinq webhooks simultanés d'un même nouveau numéro."""
    repository = UserRepository(database)

    resultats = await asyncio.gather(
        *(repository.get_or_create(phone="+22900000002", whatsapp_name="X") for _ in range(5))
    )

    assert sum(1 for _, cree in resultats if cree) == 1, "une seule création"
    assert len({user.id for user, _ in resultats}) == 1, "tous voient le même utilisateur"
    assert await database[USERS].count_documents({}) == 1


# --- Création atomique -------------------------------------------------------


async def test_creation_writes_tontine_and_owner(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    repository = TontineRepository(database)
    owner_id = await make_user(database, "+22900000003")

    tontine = await repository.create_with_owner(draft=draft(), owner_id=owner_id)

    assert tontine.status is TontineStatus.OPEN
    assert tontine.active_members_count == 1
    assert tontine.invite_code.startswith("KFT-")
    assert await database[TONTINES].count_documents({}) == 1
    membership = await database[TONTINE_MEMBERS].find_one({})
    assert membership is not None
    assert membership["role"] == "OWNER"
    assert membership["status"] == "ACTIVE"


async def test_rollback_when_the_owner_membership_fails(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    """Si le membership OWNER échoue, aucune tontine ne doit subsister."""
    repository = TontineRepository(database)
    owner_id = await make_user(database, "+22900000004")

    # Un membership identique existe déjà : la seconde insertion violera
    # l'index unique et fera échouer la transaction entière.
    tontine = await repository.create_with_owner(draft=draft(), owner_id=owner_id)
    avant = await database[TONTINES].count_documents({})

    original = repository._create_once

    async def create_with_existing_member(session: Any, **kwargs: Any) -> Any:
        resultat = await original(session, **kwargs)
        await database[TONTINE_MEMBERS].insert_one(
            {
                "tontine_id": ObjectId(tontine.id),
                "user_id": ObjectId(owner_id),
                "role": "MEMBER",
                "status": "ACTIVE",
                "position": None,
                "joined_at": resultat.created_at,
                "created_at": resultat.created_at,
                "updated_at": resultat.created_at,
            },
            session=session,
        )
        return resultat

    repository._create_once = create_with_existing_member  # type: ignore[method-assign]

    with pytest.raises(DuplicateKeyError):
        await repository.create_with_owner(draft=draft(name="Orpheline"), owner_id=owner_id)

    assert await database[TONTINES].count_documents({}) == avant, "aucune tontine orpheline"
    assert await database[TONTINES].count_documents({"name": "Orpheline"}) == 0


async def test_invite_code_collision_is_retried(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    repository = TontineRepository(database)
    owner_id = await make_user(database, "+22900000005")
    premiere = await repository.create_with_owner(draft=draft(), owner_id=owner_id)

    codes = iter([premiere.invite_code, "KFT-ZZZZZZ"])
    import app.modules.tontines.repository as module

    original = module.generate_invite_code
    module.generate_invite_code = lambda: next(codes)  # type: ignore[assignment]
    try:
        seconde = await repository.create_with_owner(
            draft=draft(name="Seconde"), owner_id=await make_user(database, "+22900000006")
        )
    finally:
        module.generate_invite_code = original  # type: ignore[assignment]

    assert seconde.invite_code == "KFT-ZZZZZZ", "un nouveau code a été tiré"
    assert await database[TONTINES].count_documents({}) == 2


async def test_persistent_collision_fails_loudly(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    repository = TontineRepository(database)
    owner_id = await make_user(database, "+22900000007")
    premiere = await repository.create_with_owner(draft=draft(), owner_id=owner_id)

    import app.modules.tontines.repository as module

    original = module.generate_invite_code
    module.generate_invite_code = lambda: premiere.invite_code  # type: ignore[assignment]
    try:
        with pytest.raises(InviteCodeGenerationFailed):
            await repository.create_with_owner(
                draft=draft(name="Jamais"), owner_id=await make_user(database, "+22900000008")
            )
    finally:
        module.generate_invite_code = original  # type: ignore[assignment]

    assert await database[TONTINES].count_documents({"name": "Jamais"}) == 0


def test_conflicting_fields_distinguishes_indexes() -> None:
    """Un doublon sur un autre index ne doit jamais passer pour une collision de code."""
    code_error = DuplicateKeyError("dup", details={"keyPattern": {"invite_code": 1}})
    member_error = DuplicateKeyError("dup", details={"keyPattern": {"tontine_id": 1, "user_id": 1}})

    assert "invite_code" in conflicting_fields(code_error)
    assert "invite_code" not in conflicting_fields(member_error)
    assert conflicting_fields(member_error) == {"tontine_id", "user_id"}


# --- Adhésion ----------------------------------------------------------------


async def test_join_increments_the_counter(database: AsyncDatabase[dict[str, Any]]) -> None:
    repository = TontineRepository(database)
    owner_id = await make_user(database, "+22900000010")
    tontine = await repository.create_with_owner(draft=draft(), owner_id=owner_id)
    member_id = await make_user(database, "+22900000011")

    rejoint = await repository.join_by_code(invite_code=tontine.invite_code, user_id=member_id)

    assert rejoint.active_members_count == 2
    assert await repository.count_active_members(tontine.id) == 2


async def test_unknown_code_is_refused(database: AsyncDatabase[dict[str, Any]]) -> None:
    repository = TontineRepository(database)
    user_id = await make_user(database, "+22900000012")

    with pytest.raises(TontineNotFound):
        await repository.join_by_code(invite_code="KFT-ABCDEF", user_id=user_id)


async def test_closed_tontine_is_refused(database: AsyncDatabase[dict[str, Any]]) -> None:
    repository = TontineRepository(database)
    owner_id = await make_user(database, "+22900000013")
    tontine = await repository.create_with_owner(draft=draft(), owner_id=owner_id)
    await database[TONTINES].update_one(
        {"_id": ObjectId(tontine.id)}, {"$set": {"status": TontineStatus.CANCELLED.value}}
    )

    with pytest.raises(TontineClosed):
        await repository.join_by_code(
            invite_code=tontine.invite_code, user_id=await make_user(database, "+22900000014")
        )


async def test_double_join_rolls_back_the_counter(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    """Le compteur ne doit pas bouger quand l'adhésion est refusée."""
    repository = TontineRepository(database)
    owner_id = await make_user(database, "+22900000015")
    tontine = await repository.create_with_owner(draft=draft(), owner_id=owner_id)
    member_id = await make_user(database, "+22900000016")
    await repository.join_by_code(invite_code=tontine.invite_code, user_id=member_id)

    with pytest.raises(AlreadyMember):
        await repository.join_by_code(invite_code=tontine.invite_code, user_id=member_id)

    document = await database[TONTINES].find_one({"_id": ObjectId(tontine.id)})
    assert document is not None
    assert document["active_members_count"] == 2, "la réservation a bien été annulée"
    assert await repository.count_active_members(tontine.id) == 2


async def test_owner_cannot_join_their_own_tontine(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    repository = TontineRepository(database)
    owner_id = await make_user(database, "+22900000017")
    tontine = await repository.create_with_owner(draft=draft(), owner_id=owner_id)

    with pytest.raises(AlreadyMember):
        await repository.join_by_code(invite_code=tontine.invite_code, user_id=owner_id)

    assert await repository.count_active_members(tontine.id) == 1


async def test_full_tontine_is_refused(database: AsyncDatabase[dict[str, Any]]) -> None:
    repository = TontineRepository(database)
    owner_id = await make_user(database, "+22900000018")
    tontine = await repository.create_with_owner(draft=draft(expected_members=2), owner_id=owner_id)
    await repository.join_by_code(
        invite_code=tontine.invite_code, user_id=await make_user(database, "+22900000019")
    )

    with pytest.raises(TontineFull):
        await repository.join_by_code(
            invite_code=tontine.invite_code, user_id=await make_user(database, "+22900000020")
        )


async def test_five_candidates_for_one_seat(database: AsyncDatabase[dict[str, Any]]) -> None:
    """L'invariant central : une seule place, cinq prétendants simultanés."""
    repository = TontineRepository(database)
    owner_id = await make_user(database, "+22900000030")
    tontine = await repository.create_with_owner(draft=draft(expected_members=2), owner_id=owner_id)
    candidats = [await make_user(database, f"+2290000004{i}") for i in range(5)]

    resultats = await asyncio.gather(
        *(
            repository.join_by_code(invite_code=tontine.invite_code, user_id=user_id)
            for user_id in candidats
        ),
        return_exceptions=True,
    )

    succes = [r for r in resultats if not isinstance(r, BaseException)]
    refus = [r for r in resultats if isinstance(r, TontineFull)]
    autres = [
        r for r in resultats if isinstance(r, BaseException) and not isinstance(r, TontineFull)
    ]

    assert autres == [], f"aucune erreur technique attendue : {autres}"
    assert len(succes) == 1, "exactement une adhésion"
    assert len(refus) == 4, "les quatre autres reçoivent TontineFull"

    document = await database[TONTINES].find_one({"_id": ObjectId(tontine.id)})
    assert document is not None
    assert document["active_members_count"] == 2, "jamais de onzième place"
    assert await repository.count_active_members(tontine.id) == 2


async def test_counter_matches_the_real_count_after_a_burst(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    """active_members_count == count(memberships ACTIVE), après concurrence."""
    repository = TontineRepository(database)
    owner_id = await make_user(database, "+22900000050")
    tontine = await repository.create_with_owner(draft=draft(expected_members=6), owner_id=owner_id)
    candidats = [await make_user(database, f"+2290000006{i}") for i in range(9)]

    await asyncio.gather(
        *(
            repository.join_by_code(invite_code=tontine.invite_code, user_id=user_id)
            for user_id in candidats
        ),
        return_exceptions=True,
    )

    document = await database[TONTINES].find_one({"_id": ObjectId(tontine.id)})
    assert document is not None
    reel = await repository.count_active_members(tontine.id)
    assert document["active_members_count"] == reel
    assert reel == 6, "la capacité a été respectée exactement"


async def test_listing_returns_tontines_of_the_user_only(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    repository = TontineRepository(database)
    alice = await make_user(database, "+22900000070")
    bob = await make_user(database, "+22900000071")
    premiere = await repository.create_with_owner(draft=draft(name="Famille"), owner_id=alice)
    await repository.create_with_owner(draft=draft(name="Collegues"), owner_id=bob)
    await repository.join_by_code(invite_code=premiere.invite_code, user_id=bob)

    vue_alice = await repository.list_for_user(alice)
    vue_bob = await repository.list_for_user(bob)

    assert [item.tontine.name for item in vue_alice] == ["Famille"]
    assert sorted(item.tontine.name for item in vue_bob) == ["Collegues", "Famille"]
    assert {item.role.value for item in vue_alice} == {"OWNER"}


# --- État conversationnel ----------------------------------------------------


async def test_conversation_compare_and_swap(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    """Deux transitions concurrentes sur la même version : une seule gagne."""
    repository = ConversationRepository(database)
    user_id = await make_user(database, "+22900000080")
    state = await repository.begin(user_id=user_id, step=ConversationStep.CREATE_NAME, data={})
    assert state is not None

    premier, second = await asyncio.gather(
        repository.transition(state, step=ConversationStep.CREATE_AMOUNT, data={"name": "Premier"}),
        repository.transition(state, step=ConversationStep.CREATE_AMOUNT, data={"name": "Second"}),
    )

    gagnants = [r for r in (premier, second) if r is not None]
    assert len(gagnants) == 1, "exactement une transition aboutit"
    courant = await repository.get(user_id)
    assert courant is not None
    assert courant.version == state.version + 1, "la version n'avance que d'un cran"
    assert courant.data["name"] == gagnants[0].data["name"], "aucun écrasement silencieux"


async def test_transition_on_a_stale_version_is_refused(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    repository = ConversationRepository(database)
    user_id = await make_user(database, "+22900000081")
    state = await repository.begin(user_id=user_id, step=ConversationStep.CREATE_NAME, data={})
    assert state is not None
    await repository.transition(state, step=ConversationStep.CREATE_AMOUNT, data={"name": "A"})

    perime = await repository.transition(
        state, step=ConversationStep.CREATE_AMOUNT, data={"name": "B"}
    )

    assert perime is None
    courant = await repository.get(user_id)
    assert courant is not None and courant.data["name"] == "A"


async def test_only_one_state_per_user(database: AsyncDatabase[dict[str, Any]]) -> None:
    repository = ConversationRepository(database)
    user_id = await make_user(database, "+22900000082")

    await repository.begin(user_id=user_id, step=ConversationStep.CREATE_NAME, data={})
    deuxieme = await repository.begin(user_id=user_id, step=ConversationStep.JOIN_CODE, data={})

    assert deuxieme is None, "un workflow vivant ne se fait pas écraser"
    assert await database[CONVERSATION_STATES].count_documents({}) == 1


async def test_expired_state_is_ignored_and_replaceable(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    from datetime import UTC, datetime, timedelta

    repository = ConversationRepository(database)
    user_id = await make_user(database, "+22900000083")
    await repository.begin(user_id=user_id, step=ConversationStep.CREATE_NAME, data={})
    await database[CONVERSATION_STATES].update_one(
        {"user_id": ObjectId(user_id)},
        {"$set": {"expires_at": datetime.now(tz=UTC) - timedelta(minutes=1)}},
    )

    assert await repository.get(user_id) is None, "expiré == inexistant"

    nouveau = await repository.begin(user_id=user_id, step=ConversationStep.JOIN_CODE, data={})
    assert nouveau is not None, "un état expiré peut être remplacé"
    assert nouveau.step is ConversationStep.JOIN_CODE


async def test_finish_is_version_conditioned(
    database: AsyncDatabase[dict[str, Any]],
) -> None:
    repository = ConversationRepository(database)
    user_id = await make_user(database, "+22900000084")
    state = await repository.begin(user_id=user_id, step=ConversationStep.CREATE_NAME, data={})
    assert state is not None
    await repository.transition(state, step=ConversationStep.CREATE_AMOUNT, data={})

    assert await repository.finish(state) is False, "version périmée : refus"
    assert await repository.get(user_id) is not None
