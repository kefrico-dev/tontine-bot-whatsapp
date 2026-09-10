"""Configuration de l'application, validée au démarrage."""

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

#: Variables sans lesquelles le canal WhatsApp ne peut pas fonctionner.
WHATSAPP_REQUIRED_FIELDS = (
    "meta_verify_token",
    "meta_app_secret",
    "whatsapp_access_token",
    "whatsapp_phone_number_id",
)


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

    # --- Meta / WhatsApp -----------------------------------------------------
    # Optionnelles en local et en staging : l'application doit pouvoir démarrer
    # sans WhatsApp pour servir /health et faire tourner les tests. Obligatoires
    # en production : une production sans WhatsApp répondrait 503 à chaque
    # message reçu, autant refuser de démarrer.
    meta_verify_token: str | None = None
    meta_app_secret: str | None = None
    whatsapp_access_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_business_account_id: str | None = None

    #: Unique endroit où la version de l'API Graph est définie.
    whatsapp_api_version: str = "v25.0"
    graph_base_url: str = "https://graph.facebook.com"

    #: Budget d'un appel sortant vers Meta, en secondes.
    whatsapp_timeout_s: float = Field(default=10.0, gt=0, le=60)

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

    @field_validator("whatsapp_api_version")
    @classmethod
    def _check_api_version(cls, value: str) -> str:
        if not value.startswith("v"):
            raise ValueError("WHATSAPP_API_VERSION doit ressembler à « v25.0 ».")
        return value

    @model_validator(mode="after")
    def _check_production_requirements(self) -> "Settings":
        """Fail fast : ce qui est indispensable en production doit être présent."""
        if self.environment != "production":
            return self

        if "localhost" in self.mongodb_uri or "127.0.0.1" in self.mongodb_uri:
            raise ValueError(
                "MONGODB_URI doit désigner une instance distante en production, pas localhost."
            )

        manquantes = [name.upper() for name in WHATSAPP_REQUIRED_FIELDS if not getattr(self, name)]
        if manquantes:
            raise ValueError(
                "Configuration WhatsApp incomplète en production : " + ", ".join(manquantes)
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def whatsapp_configured(self) -> bool:
        """Vrai si le canal WhatsApp dispose de tout ce qu'il lui faut."""
        return all(getattr(self, name) for name in WHATSAPP_REQUIRED_FIELDS)

    @property
    def whatsapp_messages_url(self) -> str:
        """Endpoint d'envoi Meta — seul endroit où l'URL complète est construite."""
        return (
            f"{self.graph_base_url.rstrip('/')}"
            f"/{self.whatsapp_api_version}"
            f"/{self.whatsapp_phone_number_id}/messages"
        )


@lru_cache
def get_settings() -> Settings:
    """Configuration mise en cache : lue une seule fois par processus."""
    return Settings()
