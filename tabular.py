"""Deterministic table transforms — the second trusted semantic adapter family.

write_file proved the shape: an action the HARNESS executes as a pure function
of its arguments can be captured, compiled, and replayed with zero model calls,
because anyone can re-derive the effect instead of trusting whoever performed
it. That surface covered "emit these exact bytes"; this module widens it to
"derive this table from those tables": select, rename, filter, sort, dedupe,
join, and aggregate over CSV files.

The model chooses WHAT transformation to request; this code performs it. There
is deliberately no path from a spec to arbitrary computation: the operation set
is closed, total (every operation terminates on bounded input), and pure (the
output depends only on the input tables and the spec). Anything unrecognized,
ragged, ambiguous, or over the size cap raises instead of guessing — a
transform that cannot be re-derived exactly is a transform that must not be
trusted as evidence.

Ordering rules are carried by LISTS in the spec (select order, group order);
JSON object key order never carries meaning, so canonicalization (sorted keys)
cannot change what a spec does.

Numbers are EXACT DECIMALS, never floats: 0.1 + 0.2 is 0.3, and a sum that
would need rounding refuses instead of losing cents. That is the minimum bar
for a substrate that will carry ledgers.
"""
import csv
import decimal
import io
import json

MAX_STEPS = 32          # a pipeline longer than this is a program, not a spec
MAX_CELLS = 250_000     # per table, at every stage — join fan-out included

_COMPARES = ("eq", "ne", "lt", "le", "gt", "ge", "contains")
_FNS = ("count", "sum", "min", "max")


def _fail(why):
    raise ValueError(f"transform spec: {why}")


def _require_keys(step, required, optional=()):
    keys = set(step) - {"op"}
    missing = set(required) - keys
    unknown = keys - set(required) - set(optional)
    if missing or unknown:
        _fail(f"{step.get('op')} step has "
              + (f"missing keys {sorted(missing)} " if missing else "")
              + (f"unknown keys {sorted(unknown)}" if unknown else ""))


def _str_list(value, what):
    if not isinstance(value, list) or not value or \
            any(not isinstance(x, str) or not x for x in value):
        _fail(f"{what} must be a non-empty list of column names")
    if len(set(value)) != len(value):
        _fail(f"{what} repeats a column")
    return value


def validate_spec(spec):
    """Structural validation. Column existence is checked at apply time,
    against the actual table — the spec alone cannot know the header."""
    if not isinstance(spec, dict) or set(spec) != {"steps"}:
        _fail('must be an object with exactly one key, "steps"')
    steps = spec["steps"]
    if not isinstance(steps, list) or not steps:
        _fail("steps must be a non-empty list")
    if len(steps) > MAX_STEPS:
        _fail(f"more than {MAX_STEPS} steps")
    joins = 0
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("op"), str):
            _fail("every step must be an object naming its op")
        op = step["op"]
        if op == "select":
            _require_keys(step, ("columns",))
            _str_list(step["columns"], "select columns")
        elif op == "rename":
            _require_keys(step, ("columns",))
            mapping = step["columns"]
            if not isinstance(mapping, dict) or not mapping or any(
                    not isinstance(k, str) or not k or
                    not isinstance(v, str) or not v
                    for k, v in mapping.items()):
                _fail("rename columns must map old names to new names")
        elif op == "filter":
            _require_keys(step, ("column", "compare"), ("value", "other"))
            if not isinstance(step["column"], str) or not step["column"]:
                _fail("filter needs a column")
            if step["compare"] not in _COMPARES:
                _fail(f"filter compare must be one of {_COMPARES}")
            has_value = "value" in step
            has_other = "other" in step
            if has_value == has_other:
                _fail('filter needs exactly one of "value" (a constant) '
                      'or "other" (another column)')
            operand = step["value"] if has_value else step["other"]
            if not isinstance(operand, str):
                _fail("filter operand must be a string")
        elif op == "sort":
            _require_keys(step, ("column",), ("descending",))
            if not isinstance(step["column"], str) or not step["column"]:
                _fail("sort needs a column")
            if not isinstance(step.get("descending", False), bool):
                _fail("sort descending must be a boolean")
        elif op == "dedupe":
            _require_keys(step, ("columns",))
            _str_list(step["columns"], "dedupe columns")
        elif op == "join":
            _require_keys(step, ("column", "with_column"), ("prefix",))
            for key in ("column", "with_column"):
                if not isinstance(step[key], str) or not step[key]:
                    _fail(f"join needs {key}")
            if not isinstance(step.get("prefix", "b_"), str):
                _fail("join prefix must be a string")
            joins += 1
        elif op == "aggregate":
            _require_keys(step, ("group", "aggregations"))
            group = step["group"]
            if not isinstance(group, list) or any(
                    not isinstance(x, str) or not x for x in group) or \
                    len(set(group)) != len(group):
                _fail("aggregate group must be a list of distinct column names")
            aggs = step["aggregations"]
            if not isinstance(aggs, dict) or not aggs:
                _fail("aggregate needs at least one aggregation")
            for name, agg in aggs.items():
                if not isinstance(name, str) or not name or name in group:
                    _fail("aggregation names must be new non-empty columns")
                if not isinstance(agg, dict) or agg.get("fn") not in _FNS:
                    _fail(f"aggregation fn must be one of {_FNS}")
                extra = set(agg) - {"fn", "column"}
                if extra:
                    _fail(f"aggregation has unknown keys {sorted(extra)}")
                if agg["fn"] == "count":
                    if "column" in agg:
                        _fail("count takes no column")
                elif not isinstance(agg.get("column"), str) or not agg["column"]:
                    _fail(f"{agg['fn']} needs a column")
        else:
            _fail(f"unknown op {op!r}")
    if joins > 1:
        _fail("at most one join per spec — there is only one second table")


