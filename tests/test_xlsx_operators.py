#!/usr/bin/env python3
"""Phase 6 exit benchmark — XLSX semantic operators, held green.

docs/DESIGN-P6-xlsx-operators.md preregistered exactly this: the workbook
bridge into the typed table world must show, before it becomes permanent,

  1. BYTE DETERMINISM  same table -> byte-identical workbook in two arenas
  2. EXACT ROUND TRIP  export -> import reproduces the CSV text exactly
  3. FOREIGN WORKBOOK  a hand-built shared-string workbook imports exactly
  4. REFUSALS          formula/merged/error cells, DOCTYPE, escaping member,
                       missing sheet, oversized grid, non-workbook, schema
                       violation — each by name, before any side effect
  5. TYPED IMPORT      schema is conforms-or-refuse; the CSV feeds
                       transform_table unchanged
  6. END TO END        import -> aggregate -> export from two gated
                       trajectories -> candidate -> owner-sealed fresh suite
                       -> PROVEN -> zero-model replay under an INDEPENDENT
                       stdlib gate that unzips the produced workbook
  7. REGISTRATION      the tool pair and the two predicates exist

Mock providers stand in for the model; the machinery under test is the
platform's. The routed task's worker gets an EMPTY provider script.

Run from the agent/ directory:  python tests/test_xlsx_operators.py
"""
import decimal
import io
import json
import os
import sys
import tempfile
import warnings
import zipfile

from common import AGENT_DIR, PY, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import fleet                    # noqa: E402
import loop                     # noqa: E402
import operators                # noqa: E402
import procedure                # noqa: E402
import runbook                  # noqa: E402
import tabletypes               # noqa: E402
import tabular                  # noqa: E402
import xlsxstate                # noqa: E402

FAMILY = "workbookreport"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _settings(root, providers):
    s = ['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
         'poll_interval_seconds = 1', 'max_task_usd = 0', 'reflect_after = []',
         'max_done_rejects = 2', 'max_task_retries = 0', '']
    for name in providers:
        s += [f'[providers.{name}]', 'type = "mock"',
              f'script = "scripts/{name}.json"', '']
    s += ['[roles.default]', f'provider = "{providers[0]}"', 'model = "mock"', '']
    for name in providers:
        s += [f'[roles.r_{name}]', f'provider = "{name}"', 'model = "mock"', '']
    io.open(os.path.join(root, "settings.toml"), "w",
            encoding="utf-8").write("\n".join(s))
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)


def _script(root, name, steps):
    json.dump(steps, io.open(os.path.join(root, "scripts", f"{name}.json"),
                             "w", encoding="utf-8"))


def _events(root):
    out = []
    for line in io.open(os.path.join(root, "logs", "agent.log"),
                        encoding="utf-8", errors="replace"):
        if "{" in line and line.rstrip().endswith("}"):
            try:
                out.append(json.loads(line[line.index("{"):]))
            except ValueError:
                pass
    return out


def _tasks(root):
    p = os.path.join(root, "state.json")
    if not os.path.isfile(p):
        return []
    return json.load(io.open(p, encoding="utf-8"))["tasks"]


def refuses(fragment, fn, *args):
    try:
        fn(*args)
    except ValueError as exc:
        assert fragment in str(exc), (fragment, str(exc))
        return
    raise AssertionError(f"accepted what must be refused: {fragment}")


def _routed_done(root, goal, inputs, done_check, family):
    agent = loop.Agent(root)
    agent.add_task("r_silent", goal, done_check=done_check, family=family,
                   inputs=inputs)
    assert run_drain(root, timeout=180) == 0
    third = _tasks(root)[-1]
    assert third["status"] == "done" and third.get("procedure_routed"), third
    routed = [e for e in _events(root) if e.get("event") == "procedure_route"]
    assert routed and routed[-1]["model_calls"] == 0, routed
    return third


