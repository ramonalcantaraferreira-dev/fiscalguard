"""Tratamento padronizado de erros: toda resposta de erro segue o mesmo formato.

    {"error": {"code": "...", "message": "...", "details": ...}}
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import errors as pg
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException

log = logging.getLogger("fiscalguard")


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


class NotFound(AppError):
    def __init__(self, what: str = "Recurso"):
        super().__init__(404, "not_found", f"{what} não encontrado")


class Forbidden(AppError):
    def __init__(self, message: str = "Permissão insuficiente"):
        super().__init__(403, "forbidden", message)


class Conflict(AppError):
    def __init__(self, message: str, details: Any = None):
        super().__init__(409, "conflict", message, details)


class Invalid(AppError):
    def __init__(self, message: str, details: Any = None):
        super().__init__(422, "invalid", message, details)


def _body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


_DB_ERRORS: list[tuple[type[Exception], int, str, str]] = [
    (pg.InsufficientPrivilege, 403, "forbidden", "Operação não permitida para este usuário"),
    (pg.UniqueViolation, 409, "conflict", "Registro duplicado"),
    (pg.ForeignKeyViolation, 422, "invalid_reference", "Referência inválida ou de outra organização"),
    (pg.CheckViolation, 422, "invalid", "Dados violam uma regra de integridade"),
    (pg.NotNullViolation, 422, "invalid", "Campo obrigatório ausente"),
    (pg.InvalidTextRepresentation, 422, "invalid", "Formato de dado inválido"),
    (pg.NoDataFound, 404, "not_found", "Registro não encontrado"),
]
_EXPOSE_MESSAGE = (pg.CheckViolation, pg.NoDataFound)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, exc: HTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(exc.status_code, "http_error")
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        details = [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(_body("validation_error", "Requisição inválida", details), status_code=422)

    @app.exception_handler(DBAPIError)
    async def _db_error(_: Request, exc: DBAPIError):
        for cls, status, code, message in _DB_ERRORS:
            if isinstance(exc.orig, cls):
                # Mensagens levantadas pelas nossas funções/triggers são seguras para expor.
                detail = str(exc.orig.diag.message_primary) if isinstance(exc.orig, _EXPOSE_MESSAGE) else None
                return JSONResponse(_body(code, message, detail), status_code=status)
        log.exception("Erro de banco não tratado")
        return JSONResponse(_body("internal_error", "Erro interno"), status_code=500)
