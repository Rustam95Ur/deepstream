"""Shared CLI output, errors, and process bootstrap."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError


class CliError(Exception):
    """Operator-facing failure. Printed without a traceback."""


@dataclass
class Ctx:
    as_json: bool = False


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


def prepare() -> None:
    """Logging to stderr, then schema migrations. Commands talk to Postgres directly."""
    from app.db import init_db
    from app.logging_config import configure_logging

    level = (os.environ.get("NEXUS_DS_LOG_LEVEL") or "WARNING").strip() or "WARNING"
    configure_logging(service="nexus-deepstream", role="cli", level=level)
    try:
        init_db()
    except Exception as exc:
        logging.getLogger(__name__).debug("init_db failed", exc_info=True)
        raise CliError(f"База недоступна: {exc}") from exc


def fail(ctx: Ctx | None, message: str, code: int = 1) -> None:
    if ctx is not None and ctx.as_json:
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
    else:
        print(message, file=sys.stderr)
    raise SystemExit(code)


def http_detail(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, str):
        return detail
    return json.dumps(detail, ensure_ascii=False)


def validation_detail(exc: ValidationError) -> str:
    lines: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc") or ())
        msg = str(err.get("msg") or "неверное значение")
        lines.append(f"{loc}: {msg}" if loc else msg)
    return "\n".join(lines) or "неверные данные"


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def cell(value: Any) -> str:
    if isinstance(value, bool):
        return "да" if value else "нет"
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value).replace("\n", " ")


def shorten(value: Any, limit: int = 72) -> str:
    text = cell(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def emit_json(data: Any) -> None:
    print(dumps(data))


def emit_kv(ctx: Ctx, data: dict[str, Any]) -> None:
    if ctx.as_json:
        emit_json(data)
        return
    if not data:
        print("(пусто)")
        return
    width = max(len(str(key)) for key in data)
    for key, value in data.items():
        print(f"{str(key).ljust(width)}  {cell(value)}")


def emit_result(ctx: Ctx, result: str, data: dict[str, Any]) -> None:
    if ctx.as_json:
        emit_json({"result": result, **data})
        return
    print(result)
    emit_kv(ctx, data)


def emit_table(
    ctx: Ctx,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    *,
    empty: str = "пусто",
    extra: dict[str, Any] | None = None,
) -> None:
    if ctx.as_json:
        payload: dict[str, Any] = {"items": rows}
        if extra:
            payload.update(extra)
        emit_json(payload)
        return
    if not rows:
        print(empty)
    else:
        headers = [title for _key, title in columns]
        body = [[shorten(row.get(key, "")) for key, _title in columns] for row in rows]
        widths = [len(header) for header in headers]
        for line in body:
            for index, item in enumerate(line):
                widths[index] = max(widths[index], len(item))

        def paint(cells: list[str]) -> str:
            return "  ".join(item.ljust(widths[i]) for i, item in enumerate(cells))

        print(paint(headers))
        print(paint(["-" * width for width in widths]))
        for line in body:
            print(paint(line))
    if extra and extra.get("next_cursor"):
        print(f"\nдальше: --cursor {extra['next_cursor']}")


def read_secret(value: str | None, label: str) -> str:
    secret = value or ""
    if secret:
        return secret
    if not sys.stdin.isatty():
        raise CliError(f"Укажите {label} флагом --password: ввод не интерактивный")
    import getpass

    first = getpass.getpass(f"{label}: ")
    second = getpass.getpass(f"{label} ещё раз: ")
    if not first:
        raise CliError("Пароль пустой")
    if first != second:
        raise CliError("Пароли не совпали")
    return first


def parse_meta(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliError(f"meta: не JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise CliError("meta: нужен JSON-объект {...}")
    return data


def require_yes(flag: bool, what: str) -> None:
    if not flag:
        raise CliError(f"Удаление {what} необратимо. Повторите команду с --yes")
