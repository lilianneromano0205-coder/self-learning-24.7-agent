"""Typed tabular state — the financial half of the Semantic Operator Runtime.

tabular.py made table DERIVATION trustworthy; this module makes table
MEANING checkable. A schema declares what each column is — identifier,
integer, exact decimal, money in a named currency, date, boolean — and a
constraint declares what must hold across rows and across tables: values
unique, values present, every key covered by another table, sums exactly
conserved. Both become observable predicates (`table_conforms`,
`table_satisfies`), so a gate, an owner-sealed suite, or a compiled
procedure's effects can state "this file IS a ledger of USD amounts and
its total IS the total of that one" and have the harness re-derive the
answer at any later moment.

Everything here inherits tabular.py's discipline: exact decimals only
(money never touches binary floats), strict parsing, and refusal on
ambiguity — an unparseable schema, an unknown type, a value that does not
fit its column, a constraint over a missing column all raise instead of
guessing. Column TYPES are keyed by name, so JSON key order carries no
meaning, matching the platform's canonicalization rule.

Type grammar (a flat string per column):

    string | identifier | integer | boolean | date | datetime
    decimal:<scale>            e.g. decimal:4
    money:<CUR>:<scale>        e.g. money:USD:2  (CUR is [A-Z]{3})
    nullable:<any of the above>   empty string means null
"""
import decimal
import json
import re

import tabular

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
_IDENT_RE = re.compile(r"^\S+$")
_INT_RE = re.compile(r"^-?\d+$")

_CONSTRAINT_KINDS = ("unique", "non_null", "subset", "sum_equals",
                     "row_count_equals")


def _fail(why):
    raise ValueError(f"table schema: {why}")


def _parse_type(spec):
    """-> (base, param, nullable). Refuses anything it does not know."""
    if not isinstance(spec, str) or not spec:
        _fail("column type must be a non-empty string")
    nullable = spec.startswith("nullable:")
    body = spec[len("nullable:"):] if nullable else spec
    parts = body.split(":")
    base = parts[0]
    if base in ("string", "identifier", "integer", "boolean", "date",
                "datetime") and len(parts) == 1:
        return base, None, nullable
    if base == "decimal" and len(parts) == 2 and parts[1].isdigit():
        return base, int(parts[1]), nullable
    if base == "money" and len(parts) == 3 and \
            _CURRENCY_RE.match(parts[1]) and parts[2].isdigit():
        return base, (parts[1], int(parts[2])), nullable
    _fail(f"unknown column type {spec!r}")


def validate_schema(schema):
    if not isinstance(schema, dict) or set(schema) != {"columns"}:
        _fail('must be an object with exactly one key, "columns"')
    columns = schema["columns"]
    if not isinstance(columns, dict) or not columns:
        _fail("columns must map at least one name to a type")
    for name, spec in columns.items():
        if not isinstance(name, str) or not name:
            _fail("column names must be non-empty strings")
        _parse_type(spec)


