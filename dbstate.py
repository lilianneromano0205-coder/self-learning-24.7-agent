"""SQLite state — the second world of the Semantic Operator Runtime.

The design (docs/DESIGN-P1-semantic-operator-runtime.md) names the rule
this module exists to enforce: every mutation runs inside a transaction
whose COMMIT is gated on declared, observable assertions re-observing true
— else it rolls back and the database is untouched. The worker never gets
"I ran some SQL"; it gets "the state I promised is now true" or a refusal.

Phase 7 (docs/DESIGN-P7-transactional-contracts.md) widens what a
transaction can PROMISE, around the same commit-or-untouched semantics:

  - preconditions: [{query, equals}] observed BEFORE any statement — one
    false and the transaction refuses with nothing mutated. "Transfer 100
    from A" applies only when A holds 100;
  - invariants: [{query}] must return the SAME rows before and after
    ("the sum of balances is unchanged"); [{query, equals}] must return
    exactly those rows both times. A broken invariant rolls back;
  - attach: {alias: {path, mode}} joins sibling databases to the ONE
    transaction under ADAPTER-issued ATTACH (worker SQL still may not
    ATTACH). mode read is a mode=ro URI that SQLite itself enforces; a
    WAL-journaled file refuses, because a multi-file commit is atomic
    only under the rollback journal.

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
  - assertions, preconditions, invariants and observations are SELECT-only
    under the same screen, and their results must contain only int / str /
    NULL — a REAL in a result refuses, because approximate numbers cannot
    gate a commit.

Tool-name mapping (the design's dotted names, as worker tools):
  db.transaction + db.assert  ->  db_transaction (statements + assertions,
                                  + preconditions, invariants, attach)
  db.select                   ->  db_query       (read-only observation)
  db.rollback                 ->  automatic on any failed assertion

Authority: writing a database requires the owner-granted token
"db-write:<relative-path>" (settings.toml [agent] db_write, default empty
— fail closed) — for the main database AND for every write-attached one.
Reading, and a read attach, is workspace read.
"""
import json
import os
import re
import sqlite3
import urllib.parse

MAX_RESULT_ROWS = 10_000
MAX_STATEMENTS = 64
MAX_ASSERTIONS = 32
MAX_ATTACH = 8

_ALLOWED_FIRST = ("select", "insert", "update", "delete", "with",
                  "create table", "create index", "create unique index")
_BANNED = ("attach", "pragma", "vacuum", "reindex", "analyze", "drop ",
           "alter ", "trigger", "load_extension", "random(", "randomblob(",
           "current_timestamp", "current_time", "current_date", "'now'",
           "'localtime'", "'utc'", "last_insert_rowid", "changes(",
           "total_changes")
_ALIAS_RE = re.compile(r"^[a-z][a-z0-9_]{0,15}$")


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


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


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
    return _canonical(out)


def _rows_ok(rows):
    return isinstance(rows, list) and not any(
        not isinstance(row, list) or any(
            value is not None and not isinstance(value, (str, int))
            or isinstance(value, bool) for value in row)
        for row in rows)


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
        if not _rows_ok(entry["equals"]):
            _fail("equals must be rows of int | str | null")
        out.append({"query": _screen(entry["query"], read_only=True),
                    "equals": entry["equals"]})
    return _canonical(out)


def canonical_conditions(text):
    """Preconditions: [{query, equals}], observed before any statement. A
    transaction may declare none, so '[]' is canonical too."""
    if text is None or (isinstance(text, str) and not text.strip()):
        return "[]"
    try:
        conditions = json.loads(text) if isinstance(text, str) else None
    except ValueError as exc:
        _fail(f"preconditions are not valid JSON ({exc})")
    if not isinstance(conditions, list) or len(conditions) > MAX_ASSERTIONS:
        _fail(f"preconditions must be a list of 0..{MAX_ASSERTIONS} entries")
    out = []
    for entry in conditions:
        if not isinstance(entry, dict) or set(entry) != {"query", "equals"}:
            _fail("each precondition is {query, equals}")
        if not _rows_ok(entry["equals"]):
            _fail("equals must be rows of int | str | null")
        out.append({"query": _screen(entry["query"], read_only=True),
                    "equals": entry["equals"]})
    return _canonical(out)


_ORDERED_RE = re.compile(r"\border\s+by\b", re.IGNORECASE)


def _is_unordered(invariant):
    """Ordered comparison is claimed only by a query that carries ORDER BY;
    every other query is compared as a multiset, because SQLite promises
    nothing about the order of an unordered scan. "unordered": true forces
    the multiset reading even with ORDER BY (docs/DESIGN-P7.1, P1-A)."""
    return bool(invariant.get("unordered")) or \
        not _ORDERED_RE.search(invariant["query"])


