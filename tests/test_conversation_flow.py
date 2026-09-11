"""Machine à états conversationnelle, de bout en bout avec des doublures."""

from datetime import UTC, datetime

import pytest

from app.modules.conversations.schemas import ConversationStep
from app.modules.conversations.service import ConversationService
from app.modules.messaging.schemas import InboundWhatsAppMessage, WhatsAppMessageType
from app.modules.tontines.service import TontineService
from app.modules.users.service import UserService
from tests.fakes import (
    FakeConversationRepository,
    FakeTontineRepository,
    FakeUserRepository,
)

SENDER = "22900000000"
AUTRE = "22911111111"


class Bot:
    """Petit harnais : envoie un message, renvoie la réponse du bot."""

    def __init__(self) -> None:
        self.users = FakeUserRepository()
        self.tontines = FakeTontineRepository()
        self.conversations = FakeConversationRepository()
        self.service = ConversationService(
            UserService(self.users),  # type: ignore[arg-type]
            TontineService(self.tontines),  # type: ignore[arg-type]
            self.conversations,  # type: ignore[arg-type]
        )
        self._counter = 0

    async def say(self, text: str, *, sender: str = SENDER) -> str:
        self._counter += 1
        message = InboundWhatsAppMessage(
            external_message_id=f"wamid.TEST{self._counter}",
            sender_phone=sender,
            sender_name="Kefrico",
            message_type=WhatsAppMessageType.TEXT,
            text=text,
            timestamp=datetime.now(tz=UTC),
        )
        return await self.service.reply_to(message, correlation_id="c1")

    def user_id(self, sender: str = SENDER) -> str:
        return self.users.by_phone[f"+{sender}"].id

    def step(self, sender: str = SENDER) -> ConversationStep | None:
        state = self.conversations.states.get(self.user_id(sender))
        return state.step if state else None


@pytest.fixture
def bot() -> Bot:
    return Bot()


# --- Accueil et menu ---------------------------------------------------------


async def test_greeting_creates_the_user_and_shows_the_menu(bot: Bot) -> None:
    reponse = await bot.say("Bonjour")

    assert "Bienvenue sur KEFRICO Tontine" in reponse
    assert "1. Créer une tontine" in reponse
    assert bot.users.by_phone["+22900000000"].whatsapp_name == "Kefrico"


async def test_same_number_is_not_created_twice(bot: Bot) -> None:
    await bot.say("Bonjour")
    await bot.say("Bonjour")

    assert len(bot.users.by_phone) == 1


async def test_unknown_input_falls_back_to_the_menu(bot: Bot) -> None:
    reponse = await bot.say("blablabla")

    assert "Je n'ai pas compris" in reponse


async def test_help(bot: Bot) -> None:
    assert "Aide" in await bot.say("aide")
    assert "Aide" in await bot.say("4")


# --- Création ----------------------------------------------------------------


async def creer_tontine(bot: Bot, *, sender: str = SENDER) -> str:
    await bot.say("Créer une tontine", sender=sender)
    await bot.say("Famille 2026", sender=sender)
    await bot.say("10000", sender=sender)
    await bot.say("1", sender=sender)
    await bot.say("10", sender=sender)
    return await bot.say("confirmer", sender=sender)


async def test_full_creation_walkthrough(bot: Bot) -> None:
    assert "Quel nom" in await bot.say("Créer une tontine")
    assert bot.step() is ConversationStep.CREATE_NAME

    assert "Quel montant" in await bot.say("Famille 2026")
    assert bot.step() is ConversationStep.CREATE_AMOUNT

    assert "fréquence" in await bot.say("10000")
    assert bot.step() is ConversationStep.CREATE_FREQUENCY

    assert "Combien de membres" in await bot.say("1")
    assert bot.step() is ConversationStep.CREATE_MEMBERS

    recap = await bot.say("10")
    assert "Récapitulatif" in recap
    assert "Famille 2026" in recap
    assert "10 000 FCFA" in recap
    assert "Hebdomadaire" in recap
    assert bot.step() is ConversationStep.CREATE_CONFIRM

    cree = await bot.say("confirmer")
    assert "Tontine créée" in cree
    assert "KFT-" in cree
    assert bot.step() is None, "l'état doit être clos après création"
    assert len(bot.tontines.tontines) == 1


