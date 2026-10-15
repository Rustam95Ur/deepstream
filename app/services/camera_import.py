"""Excel template and row parsing for bulk camera create."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas import CameraIn
from app.trigger_types import TRIGGER_TYPES
from app.xlsx_sheet import build_xlsx, read_sheet

_MAX_ROWS = 500
_TRIGGER_ORDER = list(TRIGGER_TYPES)

_HEADERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("name", ("название", "имя", "name")),
    ("main_uri", ("rtsp ссылка", "rtsp", "main_uri", "uri", "ссылка", "адрес")),
    ("stream_protocol", ("протокол потока", "протокол", "stream_protocol")),
    ("fps", ("кадров в секунду", "fps", "кадр/с")),
    ("resolution_width", ("ширина разрешения", "ширина", "resolution_width")),
    ("resolution_height", ("высота разрешения", "высота", "resolution_height")),
    ("enabled", ("активен", "enabled", "статус")),
    (
        "allow_preprocessing",
        ("разрешить предварительную обработку", "предобработка", "allow_preprocessing"),
    ),
    ("usage_modules", ("модули использования", "модули", "usage_modules")),
    ("scenarios", ("сценарии", "сценарий", "enabled_triggers")),
)

_HEADER_INDEX = {
    alias: key for key, aliases in _HEADERS for alias in aliases
}

_PROTOCOLS = {
    "2": 2,
    "rtsp": 2,
    "rtsp ссылка": 2,
    "1": 1,
    "onvif": 1,
}
_TRUE = {"1", "true", "yes", "da", "да", "вкл", "активен", "on", "y", "+"}
_FALSE = {"0", "false", "no", "net", "нет", "выкл", "off", "n", "-", "—"}
_MODULES = {
    "1": 1,
    "вовлеченность": 1,
    "engagement": 1,
    "2": 2,
    "инциденты": 2,
    "incidents": 2,
    "3": 3,
    "посещаемость": 3,
    "attendance": 3,
}
_NO_MODULES = {"нет", "нет модулей", "none", "-", "—"}
_INHERIT = {"как у ноды", "нода", "inherit", "унаследовать"}
_NO_SCENARIOS = {"нет", "нет сценариев", "none", "-", "—"}
_SCENARIOS = {
    "драка / сходка": ("convergence", "vif"),
    "драка": ("convergence", "vif"),
    "fight": ("convergence", "vif"),
    "сходка": ("convergence",),
    "convergence": ("convergence",),
    "пересечение": ("vif",),
    "vif": ("vif",),
    "падение": ("fall",),
    "fall": ("fall",),
    "курение": ("smoke",),
    "smoke": ("smoke",),
    "присутствие": ("presence",),
    "presence": ("presence",),
    "камера молчит": ("stream_silent",),
    "stream_silent": ("stream_silent",),
}


class CameraWorkbookError(ValueError):
    """The file itself cannot be imported."""


@dataclass
class CameraRowError:
    row: int
    detail: str


@dataclass
class ParsedCameras:
    cameras: list[CameraIn] = field(default_factory=list)
    errors: list[CameraRowError] = field(default_factory=list)


def template_bytes() -> bytes:
    headers = [
        "Название",
        "RTSP ссылка",
        "Протокол потока",
        "Кадров в секунду",
        "Ширина разрешения",
        "Высота разрешения",
        "Активен",
        "Разрешить предварительную обработку",
        "Модули использования",
        "Сценарии",
    ]
    help_rows: list[list[object]] = [
        [
            "Идентификатор камеры в файл не вносится. Система создаёт его при загрузке.",
            "",
            "",
            "",
        ],
        ["Поле", "Обязательно", "Что писать", "Пример"],
        ["Название", "нет", "Если пусто, подставится созданный id", "Коридор 1 этаж"],
        ["RTSP ссылка", "да", "Адрес потока", "rtsp://192.168.1.10:554/stream"],
        ["Протокол потока", "нет", "RTSP ссылка или ONVIF. Пусто = RTSP ссылка", "RTSP ссылка"],
        ["Кадров в секунду", "нет", "Целое число. Пусто = 25", 25],
        ["Ширина разрешения", "нет", "Целое число. Пусто = 1280", 1280],
        ["Высота разрешения", "нет", "Целое число. Пусто = 720", 720],
        ["Активен", "нет", "да или нет. Пусто = да", "да"],
        [
            "Разрешить предварительную обработку",
            "нет",
            "да или нет. Пусто = нет",
            "нет",
        ],
        [
            "Модули использования",
            "нет",
            "Через запятую: Вовлеченность, Инциденты, Посещаемость. Пусто = Инциденты. «нет» — без модулей",
            "Инциденты",
        ],
        [
            "Сценарии",
            "нет",
            "«как у ноды», «нет» или список: Драка / сходка, Падение, Курение, Присутствие, Камера молчит. Пусто = как у ноды",
            "как у ноды",
        ],
    ]
    return build_xlsx(
        [
            ("Камеры", [headers], 1),
            ("Справка", help_rows, 2),
        ]
    )


def rejection_message(errors: list[CameraRowError]) -> str:
    shown = errors[:12]
    parts = [f"строка {item.row}: {item.detail}" for item in shown]
    extra = len(errors) - len(shown)
    tail = f"; и ещё {extra}" if extra else ""
    return "Импорт не выполнен. " + "; ".join(parts) + tail


def parse_workbook(data: bytes) -> ParsedCameras:
    try:
        rows = read_sheet(data, preferred_name="Камеры")
    except ValueError as exc:
        raise CameraWorkbookError(str(exc)) from exc
    if not rows:
        raise CameraWorkbookError("в файле нет колонки «RTSP ссылка»")
    header_at, columns = _find_header(rows)
    if columns is None or header_at is None:
        raise CameraWorkbookError("в файле нет колонки «RTSP ссылка»")
    data_rows = [item for item in rows if item[0] > header_at]
    if len(data_rows) > _MAX_ROWS:
        raise CameraWorkbookError(f"в файле больше {_MAX_ROWS} строк")
    parsed = ParsedCameras()
    for number, cells in data_rows:
        if not any(cell.strip() for cell in cells):
            continue
        try:
            parsed.cameras.append(_row_to_camera(cells, columns))
        except ValueError as exc:
            parsed.errors.append(CameraRowError(number, str(exc)))
    if not parsed.cameras and not parsed.errors:
        raise CameraWorkbookError("в файле нет строк с камерами")
    return parsed


def _find_header(
    rows: list[tuple[int, list[str]]],
) -> tuple[int | None, dict[str, int] | None]:
    for number, cells in rows[:15]:
        mapping: dict[str, int] = {}
        for index, cell in enumerate(cells):
            key = _HEADER_INDEX.get(_norm(cell))
            if key and key not in mapping:
                mapping[key] = index
        if "main_uri" in mapping:
            return number, mapping
    return None, None


def _cell(cells: list[str], columns: dict[str, int], key: str) -> str:
    index = columns.get(key)
    if index is None or index >= len(cells):
        return ""
    return cells[index].strip()


def _row_to_camera(cells: list[str], columns: dict[str, int]) -> CameraIn:
    uri = _cell(cells, columns, "main_uri")
    if not uri:
        raise ValueError("не заполнена RTSP ссылка")
    if len(uri) > 2048:
        raise ValueError("RTSP ссылка длиннее 2048 символов")
    name = _cell(cells, columns, "name")
    if len(name) > 255:
        raise ValueError("название длиннее 255 символов")
    return CameraIn(
        name=name,
        main_uri=uri,
        enabled=_flag(_cell(cells, columns, "enabled"), default=True, label="Активен"),
        meta={
            "stream_protocol": _protocol(_cell(cells, columns, "stream_protocol")),
            "resolution_width": _positive_int(
                _cell(cells, columns, "resolution_width"),
                default=1280,
                label="Ширина разрешения",
            ),
            "resolution_height": _positive_int(
                _cell(cells, columns, "resolution_height"),
                default=720,
                label="Высота разрешения",
            ),
            "fps": _positive_int(
                _cell(cells, columns, "fps"),
                default=25,
                label="Кадров в секунду",
            ),
            "allow_preprocessing": _flag(
                _cell(cells, columns, "allow_preprocessing"),
                default=False,
                label="Разрешить предварительную обработку",
            ),
            "usage_modules": _modules(_cell(cells, columns, "usage_modules")),
        },
        enabled_triggers=_scenarios(_cell(cells, columns, "scenarios")),
    )


def _norm(value: str) -> str:
    text = value.replace("\xa0", " ").strip().lower().replace("ё", "е")
    text = text.strip("*: ")
    text = re.sub(r"\s*/\s*", " / ", text)
    return re.sub(r"\s+", " ", text)


def _positive_int(value: str, *, default: int, label: str) -> int:
    text = value.strip()
    if not text:
        return default
    try:
        number = float(text.replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"{label}: нужно целое число") from exc
    if not number.is_integer() or number <= 0:
        raise ValueError(f"{label}: нужно целое число больше 0")
    return int(number)


def _flag(value: str, *, default: bool, label: str) -> bool:
    text = _norm(value)
    if not text:
        return default
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValueError(f"{label}: напишите да или нет")


def _protocol(value: str) -> int:
    text = _norm(value)
    if not text:
        return 2
    found = _PROTOCOLS.get(text)
    if found is None:
        raise ValueError("протокол: RTSP ссылка или ONVIF")
    return found


def _split(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;\n|]+", value) if part.strip()]


def _modules(value: str) -> list[int]:
    text = value.strip()
    if not text:
        return [2]
    tokens = _split(text)
    if len(tokens) == 1 and _norm(tokens[0]) in _NO_MODULES:
        return []
    found: list[int] = []
    for token in tokens:
        key = _norm(token)
        module = _MODULES.get(key)
        if module is None:
            raise ValueError(
                f"неизвестный модуль «{token.strip()}». "
                "Допустимо: Вовлеченность, Инциденты, Посещаемость"
            )
        if module not in found:
            found.append(module)
    return sorted(found)


def _scenarios(value: str) -> list[str] | None:
    text = value.strip()
    if not text or _norm(text) in _INHERIT:
        return None
    tokens = _split(text)
    if len(tokens) == 1 and _norm(tokens[0]) in _NO_SCENARIOS:
        return []
    selected: list[str] = []
    for token in tokens:
        key = _norm(token)
        if key in _INHERIT or key in _NO_SCENARIOS:
            raise ValueError("сценарии: «как у ноды» и «нет» пишите отдельно, без списка")
        triggers = _SCENARIOS.get(key)
        if not triggers:
            raise ValueError(
                f"неизвестный сценарий «{token.strip()}». "
                "Допустимо: Драка / сходка, Падение, Курение, Присутствие, Камера молчит"
            )
        for trigger in triggers:
            if trigger not in selected:
                selected.append(trigger)
    return [name for name in _TRIGGER_ORDER if name in selected]
