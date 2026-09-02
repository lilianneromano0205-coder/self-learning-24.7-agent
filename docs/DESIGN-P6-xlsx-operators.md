# DESIGN — Phase 6: XLSX semantic operators

**Branch:** `phase6/xlsx-operators` · **Status:** BUILT — the preregistered
benchmark below is `tests/test_xlsx_operators.py` in the acceptance suite;
all seven properties hold (first run: byte-identical workbooks in two
arenas; exact round trip; a foreign shared-string workbook read exactly;
`procedure_compiled` from two gated trajectories; PROVEN on a sealed fresh
suite whose workbooks were materialized from sealed CSV; `procedure_route`
with `model_calls: 0` under an independent stdlib gate). Implementation:
`xlsxstate.py`, `sheet_equals_table`/`sheet_conforms` in `operators.py`,
the `xlsx_import`/`xlsx_export` leaves through `procedure.py` (with `.xlsx`
suite materialization), the tool pair in `loop.py`, `fileauth.write_bytes`.
· **Contract:**
[VISION_CONTRACT.md](../VISION_CONTRACT.md) binds every decision. ·
**Audit order:** the 2026-09-02 checkpoint audit's operator-universe order
after Git — *"2. XLSX/Excel — because enormous amounts of human business
labor live there"* — under the same rule: name the measurable capability
and the benchmark that must pass before the phase becomes permanent.

## The problem, stated from evidence

The table world (`transform_table`, `tabular.py`, `tabletypes.py`) is
exact, typed and provable — and CSV-only. The files business work actually
arrives in and must leave in are workbooks. Today a worker can touch an
`.xlsx` only through `run_command`, and the repository is stdlib-only by
design (zero third-party dependencies, which the invariants enforce), so
there is not even a library to call: every workbook step is a model step
that no gate can observe and no trajectory can compile. The LEARN-001
families the thesis must cover include *recurring report preparation*,
which in the world outside this repository means "produce the workbook".

## What Phase 6 builds — measurable capability

**`xlsxstate.py`** — a deterministic workbook adapter written on
`zipfile` + `xml.etree` alone, which treats a sheet as a typed table and
bridges it to the existing table world instead of inventing a fifth one:

```
xlsx_import {path, sheet, out, schema?}   sheet cell grid -> CSV file at out
                                           (exact stored values; optional
                                           conforms-or-refuse typing)
xlsx_export {source, path, sheet, schema?} CSV table -> NEW single-sheet
                                           workbook, byte-deterministic
```

The capability in one sentence: **a recurring "workbook in, computed
workbook out" job can become a proven procedure whose replay is exact and
model-free** — imported grids feed `transform_table`'s closed algebra, and
the exported workbook is a pure function of the table it came from.

### Exactness rules (the ones that make a workbook evidence)

- **Values are the stored text, verbatim.** A numeric cell's `<v>` text is
  read as written (`10.50` stays `10.50`; a stored `0.30000000000000004`
  is reported as exactly that — the adapter never floats a value it did
  not float). Shared strings and inline strings are read verbatim.
  Booleans read as `true`/`false`. Empty cells read as empty text; the
  grid is made rectangular by padding, never by dropping.
