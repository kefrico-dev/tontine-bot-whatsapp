"""Service utilisateurs."""

from app.core.logging import get_logger
from app.modules.users.phone import mask, normalize_whatsapp_phone
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import User

logger = get_logger(__name__)


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    async def get_or_create_from_whatsapp(
        self, *, wa_id: str, whatsapp_name: str | None, correlation_id: str | None
    ) -> User:
        phone = normalize_whatsapp_phone(wa_id)
        user, created = await self._repository.get_or_create(
            phone=phone, whatsapp_name=whatsapp_name
        )
        if created:
            logger.info(
                "USER_CREATED",
                correlation_id=correlation_id,
                resource_id=user.id,
                actor_user_id=user.id,
                phone=mask(user.phone),
            )
        return user
