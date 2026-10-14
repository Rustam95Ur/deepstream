"""Status, video worker, license, and history."""

from __future__ import annotations

import argparse
from typing import Any

from app import __version__
from app.billing import (
    apply_runtime_lock,
    billing_status,
    license_ok,
    license_reason,
    settings_for_check,
    validate_billing_key,
)
from app.cli.console import Ctx, emit_kv, emit_result, emit_table
from app.pipeline_status import attach_status
from app.services.history import (
    get_trigger,
    list_outbound,
    list_sends,
    list_triggers,
    resend_trigger,
    retry_outbound,
)
from app.storage import get_store
from app.video_client import notify_reload, worker_start, worker_status, worker_stop
from app.webhooks import list_enabled_webhooks


def _worker():
    store = get_store()
    return attach_status(worker_status(), store.list_cameras(), store.get_settings())


def worker_dict(status) -> dict[str, Any]:
    return status.model_dump(mode="json")


def _print_worker(ctx: Ctx, status, title: str) -> None:
    data = worker_dict(status)
    skipped = data.pop("skipped", []) or []
    errors = data.pop("recent_errors", []) or []
    if ctx.as_json:
        from app.cli.console import emit_json

        emit_json({"result": title, **worker_dict(status)})
        return
    print(title)
    emit_kv(
        ctx,
        {
            "running": data.get("running"),
            "available": data.get("available"),
            "detail": data.get("detail") or "",
            "last_error": data.get("last_error") or "",
            "reload_pending": data.get("reload_pending"),
            "camera_ids": data.get("camera_ids") or [],
            "max_streams": data.get("max_streams"),
        },
    )
    if skipped:
        print("\nне в пайплайне:")
        emit_table(
            ctx,
            skipped,
            [("camera_id", "камера"), ("name", "имя"), ("reason", "причина")],
        )
    if errors:
        print("\nпоследние ошибки:")
        emit_table(
            ctx,
            errors,
            [("level", "уровень"), ("logger", "логгер"), ("message", "сообщение")],
        )


def cmd_status(ctx: Ctx, _args: argparse.Namespace) -> None:
    store = get_store()
    settings = store.get_settings()
    cameras = store.list_cameras()
    status = _worker()
    valid = license_ok()
    try:
        hooks = list_enabled_webhooks()
        triggers_url = hooks[0].url if hooks else settings.triggers_url
    except Exception:
        triggers_url = settings.triggers_url
    emit_kv(
        ctx,
        {
            "node_id": settings.node_id,
            "node_name": settings.node_name,
            "version": __version__,
            "cameras": len(cameras),
            "cameras_enabled": sum(1 for cam in cameras if cam.enabled),
            "pipeline_running": status.running,
            "pipeline_available": status.available,
            "pipeline_detail": status.detail,
            "triggers_url": triggers_url,
            "license_valid": valid,
            "license_reason": "" if valid else license_reason(),
            "max_streams": settings.max_streams,
        },
    )


def cmd_worker_status(ctx: Ctx, _args: argparse.Namespace) -> None:
    _print_worker(ctx, _worker(), "worker")


def cmd_worker_start(ctx: Ctx, _args: argparse.Namespace) -> None:
    store = get_store()
    status = attach_status(worker_start(), store.list_cameras(), store.get_settings())
    _print_worker(ctx, status, "запущен" if status.running else "не запущен")


def cmd_worker_stop(ctx: Ctx, _args: argparse.Namespace) -> None:
    store = get_store()
    status = attach_status(worker_stop(), store.list_cameras(), store.get_settings())
    _print_worker(ctx, status, "остановлен")


def cmd_worker_reload(ctx: Ctx, _args: argparse.Namespace) -> None:
    store = get_store()
    status = notify_reload() or worker_status()
    status = attach_status(status, store.list_cameras(), store.get_settings())
    _print_worker(ctx, status, "перезагрузка запрошена")


def _billing_dict(check) -> dict[str, Any]:
    data = check.as_dict()
    reason = str(data.get("reason") or "")
    from app.billing.models import REASON_LABELS

    data["reason_label"] = REASON_LABELS.get(reason, reason)
    return data


def cmd_billing_status(ctx: Ctx, _args: argparse.Namespace) -> None:
    emit_kv(ctx, _billing_dict(billing_status()))


def cmd_billing_check(ctx: Ctx, args: argparse.Namespace) -> None:
    settings = settings_for_check(
        billing_url=args.url,
        billing_api_key=args.key,
    )
    check = apply_runtime_lock(validate_billing_key(settings))
    emit_result(ctx, "проверено", _billing_dict(check))


def _limit(value: int) -> int:
    if value < 1 or value > 500:
        from app.cli.console import CliError

        raise CliError("--limit от 1 до 500")
    return value


def cmd_triggers(ctx: Ctx, args: argparse.Namespace) -> None:
    page = list_triggers(
        limit=_limit(args.limit),
        cursor=args.cursor or "",
        camera_id=args.camera or "",
        trigger_type=args.type or "",
        event_id=args.event or "",
    )
    rows = [item.model_dump(mode="json") for item in page.items]
    emit_table(
        ctx,
        rows,
        [
            ("created_at", "время"),
            ("camera_id", "камера"),
            ("trigger_type", "тип"),
            ("category", "категория"),
            ("event_id", "событие"),
        ],
        empty="Событий нет",
        extra={"next_cursor": page.next_cursor},
    )


