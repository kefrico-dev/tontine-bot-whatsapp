"""Configuration de l'application, validée au démarrage."""

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Configuration lue depuis l'environnement (ou un fichier .env local)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---------------------------------------------------------
    app_name: str = "KEFRICO Tontine"
    app_version: str = "0.1.0"
    environment: Environment = "local"
    log_level: LogLevel = "INFO"

    # --- MongoDB -------------------------------------------------------------
    mongodb_uri: str = "mongodb://localhost:27017/?directConnection=true"
    mongodb_database: str = "kefrico_tontine"
    # 5 s : une résolution SRV (MongoDB Atlas) suivie de la sélection du
    # serveur dépasse régulièrement 2 s au premier appel.
    mongodb_timeout_ms: int = Field(default=5000, ge=100, le=30_000)

    # --- Meta / WhatsApp — Phase 1 -------------------------------------------
    # Volontairement optionnelles : la Phase 0 ne contient aucune intégration
    # WhatsApp, une fondation ne doit pas refuser de démarrer pour une
    # configuration qui appartient à la phase suivante.
    meta_verify_token: str | None = None
    meta_app_secret: str | None = None
    whatsapp_access_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_business_account_id: str | None = None

    @field_validator(
        "meta_verify_token",
        "meta_app_secret",
        "whatsapp_access_token",
        "whatsapp_phone_number_id",
        "whatsapp_business_account_id",
        mode="before",
    )
    @classmethod
    def _empty_string_is_none(cls, value: Any) -> Any:
        """Une variable présente mais vide dans .env vaut « non configurée »."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _check_production_requirements(self) -> "Settings":
        """Fail fast : en production, MongoDB doit pointer ailleurs que sur localhost."""
        if self.environment == "production" and (
            "localhost" in self.mongodb_uri or "127.0.0.1" in self.mongodb_uri
        ):
            raise ValueError(
                "MONGODB_URI doit désigner une instance distante en production, pas localhost."
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Configuration mise en cache : lue une seule fois par processus."""
    return Settings()