async def test_amount_accepts_usual_notations(bot: Bot) -> None:
    await bot.say("Créer une tontine")
    await bot.say("Famille 2026")
    await bot.say("10 000")

    assert bot.step() is ConversationStep.CREATE_FREQUENCY
    state = bot.conversations.states[bot.user_id()]
    assert state.data["amount"] == 10000


@pytest.mark.parametrize("saisie", ["beaucoup", "0", "-100", "100,50", ""])
async def test_invalid_amount_keeps_the_state(bot: Bot, saisie: str) -> None:
    await bot.say("Créer une tontine")
    await bot.say("Famille 2026")
    version_avant = bot.conversations.states[bot.user_id()].version

    reponse = await bot.say(saisie)

    assert "montant" in reponse.lower()
    assert bot.step() is ConversationStep.CREATE_AMOUNT, "l'étape ne doit pas reculer"
    assert bot.conversations.states[bot.user_id()].version == version_avant
    assert bot.conversations.states[bot.user_id()].data["name"] == "Famille 2026"


@pytest.mark.parametrize("saisie", ["A", "", "   "])
async def test_invalid_name_keeps_the_state(bot: Bot, saisie: str) -> None:
    await bot.say("Créer une tontine")

    reponse = await bot.say(saisie)

    assert "nom" in reponse.lower()
    assert bot.step() is ConversationStep.CREATE_NAME


@pytest.mark.parametrize("saisie", ["tous les jours", "5", "jamais"])
async def test_invalid_frequency_keeps_the_state(bot: Bot, saisie: str) -> None:
    await bot.say("Créer une tontine")
    await bot.say("Famille 2026")
    await bot.say("10000")

    reponse = await bot.say(saisie)

    assert "1" in reponse and "2" in reponse
    assert bot.step() is ConversationStep.CREATE_FREQUENCY


@pytest.mark.parametrize("saisie", ["1", "0", "101", "beaucoup"])
async def test_invalid_member_count_keeps_the_state(bot: Bot, saisie: str) -> None:
    await bot.say("Créer une tontine")
    await bot.say("Famille 2026")
    await bot.say("10000")
    await bot.say("1")

    reponse = await bot.say(saisie)

    assert "membres" in reponse.lower()
    assert bot.step() is ConversationStep.CREATE_MEMBERS


async def test_four_is_a_valid_member_count_not_the_help_shortcut(bot: Bot) -> None:
    """Régression : « 4 » ne doit pas déclencher l'aide au milieu du formulaire."""
    await bot.say("Créer une tontine")
    await bot.say("Famille 2026")
    await bot.say("10000")
    await bot.say("2")

    reponse = await bot.say("4")

    assert "Récapitulatif" in reponse
    assert "4 membres" in reponse


async def test_monthly_frequency(bot: Bot) -> None:
    await bot.say("Créer une tontine")
    await bot.say("Collègues")
    await bot.say("25000")
    await bot.say("2")
    await bot.say("5")

    recap = await bot.say("valider")

    assert "Tontine créée" in recap
    tontine = next(iter(bot.tontines.tontines.values()))
    assert tontine.frequency.value == "MONTHLY"


async def test_refusing_the_summary_shows_it_again(bot: Bot) -> None:
    await bot.say("Créer une tontine")
    await bot.say("Famille 2026")
    await bot.say("10000")
    await bot.say("1")
    await bot.say("10")

    reponse = await bot.say("hmm")

    assert "Récapitulatif" in reponse
    assert bot.step() is ConversationStep.CREATE_CONFIRM
    assert bot.tontines.tontines == {}


# --- Commandes globales ------------------------------------------------------


