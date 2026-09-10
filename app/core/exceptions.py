"""Exceptions métier.

Toute erreur attendue doit être une sous-classe explicite d'``AppError`` :
le message porté par l'exception est destiné à l'utilisateur, jamais le détail
interne. Les exceptions métier des tontines arriveront avec leurs modules.
"""


class AppError(Exception):
    """Erreur attendue de l'application, traduisible en réponse HTTP."""

    status_code: int = 500
    error_code: str = "internal_error"
    message: str = "Une erreur interne est survenue."

    def __init__(self, message: str | None = None) -> None:
        if message is not None:
            self.message = message
        super().__init__(self.message)


class ServiceUnavailableError(AppError):
    """Une dépendance externe indispensable est indisponible."""

    status_code = 503
    error_code = "service_unavailable"
    message = "Service temporairement indisponible."