def canonical_schema(text):
    if not isinstance(text, str) or not text.strip():
        _fail("schema must be a JSON object in a string")
    try:
        schema = json.loads(text)
    except ValueError as exc:
        _fail(f"invalid JSON ({exc})")
    validate_schema(schema)
    return json.dumps(schema, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _fits(value, base, param):
    if base == "string":
        return True
    if base == "identifier":
        return bool(_IDENT_RE.match(value))
    if base == "integer":
        return bool(_INT_RE.match(value))
    if base == "boolean":
        return value in ("true", "false")
    if base == "date":
        if not _DATE_RE.match(value):
            return False
        year, month, day = map(int, value.split("-"))
        try:
            import datetime as _dt
            _dt.date(year, month, day)
        except ValueError:
            return False
        return True
    if base == "datetime":
        return bool(_DATETIME_RE.match(value)) and _fits(value[:10], "date", None) \
            and value[11:13] < "24" and value[14:16] < "60" and value[17:19] < "60"
    # decimal / money: exact finite decimal with at most `scale` fraction digits
    scale = param if base == "decimal" else param[1]
    try:
        number = decimal.Decimal(value)
    except (decimal.InvalidOperation, ArithmeticError):
        return False
    if not number.is_finite():
        return False
    exponent = number.as_tuple().exponent
    return isinstance(exponent, int) and -exponent <= scale


def conforms(schema_text, table_text):
    """Raise ValueError naming the first offending row/column, else return
    the parsed (header, rows) so callers can chain checks without re-parsing."""
    schema = json.loads(canonical_schema(schema_text))
    header, rows = tabular.parse(table_text)
    declared = set(schema["columns"])
    if set(header) != declared:
        _fail(f"header {sorted(header)} does not match declared columns "
              f"{sorted(declared)}")
    types = {name: _parse_type(spec) for name, spec in schema["columns"].items()}
    for index, row in enumerate(rows):
        for position, name in enumerate(header):
            base, param, nullable = types[name]
            value = row[position]
            if value == "":
                if nullable:
                    continue
                _fail(f"row {index + 2} column {name!r}: empty but not nullable")
            if not _fits(value, base, param):
                _fail(f"row {index + 2} column {name!r}: {value!r} is not a "
                      f"valid {schema['columns'][name]}")
    return header, rows


def validate_constraint(constraint):
    if not isinstance(constraint, dict) or \
            constraint.get("kind") not in _CONSTRAINT_KINDS:
        _fail(f"constraint kind must be one of {_CONSTRAINT_KINDS}")
    kind = constraint["kind"]
    keys = set(constraint) - {"kind"}
    if kind in ("unique", "non_null"):
        if keys != {"columns"} or not isinstance(constraint["columns"], list) \
                or not constraint["columns"] or any(
                    not isinstance(c, str) or not c
                    for c in constraint["columns"]):
            _fail(f"{kind} needs a non-empty column list and nothing else")
    elif kind in ("subset", "sum_equals"):
        if keys != {"column", "other_column"} or any(
                not isinstance(constraint[k], str) or not constraint[k]
                for k in ("column", "other_column")):
            _fail(f"{kind} needs column and other_column (in the second table)")
    elif keys:
        _fail(f"{kind} takes no extra keys")


def canonical_constraint(text):
    if not isinstance(text, str) or not text.strip():
        _fail("constraint must be a JSON object in a string")
    try:
        constraint = json.loads(text)
    except ValueError as exc:
        _fail(f"invalid JSON ({exc})")
    validate_constraint(constraint)
    return json.dumps(constraint, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _column(header, rows, name):
    if name not in header:
        _fail(f"constraint names unknown column {name!r} (have {header})")
    index = header.index(name)
    return [row[index] for row in rows]


def _exact_sum(values, what):
    total = decimal.Decimal(0)
    for value in values:
        try:
            number = decimal.Decimal(value)
        except (decimal.InvalidOperation, ArithmeticError):
            _fail(f"{what}: {value!r} is not an exact number")
        if not number.is_finite():
            _fail(f"{what}: {value!r} is not an exact number")
        total += number
    return total


def satisfies(constraint_text, table_text, other_text=None):
    """-> bool. Structural problems (unknown column, missing second table,
    non-numeric sum values) RAISE — a constraint that cannot be evaluated
    is not 'false', it is a defect in whoever stated it."""
    constraint = json.loads(canonical_constraint(constraint_text))
    header, rows = tabular.parse(table_text)
    kind = constraint["kind"]
    if kind in ("subset", "sum_equals", "row_count_equals"):
        if other_text is None:
            _fail(f"{kind} needs a second table")
        other_header, other_rows = tabular.parse(other_text)
    if kind == "unique":
        seen = set()
        columns = [_column(header, rows, c) for c in constraint["columns"]]
        for key in zip(*columns) if columns else ():
            if key in seen:
                return False
            seen.add(key)
        return True
    if kind == "non_null":
        return all(all(v != "" for v in _column(header, rows, c))
                   for c in constraint["columns"])
    if kind == "subset":
        mine = set(_column(header, rows, constraint["column"]))
        theirs = set(_column(other_header, other_rows,
                             constraint["other_column"]))
        return mine <= theirs
    if kind == "sum_equals":
        return _exact_sum(_column(header, rows, constraint["column"]),
                          "sum_equals left") == \
            _exact_sum(_column(other_header, other_rows,
                               constraint["other_column"]),
                       "sum_equals right")
    return len(rows) == len(other_rows)          # row_count_equals
