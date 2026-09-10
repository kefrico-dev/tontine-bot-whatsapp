"""Vérification cryptographique des requêtes Meta.

Aucune fonction de ce module ne logue quoi que ce soit : elle manipule le
secret applicatif et le verify token.
"""

import hashlib
import hmac

SIGNATURE_HEADER = "X-Hub-Signature-256"
SIGNATURE_PREFIX = "sha256="


def compute_signature(*, secret: str, payload: bytes) -> str:
    """Signature attendue pour un corps brut donné, préfixe Meta inclus."""
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(*, secret: str, payload: bytes, header: str | None) -> bool:
    """Valide l'en-tête ``X-Hub-Signature-256`` sur le corps **brut** reçu.

    Le corps doit être exactement celui transmis par Meta : recalculer la
    signature sur un JSON re-sérialisé la ferait échouer sur un simple écart
    d'espacement ou d'ordre des clés.
    """
    if not header:
        return False
    expected = compute_signature(secret=secret, payload=payload)
    # Comparaison à temps constant, préfixe compris.
    return hmac.compare_digest(expected, header)


def verify_token_matches(*, provided: str | None, expected: str) -> bool:
    """Compare le verify token de Meta au nôtre, à temps constant."""
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)
