"""Machine à états conversationnelle.

Seule classe de l'application qui sait qu'on parle de tontines : le webhook et
le service de messagerie restent génériques.
"""

from typing import Any

from pydantic import ValidationError

from app.core.logging import get_logger
from app.modules.conversations import texts
from app.modules.conversations.repository import ConversationRepository
from app.modules.conversations.router import (
    Command,
    is_confirmation,
    normalize_text,
    parse_global_command,
    parse_menu_command,
)
from app.modules.conversations.schemas import ConversationState, ConversationStep
from app.modules.messaging.schemas import InboundWhatsAppMessage
from app.modules.tontines.exceptions import (
    AlreadyMember,
    TontineClosed,
    TontineFull,
    TontineNotFound,
)
from app.modules.tontines.invite_code import normalize_invite_code
from app.modules.tontines.schemas import Frequency, TontineDraft
from app.modules.tontines.service import TontineService
from app.modules.users.schemas import User
from app.modules.users.service import UserService

logger = get_logger(__name__)

_FREQUENCY_CHOICES = {
    "1": Frequency.WEEKLY,
    "hebdomadaire": Frequency.WEEKLY,
    "semaine": Frequency.WEEKLY,
    "2": Frequency.MONTHLY,
    "mensuelle": Frequency.MONTHLY,
    "mensuel": Frequency.MONTHLY,
    "mois": Frequency.MONTHLY,
}


#: Separateurs de milliers tolerés dans une saisie de montant. Les espaces
#: insecables sont designees par leur code point : elles arrivent souvent
#: d'un copier-coller depuis un affichage formate, le notre y compris.
_AMOUNT_SEPARATORS = (" ", ".", "'", chr(0x00A0), chr(0x202F))


def _parse_amount(raw: str) -> int | None:
    """Accepte « 10000 », « 10 000 » et « 10.000 » ; refuse « 100,50 »."""
    compact = raw.strip()
    for separateur in _AMOUNT_SEPARATORS:
        compact = compact.replace(separateur, "")
    if not compact.isdigit():
        return None
    return int(compact)


def _parse_members(raw: str) -> int | None:
    compact = normalize_text(raw).replace(" ", "")
    return int(compact) if compact.isdigit() else None


