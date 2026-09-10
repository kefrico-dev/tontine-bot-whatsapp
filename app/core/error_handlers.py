"""Handlers d'exception : réponses uniformes, sans fuite d'information."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.core.middleware import get_correlation_id
from app.schemas.common import ErrorResponse

logger = get_logger(__name__)


def _error_response(request: Request, *, status_code: int, code: str, message: str) -> JSONResponse:
    payload = ErrorResponse(
        code=code,
        message=message,
        correlation_id=get_correlation_id(request),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # pragma: no cover - garde-fou de typage
        return await unhandled_exception_handler(request, exc)
    logger.warning("app_error", code=exc.error_code, status_code=exc.status_code)
    return _error_response(
        request,
        status_code=exc.status_code,
        code=exc.error_code,
        message=exc.message,
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover
        return await unhandled_exception_handler(request, exc)
    return _error_response(
        request,
        status_code=exc.status_code,
        code="http_error",
        message=str(exc.detail),
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # pragma: no cover
        return await unhandled_exception_handler(request, exc)
    logger.info("request_validation_error", path=request.url.path)
    return _error_response(
        request,
        status_code=422,
        code="validation_error",
        message="Requête invalide.",
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Dernier filet de sécurité : on logue tout, on n'expose rien."""
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        correlation_id=get_correlation_id(request),
        exc_info=exc,
    )
    return _error_response(
        request,
        status_code=500,
        code="internal_error",
        message="Une erreur interne est survenue.",
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
