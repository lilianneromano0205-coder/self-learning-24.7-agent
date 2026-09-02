"""Workbook state — the XLSX bridge into the typed table world.

docs/DESIGN-P6-xlsx-operators.md names the rules this module enforces. A
sheet is a typed table: `read_table` turns a sheet's cell grid into the
exact CSV text the table world already trusts, and `export_bytes` turns a
CSV table into a workbook that is a pure function of that table — so the
imported grid feeds transform_table's closed algebra, and the exported
workbook can be re-derived by anyone at any later moment.

Exactness:
  - values are the STORED TEXT, verbatim: a numeric cell's <v> text is
    read as written (10.50 stays 10.50); shared and inline strings are
    read verbatim; booleans read as true/false; empty cells read as
    empty text, and the grid is made rectangular by padding, never by
    dropping. Date serials are the numbers they are stored as;
  - formulas, merged cells and error cells REFUSE — a cached result is
    whatever the last application computed, not something re-derivable
    here, so it cannot be evidence;
  - export writes numeric-looking cells as number cells with their exact
    text and everything else as inline strings, one constant styles part,
    constant package parts, fixed member order, a fixed timestamp and
    STORED (uncompressed) members — byte-identical across hosts and zlib
    versions, and an exact round trip.

Safety: a workbook is untrusted input. Every XML part is refused if it
carries a DOCTYPE or ENTITY declaration (the one attack the stdlib parser
does not bound); members, total bytes and cells are capped; member names
that escape are refused; nothing is ever executed from a workbook.

Authority: a workbook is a file — writing one is workspace-write through
the file authority's atomic replace; reading is workspace read.
"""
import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from xml.sax.saxutils import escape

import tabular

MAX_MEMBERS = 64
MAX_BYTES = 64 * 1024 * 1024
MAX_CELLS = tabular.MAX_CELLS
DEFAULT_SHEET = "Sheet1"

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

_SHEET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,30}$")
_NUMBER_RE = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
_CELL_RE = re.compile(r"^([A-Z]{1,3})([1-9]\d*)$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_DECLARATION_RE = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)", re.I)

_XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_CONTENT_TYPES = _XML_HEADER + (
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    '</Types>')
_RELS = _XML_HEADER + (
    f'<Relationships xmlns="{NS_PKG_REL}">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>')
_WORKBOOK = _XML_HEADER + (
    f'<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_REL}">'
    '<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets>'
    '</workbook>')
_WORKBOOK_RELS = _XML_HEADER + (
    f'<Relationships xmlns="{NS_PKG_REL}">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '</Relationships>')
_STYLES = _XML_HEADER + (
    f'<styleSheet xmlns="{NS_MAIN}">'
    '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>')
MEMBER_ORDER = ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                "xl/_rels/workbook.xml.rels", "xl/styles.xml",
                "xl/worksheets/sheet1.xml")
TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _fail(why):
    raise ValueError(f"workbook: {why}")


def _tag(name):
    return f"{{{NS_MAIN}}}{name}"


def canonical_sheet(name):
    if name is None or name == "":
        return DEFAULT_SHEET
    if not isinstance(name, str) or not _SHEET_RE.match(name):
        _fail(f"sheet name {name!r} is not acceptable (letters, digits, "
              f"space, _ . -, at most 31 chars)")
    return name


# --------------------------------------------------------------- reading

def _guard_xml(data, part):
    if _DECLARATION_RE.search(data):
        _fail(f"{part} carries a DOCTYPE/ENTITY declaration — no workbook "
              f"part legitimately does, and entity expansion is unbounded: "
              f"refused before parsing")


def _parse(zf, part):
    try:
        data = zf.read(part)
    except KeyError:
        _fail(f"missing part {part}")
    _guard_xml(data, part)
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        _fail(f"{part} is not well-formed XML ({exc})")


def _open(path):
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        _fail(f"not a workbook (not a readable zip package): {exc}")
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        zf.close()
        _fail(f"more than {MAX_MEMBERS} members")
    if sum(info.file_size for info in infos) > MAX_BYTES:
        zf.close()
        _fail(f"more than {MAX_BYTES} bytes uncompressed")
    for info in infos:
        name = info.filename
        if name.startswith(("/", "\\")) or "\\" in name or \
                (len(name) > 1 and name[1] == ":") or \
                any(part in ("..", "") for part in name.split("/")):
            zf.close()
            _fail(f"member name escapes the package: {name!r}")
    names = set(zf.namelist())
    if "xl/workbook.xml" not in names or "[Content_Types].xml" not in names:
        zf.close()
        _fail("not a workbook: no xl/workbook.xml part")
    return zf


def _column_index(letters):
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _col_letters(index):
    letters, number = "", index + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _sheet_part(zf, sheet):
    workbook = _parse(zf, "xl/workbook.xml")
    relationships = _parse(zf, "xl/_rels/workbook.xml.rels")
    targets = {rel.get("Id"): rel.get("Target") or ""
               for rel in relationships.iter(f"{{{NS_PKG_REL}}}Relationship")}
    names = []
    for entry in workbook.iter(_tag("sheet")):
        names.append(entry.get("name"))
        if entry.get("name") != sheet:
            continue
        target = targets.get(entry.get(f"{{{NS_REL}}}id"), "")
        part = target.lstrip("/") if target.startswith("/") else "xl/" + target
        if not target or part not in zf.namelist():
            _fail(f"sheet {sheet!r} names a part that does not exist")
        return part
    _fail(f"sheet {sheet!r} not found (workbook has {names})")


def _shared_strings(zf):
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = _parse(zf, "xl/sharedStrings.xml")
    return ["".join(t.text or "" for t in item.iter(_tag("t")))
            for item in root.iter(_tag("si"))]


