"""Génération et normalisation des codes d'invitation."""

import secrets

PREFIX = "KFT-"
LENGTH = 6
#: Alphabet sans I, O, 0, 1 ni L : ces caractères se confondent quand un code
#: est lu à voix haute ou recopié depuis un écran de téléphone.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
#: 31**6 ≈ 887 millions de combinaisons.
MAX_GENERATION_ATTEMPTS = 5


def generate_invite_code() -> str:
    """Code aléatoire cryptographiquement sûr.

    ``secrets`` et non ``random`` : un code prédictible permettrait de
    parcourir les tontines d'autrui.
    """
    suffix = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    return f"{PREFIX}{suffix}"


def normalize_invite_code(raw: str) -> str | None:
    """Normalise une saisie utilisateur. ``None`` si elle ne peut pas être un code.

    ``kft a7p3q9``, ``a7p3q9`` et ``KFT-A7P3Q9`` donnent tous le même code.
    """
    compact = "".join(raw.split()).upper().replace("-", "").replace("_", "")
    if compact.startswith("KFT"):
        compact = compact[3:]
    if len(compact) != LENGTH or any(character not in ALPHABET for character in compact):
        return None
    return f"{PREFIX}{compact}"