- **Formulas refuse.** A formula cell's cached value is whatever the last
  application computed; it is not re-derivable here, so it is not
  evidence. Merged cells and error cells refuse for the same reason.
  Date serials are numbers and are read as the numbers they are stored as
  (documented; typing them is the schema's job on the CSV side).
- **Export is a pure function of the table.** Numeric-looking cells
  (`-?\d+(\.\d+)?`) are written as number cells with their exact text;
  everything else as inline strings; no shared-string table, no styles
  beyond one constant minimal part, constant workbook/rels/content-types
  parts, fixed member order, fixed DOS timestamp, **stored (uncompressed)
  members** — so the output is byte-identical across hosts and zlib
  versions, not merely per host. Round trip (export → import) is exact.

### Safety of reading a foreign file

A workbook is untrusted input. The adapter refuses before parsing any part
that contains `<!DOCTYPE` or `<!ENTITY` (no legitimate workbook part has
them; entity expansion is the one attack the stdlib parser does not
bound); it caps members (≤ 64), total uncompressed bytes (≤ 64 MB) and
cells (`tabular.MAX_CELLS`); it refuses member names that are absolute or
contain `..`; it resolves the sheet through `workbook.xml` + its rels and
screens the sheet name. Nothing is ever executed from a workbook.

### Predicate

`sheet_equals_table {path, sheet, table}` — the sheet's grid, re-read now,
equals the CSV at `table` exactly (header and rows as text). One predicate
serves both directions: an import's effect is that the sheet equals the
CSV it produced; an export's effect is that the sheet equals the CSV it
came from. `sheet_conforms {path, sheet, schema}` types a sheet directly.

### Authority

A workbook is a file. Writing one is `workspace-write` through
`fileauth.write_bytes`-style atomic replace (the single mutation semantic
the invariants pin), like `transform_table`; there is no per-file token
because a workbook is not a stateful engine the way a database or a
repository is. Reading is workspace read.

### Wiring (each a one-line extension of an existing seam)

- `operators.py` — the two predicates in `validate_predicate`/`observe`.
- `procedure.py` — `xlsx_import`/`xlsx_export` join `DETERMINISTIC_TOOLS`;
  `_normalize` canonicalizes `schema`; `_snapshot` digests workbook BYTES
  (a binary file read as text would still be deterministic but would say
  nothing); `finish_action` re-derives (export: the bytes the table
  yields; import: the grid the workbook yields) and compares; `_perform`
  executes; `_compile_aligned` emits `sheet_equals_table` effects.
- `loop.py` — the tool pair with capture hooks. No route grant change.
- `signatures.py` — unchanged; two more operator leaves.

## Benchmark (exit criterion, preregistered before build)

`tests/test_xlsx_operators.py`:

1. **Byte determinism:** the same table exported in two arenas yields
   byte-identical workbooks; one cell changed changes the bytes; the
   member list and timestamps are the constants the design names.
2. **Exact round trip:** export → import reproduces the CSV text exactly
   for decimals with trailing zeros, strings with commas/quotes/newlines/
   unicode, empty cells and booleans.
3. **Foreign workbook:** a hand-built fixture using a shared-string table
   (built with `zipfile` in the test, no library) imports to exactly the
   expected CSV — the reader is not merely reading its own writer.
4. **Refusals before any side effect:** formula, merged and error cells; a
   `<!DOCTYPE`/`<!ENTITY` part; a member name with `..`; a missing sheet;
   an oversized grid; a non-workbook file; a schema the grid violates
   (money with three decimals) — each refuses by name.
5. **Typed import:** `schema` makes an import conforms-or-refuse, and the
   imported CSV feeds `transform_table` unchanged.
6. **End to end through the learning loop:** the "monthly workbook
   report" family — import a sheet → `transform_table` aggregate →
   export the report workbook — from two gated trajectories becomes a
   CANDIDATE, an owner-sealed fresh suite (edge: a sheet with an empty
   cell and a negative amount) takes it to PROVEN, and a silent worker
   replays a new month with **zero model calls** under an independent
   gate that unzips the produced workbook and checks the cells with the
   stdlib alone.
7. No existing test weakened; `test_vision_preservation.py` untouched;
   harness manifest, prose counts and execution audit updated.

## What this phase does NOT claim

No real-model result (mock workers, as in Phases 1–5). No in-place edit of
an existing multi-sheet workbook: `xlsx_export` creates a new workbook,
and replacing one sheet inside a foreign workbook while preserving its
other parts byte for byte is named as the next XLSX step, not done here.
No formulas are ever written: the harness computes, the workbook records.