def _grid(zf, part):
    root = _parse(zf, part)
    if root.find(_tag("mergeCells")) is not None:
        _fail("merged cells are not an exact grid: refused")
    shared = None
    rows, next_row = {}, 0
    for row in root.iter(_tag("row")):
        reference = row.get("r")
        row_index = int(reference) - 1 if reference and reference.isdigit() \
            else next_row
        next_row = row_index + 1
        cells, next_col = {}, 0
        for cell in row.findall(_tag("c")):
            ref = cell.get("r")
            if ref:
                match = _CELL_RE.match(ref)
                if not match:
                    _fail(f"cell reference {ref!r} is not acceptable")
                col_index = _column_index(match.group(1))
            else:
                col_index = next_col
            next_col = col_index + 1
            if cell.find(_tag("f")) is not None:
                _fail(f"cell {ref or col_index} holds a formula — a cached "
                      f"result is not re-derivable evidence: refused")
            kind = cell.get("t", "n")
            value = cell.find(_tag("v"))
            if kind == "s":
                if shared is None:
                    shared = _shared_strings(zf)
                index = int((value.text or "").strip()) if value is not None else -1
                if not 0 <= index < len(shared):
                    _fail(f"cell {ref} references shared string {index} "
                          f"of {len(shared)}")
                text = shared[index]
            elif kind == "inlineStr":
                inline = cell.find(_tag("is"))
                text = "".join(t.text or "" for t in inline.iter(_tag("t"))) \
                    if inline is not None else ""
            elif kind == "b":
                text = "true" if value is not None and \
                    (value.text or "").strip() == "1" else "false"
            elif kind == "e":
                _fail(f"cell {ref} holds an error value: refused")
            elif kind in ("n", "str"):
                text = (value.text or "") if value is not None else ""
            else:
                _fail(f"cell {ref} has unknown type {kind!r}")
            cells[col_index] = text
        rows[row_index] = cells
        if len(rows) * max((max(c, default=-1) + 1 for c in rows.values()),
                           default=0) > MAX_CELLS:
            _fail(f"sheet exceeds {MAX_CELLS} cells")
    if not rows:
        _fail("sheet is empty: no header row")
    height = max(rows) + 1
    width = max((max(cells) + 1 for cells in rows.values() if cells), default=0)
    if width == 0:
        _fail("sheet has no cells")
    if height * width > MAX_CELLS:
        _fail(f"sheet exceeds {MAX_CELLS} cells")
    return [[rows.get(r, {}).get(c, "") for c in range(width)]
            for r in range(height)]


def read_table(path, sheet=None):
    """Workbook file + sheet name -> exact CSV text of the grid (header row
    first), through tabular's own strict parser so the result is a table
    the rest of the runtime already accepts."""
    sheet = canonical_sheet(sheet)
    zf = _open(path)
    try:
        grid = _grid(zf, _sheet_part(zf, sheet))
    finally:
        zf.close()
    text = tabular.render(grid[0], grid[1:])
    tabular.parse(text)
    return text


def sheet_equals(path, sheet, table_text):
    """The sheet's grid, re-read now, equals this CSV table structurally
    (header and rows as text) — the predicate behind sheet_equals_table."""
    return tabular.parse(read_table(path, sheet)) == tabular.parse(table_text)


# --------------------------------------------------------------- writing

def _cell_xml(reference, value):
    if _CONTROL_RE.search(value):
        _fail(f"cell {reference} holds a control character XML cannot carry")
    if _NUMBER_RE.match(value):
        return f'<c r="{reference}"><v>{value}</v></c>'
    space = ' xml:space="preserve"' if value != value.strip() or \
        "\n" in value else ""
    return (f'<c r="{reference}" t="inlineStr"><is><t{space}>'
            f'{escape(value)}</t></is></c>')


def _sheet_xml(header, rows):
    parts = [_XML_HEADER, f'<worksheet xmlns="{NS_MAIN}"><sheetData>']
    for row_index, row in enumerate([header] + rows):
        cells = [_cell_xml(f"{_col_letters(col)}{row_index + 1}", value)
                 for col, value in enumerate(row) if value != ""]
        parts.append(f'<row r="{row_index + 1}">' + "".join(cells) + "</row>")
    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def export_bytes(table_text, sheet=None):
    """CSV text -> the bytes of a single-sheet workbook, a pure function of
    the table and the sheet name: constant parts, fixed order, fixed
    timestamp, stored members."""
    sheet = canonical_sheet(sheet)
    header, rows = tabular.parse(table_text)
    contents = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _RELS,
        "xl/workbook.xml": _WORKBOOK.replace("{name}", escape(sheet, {'"': "&quot;"})),
        "xl/_rels/workbook.xml.rels": _WORKBOOK_RELS,
        "xl/styles.xml": _STYLES,
        "xl/worksheets/sheet1.xml": _sheet_xml(header, rows)}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as zf:
        for name in MEMBER_ORDER:
            info = zipfile.ZipInfo(name, date_time=TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            info.external_attr = 0o644 << 16
            zf.writestr(info, contents[name].encode("utf-8"))
    return buffer.getvalue()


def write_workbook(target, table_text, sheet=None):
    """Materialize a workbook at an already-contained absolute path (owner
    suites bootstrap their input workbooks from sealed CSV text this way —
    binary fixtures cannot be sealed as text and would not be reviewable
    if they could). Atomic: temp beside the target, then replace."""
    data = export_bytes(table_text, sheet)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    temporary = f"{target}.{os.getpid()}.tmp"
    with open(temporary, "wb") as f:
        f.write(data)
    os.replace(temporary, target)
    return data
