"""Service applicatif des tontines."""

from app.core.logging import get_logger
from app.modules.tontines.repository import TontineRepository
from app.modules.tontines.schemas import Tontine, TontineDraft, TontineMembership

logger = get_logger(__name__)


class TontineService:
    def __init__(self, repository: TontineRepository) -> None:
        self._repository = repository

    async def create(
        self, *, draft: TontineDraft, owner_id: str, correlation_id: str | None
    ) -> Tontine:
        tontine = await self._repository.create_with_owner(draft=draft, owner_id=owner_id)
        logger.info(
            "TONTINE_CREATED",
            correlation_id=correlation_id,
            resource_id=tontine.id,
            actor_user_id=owner_id,
            frequency=tontine.frequency.value,
            expected_members=tontine.expected_members,
        )
        return tontine

    async def join(self, *, invite_code: str, user_id: str, correlation_id: str | None) -> Tontine:
        tontine = await self._repository.join_by_code(invite_code=invite_code, user_id=user_id)
        logger.info(
            "MEMBER_JOINED",
            correlation_id=correlation_id,
            resource_id=tontine.id,
            actor_user_id=user_id,
            active_members=tontine.active_members_count,
        )
        return tontine

    async def preview(self, *, invite_code: str) -> Tontine | None:
        """Tontine correspondant à un code, sans adhérer."""
        return await self._repository.find_by_invite_code(invite_code)

    async def list_for_user(self, user_id: str) -> list[TontineMembership]:
        return await self._repository.list_for_user(user_id)
