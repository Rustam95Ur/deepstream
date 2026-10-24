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


def _health_for_problems():
    from app.pipeline_status import attach_status
    from app.storage import get_store
    from app.video_client import video_health

    store = get_store()
    health = video_health()
    health.pipeline = attach_status(
        health.pipeline, store.list_cameras(), store.get_settings()
    )
    return health


def cmd_errors(ctx: Ctx, args: argparse.Namespace) -> None:
    import sys

    from app.cli.console import emit_json
    from app.services.camera_problems import describe_camera, is_fault
    from app.storage import get_store

    health = _health_for_problems()
    view = health if health.status == "ok" else None
    if args.id:
        cameras = [get_camera(args.id)]
    else:
        cameras = [cam for cam in get_store().list_cameras() if cam.enabled]
    rows = [describe_camera(cam, view) for cam in cameras]
    faults = [row for row in rows if is_fault(row["problem"])]
    shown = faults if not args.id else rows
    payload = {
        "ok": not faults,
        "errors": len(faults),
        "cameras": len(rows),
        "items": shown,
    }
    if not view and not ctx.as_json:
        detail = (health.pipeline.detail or health.pipeline.last_error or "").strip()
        if detail:
            print(detail, file=sys.stderr)
    if ctx.as_json:
        emit_json(payload)
    elif not shown:
        print("ошибок нет" if cameras else "Камер нет")
    elif args.id:
        row = shown[0]
        emit_result(
            ctx,
            row["problem"] or "поток в порядке",
            {
                "id": row["id"],
                "name": row["name"],
                "uri": row["uri"],
                "detect": row["detect"],
                "record": row["record"],
                "last_error": row["last_error"],
            },
        )
    else:
        emit_table(
            ctx,
            shown,
            [
                ("id", "id"),
                ("name", "имя"),
                ("detect", "детекция"),
                ("record", "запись"),
                ("problem", "что не так"),
            ],
            clip=160,
        )
        print(f"ошибки: {len(faults)} из {len(rows)}")
    if faults:
        raise SystemExit(1)


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


def cmd_webhook(ctx: Ctx, args: argparse.Namespace) -> None:
    """Same incident as the console button, for chosen cameras or the whole registry."""
    from fastapi import HTTPException

    from app.cli.console import CliError, emit_json, http_detail
    from app.services.camera_webhook import send_current_stream
    from app.storage import get_store

    ids = [item.strip() for item in args.ids if item.strip()]
    if args.all and ids:
        raise CliError("Укажите либо id камер, либо --all")
    if args.enabled and not args.all:
        raise CliError("--enabled работает только вместе с --all")
    if args.all:
        require_yes(args.yes, "всех камер в вебхук")
        cameras = get_store().list_cameras()
        if args.enabled:
            cameras = [cam for cam in cameras if cam.enabled]
        ids = [cam.id for cam in cameras]
    else:
        seen: set[str] = set()
        unique: list[str] = []
        for cam_id in ids:
            if cam_id not in seen:
                seen.add(cam_id)
                unique.append(cam_id)
        ids = unique
    if not ids:
        raise CliError("Нечего отправлять: укажите id или --all")

    results: list[dict[str, object]] = []
    total = len(ids)
    for index, cam_id in enumerate(ids, start=1):
        if not ctx.as_json:
            print(f"[{index}/{total}] {cam_id}", flush=True)
        try:
            sent = send_current_stream(cam_id)
        except HTTPException as exc:
            row = {
                "id": cam_id,
                "ok": False,
                "event_id": "",
                "queued": 0,
                "error": http_detail(exc),
            }
        else:
            row = {
                "id": cam_id,
                "ok": True,
                "event_id": sent.event_id,
                "queued": sent.queued,
                "error": "",
            }
        results.append(row)
        if ctx.as_json:
            continue
        if row["ok"]:
            print(f"  в очереди: {row['queued']}  событие: {row['event_id']}")
        else:
            print(f"  ошибка: {row['error']}")

    ok_count = sum(1 for row in results if row["ok"])
    if ctx.as_json:
        emit_json(
            {
                "ok": ok_count,
                "failed": total - ok_count,
                "items": results,
            }
        )
    else:
        print(f"готово: {ok_count} из {total}")
    if ok_count != total:
        raise SystemExit(1)


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


def _resolve_rtsp(args: argparse.Namespace) -> tuple[str, str]:
    """Return (camera_id_or_empty, rtsp_url) from ``id`` and/or ``--uri``."""
    from app.cli.console import CliError

    camera_id = (getattr(args, "id", None) or "").strip()
    uri = (getattr(args, "uri", None) or "").strip()
    if camera_id and uri:
        raise CliError("Укажите либо id камеры, либо --uri, не оба сразу")
    if not camera_id and not uri:
        raise CliError("Укажите id камеры или --uri rtsp://…")
    if uri:
        if not uri.lower().startswith("rtsp://"):
            raise CliError("--uri должен начинаться с rtsp://")
        return "", uri
    cam = get_camera(camera_id)
    url = (cam.main_uri or "").strip()
    if not url.lower().startswith("rtsp://"):
        raise CliError(f"У камеры {camera_id} URI не RTSP: {url or '(пусто)'}")
    return cam.id, url