def canonical(text):
    """Parse, validate, and re-render a spec into one canonical byte form, so
    equal meanings are equal strings for alignment and hashing."""
    if not isinstance(text, str) or not text.strip():
        _fail("spec must be a JSON object in a string")
    try:
        spec = json.loads(text)
    except ValueError as exc:
        _fail(f"invalid JSON ({exc})")
    validate_spec(spec)
    return json.dumps(spec, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def parse(text):
    """CSV text -> (header, rows). Strict: a header of distinct non-empty
    names, and every row exactly as wide as the header."""
    if not isinstance(text, str):
        _fail("table must be text")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        _fail("table needs a header row")
    header = rows[0]
    if not header or any(not isinstance(c, str) or not c for c in header) or \
            len(set(header)) != len(header):
        _fail("header must be distinct non-empty column names")
    body = rows[1:]
    for index, row in enumerate(body):
        if len(row) != len(header):
            _fail(f"row {index + 2} has {len(row)} cells, header has {len(header)}")
    _check_cells(header, body)
    return header, body


def render(header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def _check_cells(header, rows):
    if len(header) * (len(rows) + 1) > MAX_CELLS:
        _fail(f"table exceeds {MAX_CELLS} cells")


def _col(header, name):
    if name not in header:
        _fail(f"unknown column {name!r} (have {header})")
    return header.index(name)


def _num(value):
    """Exact decimal, or None. Floats never touch a cell: 0.1 + 0.2 must be
    0.3 in a substrate that will carry ledgers, not 0.30000000000000004."""
    try:
        number = decimal.Decimal(value.strip())
    except (decimal.InvalidOperation, ValueError, ArithmeticError, AttributeError):
        return None
    return number if number.is_finite() else None


def _order_key(value):
    number = _num(value)
    return (0, number, "") if number is not None else (1, decimal.Decimal(0), value)


def _fmt(value):
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _compare(left, compare, right):
    if compare == "contains":
        return right in left
    ln, rn = _num(left), _num(right)
    if ln is not None and rn is not None:
        left, right = ln, rn
    return {"eq": left == right, "ne": left != right,
            "lt": left < right, "le": left <= right,
            "gt": left > right, "ge": left >= right}[compare]


def apply(spec_text, primary, secondary=None):
    """Run a canonical spec over CSV text. Pure: same bytes in, same bytes
    out, on any machine, any number of times."""
    spec = json.loads(canonical(spec_text))
    header, rows = parse(primary)
    second = parse(secondary) if secondary is not None else None
    has_join = any(step["op"] == "join" for step in spec["steps"])
    if secondary is not None and not has_join:
        _fail("a second source is declared but no join consumes it")
    if has_join and second is None:
        _fail("join needs a second source table")
    for step in spec["steps"]:
        op = step["op"]
        if op == "select":
            indexes = [_col(header, c) for c in step["columns"]]
            header = list(step["columns"])
            rows = [[row[i] for i in indexes] for row in rows]
        elif op == "rename":
            for old in step["columns"]:
                _col(header, old)
            header = [step["columns"].get(c, c) for c in header]
            if len(set(header)) != len(header):
                _fail("rename would collide column names")
        elif op == "filter":
            i = _col(header, step["column"])
            if "other" in step:
                j = _col(header, step["other"])
                rows = [r for r in rows if _compare(r[i], step["compare"], r[j])]
            else:
                rows = [r for r in rows
                        if _compare(r[i], step["compare"], step["value"])]
        elif op == "sort":
            i = _col(header, step["column"])
            rows = sorted(rows, key=lambda r: _order_key(r[i]),
                          reverse=bool(step.get("descending", False)))
        elif op == "dedupe":
            indexes = [_col(header, c) for c in step["columns"]]
            seen, kept = set(), []
            for row in rows:
                key = tuple(row[i] for i in indexes)
                if key not in seen:
                    seen.add(key)
                    kept.append(row)
            rows = kept
        elif op == "join":
            right_header, right_rows = second
            i = _col(header, step["column"])
            j = _col(right_header, step["with_column"])
            prefix = step.get("prefix", "b_")
            carried = [k for k in range(len(right_header)) if k != j]
            joined_header = header + [prefix + right_header[k] for k in carried]
            if len(set(joined_header)) != len(joined_header):
                _fail("join would collide column names; use another prefix")
            index = {}
            for row in right_rows:
                index.setdefault(row[j], []).append(row)
            joined = []
            for row in rows:
                for other in index.get(row[i], ()):
                    joined.append(row + [other[k] for k in carried])
                    if len(joined_header) * (len(joined) + 1) > MAX_CELLS:
                        _fail(f"join result exceeds {MAX_CELLS} cells")
            header, rows = joined_header, joined
        elif op == "aggregate":
            group_indexes = [_col(header, c) for c in step["group"]]
            names = sorted(step["aggregations"])
            columns = {name: (_col(header, step["aggregations"][name]["column"])
                              if step["aggregations"][name]["fn"] != "count"
                              else None)
                       for name in names}
            out_header = list(step["group"]) + names
            if len(set(out_header)) != len(out_header):
                _fail("aggregate would collide column names")
            groups = {}
            for row in rows:
                groups.setdefault(tuple(row[i] for i in group_indexes),
                                  []).append(row)
            out = []
            for key in sorted(groups, key=lambda k: tuple(_order_key(v) for v in k)):
                record = list(key)
                for name in names:
                    fn = step["aggregations"][name]["fn"]
                    members = groups[key]
                    if fn == "count":
                        record.append(str(len(members)))
                        continue
                    values = [m[columns[name]] for m in members]
                    if fn == "sum":
                        numbers = [_num(v) for v in values]
                        if any(n is None for n in numbers):
                            _fail(f"sum over non-numeric values in {name!r}")
                        # EXACT OR REFUSE: the Inexact trap means a sum that
                        # would round (beyond 60 significant digits) raises
                        # instead of silently losing cents
                        try:
                            with decimal.localcontext() as ctx:
                                ctx.prec = 60
                                ctx.traps[decimal.Inexact] = True
                                total = sum(numbers, decimal.Decimal(0))
                        except (decimal.Inexact, decimal.InvalidOperation):
                            _fail(f"sum in {name!r} exceeds exact precision")
                        record.append(_fmt(total))
                    else:
                        picked = (min if fn == "min" else max)(
                            values, key=_order_key)
                        record.append(picked)
                out.append(record)
            header, rows = out_header, out
        _check_cells(header, rows)
    return render(header, rows)