def canonical_invariants(text):
    """Invariants: [{query}] — the same rows before and after — or
    [{query, equals}] — exactly those rows both times. '[]' when none.
    Row order without ORDER BY is not a guarantee SQLite makes, so the rows
    are compared as an ordered list only when the query carries ORDER BY and
    as a multiset otherwise; "unordered": true forces the multiset reading
    (docs/DESIGN-P7.1, P1-A)."""
    if text is None or (isinstance(text, str) and not text.strip()):
        return "[]"
    try:
        invariants = json.loads(text) if isinstance(text, str) else None
    except ValueError as exc:
        _fail(f"invariants are not valid JSON ({exc})")
    if not isinstance(invariants, list) or len(invariants) > MAX_ASSERTIONS:
        _fail(f"invariants must be a list of 0..{MAX_ASSERTIONS} entries")
    out = []
    for entry in invariants:
        if not isinstance(entry, dict) or "query" not in entry or \
                set(entry) - {"query", "equals", "unordered"}:
            _fail("each invariant is {query} or {query, equals}, optionally "
                  "with \"unordered\": true")
        item = {"query": _screen(entry["query"], read_only=True)}
        if "unordered" in entry:
            if entry["unordered"] is not True:
                _fail("unordered must be true when present")
            item["unordered"] = True
        if "equals" in entry:
            if not _rows_ok(entry["equals"]):
                _fail("equals must be rows of int | str | null")
            item["equals"] = entry["equals"]
        out.append(item)
    return _canonical(out)


def canonical_attach(text):
    """{alias: {path, mode}} -> canonical JSON ('{}' when none). Aliases are
    screened identifiers the adapter interpolates into ATTACH itself; paths
    are relative and contained (resolved by the caller); mode read | write."""
    if text is None or (isinstance(text, str) and not text.strip()):
        return "{}"
    try:
        attach = json.loads(text) if isinstance(text, str) else None
    except ValueError as exc:
        _fail(f"attach is not valid JSON ({exc})")
    if not isinstance(attach, dict) or len(attach) > MAX_ATTACH:
        _fail(f"attach must be an object of at most {MAX_ATTACH} aliases")
    out = {}
    for alias, entry in attach.items():
        if not isinstance(alias, str) or not _ALIAS_RE.match(alias) or \
                alias in ("main", "temp"):
            _fail(f"attach alias {alias!r} is not acceptable "
                  f"([a-z][a-z0-9_]*, never main or temp)")
        if not isinstance(entry, dict) or set(entry) != {"path", "mode"}:
            _fail(f"attach {alias} must be {{path, mode}}")
        path = entry["path"]
        if not isinstance(path, str) or not path:
            _fail(f"attach {alias} path must be a relative path")
        path = path.replace("\\", "/")
        if path.startswith("/") or (len(path) > 1 and path[1] == ":") or \
                ".." in path.split("/"):
            _fail(f"attach {alias} path must be relative and contained")
        if entry["mode"] not in ("read", "write"):
            _fail(f"attach {alias} mode must be read or write")
        out[alias] = {"path": path, "mode": entry["mode"]}
    return _canonical(out)


def _same_rows(got, want, unordered=False):
    """Invariant comparison. Ordered by default (the query carries ORDER BY);
    an `unordered` invariant compares multisets, because SQLite promises
    nothing about the order of an unordered scan (docs/DESIGN-P7.1, P1-A)."""
    if not unordered:
        return got == want

    def key(row):
        return json.dumps(row, sort_keys=True)
    return sorted(got, key=key) == sorted(want, key=key)


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


def _uri(path, read_only):
    """A file: URI SQLite accepts for both connect and ATTACH, with the path
    quoted so spaces and percent signs survive. The mode is ALWAYS explicit:
    mode=ro for observation, mode=rw for mutation — never the default that
    lets a plain open create an empty database (docs/DESIGN-P7.1, P0-A)."""
    return "file:" + urllib.parse.quote(
        os.path.abspath(path).replace("\\", "/")) + \
        ("?mode=ro" if read_only else "?mode=rw")


def _attach(connection, attach, *, mutating):
    """Join sibling databases to this connection. `attach` is
    {alias: {path: ABSOLUTE, mode}} — the caller has already contained and
    authorized every path. Read mode is enforced by SQLite (mode=ro); a
    mutating transaction refuses any WAL-journaled file."""
    for alias in sorted(attach or {}):
        entry = attach[alias]
        if not _ALIAS_RE.match(alias) or alias in ("main", "temp"):
            _fail(f"attach alias {alias!r} is not acceptable")
        read_only = not mutating or entry.get("mode") != "write"
        if not os.path.isfile(entry["path"]):
            _fail(f"attach {alias}: {entry['path']!r} does not exist")
        try:
            connection.execute(f"ATTACH DATABASE ? AS {alias}",
                               (_uri(entry["path"], read_only),))
        except sqlite3.Error as exc:
            _fail(f"attach {alias} failed: {exc}")
        if mutating:
            journal = connection.execute(
                f"PRAGMA {alias}.journal_mode").fetchone()[0]
            if str(journal).lower() == "wal":
                _fail(f"attach {alias}: {entry['path']!r} uses WAL journaling "
                      f"— a multi-file commit is atomic only under the "
                      f"rollback journal; refused")
    if mutating and attach:
        journal = connection.execute("PRAGMA main.journal_mode").fetchone()[0]
        if str(journal).lower() == "wal":
            _fail("the main database uses WAL journaling — a multi-file "
                  "commit is atomic only under the rollback journal; refused")