def cmd_probe(ctx: Ctx, args: argparse.Namespace) -> None:
    """ffprobe → fallback ffmpeg: resolution and fps."""
    from app.cli.console import emit_json
    from app.services.gstreamer_probe import mask_rtsp_credentials
    from app.services.rtsp_probe import probe_rtsp_url

    camera_id, url = _resolve_rtsp(args)
    result = probe_rtsp_url(url, timeout_sec=float(args.timeout))
    payload: dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "camera_id": camera_id or None,
        "rtsp_url": mask_rtsp_credentials(url),
        **{k: v for k, v in result.items() if k != "ok"},
    }
    if ctx.as_json:
        emit_json(payload)
    elif payload["ok"]:
        emit_result(
            ctx,
            "поток отвечает",
            {
                "camera_id": camera_id or "",
                "rtsp_url": payload["rtsp_url"],
                "width": result.get("resolution_width"),
                "height": result.get("resolution_height"),
                "fps": result.get("fps"),
            },
        )
    else:
        emit_result(
            ctx,
            "поток не отвечает",
            {
                "camera_id": camera_id or "",
                "rtsp_url": payload["rtsp_url"],
                "error": result.get("error") or "",
            },
        )
    if not payload["ok"]:
        raise SystemExit(1)


def cmd_gst_probe(ctx: Ctx, args: argparse.Namespace) -> None:
    """GStreamer rtspsrc → fakesink diagnostics."""
    from app.cli.console import emit_json
    from app.services.gstreamer_probe import probe_rtsp_gstreamer

    camera_id, url = _resolve_rtsp(args)
    result = probe_rtsp_gstreamer(
        url,
        duration_sec=float(args.duration),
        startup_timeout_sec=float(args.startup_timeout),
    )
    data = result.to_dict()
    data["camera_id"] = camera_id or None
    if ctx.as_json:
        emit_json(data)
    else:
        summary = {
            "camera_id": camera_id or "",
            "rtsp_url": result.rtsp_url_masked,
            "ok": result.ok,
            "codec": result.video_codec or "",
            "playing": result.reached_playing,
            "video_linked": result.video_linked,
            "buffers": result.buffer_count,
            "elapsed_sec": result.elapsed_sec,
            "pipeline": result.pipeline_state,
            "error": result.error or "",
            "error_detail": (result.error_detail or "")[:300],
        }
        emit_result(ctx, "GStreamer probe ok" if result.ok else "GStreamer probe fail", summary)
        if args.verbose and result.messages:
            print("\nсообщения:")
            for msg in result.messages:
                print(f"  [{msg.elapsed_ms:>5}ms] {msg.level} {msg.source}: {msg.text}")
    if not result.ok:
        raise SystemExit(1)


def cmd_record_mkv(ctx: Ctx, args: argparse.Namespace) -> None:
    """Short gst-launch TCP recording to MKV (+ optional validation)."""
    from pathlib import Path

    from app.cli.console import CliError, emit_json
    from app.services.gstreamer_probe import mask_rtsp_credentials
    from app.services.tcp_mkv_recording import (
        record_camera_tcp_mkv_check,
        record_rtsp_tcp_mkv,
    )

    camera_id, url = _resolve_rtsp(args)
    codec = (args.codec or "h265").strip().lower()
    if codec not in {"h264", "h265", "avc", "hevc"}:
        raise CliError("--codec: h264 или h265")
    if codec == "hevc":
        codec = "h265"
    if codec == "avc":
        codec = "h264"
    out = Path(args.out) if args.out else None
    validate = not args.no_validate
    if camera_id and out is None:
        result = record_camera_tcp_mkv_check(
            camera_id,
            url,
            duration_sec=int(args.duration),
            validate=validate,
            codec=codec,
        )
    else:
        result = record_rtsp_tcp_mkv(
            url,
            duration_sec=int(args.duration),
            output_path=out,
            validate=validate,
            codec=codec,
        )
    payload = result.as_dict()
    payload["camera_id"] = camera_id or None
    payload["rtsp_url"] = mask_rtsp_credentials(url)
    if ctx.as_json:
        emit_json(payload)
    else:
        emit_result(
            ctx,
            "запись ok" if result.ok else "запись fail",
            {
                "camera_id": camera_id or "",
                "rtsp_url": payload["rtsp_url"],
                "output": result.output_path or "",
                "size_bytes": result.file_size_bytes,
                "duration_sec": result.duration_sec,
                "error": result.error or "",
                "validation": (
                    result.validation.reason if result.validation is not None else ""
                ),
            },
        )
        if args.verbose and result.stderr_tail:
            print("\nstderr (хвост):")
            print(result.stderr_tail)
    if not result.ok:
        raise SystemExit(1)


