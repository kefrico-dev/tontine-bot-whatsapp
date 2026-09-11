"""Normalisation des identifiants WhatsApp.

⚠️ Portée volontairement étroite : cette fonction normalise un ``wa_id``
fourni par Meta, qui est **déjà** un numéro international valide. Ce n'est
**pas** un validateur de numéros de téléphone universel et elle ne doit pas
être utilisée comme tel. La validation d'un numéro saisi librement par un
utilisateur relèvera d'un autre mécanisme, le jour où ce besoin existera.
"""


def normalize_whatsapp_phone(wa_id: str) -> str:
    """Transforme un ``wa_id`` Meta en identifiant canonique ``+<chiffres>``.

    Meta transmet ``22997818212`` ; nous stockons ``+22997818212``.
    """
    digits = "".join(character for character in wa_id if character.isdigit())
    if len(digits) < 6:
        raise ValueError("Identifiant WhatsApp inexploitable.")
    return f"+{digits}"


def mask(phone: str) -> str:
    """Numéro tronqué pour les logs : seuls les 4 derniers chiffres restent."""
    digits = "".join(character for character in phone if character.isdigit())
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]
