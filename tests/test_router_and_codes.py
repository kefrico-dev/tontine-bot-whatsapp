"""Routeur de commandes, codes d'invitation et validation des montants."""

import pytest
from pydantic import ValidationError

from app.modules.conversations.router import (
    Command,
    is_confirmation,
    normalize_text,
    parse_global_command,
    parse_menu_command,
)
from app.modules.tontines.invite_code import (
    ALPHABET,
    LENGTH,
    PREFIX,
    generate_invite_code,
    normalize_invite_code,
)
from app.modules.tontines.schemas import Frequency, TontineDraft
from app.modules.users.phone import mask, normalize_whatsapp_phone

# --- Routeur -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("saisie", "attendu"),
    [
        ("annuler", Command.CANCEL),
        ("ANNULER", Command.CANCEL),
        ("  Annuler  ", Command.CANCEL),
        ("stop", Command.CANCEL),
        ("menu", Command.MENU),
        ("Menu", Command.MENU),
        ("aide", Command.HELP),
        ("AIDE", Command.HELP),
        ("help", Command.HELP),
    ],
)
def test_global_commands_are_recognised(saisie: str, attendu: Command) -> None:
    assert parse_global_command(saisie) is attendu


@pytest.mark.parametrize("saisie", ["1", "2", "3", "4", "Famille 2026", "10000", ""])
def test_non_global_inputs_are_not_intercepted(saisie: str) -> None:
    """Un chiffre doit pouvoir être une réponse métier, pas un raccourci."""
    assert parse_global_command(saisie) is None


@pytest.mark.parametrize(
    ("saisie", "attendu"),
    [
        ("1", Command.CREATE_TONTINE),
        ("creer une tontine", Command.CREATE_TONTINE),
        ("Créer une tontine", Command.CREATE_TONTINE),
        ("CRÉER UNE TONTINE", Command.CREATE_TONTINE),
        ("2", Command.MY_TONTINES),
        ("mes tontines", Command.MY_TONTINES),
        ("Mes Tontines", Command.MY_TONTINES),
        ("3", Command.JOIN_TONTINE),
        ("rejoindre", Command.JOIN_TONTINE),
        ("4", Command.HELP),
        ("bonjour", Command.GREETING),
        ("Bonsoir", Command.GREETING),
        ("n'importe quoi", Command.UNKNOWN),
        ("", Command.UNKNOWN),
    ],
)
def test_menu_commands(saisie: str, attendu: Command) -> None:
    assert parse_menu_command(saisie) is attendu


def test_accents_are_ignored() -> None:
    assert normalize_text("Créér  UNE   Tontiné") == "creer une tontine"


@pytest.mark.parametrize("saisie", ["confirmer", "Confirmer", "oui", "OK", "valider", "rejoindre"])
def test_confirmations(saisie: str) -> None:
    assert is_confirmation(saisie) is True


@pytest.mark.parametrize("saisie", ["non", "peut-etre", "plus tard", ""])
def test_non_confirmations(saisie: str) -> None:
    assert is_confirmation(saisie) is False


# --- Codes d'invitation ------------------------------------------------------


def test_generated_code_has_the_expected_shape() -> None:
    code = generate_invite_code()

    assert code.startswith(PREFIX)
    assert len(code) == len(PREFIX) + LENGTH
    assert all(character in ALPHABET for character in code[len(PREFIX) :])


def test_generated_codes_avoid_ambiguous_characters() -> None:
    """Ni I, ni O, ni 0, ni 1, ni L : ils se confondent à la lecture."""
    codes = "".join(generate_invite_code() for _ in range(300))

    for ambigu in "IO01L":
        assert ambigu not in codes[len(PREFIX) :].replace(PREFIX, "")


def test_generated_codes_are_not_sequential() -> None:
    codes = {generate_invite_code() for _ in range(200)}

    assert len(codes) == 200, "un generateur previsible produirait des collisions"


@pytest.mark.parametrize(
    ("saisie", "attendu"),
    [
        ("KFT-A7P3Q9", "KFT-A7P3Q9"),
        ("kft-a7p3q9", "KFT-A7P3Q9"),
        ("kft a7p3q9", "KFT-A7P3Q9"),
        ("A7P3Q9", "KFT-A7P3Q9"),
        ("  a7p3q9  ", "KFT-A7P3Q9"),
        ("KFT_A7P3Q9", "KFT-A7P3Q9"),
    ],
)
def test_invite_code_normalisation(saisie: str, attendu: str) -> None:
    assert normalize_invite_code(saisie) == attendu


@pytest.mark.parametrize(
    "saisie", ["", "KFT-", "TROPCOURT", "KFT-A7P3Q", "KFT-A7P3Q90", "KFT-AIO01"]
)
def test_invalid_invite_codes_are_rejected(saisie: str) -> None:
    assert normalize_invite_code(saisie) is None


# --- Numéros -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("saisie", "attendu"),
    [
        ("22997818212", "+22997818212"),
        ("+22997818212", "+22997818212"),
        ("229 97 81 82 12", "+22997818212"),
        ("+229-97-81-82-12", "+22997818212"),
    ],
)
def test_phone_normalisation(saisie: str, attendu: str) -> None:
    assert normalize_whatsapp_phone(saisie) == attendu


def test_unusable_identifier_is_rejected() -> None:
    with pytest.raises(ValueError, match="inexploitable"):
        normalize_whatsapp_phone("abc")


def test_phone_masking_keeps_only_the_last_digits() -> None:
    assert mask("+22997818212") == "*******8212"
    assert mask("12") == "**"


# --- Validation des tontines -------------------------------------------------


def valid_draft(**overrides: object) -> TontineDraft:
    values: dict[str, object] = {
        "name": "Famille 2026",
        "contribution_amount": 10000,
        "frequency": Frequency.WEEKLY,
        "expected_members": 10,
    }
    values.update(overrides)
    return TontineDraft(**values)  # type: ignore[arg-type]


def test_valid_draft() -> None:
    draft = valid_draft()

    assert draft.contribution_amount == 10000
    assert draft.currency.value == "XOF"


@pytest.mark.parametrize("amount", [0, -1, -10000])
def test_non_positive_amounts_are_refused(amount: int) -> None:
    with pytest.raises(ValidationError):
        valid_draft(contribution_amount=amount)


def test_decimal_amount_is_refused() -> None:
    """Le franc CFA n'a pas de centimes : un décimal serait une ambiguïté."""
    with pytest.raises(ValidationError):
        valid_draft(contribution_amount=100.50)


def test_integer_valued_float_is_accepted() -> None:
    assert valid_draft(contribution_amount=10000.0).contribution_amount == 10000


def test_excessive_amount_is_refused() -> None:
    with pytest.raises(ValidationError):
        valid_draft(contribution_amount=10_000_000_000)


@pytest.mark.parametrize("members", [0, 1, -5, 101, 1000])
def test_invalid_member_counts_are_refused(members: int) -> None:
    with pytest.raises(ValidationError):
        valid_draft(expected_members=members)


@pytest.mark.parametrize("name", ["", "A", "   ", "x" * 61])
def test_invalid_names_are_refused(name: str) -> None:
    with pytest.raises(ValidationError):
        valid_draft(name=name)


def test_name_is_trimmed() -> None:
    assert valid_draft(name="  Famille   2026  ").name == "Famille 2026"


def test_invalid_frequency_is_refused() -> None:
    with pytest.raises(ValidationError):
        valid_draft(frequency="QUOTIDIENNE")