def cmd_validate(ctx: Ctx, args: argparse.Namespace) -> None:
    """ffprobe structure + ghosting check on a local video file."""
    from pathlib import Path

    from app.cli.console import CliError, emit_json
    from app.services.video_validation import validate_video

    path = Path(args.path)
    if not path.exists():
        raise CliError(f"файл не найден: {path}")
    result = validate_video(path)
    data = result.as_dict()
    data["path"] = str(path)
    if ctx.as_json:
        emit_json(data)
    else:
        emit_result(
            ctx,
            "валидация ok" if result.ok else "валидация fail",
            {
                "path": str(path),
                "reason": result.reason,
                "duration_sec": result.duration_sec,
                "width": result.width,
                "height": result.height,
                "ffprobe_ok": result.ffprobe_ok,
                "ghosting_ok": result.ghosting_ok,
                "details": result.details or {},
            },
        )
    if not result.ok:
        raise SystemExit(1)


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
        "cameras",
        help=(
            "Камеры: список, probe/gst-probe/record-mkv, ошибки потока, "
            "создание, правка, отправка в вебхук, удаление"
        ),
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

    errors = commands.add_parser(
        "errors",
        help="Ошибки потока и записи: все включённые камеры или одна",
    )
    errors.add_argument(
        "id",
        nargs="?",
        default="",
        help="id одной камеры. Без id — все включённые, у которых есть ошибка",
    )
    errors.set_defaults(func=cmd_errors)

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

    hook = commands.add_parser(
        "webhook",
        help="Отправить текущий поток в вебхук, как кнопка в реестре",
    )
    hook.add_argument(
        "ids",
        nargs="*",
        help="Одна или несколько камер. Пустой список — только вместе с --all",
    )
    hook.add_argument(
        "--all",
        action="store_true",
        help="Все камеры реестра. Нужен --yes",
    )
    hook.add_argument(
        "--enabled",
        action="store_true",
        help="Вместе с --all: только включённые камеры",
    )
    hook.add_argument(
        "--yes",
        action="store_true",
        help="Подтвердить массовую отправку",
    )
    hook.set_defaults(func=cmd_webhook)

    test = commands.add_parser(
        "test", help="Создать несколько тестовых камер на один URI"
    )
    test.add_argument("--uri", required=True, help="rtsp:// или file://")
    test.add_argument(
        "--count", type=int, required=True, help="Сколько камер, от 1 до 128"
    )
    test.set_defaults(func=cmd_test)

    probe = commands.add_parser(
        "probe",
        help="Проверка RTSP: ffprobe, при ошибке — ffmpeg (разрешение и fps)",
    )
    probe.add_argument(
        "id",
        nargs="?",
        default="",
        help="id камеры из реестра. Либо укажите --uri",
    )
    probe.add_argument("--uri", default="", help="rtsp://… напрямую, без камеры в БД")
    probe.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Таймаут пробы в секундах (по умолчанию 20)",
    )
    probe.set_defaults(func=cmd_probe)

    gst = commands.add_parser(
        "gst-probe",
        help="Диагностика RTSP через GStreamer (rtspsrc → fakesink)",
    )
    gst.add_argument(
        "id",
        nargs="?",
        default="",
        help="id камеры из реестра. Либо укажите --uri",
    )
    gst.add_argument("--uri", default="", help="rtsp://… напрямую, без камеры в БД")
    gst.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Сколько секунд слушать поток (3–30, по умолчанию 10)",
    )
    gst.add_argument(
        "--startup-timeout",
        type=float,
        default=5.0,
        help="Сколько ждать PLAYING (по умолчанию 5)",
    )
    gst.add_argument(
        "--verbose",
        action="store_true",
        help="Печатать сообщения шины GStreamer",
    )
    gst.set_defaults(func=cmd_gst_probe)

    record = commands.add_parser(
        "record-mkv",
        help="Короткая запись RTSP в MKV через gst-launch (TCP, без перекодирования)",
    )
    record.add_argument(
        "id",
        nargs="?",
        default="",
        help="id камеры из реестра. Либо укажите --uri",
    )
    record.add_argument("--uri", default="", help="rtsp://… напрямую, без камеры в БД")
    record.add_argument(
        "--duration",
        type=int,
        default=12,
        help="Длительность записи в секундах (5–60, по умолчанию 12)",
    )
    record.add_argument(
        "--codec",
        default="h265",
        help="h264 или h265 (по умолчанию h265)",
    )
    record.add_argument(
        "--out",
        default="",
        help="Путь к .mkv. Без флага — временный файл или data/.camera_recording_checks",
    )
    record.add_argument(
        "--no-validate",
        action="store_true",
        help="Не гонять ffprobe/ghosting после записи",
    )
    record.add_argument(
        "--verbose",
        action="store_true",
        help="Печатать хвост stderr gst-launch",
    )
    record.set_defaults(func=cmd_record_mkv)

    validate = commands.add_parser(
        "validate",
        help="Проверка локального видео: структура ffprobe + ghosting I/P",
    )
    validate.add_argument("path", help="Путь к файлу (mkv/mp4/…)")
    validate.set_defaults(func=cmd_validate)
