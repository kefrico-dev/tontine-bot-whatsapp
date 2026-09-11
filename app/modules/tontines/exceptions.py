"""Exceptions métier des tontines.

Ces erreurs sont **fonctionnelles** : elles décrivent un refus légitime, pas
une panne. Elles ne doivent jamais être rejouées comme un conflit technique
de transaction.
"""

from app.core.exceptions import AppError


class TontineNotFound(AppError):
    status_code = 404
    error_code = "tontine_not_found"
    message = "Aucune tontine ne correspond à ce code."


class TontineClosed(AppError):
    status_code = 409
    error_code = "tontine_closed"
    message = "Cette tontine n'accepte plus de nouveaux membres."


class TontineFull(AppError):
    status_code = 409
    error_code = "tontine_full"
    message = "Cette tontine a déjà atteint son nombre de membres."


class AlreadyMember(AppError):
    status_code = 409
    error_code = "already_member"
    message = "Vous êtes déjà membre de cette tontine."


class InviteCodeGenerationFailed(AppError):
    status_code = 500
    error_code = "invite_code_generation_failed"
    message = "Impossible de générer un code d'invitation."


#: Erreurs métier : jamais retentées par le mécanisme de transaction.
BUSINESS_ERRORS = (
    TontineNotFound,
    TontineClosed,
    TontineFull,
    AlreadyMember,
)
