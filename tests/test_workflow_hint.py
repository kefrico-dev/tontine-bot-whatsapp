"""Non-régression : la sortie d'un workflow doit toujours être visible.

Défaut observé lors de l'acceptance réelle du 11 septembre 2026 : `menu` et
`annuler` fonctionnaient parfaitement, mais rien à l'écran ne révélait leur
existence. Techniquement l'utilisateur pouvait sortir ; humainement il ne
pouvait pas le deviner.
"""

import pytest

from app.modules.conversations import texts
from app.modules.conversations.schemas import ConversationStep
from tests.test_conversation_flow import SENDER, Bot

#: Toute question posée pendant un workflow doit rappeler comment en sortir.
QUESTIONS_DE_WORKFLOW = [
    texts.ask_name(),
    texts.ask_amount("Famille 2026"),
    texts.ask_frequency(),
    texts.ask_members(),
    texts.invalid_name(),
    texts.invalid_amount(),
    texts.invalid_frequency(),
    texts.invalid_members(),
    texts.ask_invite_code(),
    texts.invalid_invite_code(),
    texts.unknown_invite_code(),
]


@pytest.mark.parametrize("texte", QUESTIONS_DE_WORKFLOW)
def test_every_workflow_prompt_shows_the_way_out(texte: str) -> None:
    assert "menu" in texte
    assert "annuler" in texte


@pytest.mark.parametrize(
    "texte",
    [
        texts.creation_summary(
            name="Famille 2026", amount=10000, frequency=texts.Frequency.WEEKLY, expected_members=3
        ),
    ],
)
def test_summaries_already_offer_an_exit(texte: str) -> None:
    """Les récapitulatifs proposent déjà explicitement d'annuler."""
    assert "annuler" in texte


async def test_the_hint_is_visible_at_every_real_step() -> None:
    """Parcours complet : chaque réponse du bot doit porter le rappel."""
    bot = Bot()
    etapes = [
        ("Créer une tontine", ConversationStep.CREATE_NAME),
        ("Famille 2026", ConversationStep.CREATE_AMOUNT),
        ("10000", ConversationStep.CREATE_FREQUENCY),
        ("1", ConversationStep.CREATE_MEMBERS),
    ]
    for message, etape_attendue in etapes:
        reponse = await bot.say(message, sender=SENDER)
        assert bot.step() is etape_attendue
        assert texts.WORKFLOW_HINT in reponse, f"rappel absent apres « {message} »"

    # Le récapitulatif clôt la saisie : il propose « annuler » dans son texte.
    recap = await bot.say("3", sender=SENDER)
    assert "annuler" in recap


async def test_an_invalid_answer_still_shows_the_way_out() -> None:
    """C'est justement quand l'utilisateur se trompe qu'il doit pouvoir sortir."""
    bot = Bot()
    await bot.say("Créer une tontine")
    await bot.say("Famille 2026")

    reponse = await bot.say("beaucoup")

    assert texts.WORKFLOW_HINT in reponse
    assert bot.step() is ConversationStep.CREATE_AMOUNT
