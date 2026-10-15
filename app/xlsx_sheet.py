"""Small .xlsx reader and writer. Enough for the camera import template."""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

_MAX_PART = 8_000_000


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _col_name(index: int) -> str:
    n = index + 1
    name = ""
    while n:
        n, rem = divmod(n - 1, 26)
        name = chr(65 + rem) + name
    return name


def _col_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _xml(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def _cell_xml(ref: str, value: object, *, style: int = 0) -> str:
    if value is None:
        return ""
    style_attr = f' s="{style}"' if style else ""
    if isinstance(value, bool):
        return f'<c r="{ref}"{style_attr} t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{style_attr}><v>{value}</v></c>'
    text = str(value)
    if text == "":
        return ""
    safe = escape(text)
    return (
        f'<c r="{ref}"{style_attr} t="inlineStr"><is>'
        f'<t xml:space="preserve">{safe}</t></is></c>'
    )


def _widths(rows: list[list[object]]) -> list[float]:
    if not rows:
        return []
    cols = max(len(row) for row in rows)
    widths: list[float] = []
    for index in range(cols):
        longest = 10
        for row in rows:
            if index < len(row) and row[index] is not None:
                longest = max(longest, len(str(row[index])))
        widths.append(float(min(56, max(14, longest + 2))))
    return widths


def _sheet_xml(rows: list[list[object]], *, bold_row: int) -> str:
    widths = _widths(rows)
    cols = ""
    if widths:
        parts = [
            f'<col min="{i + 1}" max="{i + 1}" width="{width}" customWidth="1"/>'
            for i, width in enumerate(widths)
        ]
        cols = "<cols>" + "".join(parts) + "</cols>"
    body: list[str] = []
    for r_index, row in enumerate(rows, start=1):
        cells = []
        style = 1 if r_index == bold_row else 0
        for c_index, value in enumerate(row):
            cell = _cell_xml(f"{_col_name(c_index)}{r_index}", value, style=style)
            if cell:
                cells.append(cell)
        body.append(f'<row r="{r_index}">{"".join(cells)}</row>')
    freeze = ""
    if bold_row > 0:
        freeze = (
            "<sheetViews><sheetView workbookViewId=\"0\">"
            f'<pane ySplit="{bold_row}" topLeftCell="A{bold_row + 1}" '
            'activePane="bottomLeft" state="frozen"/>'
            "</sheetView></sheetViews>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"{freeze}{cols}<sheetData>{''.join(body)}</sheetData></worksheet>"
    )


_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><name val="Calibri"/></font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="2">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
  </cellXfs>
</styleSheet>
"""


def build_xlsx(sheets: list[tuple[str, list[list[object]], int]]) -> bytes:
    """Build a workbook. Each sheet is ``(name, rows, bold_row)``; bold_row is 1-based."""
    if not sheets:
        raise ValueError("workbook has no sheets")
    overrides = [
        (
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        ),
        (
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        ),
    ]
    sheet_tags = []
    rels = [
        (
            '<Relationship Id="rIdStyles" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/>'
        )
    ]
    parts: list[tuple[str, str]] = [("xl/styles.xml", _STYLES)]
    for index, (name, rows, bold_row) in enumerate(sheets, start=1):
        path = f"xl/worksheets/sheet{index}.xml"
        overrides.append(
            f'<Override PartName="/{path}" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        sheet_tags.append(
            f'<sheet name="{_xml(name)}" sheetId="{index}" r:id="rId{index}"/>'
        )
        rels.append(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
        parts.append((path, _sheet_xml(rows, bold_row=bold_row)))
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{''.join(sheet_tags)}</sheets></workbook>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{''.join(overrides)}</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(rels)}</Relationships>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        for name, data in parts:
            zf.writestr(name, data)
    return buf.getvalue()


def _safe_name(name: str) -> str:
    cleaned = name.replace("\\", "/").lstrip("/")
    if not cleaned or ".." in cleaned.split("/"):
        raise ValueError("не удалось прочитать файл Excel")
    return cleaned


def _read_part(zf: zipfile.ZipFile, name: str) -> bytes:
    target = _safe_name(name)
    try:
        info = zf.getinfo(target)
    except KeyError as exc:
        raise ValueError("не удалось прочитать файл Excel") from exc
    if info.file_size > _MAX_PART:
        raise ValueError("файл Excel слишком большой")
    return zf.read(target)


def _resolve(base: str, target: str) -> str:
    if target.startswith("/"):
        return _safe_name(target)
    parent = base.rsplit("/", 1)[0] if "/" in base else ""
    parts: list[str] = []
    for part in f"{parent}/{target}".split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise ValueError("не удалось прочитать файл Excel")
            parts.pop()
            continue
        parts.append(part)
    return _safe_name("/".join(parts))


def _text_of(node: ET.Element) -> str:
    parts: list[str] = []
    for child in node:
        name = _local(child.tag)
        if name == "t":
            parts.append(child.text or "")
        elif name == "r":
            for inner in child:
                if _local(inner.tag) == "t":
                    parts.append(inner.text or "")
    return "".join(parts)


def _shared_strings(raw: bytes) -> list[str]:
    root = ET.fromstring(raw)
    return [_text_of(node) for node in root if _local(node.tag) == "si"]


def _number_text(raw: str) -> str:
    try:
        value = float(raw)
    except ValueError:
        return raw
    if value.is_integer():
        return str(int(value))
    return raw


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.attrib.get("t") or ""
    if kind == "inlineStr":
        for child in cell:
            if _local(child.tag) == "is":
                return _text_of(child)
        return ""
    value = ""
    for child in cell:
        if _local(child.tag) == "v":
            value = child.text or ""
            break
    if kind == "s":
        try:
            return shared[int(value)]
        except (ValueError, IndexError):
            return ""
    if kind == "b":
        return "true" if value in {"1", "true"} else "false"
    if kind in {"", "n"}:
        return _number_text(value) if value else ""
    return value


def _sheet_rows(raw: bytes, shared: list[str]) -> list[tuple[int, list[str]]]:
    root = ET.fromstring(raw)
    rows: list[tuple[int, list[str]]] = []
    seen = 0
    for node in root.iter():
        if _local(node.tag) != "row":
            continue
        seen += 1
        try:
            number = int(node.attrib.get("r") or seen)
        except ValueError:
            number = seen
        cells: dict[int, str] = {}
        for cell in node:
            if _local(cell.tag) != "c":
                continue
            ref = cell.attrib.get("r") or ""
            index = _col_index(ref) if ref else len(cells)
            if index < 0:
                continue
            cells[index] = _cell_text(cell, shared).strip()
        if not cells or not any(cells.values()):
            continue
        width = max(cells) + 1
        rows.append((number, [cells.get(i, "") for i in range(width)]))
    return rows


def _relationships(raw: bytes) -> dict[str, str]:
    root = ET.fromstring(raw)
    out: dict[str, str] = {}
    for node in root:
        if _local(node.tag) != "Relationship":
            continue
        rel_id = node.attrib.get("Id") or ""
        target = node.attrib.get("Target") or ""
        if rel_id and target:
            out[rel_id] = target
    return out


def read_sheet(data: bytes, *, preferred_name: str = "") -> list[tuple[int, list[str]]]:
    """Return ``(excel_row_number, cells)`` for a worksheet."""
    if not data.startswith(b"PK"):
        raise ValueError("нужен файл .xlsx")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("не удалось прочитать файл Excel") from exc
    with zf:
        workbook = ET.fromstring(_read_part(zf, "xl/workbook.xml"))
        rels = _relationships(_read_part(zf, "xl/_rels/workbook.xml.rels"))
        sheets: list[tuple[str, str]] = []
        for node in workbook.iter():
            if _local(node.tag) != "sheet":
                continue
            name = node.attrib.get("name") or ""
            rel_id = node.attrib.get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ) or ""
            target = rels.get(rel_id)
            if target:
                sheets.append((name, _resolve("xl/workbook.xml", target)))
        if not sheets:
            raise ValueError("не удалось прочитать файл Excel")
        wanted = preferred_name.casefold()
        path = next(
            (item[1] for item in sheets if item[0].casefold() == wanted),
            sheets[0][1],
        )
        shared: list[str] = []
        names = set(zf.namelist())
        shared_name = next(
            (name for name in names if name.replace("\\", "/").endswith("sharedStrings.xml")),
            "",
        )
        if shared_name:
            shared = _shared_strings(_read_part(zf, shared_name))
        return _sheet_rows(_read_part(zf, path), shared)
