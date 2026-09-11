"""Tous les textes envoyés à l'utilisateur, réunis en un seul endroit."""

from app.modules.tontines.schemas import Frequency, Tontine, TontineMembership

FREQUENCY_LABELS = {
    Frequency.WEEKLY: "Hebdomadaire",
    Frequency.MONTHLY: "Mensuelle",
}
FREQUENCY_PER = {
    Frequency.WEEKLY: "semaine",
    Frequency.MONTHLY: "mois",
}


def format_amount(amount: int, currency: str = "FCFA") -> str:
    """10000 -> « 10 000 FCFA »."""
    return f"{amount:,}".replace(",", " ") + f" {currency}"


def welcome() -> str:
    return (
        "Bienvenue sur KEFRICO Tontine 👋\n\n"
        "Je suis votre assistant pour gérer vos tontines directement depuis WhatsApp.\n\n" + menu()
    )


def menu() -> str:
    return (
        "Que souhaitez-vous faire ?\n\n"
        "1. Créer une tontine\n"
        "2. Mes tontines\n"
        "3. Rejoindre une tontine\n"
        "4. Aide\n\n"
        "Répondez par un numéro ou écrivez votre choix."
    )


def help_text() -> str:
    return (
        "❓ Aide\n\n"
        "Commandes disponibles :\n"
        "• *créer une tontine* — créer une nouvelle tontine\n"
        "• *mes tontines* — voir vos tontines\n"
        "• *rejoindre une tontine* — entrer avec un code d'invitation\n"
        "• *menu* — revenir au menu principal\n"
        "• *annuler* — abandonner l'opération en cours\n\n"
        "Vous pouvez écrire *menu* ou *annuler* à tout moment."
    )


def unknown_command() -> str:
    return "Je n'ai pas compris votre demande.\n\n" + menu()


def cancelled() -> str:
    return "Opération annulée.\n\n" + menu()


def conflict_retry() -> str:
    """Deux messages traités en parallèle ont voulu faire avancer l'échange."""
    return (
        "Vos deux derniers messages se sont croisés et je n'ai pas pu suivre.\n\n"
        "Écrivez *menu* pour repartir sur une base claire."
    )


# --- Création ----------------------------------------------------------------


def ask_name() -> str:
    return "Créons votre tontine.\n\nQuel nom souhaitez-vous lui donner ?"


def ask_amount(name: str) -> str:
    return f"« {name} », très bien.\n\nQuel montant chaque membre cotisera-t-il ? (en FCFA)"


def ask_frequency() -> str:
    return "À quelle fréquence ?\n\n1. Hebdomadaire\n2. Mensuelle\n\nRépondez par 1 ou 2."


def ask_members() -> str:
    return "Combien de membres prévoyez-vous ?"


def invalid_name() -> str:
    return "Ce nom ne convient pas. Il doit contenir entre 2 et 60 caractères.\n\nQuel nom ?"


def invalid_amount() -> str:
    return (
        "Ce montant ne convient pas. Indiquez un nombre entier de francs, "
        "par exemple *10000*.\n\nQuel montant ?"
    )


def invalid_frequency() -> str:
    return "Répondez par *1* pour hebdomadaire ou *2* pour mensuelle."


def invalid_members() -> str:
    return "Indiquez un nombre de membres entre 2 et 100.\n\nCombien de membres ?"


def creation_summary(*, name: str, amount: int, frequency: Frequency, expected_members: int) -> str:
    return (
        "📋 Récapitulatif\n\n"
        f"*{name}*\n"
        f"{expected_members} membres\n"
        f"{format_amount(amount)}\n"
        f"{FREQUENCY_LABELS[frequency]}\n\n"
        "Répondez *confirmer* pour créer, ou *annuler*."
    )


def tontine_created(tontine: Tontine) -> str:
    return (
        "✅ Tontine créée\n\n"
        f"*{tontine.name}*\n"
        f"{format_amount(tontine.contribution_amount)} / "
        f"{FREQUENCY_PER[tontine.frequency]}\n"
        f"{tontine.active_members_count}/{tontine.expected_members} membres\n\n"
        f"Code d'invitation :\n*{tontine.invite_code}*\n\n"
        "Partagez ce code pour que d'autres puissent rejoindre."
    )


# --- Adhésion ----------------------------------------------------------------


def ask_invite_code() -> str:
    return "Entrez le code d'invitation.\n\nExemple : *KFT-A7P3Q9*"


def invalid_invite_code() -> str:
    return "Ce code n'a pas le bon format. Il ressemble à *KFT-A7P3Q9*.\n\nEntrez le code."


def unknown_invite_code() -> str:
    return "Aucune tontine ne correspond à ce code.\n\nVérifiez-le et réessayez, ou écrivez *menu*."


def join_preview(tontine: Tontine) -> str:
    return (
        "Tontine trouvée\n\n"
        f"*{tontine.name}*\n"
        f"{format_amount(tontine.contribution_amount)} / "
        f"{FREQUENCY_PER[tontine.frequency]}\n"
        f"{FREQUENCY_LABELS[tontine.frequency]}\n"
        f"{tontine.active_members_count}/{tontine.expected_members} membres\n\n"
        "Répondez *rejoindre* pour en faire partie, ou *annuler*."
    )


def joined(tontine: Tontine) -> str:
    return (
        "✅ Vous avez rejoint la tontine\n\n"
        f"*{tontine.name}*\n"
        f"{format_amount(tontine.contribution_amount)} / "
        f"{FREQUENCY_PER[tontine.frequency]}\n"
        f"{tontine.active_members_count}/{tontine.expected_members} membres"
    )


def tontine_full() -> str:
    return "Cette tontine a déjà atteint son nombre de membres.\n\n" + menu()


def tontine_closed() -> str:
    return "Cette tontine n'accepte plus de nouveaux membres.\n\n" + menu()


def already_member() -> str:
    return "Vous êtes déjà membre de cette tontine.\n\n" + menu()


# --- Consultation ------------------------------------------------------------


def no_tontines() -> str:
    return "Vous n'êtes encore membre d'aucune tontine.\n\n" + menu()


def tontine_list(memberships: list[TontineMembership]) -> str:
    from app.modules.tontines.permissions import can_view_invite_code

    lignes = ["📋 Vos tontines\n"]
    for index, item in enumerate(memberships, start=1):
        tontine = item.tontine
        lignes.append(f"{index}. *{tontine.name}*")
        lignes.append(
            f"   {format_amount(tontine.contribution_amount)} / {FREQUENCY_PER[tontine.frequency]}"
        )
        lignes.append(
            f"   {tontine.active_members_count}/{tontine.expected_members} membres — "
            f"{tontine.status.value}"
        )
        if can_view_invite_code(item.role):
            lignes.append(f"   Code : {tontine.invite_code}")
        lignes.append("")
    return "\n".join(lignes).rstrip()