@pytest.mark.parametrize(
    "etape",
    ["Créer une tontine", "Famille 2026", "10000", "1", "10"],
)
async def test_cancel_works_at_every_step(bot: Bot, etape: str) -> None:
    messages = ["Créer une tontine", "Famille 2026", "10000", "1", "10"]
    for message in messages[: messages.index(etape) + 1]:
        await bot.say(message)

    reponse = await bot.say("annuler")

    assert "annulée" in reponse.lower()
    assert bot.step() is None
    assert bot.tontines.tontines == {}


async def test_menu_leaves_the_workflow(bot: Bot) -> None:
    await bot.say("Créer une tontine")
    await bot.say("Famille 2026")

    reponse = await bot.say("menu")

    assert "Que souhaitez-vous faire" in reponse
    assert bot.step() is None


async def test_help_does_not_destroy_the_workflow(bot: Bot) -> None:
    await bot.say("Créer une tontine")
    await bot.say("Famille 2026")

    reponse = await bot.say("aide")

    assert "Aide" in reponse
    assert bot.step() is ConversationStep.CREATE_AMOUNT, "l'aide ne doit rien effacer"


# --- Expiration --------------------------------------------------------------


async def test_expired_state_is_treated_as_absent(bot: Bot) -> None:
    await bot.say("Créer une tontine")
    await bot.say("Famille 2026")
    bot.conversations.expire(bot.user_id())

    reponse = await bot.say("10000")

    assert "Je n'ai pas compris" in reponse, "l'état expiré ne doit pas être repris"


async def test_a_new_workflow_can_start_after_expiry(bot: Bot) -> None:
    await bot.say("Créer une tontine")
    bot.conversations.expire(bot.user_id())

    reponse = await bot.say("Créer une tontine")

    assert "Quel nom" in reponse


# --- Concurrence de la machine à états ---------------------------------------


async def test_two_concurrent_transitions_only_one_wins(bot: Bot) -> None:
    """Deux messages lisent la même version : une seule transition l'emporte."""
    await bot.say("Créer une tontine")
    user_id = bot.user_id()
    state = bot.conversations.states[user_id]

    premier = await bot.conversations.transition(
        state, step=ConversationStep.CREATE_AMOUNT, data={"name": "Premier"}
    )
    second = await bot.conversations.transition(
        state, step=ConversationStep.CREATE_AMOUNT, data={"name": "Second"}
    )

    assert premier is not None
    assert second is None, "la version périmée doit être refusée"
    assert bot.conversations.states[user_id].data["name"] == "Premier"
    assert bot.conversations.states[user_id].version == state.version + 1


async def test_conflict_is_explained_to_the_user(bot: Bot) -> None:
    await bot.say("Créer une tontine")
    user_id = bot.user_id()
    state = bot.conversations.states[user_id]
    # Un autre message a déjà fait avancer l'état.
    await bot.conversations.transition(
        state, step=ConversationStep.CREATE_AMOUNT, data={"name": "Deja"}
    )

    reponse = await bot.service._step_create_name(state, "Trop tard")

    assert "croisés" in reponse
    assert bot.conversations.states[user_id].data["name"] == "Deja"


async def test_two_confirmations_create_only_one_tontine(bot: Bot) -> None:
    await bot.say("Créer une tontine")
    await bot.say("Famille 2026")
    await bot.say("10000")
    await bot.say("1")
    await bot.say("10")
    state = bot.conversations.states[bot.user_id()]

    premier = await bot.say("confirmer")
    # Le second message porte la même version : le compare-and-swap le refuse.
    second = await bot.service._step_create_confirm(
        state, "confirmer", bot.users.by_phone["+22900000000"], correlation_id="c2"
    )

    assert "Tontine créée" in premier
    assert "croisés" in second
    assert len(bot.tontines.tontines) == 1


# --- Adhésion ----------------------------------------------------------------


async def test_join_walkthrough(bot: Bot) -> None:
    await creer_tontine(bot)
    code = next(iter(bot.tontines.tontines.values())).invite_code

    assert "code d'invitation" in (await bot.say("rejoindre", sender=AUTRE)).lower()
    apercu = await bot.say(code, sender=AUTRE)
    assert "Famille 2026" in apercu
    assert "10 000 FCFA" in apercu

    rejoint = await bot.say("rejoindre", sender=AUTRE)
    assert "Vous avez rejoint" in rejoint
    assert "2/10 membres" in rejoint


