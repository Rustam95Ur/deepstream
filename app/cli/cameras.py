"""Camera commands."""

from __future__ import annotations

import argparse
from typing import Any

from app.cli.console import Ctx, emit_result, emit_table, parse_meta, require_yes
from app.schemas import CameraIn, CameraOut, CameraPatch
from app.services.cameras import (
    create_test_batch,
    delete_camera,
    get_camera,
    list_cameras,
    patch_camera,
    upsert_camera,
)
from app.trigger_types import TRIGGER_TYPES, normalize_enabled_triggers

_TRIGGER_HELP = (
    "Типы через запятую: "
    + ", ".join(TRIGGER_TYPES)
    + ". Пустой список — --no-triggers."
)


def camera_dict(cam: CameraOut) -> dict[str, Any]:
    data = cam.model_dump(mode="json")
    data.pop("uri", None)
    data.pop("rtsp_url", None)
    return data


def parse_triggers(raw: str) -> list[str]:
    from app.cli.console import CliError

    parts = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if not parts or raw.strip().lower() in {"none", "-"}:
        return []
    known = set(TRIGGER_TYPES)
    unknown = [part for part in parts if part not in known]
    if unknown:
        raise CliError(
            "неизвестные типы: "
            + ", ".join(unknown)
            + ". Допустимо: "
            + ", ".join(TRIGGER_TYPES)
        )
    return normalize_enabled_triggers(parts)


def triggers_value(args: argparse.Namespace) -> list[str] | None:
    """None means inherit node settings."""
    if getattr(args, "no_triggers", False):
        return []
    if getattr(args, "inherit_triggers", False):
        return None
    raw = getattr(args, "triggers", None)
    if raw:
        return parse_triggers(raw)
    return None


def _enabled_filter(raw: str | None) -> bool | None:
    if raw is None:
        return None
    return raw == "true"


def cmd_list(ctx: Ctx, args: argparse.Namespace) -> None:
    from app.cli.console import CliError

    if args.limit is not None and not 1 <= args.limit <= 500:
        raise CliError("--limit от 1 до 500")
    page = list_cameras(
        q=args.q or "",
        enabled=_enabled_filter(args.enabled),
        cursor=args.cursor or "",
        limit=args.limit,
    )
    rows = [camera_dict(cam) for cam in page.cameras]
    emit_table(
        ctx,
        rows,
        [
            ("id", "id"),
            ("name", "имя"),
            ("enabled", "вкл"),
            ("main_uri", "uri"),
            ("external_id", "external"),
            ("enabled_triggers", "триггеры"),
        ],
        empty="Камер нет",
        extra={"next_cursor": page.next_cursor, "node_id": page.node_id},
    )


def cmd_get(ctx: Ctx, args: argparse.Namespace) -> None:
    emit_result(ctx, args.id, camera_dict(get_camera(args.id)))


def cmd_add(ctx: Ctx, args: argparse.Namespace) -> None:
    from app.cli.console import CliError
    from app.storage import get_store

    body = CameraIn(
        id=args.id or "",
        name=args.name or "",
        main_uri=args.uri,
        enabled=not args.disabled,
        external_id=args.external_id or "",
        meta=parse_meta(args.meta) or {},
        enabled_triggers=triggers_value(args),
    )
    store = get_store()
    cam_id = (body.id or body.external_id or "").strip()
    if cam_id and store.get_camera(cam_id):
        raise CliError(f"Камера {cam_id} уже есть. Для изменений: cameras update")
    cam, created = upsert_camera(body)
    emit_result(ctx, "создана" if created else "обновлена", camera_dict(cam))


def cmd_update(ctx: Ctx, args: argparse.Namespace) -> None:
    from app.cli.console import CliError

    patch: dict[str, Any] = {}
    if args.name is not None:
        patch["name"] = args.name
    if args.uri is not None:
        patch["main_uri"] = args.uri
    if args.external_id is not None:
        patch["external_id"] = args.external_id
    if args.enabled:
        patch["enabled"] = True
    elif args.disabled:
        patch["enabled"] = False
    meta = parse_meta(args.meta)
    if meta is not None:
        patch["meta"] = meta
    triggers_set = bool(args.triggers) or args.no_triggers or args.inherit_triggers
    if triggers_set:
        patch["enabled_triggers"] = triggers_value(args)
    if not patch:
        raise CliError("Нечего менять: укажите хотя бы один флаг")
    cam = patch_camera(args.id, CameraPatch.model_validate(patch))
    emit_result(ctx, "обновлена", camera_dict(cam))


