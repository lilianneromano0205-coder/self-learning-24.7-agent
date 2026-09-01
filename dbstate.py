"""SQLite state — the second world of the Semantic Operator Runtime.

The design (docs/DESIGN-P1-semantic-operator-runtime.md) names the rule
this module exists to enforce: every mutation runs inside a transaction
whose COMMIT is gated on declared, observable assertions re-observing true
— else it rolls back and the database is untouched. The worker never gets
"I ran some SQL"; it gets "the state I promised is now true" or a refusal.

Determinism is what makes a db action trustable as evidence, so the SQL
surface is closed and screened:

  - statements: single INSERT / UPDATE / DELETE / CREATE TABLE /
    CREATE [UNIQUE] INDEX / SELECT / WITH, parameterized (?), params are
    str | int | None only — no floats (money is integer cents or text),
    no blobs;
  - banned everywhere: ATTACH, PRAGMA, VACUUM, DROP, ALTER, TRIGGER,
    load_extension, random(), and the clock family (CURRENT_*, 'now',
    'localtime') — a statement whose result depends on when it ran can
    never be re-derived;
  - assertions and observations are SELECT-only under the same screen,
    and their results must contain only int / str / NULL — a REAL in a
    result refuses, because approximate numbers cannot gate a commit.

Tool-name mapping (the design's dotted names, as worker tools):
  db.transaction + db.assert  ->  db_transaction (statements + assertions)
  db.select                   ->  db_query       (read-only observation)
  db.rollback                 ->  automatic on any failed assertion

Authority: writing a database requires the owner-granted token
"db-write:<relative-path>" (settings.toml [agent] db_write, default empty
— fail closed). Reading is workspace read.
"""
import json
import os
import re
import sqlite3

MAX_RESULT_ROWS = 10_000
MAX_STATEMENTS = 64
MAX_ASSERTIONS = 32

_ALLOWED_FIRST = ("select", "insert", "update", "delete", "with",
                  "create table", "create index", "create unique index")
_BANNED = ("attach", "pragma", "vacuum", "reindex", "analyze", "drop ",
           "alter ", "trigger", "load_extension", "random(", "randomblob(",
           "current_timestamp", "current_time", "current_date", "'now'",
           "'localtime'", "'utc'", "last_insert_rowid", "changes(",
           "total_changes")


def _fail(why):
    raise ValueError(f"db state: {why}")


def _screen(sql, *, read_only=False):
    if not isinstance(sql, str) or not sql.strip():
        _fail("empty SQL statement")
    lowered = " ".join(sql.lower().split())
    lowered_spaced = lowered + " "
    for token in _BANNED:
        if token in lowered_spaced:
            _fail(f"banned construct {token.strip()!r} in: {sql[:80]!r}")
    allowed = ("select", "with") if read_only else _ALLOWED_FIRST
    if not any(lowered.startswith(prefix) for prefix in allowed):
        _fail(f"statement must start with one of {allowed}: {sql[:80]!r}")
    return sql.strip()


def _screen_params(params):
    if not isinstance(params, list) or len(params) > 256:
        _fail("params must be a list of at most 256 values")
    for value in params:
        if value is not None and not isinstance(value, (str, int)) or \
                isinstance(value, bool):
            _fail(f"param {value!r} is not str | int | null — floats and "
                  f"blobs cannot be exact evidence")
    return params


