"""Webhook commands."""

from __future__ import annotations

import argparse
from typing import Any

from fastapi import HTTPException

from app.cli.console import (
    CliError,
    Ctx,
    emit_result,
    emit_table,
    read_secret,
    require_yes,
)
from app.schemas import WebhookIn
from app.webhooks import (
    Webhook,
    create_webhook,
    delete_webhook,
    get_webhook,
    list_webhooks,
    update_webhook,
)


def webhook_dict(hook: Webhook) -> dict[str, Any]:
    return {
        "id": hook.id,
        "name": hook.name,
        "url": hook.url,
        "enabled": hook.enabled,
        "login": hook.login,
        "auth_configured": hook.auth_configured,
        "timeout_sec": hook.timeout_sec,
        "max_retries": hook.max_retries,
        "created_at": hook.created_at,
        "updated_at": hook.updated_at,
    }


def _require(hook: Webhook | None, webhook_id: str) -> Webhook:
    if hook is None:
        raise HTTPException(status_code=404, detail=f"Webhook {webhook_id} не найден")
    return hook


def _save(
    hook: Webhook,
    *,
    name: str | None = None,
    url: str | None = None,
    enabled: bool | None = None,
    login: str | None = None,
    password: str | None = None,
    timeout_sec: float | None = None,
    max_retries: int | None = None,
) -> Webhook:
    next_login = hook.login if login is None else login
    body = WebhookIn(
        name=hook.name if name is None else name,
        url=hook.url if url is None else url,
        enabled=hook.enabled if enabled is None else enabled,
        login=next_login,
        password=password,
        timeout_sec=hook.timeout_sec if timeout_sec is None else timeout_sec,
        max_retries=hook.max_retries if max_retries is None else max_retries,
    )
    if next_login and not hook.auth_configured and not body.password:
        raise CliError("Для нового логина нужен --password (минимум 8 символов)")
    saved = update_webhook(
        hook.id,
        name=body.name,
        url=body.url,
        enabled=body.enabled,
        timeout_sec=body.timeout_sec,
        max_retries=body.max_retries,
        login=None if login is None else body.login,
        password=body.password,
    )
    return _require(saved, hook.id)


def cmd_list(ctx: Ctx, _args: argparse.Namespace) -> None:
    rows = [webhook_dict(hook) for hook in list_webhooks()]
    emit_table(
        ctx,
        rows,
        [
            ("id", "id"),
            ("name", "имя"),
            ("enabled", "вкл"),
            ("url", "url"),
            ("login", "логин"),
            ("auth_configured", "пароль"),
        ],
        empty="Webhook нет",
    )


def cmd_get(ctx: Ctx, args: argparse.Namespace) -> None:
    emit_result(ctx, args.id, webhook_dict(_require(get_webhook(args.id), args.id)))


def cmd_add(ctx: Ctx, args: argparse.Namespace) -> None:
    password = read_secret(args.password, "Пароль webhook")
    body = WebhookIn(
        name=args.name or "",
        url=args.url,
        enabled=not args.disabled,
        login=args.login,
        password=password,
        timeout_sec=args.timeout,
        max_retries=args.retries,
    )
    if not body.login:
        raise CliError("Укажите --login. Им Campus запрашивает список камер")
    if not body.password:
        raise CliError("Укажите --password (минимум 8 символов)")
    hook = create_webhook(
        name=body.name,
        url=body.url,
        enabled=body.enabled,
        login=body.login,
        password=body.password,
        timeout_sec=body.timeout_sec,
        max_retries=body.max_retries,
    )
    emit_result(ctx, "создан", webhook_dict(hook))


def cmd_update(ctx: Ctx, args: argparse.Namespace) -> None:
    hook = _require(get_webhook(args.id), args.id)
    enabled: bool | None = None
    if args.enabled:
        enabled = True
    elif args.disabled:
        enabled = False
    changed = any(
        value is not None
        for value in (
            args.name,
            args.url,
            args.login,
            args.password,
            args.timeout,
            args.retries,
            enabled,
        )
    )
    if not changed:
        raise CliError("Нечего менять: укажите хотя бы один флаг")
    saved = _save(
        hook,
        name=args.name,
        url=args.url,
        enabled=enabled,
        login=args.login,
        password=args.password,
        timeout_sec=args.timeout,
        max_retries=args.retries,
    )
    emit_result(ctx, "обновлён", webhook_dict(saved))


def cmd_enable(ctx: Ctx, args: argparse.Namespace) -> None:
    hook = _require(get_webhook(args.id), args.id)
    emit_result(ctx, "включён", webhook_dict(_save(hook, enabled=True)))


def cmd_disable(ctx: Ctx, args: argparse.Namespace) -> None:
    hook = _require(get_webhook(args.id), args.id)
    emit_result(ctx, "выключен", webhook_dict(_save(hook, enabled=False)))


def cmd_delete(ctx: Ctx, args: argparse.Namespace) -> None:
    require_yes(args.yes, f"webhook {args.id}")
    if not delete_webhook(args.id):
        raise HTTPException(status_code=404, detail=f"Webhook {args.id} не найден")
    emit_result(ctx, "удалён", {"id": args.id})


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("webhooks", help="Куда слать события и логин входящего API")
    commands = parser.add_subparsers(dest="action", required=True)

    listed = commands.add_parser("list", help="Список webhook")
    listed.set_defaults(func=cmd_list)

    one = commands.add_parser("get", help="Один webhook")
    one.add_argument("id")
    one.set_defaults(func=cmd_get)

    add = commands.add_parser("add", help="Создать webhook")
    add.add_argument("--url", required=True, help="http:// или https://")
    add.add_argument(
        "--login", required=True, help="Логин, которым Campus ходит в API камер"
    )
    add.add_argument("--password", default="", help="Минимум 8 символов. Иначе спросит")
    add.add_argument("--name", default="", help="Короткое имя")
    add.add_argument(
        "--timeout", type=float, default=5.0, help="Таймаут запроса, секунды"
    )
    add.add_argument(
        "--retries", type=int, default=5, help="Сколько повторов после ошибки"
    )
    add.add_argument("--disabled", action="store_true", help="Создать выключенным")
    add.set_defaults(func=cmd_add)

    update = commands.add_parser("update", help="Изменить webhook")
    update.add_argument("id")
    update.add_argument("--url", default=None)
    update.add_argument("--name", default=None)
    update.add_argument("--login", default=None)
    update.add_argument(
        "--password", default=None, help="Новый пароль, минимум 8 символов"
    )
    update.add_argument("--timeout", type=float, default=None)
    update.add_argument("--retries", type=int, default=None)
    state = update.add_mutually_exclusive_group()
    state.add_argument("--enabled", action="store_true")
    state.add_argument("--disabled", action="store_true")
    update.set_defaults(func=cmd_update)

    enable = commands.add_parser("enable", help="Включить webhook")
    enable.add_argument("id")
    enable.set_defaults(func=cmd_enable)

    disable = commands.add_parser("disable", help="Выключить webhook")
    disable.add_argument("id")
    disable.set_defaults(func=cmd_disable)

    delete = commands.add_parser("delete", help="Удалить webhook")
    delete.add_argument("id")
    delete.add_argument("--yes", action="store_true", help="Подтвердить удаление")
    delete.set_defaults(func=cmd_delete)