async def test_join_accepts_a_sloppy_code(bot: Bot) -> None:
    await creer_tontine(bot)
    code = next(iter(bot.tontines.tontines.values())).invite_code
    saisie = code.removeprefix("KFT-").lower()

    await bot.say("rejoindre", sender=AUTRE)
    apercu = await bot.say(f"  {saisie} ", sender=AUTRE)

    assert "Famille 2026" in apercu


async def test_malformed_code_keeps_the_state(bot: Bot) -> None:
    await bot.say("rejoindre")

    reponse = await bot.say("XXX")

    assert "format" in reponse
    assert bot.step() is ConversationStep.JOIN_CODE


async def test_unknown_code_keeps_the_state(bot: Bot) -> None:
    await bot.say("rejoindre")

    reponse = await bot.say("KFT-A7P3Q9")

    assert "Aucune tontine" in reponse
    assert bot.step() is ConversationStep.JOIN_CODE


async def test_joining_twice_is_refused(bot: Bot) -> None:
    await creer_tontine(bot)
    code = next(iter(bot.tontines.tontines.values())).invite_code

    await bot.say("rejoindre", sender=AUTRE)
    await bot.say(code, sender=AUTRE)
    await bot.say("rejoindre", sender=AUTRE)

    await bot.say("rejoindre", sender=AUTRE)
    await bot.say(code, sender=AUTRE)
    reponse = await bot.say("rejoindre", sender=AUTRE)

    assert "déjà membre" in reponse


async def test_joining_a_full_tontine_is_refused(bot: Bot) -> None:
    await creer_tontine(bot)
    tontine = next(iter(bot.tontines.tontines.values()))
    bot.tontines.fill(tontine.id)

    await bot.say("rejoindre", sender=AUTRE)
    await bot.say(tontine.invite_code, sender=AUTRE)
    reponse = await bot.say("rejoindre", sender=AUTRE)

    assert "nombre de membres" in reponse


async def test_joining_a_closed_tontine_is_refused(bot: Bot) -> None:
    await creer_tontine(bot)
    tontine = next(iter(bot.tontines.tontines.values()))

    await bot.say("rejoindre", sender=AUTRE)
    await bot.say(tontine.invite_code, sender=AUTRE)
    bot.tontines.close(tontine.id)
    reponse = await bot.say("rejoindre", sender=AUTRE)

    assert "n'accepte plus" in reponse


# --- Mes tontines ------------------------------------------------------------


async def test_no_tontines_yet(bot: Bot) -> None:
    reponse = await bot.say("mes tontines")

    assert "aucune tontine" in reponse.lower()


async def test_listing_shows_the_invite_code_to_the_owner_only(bot: Bot) -> None:
    await creer_tontine(bot)
    code = next(iter(bot.tontines.tontines.values())).invite_code
    await bot.say("rejoindre", sender=AUTRE)
    await bot.say(code, sender=AUTRE)
    await bot.say("rejoindre", sender=AUTRE)

    vue_owner = await bot.say("mes tontines")
    vue_membre = await bot.say("mes tontines", sender=AUTRE)

    assert "Famille 2026" in vue_owner
    assert "10 000 FCFA / semaine" in vue_owner
    assert "2/10 membres" in vue_owner
    assert code in vue_owner, "le propriétaire voit le code"

    assert "Famille 2026" in vue_membre
    assert code not in vue_membre, "un simple membre ne voit pas le code"


async def test_rollback_when_owner_membership_fails(bot: Bot) -> None:
    """Si le membership OWNER échoue, aucune tontine ne doit subsister."""
    bot.tontines.fail_owner_membership = True
    await bot.say("Créer une tontine")
    await bot.say("Famille 2026")
    await bot.say("10000")
    await bot.say("1")
    await bot.say("10")

    with pytest.raises(RuntimeError):
        await bot.say("confirmer")

    assert bot.tontines.tontines == {}
    assert bot.tontines.members == {}
