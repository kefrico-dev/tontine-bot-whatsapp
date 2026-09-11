"""Règles d'autorisation des tontines.

Centralisées ici plutôt que dispersées en ``if role == ...`` dans les
services et les réponses conversationnelles. La Phase 2 n'en contient que
deux ; l'important est qu'elles aient déjà un seul endroit où vivre.
"""

from app.modules.tontines.schemas import MemberRole

#: Rôles autorisés à administrer une tontine.
ADMIN_ROLES = frozenset({MemberRole.OWNER, MemberRole.ADMIN})


def can_view_invite_code(role: MemberRole) -> bool:
    """Seule l'administration diffuse le code d'invitation."""
    return role in ADMIN_ROLES


def can_view_tontine(role: MemberRole) -> bool:
    """Tout membre actif consulte sa tontine."""
    return role in {MemberRole.OWNER, MemberRole.ADMIN, MemberRole.MEMBER}