class ConversationService:
    """Traduit un message entrant en réponse, en s'appuyant sur l'état stocké."""

    def __init__(
        self,
        users: UserService,
        tontines: TontineService,
        conversations: ConversationRepository,
    ) -> None:
        self._users = users
        self._tontines = tontines
        self._conversations = conversations

    async def reply_to(self, message: InboundWhatsAppMessage, *, correlation_id: str | None) -> str:
        user = await self._users.get_or_create_from_whatsapp(
            wa_id=message.sender_phone,
            whatsapp_name=message.sender_name,
            correlation_id=correlation_id,
        )
        text = message.text or ""

        # Les commandes globales priment sur l'étape en cours : un utilisateur
        # ne doit jamais rester prisonnier d'un formulaire.
        global_command = parse_global_command(text)
        if global_command is not None:
            return await self._handle_global(global_command, user)

        state = await self._conversations.get(user.id)
        if state is None or state.step is ConversationStep.IDLE:
            return await self._handle_idle(text, user, correlation_id=correlation_id)

        return await self._handle_step(state, text, user, correlation_id=correlation_id)

    # --- Commandes globales --------------------------------------------------

    async def _handle_global(self, command: Command, user: User) -> str:
        if command is Command.HELP:
            return texts.help_text()
        await self._conversations.clear(user.id)
        return texts.cancelled() if command is Command.CANCEL else texts.menu()

    # --- Au repos ------------------------------------------------------------

    async def _handle_idle(self, text: str, user: User, *, correlation_id: str | None) -> str:
        command = parse_menu_command(text)

        if command is Command.GREETING:
            return texts.welcome()
        if command is Command.HELP:
            return texts.help_text()
        if command is Command.MY_TONTINES:
            return await self._list_tontines(user)
        if command is Command.CREATE_TONTINE:
            started = await self._conversations.begin(
                user_id=user.id, step=ConversationStep.CREATE_NAME, data={}
            )
            return texts.ask_name() if started else texts.conflict_retry()
        if command is Command.JOIN_TONTINE:
            started = await self._conversations.begin(
                user_id=user.id, step=ConversationStep.JOIN_CODE, data={}
            )
            return texts.ask_invite_code() if started else texts.conflict_retry()

        return texts.unknown_command()

    async def _list_tontines(self, user: User) -> str:
        memberships = await self._tontines.list_for_user(user.id)
        return texts.tontine_list(memberships) if memberships else texts.no_tontines()

    # --- Workflows -----------------------------------------------------------

    async def _handle_step(
        self, state: ConversationState, text: str, user: User, *, correlation_id: str | None
    ) -> str:
        match state.step:
            case ConversationStep.CREATE_NAME:
                return await self._step_create_name(state, text)
            case ConversationStep.CREATE_AMOUNT:
                return await self._step_create_amount(state, text)
            case ConversationStep.CREATE_FREQUENCY:
                return await self._step_create_frequency(state, text)
            case ConversationStep.CREATE_MEMBERS:
                return await self._step_create_members(state, text)
            case ConversationStep.CREATE_CONFIRM:
                return await self._step_create_confirm(
                    state, text, user, correlation_id=correlation_id
                )
            case ConversationStep.JOIN_CODE:
                return await self._step_join_code(state, text)
            case ConversationStep.JOIN_CONFIRM:
                return await self._step_join_confirm(
                    state, text, user, correlation_id=correlation_id
                )
            case _:  # pragma: no cover - IDLE traité en amont
                return texts.unknown_command()

    async def _advance(
        self, state: ConversationState, *, step: ConversationStep, data: dict[str, Any], reply: str
    ) -> str:
        """Transition compare-and-swap. Un conflit n'écrase jamais l'état récent."""
        updated = await self._conversations.transition(state, step=step, data=data)
        if updated is None:
            logger.info(
                "conversation_state_conflict",
                user_id=state.user_id,
                step=state.step.value,
                version=state.version,
            )
            return texts.conflict_retry()
        return reply

    async def _step_create_name(self, state: ConversationState, text: str) -> str:
        name = " ".join(text.split())
        if not 2 <= len(name) <= 60:
            return texts.invalid_name()
        return await self._advance(
            state,
            step=ConversationStep.CREATE_AMOUNT,
            data={**state.data, "name": name},
            reply=texts.ask_amount(name),
        )

    async def _step_create_amount(self, state: ConversationState, text: str) -> str:
        amount = _parse_amount(text)
        if amount is None or amount <= 0:
            return texts.invalid_amount()
        return await self._advance(
            state,
            step=ConversationStep.CREATE_FREQUENCY,
            data={**state.data, "amount": amount},
            reply=texts.ask_frequency(),
        )

    async def _step_create_frequency(self, state: ConversationState, text: str) -> str:
        frequency = _FREQUENCY_CHOICES.get(normalize_text(text))
        if frequency is None:
            return texts.invalid_frequency()
        return await self._advance(
            state,
            step=ConversationStep.CREATE_MEMBERS,
            data={**state.data, "frequency": frequency.value},
            reply=texts.ask_members(),
        )

    async def _step_create_members(self, state: ConversationState, text: str) -> str:
        members = _parse_members(text)
        if members is None or not 2 <= members <= 100:
            return texts.invalid_members()
        data = {**state.data, "expected_members": members}
        return await self._advance(
            state,
            step=ConversationStep.CREATE_CONFIRM,
            data=data,
            reply=texts.creation_summary(
                name=data["name"],
                amount=data["amount"],
                frequency=Frequency(data["frequency"]),
                expected_members=members,
            ),
        )

    async def _step_create_confirm(
        self, state: ConversationState, text: str, user: User, *, correlation_id: str | None
    ) -> str:
        if not is_confirmation(text):
            return texts.creation_summary(
                name=state.data["name"],
                amount=state.data["amount"],
                frequency=Frequency(state.data["frequency"]),
                expected_members=state.data["expected_members"],
            )

        try:
            draft = TontineDraft(
                name=state.data["name"],
                contribution_amount=state.data["amount"],
                frequency=Frequency(state.data["frequency"]),
                expected_members=state.data["expected_members"],
            )
        except (ValidationError, KeyError, ValueError):  # pragma: no cover - brouillon corrompu
            await self._conversations.clear(user.id)
            return texts.unknown_command()

        # La clôture précède la création : si deux confirmations se croisent,
        # une seule remporte le compare-and-swap, donc une seule tontine naît.
        if not await self._conversations.finish(state):
            return texts.conflict_retry()

        tontine = await self._tontines.create(
            draft=draft, owner_id=user.id, correlation_id=correlation_id
        )
        return texts.tontine_created(tontine)

    async def _step_join_code(self, state: ConversationState, text: str) -> str:
        code = normalize_invite_code(text)
        if code is None:
            return texts.invalid_invite_code()

        tontine = await self._tontines.preview(invite_code=code)
        if tontine is None:
            return texts.unknown_invite_code()

        return await self._advance(
            state,
            step=ConversationStep.JOIN_CONFIRM,
            data={**state.data, "invite_code": code},
            reply=texts.join_preview(tontine),
        )

    async def _step_join_confirm(
        self, state: ConversationState, text: str, user: User, *, correlation_id: str | None
    ) -> str:
        if not is_confirmation(text):
            tontine = await self._tontines.preview(invite_code=state.data["invite_code"])
            return texts.join_preview(tontine) if tontine else texts.unknown_invite_code()

        if not await self._conversations.finish(state):
            return texts.conflict_retry()

        try:
            tontine = await self._tontines.join(
                invite_code=state.data["invite_code"],
                user_id=user.id,
                correlation_id=correlation_id,
            )
        except TontineFull:
            return texts.tontine_full()
        except AlreadyMember:
            return texts.already_member()
        except TontineClosed:
            return texts.tontine_closed()
        except TontineNotFound:
            return texts.unknown_invite_code()

        return texts.joined(tontine)
