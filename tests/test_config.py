import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_are_local() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "local"
    assert settings.is_production is False
    assert settings.mongodb_database == "kefrico_tontine"


def test_meta_variables_stay_optional_even_in_production() -> None:
    """La Phase 0 ne contient aucune intégration WhatsApp : rien ne doit bloquer."""
    settings = Settings(
        environment="production",
        mongodb_uri="mongodb://cluster.example.net:27017/?replicaSet=rs0",
        _env_file=None,
    )

    assert settings.is_production is True
    assert settings.meta_app_secret is None
    assert settings.whatsapp_access_token is None


def test_empty_meta_variable_is_treated_as_absent() -> None:
    settings = Settings(meta_verify_token="   ", _env_file=None)

    assert settings.meta_verify_token is None


def test_production_refuses_a_localhost_database() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            mongodb_uri="mongodb://localhost:27017/?directConnection=true",
            _env_file=None,
        )


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="prod", _env_file=None)