def _arena(name):
    base = os.environ.get("AGENT_TEST_TMP") or os.path.join(
        tempfile.gettempdir(), "agent-suite")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix=f"xlsx-{name}-", dir=base)


TABLE = ('region,amount,note,flag\n'
         'north,10.50,"has, comma",true\n'
         'south,-3.25,"multi\nline",false\n'
         'east,007,leading zero stays text,\n'
         'west,0,"quote ""q"" and unicode — é",true\n')

SHARED = ('<?xml version="1.0" encoding="UTF-8"?>'
          f'<sst xmlns="{NS}" count="3" uniqueCount="3">'
          '<si><t>name</t></si><si><r><t>ri</t></r><r><t>ch</t></r></si>'
          '<si><t xml:space="preserve"> padded </t></si></sst>')
SHEET = ('<?xml version="1.0" encoding="UTF-8"?>'
         f'<worksheet xmlns="{NS}"><sheetData>'
         '<row r="1"><c r="A1" t="s"><v>0</v></c>'
         '<c r="B1" t="inlineStr"><is><t>qty</t></is></c></row>'
         '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>3</v></c></row>'
         '<row r="3"><c r="A3" t="s"><v>2</v></c><c r="B3" t="b"><v>1</v></c></row>'
         '</sheetData></worksheet>')
WORKBOOK = ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships"><sheets>'
            '<sheet name="Data" sheetId="1" r:id="rId3"/></sheets></workbook>')
RELS = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://'
        'schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId3" Type="x" Target="/xl/worksheets/sheet7.xml"/>'
        '<Relationship Id="rId9" Type="y" Target="sharedStrings.xml"/>'
        '</Relationships>')