def canonical_statements(text):
    """[{sql, params?}] -> one canonical JSON string, fully screened."""
    try:
        statements = json.loads(text) if isinstance(text, str) else None
    except ValueError as exc:
        _fail(f"statements are not valid JSON ({exc})")
    if not isinstance(statements, list) or not statements or \
            len(statements) > MAX_STATEMENTS:
        _fail(f"statements must be a list of 1..{MAX_STATEMENTS} entries")
    out = []
    for entry in statements:
        if not isinstance(entry, dict) or set(entry) - {"sql", "params"}:
            _fail("each statement is {sql, params?}")
        out.append({"sql": _screen(entry.get("sql")),
                    "params": _screen_params(entry.get("params") or [])})
    return json.dumps(out, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def canonical_assertions(text):
    """[{query, equals}] -> canonical JSON. `equals` is the exact expected
    result: a list of rows, each a list of int | str | null."""
    try:
        assertions = json.loads(text) if isinstance(text, str) else None
    except ValueError as exc:
        _fail(f"assertions are not valid JSON ({exc})")
    if not isinstance(assertions, list) or not assertions or \
            len(assertions) > MAX_ASSERTIONS:
        _fail(f"assertions must be a list of 1..{MAX_ASSERTIONS} entries — "
              f"a mutation with no declared observable effect is not gated")
    out = []
    for entry in assertions:
        if not isinstance(entry, dict) or set(entry) != {"query", "equals"}:
            _fail("each assertion is {query, equals}")
        rows = entry["equals"]
        if not isinstance(rows, list) or any(
                not isinstance(row, list) or any(
                    value is not None and not isinstance(value, (str, int))
                    or isinstance(value, bool) for value in row)
                for row in rows):
            _fail("equals must be rows of int | str | null")
        out.append({"query": _screen(entry["query"], read_only=True),
                    "equals": rows})
    return json.dumps(out, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _rows(cursor):
    rows = cursor.fetchmany(MAX_RESULT_ROWS + 1)
    if len(rows) > MAX_RESULT_ROWS:
        _fail(f"result exceeds {MAX_RESULT_ROWS} rows")
    out = []
    for row in rows:
        record = []
        for value in row:
            if value is not None and not isinstance(value, (str, int)):
                _fail(f"result value {value!r} is not int | str | null — "
                      f"approximate numbers cannot be exact evidence")
            record.append(value)
        out.append(record)
    return out


def check_assertions(dbfile, assertions_text):
    """Re-observe every assertion read-only. -> (ok, first_mismatch_or_'').
    The connection is closed deterministically: an open handle on Windows
    blocks the deletion of the evaluation arena that contains the file."""
    assertions = json.loads(canonical_assertions(assertions_text))
    connection = sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True)
    try:
        for assertion in assertions:
            got = _rows(connection.execute(assertion["query"]))
            if got != assertion["equals"]:
                return False, (f"assertion {assertion['query'][:80]!r} "
                               f"observed {got!r}, declared "
                               f"{assertion['equals']!r}")
    finally:
        connection.close()
    return True, ""


def transact(dbfile, statements_text, assertions_text):
    """Execute inside ONE transaction; COMMIT only if every declared
    assertion observes true afterwards, else ROLLBACK and raise. The
    database is either in the asserted state or untouched — never between."""
    statements = json.loads(canonical_statements(statements_text))
    assertions = json.loads(canonical_assertions(assertions_text))
    connection = sqlite3.connect(dbfile)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for statement in statements:
            connection.execute(statement["sql"], statement["params"])
        for assertion in assertions:
            got = _rows(connection.execute(assertion["query"]))
            if got != assertion["equals"]:
                connection.rollback()
                _fail(f"effect did not hold — rolled back: "
                      f"{assertion['query'][:80]!r} observed {got!r}, "
                      f"declared {assertion['equals']!r}")
        connection.commit()
    except sqlite3.Error as exc:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        _fail(f"rolled back: {exc}")
    finally:
        connection.close()


def query(dbfile, sql, params=None):
    """Read-only observation. -> rows (list of lists of int | str | null)."""
    _screen(sql, read_only=True)
    _screen_params(params or [])
    if not os.path.isfile(dbfile):
        _fail(f"database {dbfile!r} does not exist")
    connection = sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True)
    try:
        return _rows(connection.execute(sql, params or []))
    finally:
        connection.close()


def run_script(dbfile, script):
    """Materialize an owner-sealed suite's database from a SQL script.
    Screened with the same ban list; the caller has already contained the
    path. Owner-sealed content plus screening is defense in depth, not a
    substitute for the seal."""
    if not isinstance(script, str) or not script.strip():
        _fail("empty materialization script")
    lowered = " ".join(script.lower().split()) + " "
    for token in _BANNED:
        if token in lowered:
            _fail(f"banned construct {token.strip()!r} in suite script")
    os.makedirs(os.path.dirname(dbfile) or ".", exist_ok=True)
    connection = sqlite3.connect(dbfile)
    try:
        connection.executescript(script)
        connection.commit()
    except sqlite3.Error as exc:
        _fail(f"suite script failed: {exc}")
    finally:
        connection.close()
