"""Turn FastAPI errors into a single string for the console UI."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("nexus_deepstream")


def _loc(parts: object) -> str:
    if not isinstance(parts, (list, tuple)):
        return ""
    return ".".join(str(p) for p in parts if p not in {"body", "query", "path"})


def format_validation_errors(errors: list[object]) -> str:
    msgs: list[str] = []
    for item in errors:
        if not isinstance(item, dict):
            msgs.append(str(item))
            continue
        where = _loc(item.get("loc"))
        msg = str(item.get("msg") or "некорректное значение")
        msgs.append(f"{where}: {msg}" if where else msg)
    return "; ".join(msgs) or "Некорректные данные"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": format_validation_errors(list(exc.errors()))},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": detail},
            headers=dict(exc.headers or {}),
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("%s %s", request.method, request.url.path)
        text = str(exc).strip() or type(exc).__name__
        return JSONResponse(status_code=500, content={"detail": text})