def cmd_enable(ctx: Ctx, args: argparse.Namespace) -> None:
    cam = patch_camera(args.id, CameraPatch.model_validate({"enabled": True}))
    emit_result(ctx, "включена", camera_dict(cam))


def cmd_disable(ctx: Ctx, args: argparse.Namespace) -> None:
    cam = patch_camera(args.id, CameraPatch.model_validate({"enabled": False}))
    emit_result(ctx, "выключена", camera_dict(cam))


def cmd_delete(ctx: Ctx, args: argparse.Namespace) -> None:
    require_yes(args.yes, f"камеры {args.id}")
    delete_camera(args.id)
    emit_result(ctx, "удалена", {"id": args.id})


def cmd_test(ctx: Ctx, args: argparse.Namespace) -> None:
    from app.cli.console import CliError

    if args.count < 1 or args.count > 128:
        raise CliError("--count от 1 до 128")
    batch = create_test_batch(main_uri=args.uri, count=args.count)
    rows = [camera_dict(cam) for cam in batch.cameras]
    if ctx.as_json:
        from app.cli.console import emit_json

        emit_json({"result": "created", "created": batch.created, "items": rows})
        return
    print(f"создано: {batch.created}")
    emit_table(
        ctx,
        rows,
        [("id", "id"), ("name", "имя"), ("main_uri", "uri")],
        empty="Ничего не создано",
    )


def _triggers(parser: argparse.ArgumentParser, *, inherit: bool) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--triggers", metavar="LIST", help=_TRIGGER_HELP)
    group.add_argument(
        "--no-triggers",
        action="store_true",
        help="На этой камере не запускать ни один тип",
    )
    if inherit:
        group.add_argument(
            "--inherit-triggers",
            action="store_true",
            help="Снова брать типы из настроек ноды",
        )


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "cameras", help="Камеры: список, создание, правка, удаление"
    )
    commands = parser.add_subparsers(dest="action", required=True)

    listed = commands.add_parser("list", help="Список камер")
    listed.add_argument("--q", default="", help="Поиск по id, имени или URI")
    listed.add_argument(
        "--enabled",
        choices=("true", "false"),
        default=None,
        help="Только включённые или только выключенные",
    )
    listed.add_argument("--limit", type=int, default=None, help="Размер страницы")
    listed.add_argument("--cursor", default="", help="Курсор следующей страницы")
    listed.set_defaults(func=cmd_list)

    one = commands.add_parser("get", help="Одна камера")
    one.add_argument("id", help="id камеры")
    one.set_defaults(func=cmd_get)

    add = commands.add_parser("add", help="Создать камеру")
    add.add_argument("--uri", required=True, help="rtsp:// или file://")
    add.add_argument("--id", default="", help="Стабильный id. Иначе будет назначен")
    add.add_argument("--name", default="", help="Имя. По умолчанию совпадает с id")
    add.add_argument("--external-id", default="", help="id камеры на стороне Campus")
    add.add_argument("--disabled", action="store_true", help="Создать выключенной")
    add.add_argument(
        "--meta",
        default="",
        help='Доп. поля JSON, например {"fps":25,"resolution_width":1280}',
    )
    _triggers(add, inherit=False)
    add.set_defaults(func=cmd_add, inherit_triggers=False)

    update = commands.add_parser("update", help="Изменить существующую камеру")
    update.add_argument("id")
    update.add_argument("--uri", default=None)
    update.add_argument("--name", default=None)
    update.add_argument("--external-id", default=None)
    state = update.add_mutually_exclusive_group()
    state.add_argument("--enabled", action="store_true", help="Включить")
    state.add_argument("--disabled", action="store_true", help="Выключить")
    update.add_argument(
        "--meta", default="", help="JSON-объект, поля допишутся к текущим"
    )
    _triggers(update, inherit=True)
    update.set_defaults(func=cmd_update)

    enable = commands.add_parser("enable", help="Включить камеру")
    enable.add_argument("id")
    enable.set_defaults(func=cmd_enable)

    disable = commands.add_parser(
        "disable", help="Выключить камеру и убрать её из пайплайна"
    )
    disable.add_argument("id")
    disable.set_defaults(func=cmd_disable)

    delete = commands.add_parser("delete", help="Удалить камеру")
    delete.add_argument("id")
    delete.add_argument("--yes", action="store_true", help="Подтвердить удаление")
    delete.set_defaults(func=cmd_delete)

    test = commands.add_parser(
        "test", help="Создать несколько тестовых камер на один URI"
    )
    test.add_argument("--uri", required=True, help="rtsp:// или file://")
    test.add_argument(
        "--count", type=int, required=True, help="Сколько камер, от 1 до 128"
    )
    test.set_defaults(func=cmd_test)