def _foreign(path, sheet_xml=SHEET, extra=None):
    """A workbook this adapter did NOT write: deflated, shared strings with
    rich runs, an absolute relationship target, a non-default part name."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", WORKBOOK)
        zf.writestr("xl/_rels/workbook.xml.rels", RELS)
        zf.writestr("xl/sharedStrings.xml", SHARED)
        zf.writestr("xl/worksheets/sheet7.xml", sheet_xml)
        for name, body in (extra or {}).items():
            zf.writestr(name, body)
    return path


# ------------------------------------------------------- 7. registration

def check_registration():
    for tool in ("xlsx_import", "xlsx_export"):
        assert tool in procedure.DETERMINISTIC_TOOLS, tool
    names = [t["function"]["name"] for t in loop.TOOL_DEFS]
    assert "xlsx_import" in names and "xlsx_export" in names, names
    operators.validate_predicate({"predicate": "sheet_equals_table", "path": "w",
                                  "sheet": "S", "table": "t.csv"})
    operators.validate_predicate({"predicate": "sheet_conforms", "path": "w",
                                  "sheet": "S", "schema": "{}"})
    refuses("sheet_equals_table needs", operators.validate_predicate,
            {"predicate": "sheet_equals_table", "path": "w", "sheet": "S"})
    refuses("sheet_conforms needs", operators.validate_predicate,
            {"predicate": "sheet_conforms", "path": "w", "sheet": "S"})
    print("[registration] xlsx_import/xlsx_export declared; sheet_equals_table "
          "and sheet_conforms in the observable algebra")


# ---------------------------------------------------- 1. byte determinism

def check_byte_determinism():
    a = os.path.join(_arena("det-a"), "t.xlsx")
    b = os.path.join(_arena("det-b"), "t.xlsx")
    xlsxstate.write_workbook(a, TABLE, "Sales")
    xlsxstate.write_workbook(b, TABLE, "Sales")
    with open(a, "rb") as fa, open(b, "rb") as fb:
        bytes_a, bytes_b = fa.read(), fb.read()
    assert bytes_a == bytes_b and bytes_a == xlsxstate.export_bytes(TABLE, "Sales")
    assert xlsxstate.export_bytes(TABLE.replace("10.50", "10.51"), "Sales") != bytes_a
    assert xlsxstate.export_bytes(TABLE, "Other") != bytes_a
    with zipfile.ZipFile(io.BytesIO(bytes_a)) as zf:
        infos = zf.infolist()
        assert [i.filename for i in infos] == list(xlsxstate.MEMBER_ORDER)
        assert all(i.date_time == xlsxstate.TIMESTAMP and
                   i.compress_type == zipfile.ZIP_STORED and
                   i.create_system == 0 for i in infos), \
            "stored members, fixed timestamp, fixed creator: the constants"
    print("[byte-determinism] the same table in two arenas is one workbook, "
          "byte for byte; a cell or the sheet name changed changes it")


# ------------------------------------------------------- 2. round trip

def check_exact_round_trip():
    path = os.path.join(_arena("trip"), "t.xlsx")
    xlsxstate.write_workbook(path, TABLE, "Sales")
    back = xlsxstate.read_table(path, "Sales")
    assert back == TABLE, (back, TABLE)
    assert xlsxstate.sheet_equals(path, "Sales", TABLE)
    assert not xlsxstate.sheet_equals(path, "Sales", TABLE.replace("007", "7"))
    empty = "a,b\n,\n"
    p2 = os.path.join(_arena("trip2"), "e.xlsx")
    xlsxstate.write_workbook(p2, empty)
    assert xlsxstate.read_table(p2) == empty, "empty cells survive by padding"
    print("[round-trip] decimals with trailing zeros, a leading-zero text, "
          "commas, quotes, newlines, unicode, booleans and empty cells came "
          "back as the identical CSV text")


# --------------------------------------------------- 3. foreign workbook

def check_foreign_workbook():
    path = _foreign(os.path.join(_arena("foreign"), "f.xlsx"))
    assert xlsxstate.read_table(path, "Data") == "name,qty\nrich,3\n padded ,true\n"
    print("[foreign] a deflated workbook with shared strings, rich runs, "
          "preserved spaces, an absolute relationship target and a "
          "non-default part name imported exactly")


# --------------------------------------------------------- 4. refusals

def check_refusals(home):
    arena = _arena("refuse")
    mk = lambda name, xml, extra=None: _foreign(os.path.join(arena, name), xml, extra)
    refuses("formula", xlsxstate.read_table, mk("f.xlsx", SHEET.replace(
        '<c r="B2"><v>3</v></c>', '<c r="B2"><f>1+2</f><v>3</v></c>')), "Data")
    refuses("merged", xlsxstate.read_table, mk("m.xlsx", SHEET.replace(
        "</sheetData>", '</sheetData><mergeCells count="1">'
                        '<mergeCell ref="A1:B1"/></mergeCells>')), "Data")
    refuses("error value", xlsxstate.read_table, mk("e.xlsx", SHEET.replace(
        '<c r="B2"><v>3</v></c>', '<c r="B2" t="e"><v>#DIV/0!</v></c>')), "Data")
    refuses("DOCTYPE", xlsxstate.read_table, mk(
        "d.xlsx", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "boom">]>'
                  + SHEET[SHEET.index("<worksheet"):]), "Data")
    refuses("escapes", xlsxstate.read_table,
            mk("t.xlsx", SHEET, {"../evil.xml": "<x/>"}), "Data")
    refuses("not found", xlsxstate.read_table, mk("n.xlsx", SHEET), "Nope")
    refuses("exceeds", xlsxstate.read_table, mk("big.xlsx", SHEET.replace(
        "</sheetData>", '<row r="250001"><c r="A250001"><v>1</v></c></row>'
                        "</sheetData>")), "Data")
    plain = os.path.join(arena, "plain.xlsx")
    with open(plain, "wb") as f:
        f.write(b"not a zip")
    refuses("not a workbook", xlsxstate.read_table, plain, "Data")
    refuses("not acceptable", xlsxstate.canonical_sheet, "bad/name")
    refuses("control character", xlsxstate.export_bytes, "a\n\x01\n", "S")
    # ambiguity is refused, not interpreted (docs/DESIGN-P6.1, finding 5)
    refuses("duplicate cell", xlsxstate.read_table, mk("dupcell.xlsx", SHEET.replace(
        '<c r="B2"><v>3</v></c>', '<c r="B2"><v>3</v></c><c r="B2"><v>4</v></c>')),
        "Data")
    refuses("duplicate row", xlsxstate.read_table, mk("duprow.xlsx", SHEET.replace(
        '<row r="3">', '<row r="2">')), "Data")
    refuses("numbered from 1", xlsxstate.read_table, mk("row0.xlsx", SHEET.replace(
        '<row r="1">', '<row r="0">')), "Data")
    refuses("stored as 0 or 1", xlsxstate.read_table, mk("bool.xlsx", SHEET.replace(
        '<c r="B3" t="b"><v>1</v></c>', '<c r="B3" t="b"><v>2</v></c>')), "Data")
    dup = os.path.join(arena, "dupmember.xlsx")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(dup, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("xl/workbook.xml", WORKBOOK)
            zf.writestr("xl/workbook.xml", WORKBOOK.replace("Data", "Other"))
            zf.writestr("xl/_rels/workbook.xml.rels", RELS)
            zf.writestr("xl/sharedStrings.xml", SHARED)
            zf.writestr("xl/worksheets/sheet7.xml", SHEET)
    refuses("duplicate member", xlsxstate.read_table, dup, "Data")
    # the worker tool: a schema violation refuses before the CSV lands
    desk = fleet.create(home, "Refusal Desk", "checks workbook refusals")
    _settings(desk, ["m"])
    _script(desk, "m", [])
    os.makedirs(os.path.join(desk, "in"), exist_ok=True)
    xlsxstate.write_workbook(os.path.join(desk, "in", "bad.xlsx"),
                             "region,amount\nnorth,1.005\n")
    agent = loop.Agent(desk)
    probe = {"id": "refuse-probe", "role": "r_m", "goal": "probe"}
    out = agent._exec_tool(probe, "xlsx_import", {
        "path": "in/bad.xlsx", "sheet": "Sheet1", "out": "work/bad.csv",
        "schema": json.dumps({"columns": {"region": "identifier",
                                          "amount": "money:USD:2"}})})
    assert out.startswith("ERROR") and "money:USD:2" in out, out
    assert not os.path.exists(os.path.join(desk, "work", "bad.csv"))
    out = agent._exec_tool(probe, "xlsx_import", {
        "path": "in/bad.xlsx", "sheet": "Ghost", "out": "work/bad.csv"})
    assert out.startswith("ERROR") and "not found" in out, out
    print("[refusals] formula, merged and error cells, a DOCTYPE, an escaping "
          "member, a missing sheet, an oversized grid, a non-workbook, a bad "
          "sheet name, a control character, a schema violation, duplicate "
          "cells, duplicate rows, row zero, a malformed boolean and a "
          "duplicate package member each refused by name before any side "
          "effect")


def check_evidence_hashes_workbook_bytes():
    """Finding 4 of docs/DESIGN-P6.1: a lossy text decode lets two different
    files share one hash; workbook evidence must be the bytes."""
    import fileauth
    root = _arena("bytes")
    os.makedirs(os.path.join(root, "out"))
    for name, data in (("a.xlsx", b"\xff"), ("b.xlsx", b"\xfe")):
        with open(os.path.join(root, "out", name), "wb") as f:
            f.write(data)
    assert fileauth.read_text(root, "out/a.xlsx") == \
        fileauth.read_text(root, "out/b.xlsx"), "the decode reads them as one"

    def evidence(name):
        return procedure._snapshot(root, {
            "tool": "xlsx_export",
            "args": {"source": "x.csv", "path": f"out/{name}", "sheet": "S"}})
    assert evidence("a.xlsx")["path"]["hash"] != evidence("b.xlsx")["path"]["hash"]
    assert evidence("a.xlsx")["path"]["hash"] == fileauth.sha256_bytes(root, "out/a.xlsx")
    print("[byte-evidence] two workbooks that decode to the same text but "
          "differ in bytes carry different trajectory evidence — hashed as "
          "the bytes they are")


# ------------------------------------------------------ 5. typed import

SALES_SCHEMA = json.dumps({"columns": {"region": "identifier",
                                       "amount": "money:USD:2"}})
REPORT_SPEC = json.dumps({"steps": [
    {"op": "aggregate", "group": ["region"],
     "aggregations": {"total": {"fn": "sum", "column": "amount"}}},
    {"op": "sort", "column": "region"}]})
REPORT_SCHEMA = json.dumps({"columns": {"region": "identifier",
                                        "total": "money:USD:2"}})


def check_typed_import_feeds_the_table_world(home):
    desk = fleet.create(home, "Typed Desk", "imports typed sheets")
    _settings(desk, ["m"])
    _script(desk, "m", [])
    os.makedirs(os.path.join(desk, "in"), exist_ok=True)
    sales = "region,amount\nnorth,10.50\nsouth,3.25\nnorth,1.00\n"
    xlsxstate.write_workbook(os.path.join(desk, "in", "sales.xlsx"), sales)
    agent = loop.Agent(desk)
    probe = {"id": "typed-probe", "role": "r_m", "goal": "probe"}
    out = agent._exec_tool(probe, "xlsx_import", {
        "path": "in/sales.xlsx", "sheet": "Sheet1", "out": "work/sales.csv",
        "schema": SALES_SCHEMA})
    assert out.startswith("ok, imported 3 row(s)"), out
    assert io.open(os.path.join(desk, "work", "sales.csv"),
                   encoding="utf-8").read() == sales
    out = agent._exec_tool(probe, "transform_table", {
        "source": "work/sales.csv", "path": "work/report.csv",
        "spec": REPORT_SPEC, "schema": REPORT_SCHEMA})
    assert out.startswith("ok, derived 2 data row(s)"), out
    report = io.open(os.path.join(desk, "work", "report.csv"),
                     encoding="utf-8").read()
    assert report == tabular.apply(REPORT_SPEC, sales), report
    assert tabular.parse(report)[1][0][0] == "north" and \
        decimal.Decimal(tabular.parse(report)[1][0][1]) == decimal.Decimal("11.50")
    out = agent._exec_tool(probe, "xlsx_export", {
        "source": "work/report.csv", "path": "out/report.xlsx",
        "sheet": "Report", "schema": REPORT_SCHEMA})
    assert out.startswith("ok, exported 2 data row(s)"), out
    assert xlsxstate.sheet_equals(os.path.join(desk, "out", "report.xlsx"),
                                  "Report", report)
    assert operators.observe(desk, {"predicate": "sheet_equals_table",
                                    "path": "out/report.xlsx", "sheet": "Report",
                                    "table": "work/report.csv"})
    assert operators.observe(desk, {"predicate": "sheet_conforms",
                                    "path": "out/report.xlsx", "sheet": "Report",
                                    "schema": REPORT_SCHEMA})
    assert not operators.observe(desk, {"predicate": "sheet_equals_table",
                                        "path": "out/report.xlsx",
                                        "sheet": "Report",
                                        "table": "work/sales.csv"})
    print("[typed-import] a money-typed sheet imported conforms-or-refuse, "
          "fed transform_table unchanged, and the aggregate went back out as "
          "a workbook both predicates observe")


# --------------------------------------------- 6. end to end (learning)

GATE = r'''import csv, decimal, io, sys, zipfile
import xml.etree.ElementTree as ET
out, expect = sys.argv[1], sys.argv[2]
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
with zipfile.ZipFile(out) as zf:
    root = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    names = [s.get("name") for s in
             ET.fromstring(zf.read("xl/workbook.xml")).iter(NS + "sheet")]
rows = []
for row in root.iter(NS + "row"):
    cells = []
    for c in row.findall(NS + "c"):
        if c.get("t") == "inlineStr":
            cells.append("".join(t.text or "" for t in c.iter(NS + "t")))
        else:
            v = c.find(NS + "v")
            cells.append(v.text if v is not None else "")
    rows.append(cells)
want = list(csv.reader(io.open(expect, encoding="utf-8")))
ok = (names == ["Report"] and rows[0] == want[0] and len(rows) == len(want)
      and all(r[0] == w[0] and decimal.Decimal(r[1]) == decimal.Decimal(w[1])
              for r, w in zip(rows[1:], want[1:])))
sys.exit(0 if ok else 1)
'''

MONTHS = {
    "m1": ("region,amount\nnorth,10.50\nsouth,3.25\nnorth,1.00\n",
           "region,total\nnorth,11.50\nsouth,3.25\n"),
    "m2": ("region,amount\neast,2.00\nwest,5.75\neast,0.25\n",
           "region,total\neast,2.25\nwest,5.75\n"),
    "m4": ("region,amount\nalpha,1.10\nbeta,2.20\nalpha,3.30\n",
           "region,total\nalpha,4.40\nbeta,2.20\n"),
    "m5": ("region,amount\nsolo,9.99\n", "region,total\nsolo,9.99\n"),
    "m6": ("region,amount\nneg,-4.00\npos,4.00\nneg,-1.00\n",
           "region,total\nneg,-5.00\npos,4.00\n"),
    "m9": ("region,amount\nnorth,100.00\nnorth,0.01\nsouth,7.00\n",
           "region,total\nnorth,100.01\nsouth,7.00\n"),
}


def _inputs(month):
    return {"workbook": f"in/sales-{month}.xlsx",
            "sales": f"work/sales-{month}.csv",
            "report": f"work/report-{month}.csv",
            "output": f"out/report-{month}.xlsx"}


def _steps(inp):
    return [
        {"tool": "xlsx_import", "args": {"path": inp["workbook"],
                                         "sheet": "Sheet1", "out": inp["sales"],
                                         "schema": SALES_SCHEMA}},
        {"tool": "transform_table", "args": {"source": inp["sales"],
                                             "path": inp["report"],
                                             "spec": REPORT_SPEC,
                                             "schema": REPORT_SCHEMA}},
        {"tool": "xlsx_export", "args": {"source": inp["report"],
                                         "path": inp["output"],
                                         "sheet": "Report"}},
        {"tool": "finish_task", "args": {"summary": "reported"}}]


def _gate(root, month):
    io.open(os.path.join(root, f"expect-{month}.csv"), "w",
            encoding="utf-8").write(MONTHS[month][1])
    return f'"{PY}" check.py out/report-{month}.xlsx expect-{month}.csv'


def check_end_to_end_learning(home):
    root = fleet.create(home, "Report Desk", "turns sales workbooks into reports")
    _settings(root, ["wa", "wb", "silent"])
    io.open(os.path.join(root, "check.py"), "w", encoding="utf-8").write(GATE)
    os.makedirs(os.path.join(root, "in"), exist_ok=True)
    agent = loop.Agent(root)
    for prov, month in (("wa", "m1"), ("wb", "m2")):
        xlsxstate.write_workbook(os.path.join(root, "in", f"sales-{month}.xlsx"),
                                 MONTHS[month][0])
        inp = _inputs(month)
        _script(root, prov, _steps(inp))
        agent.add_task(f"r_{prov}", f"prepare the {FAMILY} for {month}",
                       done_check=_gate(root, month), family=FAMILY, inputs=inp)
    assert run_drain(root, timeout=240) == 0
    done = _tasks(root)[-2:]
    assert all(t["status"] == "done" for t in done), done
    assert any(e.get("event") == "procedure_compiled" for e in _events(root)), \
        [e for e in _events(root) if "procedure" in str(e.get("event"))]
    assert runbook.status(root, f"proc-{FAMILY}") == "candidate"
    rb = runbook.load(root, f"proc-{FAMILY}")
    assert rb["operator"]["inputs"] == {"workbook": "path", "sales": "path",
                                        "report": "path", "output": "path"}, \
        rb["operator"]["inputs"]
    tools = [s["action"]["tool"] for s in rb["steps"]]
    assert tools == ["xlsx_import", "transform_table", "xlsx_export"], tools
    assert rb["steps"][0]["effects"][0] == {
        "predicate": "sheet_equals_table", "path": {"input": "workbook"},
        "sheet": "Sheet1", "table": {"input": "sales"}}, rb["steps"][0]["effects"]
    assert rb["steps"][2]["effects"][0] == {
        "predicate": "sheet_equals_table", "path": {"input": "output"},
        "sheet": "Report", "table": {"input": "report"}}, rb["steps"][2]["effects"]
    assert rb["steps"][0]["action"]["args"]["schema"] == \
        tabletypes.canonical_schema(SALES_SCHEMA), "constants stay literal"
    fresh = ["m4", "m5", "m6"]
    procedure.seal_suite(root, f"{FAMILY}-fresh", {
        "family": FAMILY,
        "cases": [{"id": month, "edge": month == "m6", "inputs": _inputs(month)}
                  for month in fresh],
        "initial_files": [{"path": f"in/sales-{month}.xlsx",
                           "content": MONTHS[month][0]} for month in fresh],
        "checks": [{"predicate": "sheet_equals_table",
                    "path": {"input": "workbook"}, "sheet": "Sheet1",
                    "table": {"input": "sales"}},
                   {"predicate": "file_derives", "path": {"input": "report"},
                    "spec": tabular.canonical(REPORT_SPEC),
                    "source": {"input": "sales"}},
                   {"predicate": "sheet_conforms", "path": {"input": "output"},
                    "sheet": "Report", "schema": REPORT_SCHEMA},
                   {"predicate": "sheet_equals_table",
                    "path": {"input": "output"}, "sheet": "Report",
                    "table": {"input": "report"}}]})
    verdict = procedure.evaluate(root, f"proc-{FAMILY}", f"{FAMILY}-fresh")
    assert verdict["accepted"] and verdict["status"] == "proven", verdict
    _script(root, "silent", [])
    xlsxstate.write_workbook(os.path.join(root, "in", "sales-m9.xlsx"),
                             MONTHS["m9"][0])
    _routed_done(root, f"prepare the {FAMILY} for m9", _inputs("m9"),
                 _gate(root, "m9"), FAMILY)
    produced = xlsxstate.read_table(os.path.join(root, "out", "report-m9.xlsx"),
                                    "Report")
    assert tabular.parse(produced) == tabular.parse(
        tabular.apply(REPORT_SPEC, MONTHS["m9"][0])), produced
    assert decimal.Decimal(tabular.parse(produced)[1][0][1]) == \
        decimal.Decimal("100.01"), "exact cents, never a float"
    print("[end-to-end] import -> aggregate -> export went candidate from two "
          "gated trajectories, PROVEN on a sealed fresh suite whose workbooks "
          "were materialized from sealed CSV (edge: negative amounts), and "
          "replayed month nine with zero model calls under an independent "
          "stdlib gate that unzipped the produced workbook")


def main():
    home = make_sandbox("xlsx-operators",
                        providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    check_registration()
    check_byte_determinism()
    check_exact_round_trip()
    check_foreign_workbook()
    check_refusals(home)
    check_evidence_hashes_workbook_bytes()
    check_typed_import_feeds_the_table_world(home)
    check_end_to_end_learning(home)
    print("PASS test_xlsx_operators")


if __name__ == "__main__":
    main()
