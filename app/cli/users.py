"""Console user commands. These accounts log into the web UI, not into Campus."""

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
from app.schemas import UserIn, UserUpdateIn
from app.users import (
    EmailTakenError,
    UserRecord,
    create_user,
    delete_user,
    get_user,
    get_user_by_email,
    list_users,
    update_user,
)


def user_dict(user: UserRecord) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def resolve_user(token: str) -> UserRecord:
    text = (token or "").strip()
    found = get_user_by_email(text) if "@" in text else get_user(text)
    if found is None and "@" not in text:
        found = get_user_by_email(text)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Пользователь {token} не найден")
    return found


def cmd_list(ctx: Ctx, args: argparse.Namespace) -> None:
    users, _cursor = list_users(q=args.q or "")
    emit_table(
        ctx,
        [user_dict(user) for user in users],
        [("id", "id"), ("email", "email"), ("name", "имя")],
        empty="Пользователей нет",
    )


def cmd_get(ctx: Ctx, args: argparse.Namespace) -> None:
    user = resolve_user(args.user)
    emit_result(ctx, user.email, user_dict(user))


def cmd_add(ctx: Ctx, args: argparse.Namespace) -> None:
    password = read_secret(args.password, "Пароль")
    body = UserIn(email=args.email, password=password, name=args.name or "")
    try:
        user = create_user(body.email, body.password, body.name)
    except EmailTakenError as exc:
        raise CliError(f"Email уже занят: {exc}") from exc
    emit_result(ctx, "создан", user_dict(user))


def cmd_update(ctx: Ctx, args: argparse.Namespace) -> None:
    current = resolve_user(args.user)
    if args.email is None and args.name is None and not args.password:
        raise CliError("Нечего менять: укажите --email, --name или --password")
    body = UserUpdateIn(
        email=args.email or current.email,
        name=current.name if args.name is None else args.name,
        password=args.password or "",
    )
    try:
        saved = update_user(
            current.id,
            email=body.email,
            name=body.name,
            password=body.password,
        )
    except EmailTakenError as exc:
        raise CliError(f"Email уже занят: {exc}") from exc
    if saved is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    emit_result(ctx, "обновлён", user_dict(saved))


def cmd_delete(ctx: Ctx, args: argparse.Namespace) -> None:
    user = resolve_user(args.user)
    require_yes(args.yes, f"пользователя {user.email}")
    if not delete_user(user.id):
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    emit_result(ctx, "удалён", {"id": user.id, "email": user.email})


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("users", help="Пользователи веб-консоли")
    commands = parser.add_subparsers(dest="action", required=True)

    listed = commands.add_parser("list", help="Список")
    listed.add_argument("--q", default="", help="Поиск по email или имени")
    listed.set_defaults(func=cmd_list)

    one = commands.add_parser("get", help="Один пользователь по id или email")
    one.add_argument("user")
    one.set_defaults(func=cmd_get)

    add = commands.add_parser("add", help="Создать пользователя")
    add.add_argument("--email", required=True)
    add.add_argument("--password", default="", help="Минимум 8 символов. Иначе спросит")
    add.add_argument("--name", default="")
    add.set_defaults(func=cmd_add)

    update = commands.add_parser("update", help="Изменить email, имя или пароль")
    update.add_argument("user", help="id или email")
    update.add_argument("--email", default=None)
    update.add_argument("--name", default=None)
    update.add_argument(
        "--password", default="", help="Новый пароль, минимум 8 символов"
    )
    update.set_defaults(func=cmd_update)

    delete = commands.add_parser("delete", help="Удалить пользователя")
    delete.add_argument("user", help="id или email")
    delete.add_argument("--yes", action="store_true", help="Подтвердить удаление")
    delete.set_defaults(func=cmd_delete)
