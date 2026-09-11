"""Routeur de commandes déterministe.

Aucune IA : une table de correspondances, insensible à la casse et aux
accents. Il ne cherche pas à comprendre le français, seulement à reconnaître
un petit vocabulaire fixe.
"""

import unicodedata
from enum import StrEnum


class Command(StrEnum):
    # Commandes globales, prioritaires sur tout workflow en cours.
    CANCEL = "CANCEL"
    MENU = "MENU"
    HELP = "HELP"

    # Commandes du menu principal, reconnues au repos uniquement.
    GREETING = "GREETING"
    CREATE_TONTINE = "CREATE_TONTINE"
    MY_TONTINES = "MY_TONTINES"
    JOIN_TONTINE = "JOIN_TONTINE"

    # Réponse de confirmation d'un récapitulatif.
    CONFIRM = "CONFIRM"

    UNKNOWN = "UNKNOWN"


#: Ces commandes court-circuitent l'étape en cours, quelle qu'elle soit.
#: Corollaire assumé : leurs libellés sont des mots réservés et ne peuvent pas
#: servir de réponse métier — on ne peut pas nommer une tontine « annuler ».
#: Les chiffres en sont volontairement absents : « 4 » doit pouvoir être un
#: nombre de membres, pas un raccourci vers l'aide au milieu d'un formulaire.
_GLOBAL_KEYWORDS: dict[Command, frozenset[str]] = {
    Command.CANCEL: frozenset({"annuler", "annule", "cancel", "stop", "abandonner"}),
    Command.MENU: frozenset({"menu", "accueil", "retour"}),
    Command.HELP: frozenset({"aide", "help", "?"}),
}

#: Reconnues uniquement au repos, jamais pendant un workflow.
_MENU_KEYWORDS: dict[Command, frozenset[str]] = {
    Command.GREETING: frozenset({"bonjour", "bonsoir", "salut", "hello", "hi", "coucou"}),
    Command.CREATE_TONTINE: frozenset(
        {"creer", "creer une tontine", "creer tontine", "nouvelle tontine", "creation"}
    ),
    Command.MY_TONTINES: frozenset(
        {"mes tontines", "mes tontine", "ma tontine", "tontines", "liste"}
    ),
    Command.JOIN_TONTINE: frozenset({"rejoindre", "rejoindre une tontine", "rejoindre tontine"}),
}

#: Raccourcis numériques du menu, valables au repos seulement.
_MENU_DIGITS: dict[str, Command] = {
    "1": Command.CREATE_TONTINE,
    "2": Command.MY_TONTINES,
    "3": Command.JOIN_TONTINE,
    "4": Command.HELP,
}

_CONFIRM_WORDS = frozenset({"confirmer", "confirme", "oui", "ok", "valider", "rejoindre", "1"})


def normalize_text(raw: str) -> str:
    """Minuscules, sans accents, espaces normalisés."""
    lowered = raw.strip().lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    without_accents = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " ".join(without_accents.split())


def parse_global_command(raw: str) -> Command | None:
    """Commande globale éventuelle, à tester avant toute logique d'étape."""
    text = normalize_text(raw)
    for command, keywords in _GLOBAL_KEYWORDS.items():
        if text in keywords:
            return command
    return None


def parse_menu_command(raw: str) -> Command:
    """Commande du menu principal. ``UNKNOWN`` si la saisie n'en est pas une."""
    text = normalize_text(raw)
    if not text:
        return Command.UNKNOWN

    global_command = parse_global_command(raw)
    if global_command is not None:
        return global_command

    if text in _MENU_DIGITS:
        return _MENU_DIGITS[text]

    for command, keywords in _MENU_KEYWORDS.items():
        if text in keywords:
            return command
    return Command.UNKNOWN


def is_confirmation(raw: str) -> bool:
    """Vrai si la saisie vaut acceptation d'un récapitulatif."""
    return normalize_text(raw) in _CONFIRM_WORDS
