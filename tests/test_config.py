import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_are_local() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "local"
    assert settings.is_production is False
    assert settings.mongodb_database == "kefrico_tontine"


def test_meta_variables_stay_optional_outside_production() -> None:
    """En local et en staging, l'application doit démarrer sans WhatsApp.

    La règle diffère en production depuis la Phase 1 : voir
    ``test_production_requires_the_whatsapp_credentials``.
    """
    for environment in ("local", "staging"):
        settings = Settings(environment=environment, _env_file=None)

        assert settings.meta_app_secret is None
        assert settings.whatsapp_access_token is None
        assert settings.whatsapp_configured is False


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


# --- Configuration WhatsApp ---------------------------------------------------


def test_whatsapp_is_optional_in_local() -> None:
    settings = Settings(environment="local", _env_file=None)

    assert settings.whatsapp_configured is False


def test_production_requires_the_whatsapp_credentials() -> None:
    """Une production sans WhatsApp repondrait 503 a chaque message : refus de demarrer."""
    with pytest.raises(ValidationError) as raised:
        Settings(
            environment="production",
            mongodb_uri="mongodb://cluster.example.net:27017/",
            meta_verify_token="v",
            _env_file=None,
        )

    message = str(raised.value)
    assert "META_APP_SECRET" in message
    assert "WHATSAPP_ACCESS_TOKEN" in message
    assert "WHATSAPP_PHONE_NUMBER_ID" in message


def test_production_starts_when_whatsapp_is_complete() -> None:
    settings = Settings(
        environment="production",
        mongodb_uri="mongodb+srv://cluster.example.net/",
        meta_verify_token="v",
        meta_app_secret="s",
        whatsapp_access_token="t",
        whatsapp_phone_number_id="123",
        _env_file=None,
    )

    assert settings.whatsapp_configured is True
    # WHATSAPP_BUSINESS_ACCOUNT_ID reste facultatif : inutile pour envoyer ou recevoir.
    assert settings.whatsapp_business_account_id is None


def test_business_account_id_stays_optional_in_production() -> None:
    settings = Settings(
        environment="production",
        mongodb_uri="mongodb+srv://cluster.example.net/",
        meta_verify_token="v",
        meta_app_secret="s",
        whatsapp_access_token="t",
        whatsapp_phone_number_id="123",
        _env_file=None,
    )

    assert settings.is_production is True


def test_api_version_is_centralised_in_the_url() -> None:
    settings = Settings(
        whatsapp_api_version="v25.0", whatsapp_phone_number_id="999", _env_file=None
    )

    assert settings.whatsapp_messages_url == "https://graph.facebook.com/v25.0/999/messages"


def test_api_version_must_look_like_a_graph_version() -> None:
    with pytest.raises(ValidationError):
        Settings(whatsapp_api_version="25.0", _env_file=None)