def check_assertions(dbfile, assertions_text, attach=None):
    """Re-observe every assertion read-only. -> (ok, first_mismatch_or_'').
    The connection is closed deterministically: an open handle on Windows
    blocks the deletion of the evaluation arena that contains the file."""
    assertions = json.loads(canonical_assertions(assertions_text))
    connection = sqlite3.connect(_uri(dbfile, True), uri=True)
    try:
        _attach(connection, attach, mutating=False)
        for assertion in assertions:
            got = _rows(connection.execute(assertion["query"]))
            if got != assertion["equals"]:
                return False, (f"assertion {assertion['query'][:80]!r} "
                               f"observed {got!r}, declared "
                               f"{assertion['equals']!r}")
    finally:
        connection.close()
    return True, ""


def transact(dbfile, statements_text, assertions_text, preconditions=None,
             invariants=None, attach=None):
    """Execute inside ONE transaction; COMMIT only if every declared
    assertion observes true afterwards, else ROLLBACK and raise. The
    database is either in the asserted state or untouched — never between.

    Preconditions are observed first: one false and nothing is mutated.
    Invariants are observed before and after: a bare {query} must give the
    same rows both times, {query, equals} exactly those rows both times.
    Attached databases share the transaction, so a failure on any file
    rolls back every file."""
    statements = json.loads(canonical_statements(statements_text))
    assertions = json.loads(canonical_assertions(assertions_text))
    conditions = json.loads(canonical_conditions(preconditions))
    checks = json.loads(canonical_invariants(invariants))
    if not os.path.isfile(dbfile):
        # docs/DESIGN-P7.1, P0-A: a guarded transaction never creates a
        # database. Creation is a separate, explicit operation (run_script),
        # so a false precondition can leave nothing behind.
        _fail(f"database {dbfile!r} does not exist — a guarded transaction "
              f"never creates a database; create it explicitly first")
    connection = sqlite3.connect(_uri(dbfile, False), uri=True)
    try:
        _attach(connection, attach, mutating=True)
        connection.execute("BEGIN IMMEDIATE")
        for condition in conditions:
            got = _rows(connection.execute(condition["query"]))
            if got != condition["equals"]:
                connection.rollback()
                _fail(f"precondition did not hold — nothing was mutated: "
                      f"{condition['query'][:80]!r} observed {got!r}, "
                      f"declared {condition['equals']!r}")
        before = []
        for invariant in checks:
            got = _rows(connection.execute(invariant["query"]))
            if "equals" in invariant and not _same_rows(
                    got, invariant["equals"], _is_unordered(invariant)):
                connection.rollback()
                _fail(f"invariant did not hold before the transaction — "
                      f"nothing was mutated: {invariant['query'][:80]!r} "
                      f"observed {got!r}, declared {invariant['equals']!r}")
            before.append(got)
        for statement in statements:
            connection.execute(statement["sql"], statement["params"])
        for assertion in assertions:
            got = _rows(connection.execute(assertion["query"]))
            if got != assertion["equals"]:
                connection.rollback()
                _fail(f"effect did not hold — rolled back: "
                      f"{assertion['query'][:80]!r} observed {got!r}, "
                      f"declared {assertion['equals']!r}")
        for invariant, was in zip(checks, before):
            got = _rows(connection.execute(invariant["query"]))
            want = invariant.get("equals", was)
            if not _same_rows(got, want, _is_unordered(invariant)):
                connection.rollback()
                _fail(f"invariant broken — rolled back: "
                      f"{invariant['query'][:80]!r} was {was!r}, now {got!r}")
        connection.commit()
    except sqlite3.Error as exc:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        _fail(f"rolled back: {exc}")
    finally:
        connection.close()


def query(dbfile, sql, params=None, attach=None):
    """Read-only observation. -> rows (list of lists of int | str | null)."""
    _screen(sql, read_only=True)
    _screen_params(params or [])
    if not os.path.isfile(dbfile):
        _fail(f"database {dbfile!r} does not exist")
    connection = sqlite3.connect(_uri(dbfile, True), uri=True)
    try:
        _attach(connection, attach, mutating=False)
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
