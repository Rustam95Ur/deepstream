"""Node settings commands."""

from __future__ import annotations

import argparse
import json
from typing import Any, get_origin

from app.billing import apply_runtime_lock, validate_billing_key
from app.cli.console import CliError, Ctx, emit_kv, emit_table
from app.settings import NodeSettings
from app.storage import get_store
from app.trigger_types import TRIGGER_TYPES
from app.video_client import notify_reload

_SECRET = frozenset({"billing_api_key"})

HELP = {
    "node_id": "Идентификатор ноды, например ds-1",
    "node_name": "Имя ноды в консоли и в событиях",
    "triggers_url": "Запасной URL: первый webhook создаётся из него, только если таблица пустая",
    "triggers_timeout_sec": "Таймаут этого запасного webhook, секунды",
    "enable_http_sink": "Отправлять события на webhook",
    "enable_log_sink": "Писать события в лог",
    "enable_clip_record": "Вырезать ролик из кольцевого буфера",
    "billing_url": "Адрес проверки лицензии",
    "billing_api_key": "Ключ лицензии",
    "billing_timeout_sec": "Таймаут проверки лицензии, секунды",
    "trigger_mode": "Режим детектора, обычно convergence",
    "enabled_triggers": "Типы событий ноды через запятую: " + ", ".join(TRIGGER_TYPES),
    "min_tracks": "Сколько людей нужно для схождения",
    "converge_dist_bh": "Дистанция схождения в высотах рамки",
    "speed_thresh_bh": "Порог скорости схождения",
    "sustain_s": "Сколько секунд держать условие схождения",
    "cooldown_s": "Пауза перед повторным событием того же типа, секунды",
    "presence_min_people": "Минимум людей для присутствия",
    "presence_sustain_s": "Сколько секунд человек должен быть в кадре",
    "vif_iou_thresh": "Порог пересечения рамок",
    "vif_sustain_s": "Сколько секунд держать пересечение",
    "clip_pre_s": "Секунд видео до события",
    "clip_post_s": "Секунд видео после события",
    "infer_interval": "Запускать детектор каждый N-й кадр",
    "conf_threshold": "Порог уверенности детектора, 0..1",
    "reconnect_s": "Пауза перед переподключением RTSP, секунды",
    "stream_silent_s": "Через сколько секунд без кадров считать поток молчащим",
    "mux_width": "Ширина кадра в пайплайне",
    "mux_height": "Высота кадра в пайплайне",
    "person_class_id": "Номер класса «человек» в модели",
    "detector_model": "Имя модели детектора людей, обычно peoplenet",
    "auto_start_pipeline": "Запускать разбор видео при старте video-контейнера",
    "max_streams": "Сколько камер разбирать одновременно",
    "trigger_thresholds": "Пороги по типам одним JSON-объектом",
}


def field_kind(annotation: Any) -> str:
    origin = get_origin(annotation)
    if annotation is bool:
        return "bool"
    if annotation is int:
        return "int"
    if annotation is float:
        return "float"
    if origin is list:
        return "list"
    if origin is dict:
        return "json"
    return "str"


def _parse_bool(raw: str) -> bool:
    text = raw.strip().lower()
    if text in {"1", "true", "yes", "y", "on", "да"}:
        return True
    if text in {"0", "false", "no", "n", "off", "нет"}:
        return False
    raise CliError(f"ожидалось true или false, получено: {raw}")


def coerce(key: str, raw: str) -> Any:
    if key not in NodeSettings.model_fields:
        known = ", ".join(NodeSettings.model_fields)
        raise CliError(f"Неизвестная настройка {key}. Допустимо: {known}")
    kind = field_kind(NodeSettings.model_fields[key].annotation)
    if key == "enabled_triggers":
        from app.cli.cameras import parse_triggers

        if raw.strip().lower() in {"", "none", "-"}:
            return []
        return parse_triggers(raw)
    if kind == "bool":
        return _parse_bool(raw)
    if kind == "int":
        try:
            return int(raw)
        except ValueError as exc:
            raise CliError(f"{key}: нужно целое число") from exc
    if kind == "float":
        try:
            return float(raw)
        except ValueError as exc:
            raise CliError(f"{key}: нужно число") from exc
    if kind == "list":
        return [part.strip() for part in raw.split(",") if part.strip()]
    if kind == "json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CliError(f"{key}: не JSON ({exc})") from exc
        if not isinstance(data, dict):
            raise CliError(f"{key}: нужен JSON-объект")
        return data
    return raw


def parse_pairs(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise CliError(f"Ожидалось ИМЯ=значение, получено: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise CliError(f"Пустое имя настройки: {item}")
        out[key] = value.strip()
    return out


def public_settings(settings: NodeSettings, *, reveal: bool) -> dict[str, Any]:
    data = settings.model_dump(mode="json")
    if not reveal:
        secret = str(data.get("billing_api_key") or "")
        data["billing_api_key"] = "задан" if secret else ""
    return data


def _billing_changed(before: NodeSettings, after: NodeSettings) -> bool:
    return (
        before.billing_url != after.billing_url
        or before.billing_api_key != after.billing_api_key
        or before.billing_timeout_sec != after.billing_timeout_sec
    )


def cmd_show(ctx: Ctx, args: argparse.Namespace) -> None:
    emit_kv(ctx, public_settings(get_store().get_settings(), reveal=args.reveal))


def cmd_keys(ctx: Ctx, args: argparse.Namespace) -> None:
    current = public_settings(get_store().get_settings(), reveal=args.reveal)
    rows = []
    for name, field in NodeSettings.model_fields.items():
        rows.append(
            {
                "key": name,
                "type": field_kind(field.annotation),
                "value": current.get(name, ""),
                "help": HELP.get(name, ""),
            }
        )
    emit_table(
        ctx,
        rows,
        [("key", "ключ"), ("type", "тип"), ("value", "сейчас"), ("help", "смысл")],
        empty="Нет настроек",
    )


def cmd_set(ctx: Ctx, args: argparse.Namespace) -> None:
    pairs = parse_pairs(args.pairs)
    patch = {key: coerce(key, value) for key, value in pairs.items()}
    store = get_store()
    before = store.get_settings()
    updated = store.update_settings(patch)
    if _billing_changed(before, updated):
        apply_runtime_lock(validate_billing_key(updated))
    notify_reload()
    shown = public_settings(updated, reveal=args.reveal)
    changed = {key: shown.get(key) for key in patch}
    emit_kv(ctx, changed)


def _reveal(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--reveal",
        action="store_true",
        help="Показать ключ лицензии. Без флага печатается только «задан»",
    )


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("settings", help="Настройки ноды (settings.json)")
    commands = parser.add_subparsers(dest="action", required=True)

    show = commands.add_parser("show", help="Текущие настройки")
    _reveal(show)
    show.set_defaults(func=cmd_show)

    keys = commands.add_parser("keys", help="Имена настроек, типы и текущие значения")
    _reveal(keys)
    keys.set_defaults(func=cmd_keys)

    setter = commands.add_parser("set", help="Изменить одну или несколько настроек")
    _reveal(setter)
    setter.add_argument(
        "pairs",
        nargs="+",
        metavar="КЛЮЧ=ЗНАЧЕНИЕ",
        help="Например max_streams=8 enable_clip_record=true",
    )
    setter.set_defaults(func=cmd_set)