def cmd_show_trigger(ctx: Ctx, args: argparse.Namespace) -> None:
    item = get_trigger(args.event_id)
    data = item.model_dump(mode="json")
    if ctx.as_json:
        from app.cli.console import emit_json

        emit_json(data)
        return
    payload = data.pop("payload", {})
    evidence = data.pop("evidence", {})
    clip = data.pop("clip", {})
    emit_kv(ctx, data)
    if clip:
        print("\nролик:")
        emit_kv(ctx, clip if isinstance(clip, dict) else {"clip": clip})
    if evidence:
        print("\nпризнаки:")
        emit_kv(ctx, evidence if isinstance(evidence, dict) else {"evidence": evidence})
    if payload:
        print("\npayload: добавьте --json, чтобы напечатать целиком")


def cmd_resend(ctx: Ctx, args: argparse.Namespace) -> None:
    result = resend_trigger(args.event_id)
    emit_result(ctx, "поставлено в очередь", result.model_dump(mode="json"))


def cmd_outbound(ctx: Ctx, args: argparse.Namespace) -> None:
    page = list_outbound(
        limit=_limit(args.limit),
        cursor=args.cursor or "",
        status=args.status or "",
        event_id=args.event or "",
    )
    rows = [item.model_dump(mode="json") for item in page.items]
    emit_table(
        ctx,
        rows,
        [
            ("status", "статус"),
            ("attempts", "попытки"),
            ("http_status", "http"),
            ("event_id", "событие"),
            ("url", "url"),
            ("last_error", "ошибка"),
            ("id", "id"),
        ],
        empty="Заданий нет",
        extra={"next_cursor": page.next_cursor},
    )


def cmd_retry(ctx: Ctx, args: argparse.Namespace) -> None:
    job = retry_outbound(args.job_id)
    emit_result(ctx, "повтор поставлен", job.model_dump(mode="json"))


def cmd_sends(ctx: Ctx, args: argparse.Namespace) -> None:
    page = list_sends(
        limit=_limit(args.limit),
        cursor=args.cursor or "",
        status=args.status or "",
        event_id=args.event or "",
    )
    rows = [item.model_dump(mode="json") for item in page.items]
    emit_table(
        ctx,
        rows,
        [
            ("created_at", "время"),
            ("status", "статус"),
            ("http_status", "http"),
            ("sink", "канал"),
            ("event_id", "событие"),
            ("error", "ошибка"),
        ],
        empty="Отправок нет",
        extra={"next_cursor": page.next_cursor},
    )


def _page_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=20, help="Сколько строк, 1..500")
    parser.add_argument("--cursor", default="", help="Курсор следующей страницы")


def register_worker(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("worker", help="Разбор видео в контейнере video")
    commands = parser.add_subparsers(dest="action", required=True)
    status = commands.add_parser("status", help="Состояние пайплайна")
    status.set_defaults(func=cmd_worker_status)
    start = commands.add_parser("start", help="Запустить разбор")
    start.set_defaults(func=cmd_worker_start)
    stop = commands.add_parser("stop", help="Остановить разбор")
    stop.set_defaults(func=cmd_worker_stop)
    reload_cmd = commands.add_parser("reload", help="Перечитать камеры и настройки")
    reload_cmd.set_defaults(func=cmd_worker_reload)


def register_billing(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("billing", help="Лицензия")
    commands = parser.add_subparsers(dest="action", required=True)
    status = commands.add_parser("status", help="Последняя проверка")
    status.set_defaults(func=cmd_billing_status)
    check = commands.add_parser(
        "check",
        help="Проверить ключ сейчас. --url и --key не сохраняются",
    )
    check.add_argument("--url", default=None, help="Адрес проверки на один запрос")
    check.add_argument("--key", default=None, help="Ключ на один запрос")
    check.set_defaults(func=cmd_billing_check)


def register_history(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("history", help="События и очередь отправки")
    commands = parser.add_subparsers(dest="action", required=True)

    triggers = commands.add_parser("triggers", help="Список сработок")
    _page_flags(triggers)
    triggers.add_argument("--camera", default="", help="id камеры")
    triggers.add_argument("--type", default="", help="presence, convergence, vif, …")
    triggers.add_argument("--event", default="", help="event_id")
    triggers.set_defaults(func=cmd_triggers)

    show = commands.add_parser("show", help="Одно событие")
    show.add_argument("event_id")
    show.set_defaults(func=cmd_show_trigger)

    resend = commands.add_parser(
        "resend", help="Снова поставить событие во все включённые webhook"
    )
    resend.add_argument("event_id")
    resend.set_defaults(func=cmd_resend)

    outbound = commands.add_parser("outbound", help="Очередь доставки")
    _page_flags(outbound)
    outbound.add_argument(
        "--status",
        default="",
        help="Фильтр: pending, retrying, dead, ok",
    )
    outbound.add_argument("--event", default="", help="event_id")
    outbound.set_defaults(func=cmd_outbound)

    retry = commands.add_parser("retry", help="Повторить одно задание очереди")
    retry.add_argument("job_id")
    retry.set_defaults(func=cmd_retry)

    sends = commands.add_parser("sends", help="Журнал HTTP-попыток")
    _page_flags(sends)
    sends.add_argument("--status", default="")
    sends.add_argument("--event", default="")
    sends.set_defaults(func=cmd_sends)


def register_status(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("status", help="Кратко: нода, камеры, пайплайн, лицензия")
    parser.set_defaults(func=cmd_status)
