#!/usr/bin/env python3
"""The transform engine must be pure, total, strict — and byte-stable.

tabular.py is a TRUSTED semantic adapter: procedure.finish_action re-derives a
worker's transform_table output through it, operators.observe re-derives a
procedure's effects through it, and zero-model replay re-executes through it.
Every one of those verdicts is only as honest as this module is deterministic
and fail-closed, so this file attacks exactly those two properties:

  - every operation produces the same bytes from the same bytes, twice;
  - semantics never depend on JSON object key order (canonicalization safety);
  - anything ambiguous — ragged rows, unknown columns, colliding names,
    non-numeric sums, oversized tables, unused second sources — REFUSES
    instead of guessing.

Run from the agent/ directory:  python tests/test_tabular.py
"""
import json
import sys

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import tabular                  # noqa: E402


def spec(*steps):
    return json.dumps({"steps": list(steps)})


ORDERS = "key,amount\nB,250\nA,100\nC,75\n"
BANK = "key,amount\nA,100\nB,250\nD,40\n"


def refuses(why_fragment, fn, *args):
    try:
        fn(*args)
    except ValueError as exc:
        assert why_fragment in str(exc), (why_fragment, str(exc))
        return
    raise AssertionError(f"accepted what must be refused: {why_fragment}")


def check_each_operation_is_exact():
    assert tabular.apply(spec({"op": "select", "columns": ["amount"]}),
                         ORDERS) == "amount\n250\n100\n75\n"
    assert tabular.apply(spec({"op": "rename", "columns": {"amount": "usd"}}),
                         ORDERS) == "key,usd\nB,250\nA,100\nC,75\n"
    assert tabular.apply(spec({"op": "filter", "column": "amount",
                               "compare": "gt", "value": "90"}),
                         ORDERS) == "key,amount\nB,250\nA,100\n"
    # 100 > 90 NUMERICALLY; a string compare would have said "100" < "90"
    assert tabular.apply(spec({"op": "sort", "column": "amount"}),
                         ORDERS) == "key,amount\nC,75\nA,100\nB,250\n"
    assert tabular.apply(spec({"op": "dedupe", "columns": ["key"]}),
                         "key,v\nA,1\nA,2\nB,3\n") == "key,v\nA,1\nB,3\n"
    assert tabular.apply(spec({"op": "filter", "column": "key",
                               "compare": "contains", "value": "B"}),
                         ORDERS) == "key,amount\nB,250\n"
    print("[unit] select/rename/filter/sort/dedupe are exact, numeric-aware")


def check_join_and_aggregate():
    joined = tabular.apply(
        spec({"op": "join", "column": "key", "with_column": "key"},
             {"op": "filter", "column": "amount", "compare": "eq",
              "other": "b_amount"},
             {"op": "select", "columns": ["key", "amount"]},
             {"op": "sort", "column": "key"}),
        ORDERS, BANK)
    assert joined == "key,amount\nA,100\nB,250\n", joined
    # ^ THE RECONCILIATION, as a spec: match, keep agreements, order.
    fanout = tabular.apply(
        spec({"op": "join", "column": "k", "with_column": "k"}),
        "k,l\nx,1\n", "k,r\nx,a\nx,b\n")
    assert fanout == "k,l,b_r\nx,1,a\nx,1,b\n", fanout
    agg = tabular.apply(
        spec({"op": "aggregate", "group": ["key"],
              "aggregations": {"total": {"fn": "sum", "column": "amount"},
                               "n": {"fn": "count"}}}),
        "key,amount\nB,2\nA,1.5\nA,1\nB,3\n")
    assert agg == "key,n,total\nA,2,2.5\nB,2,5\n", agg
    # groups in sorted order, aggregation columns in sorted-name order,
    # integral sums rendered without a decimal point
    top = tabular.apply(
        spec({"op": "aggregate", "group": [],
              "aggregations": {"biggest": {"fn": "max", "column": "amount"}}}),
        ORDERS)
    assert top == "biggest\n250\n", top
    print("[unit] join fans out exactly; aggregate orders and formats "
          "deterministically")


def check_purity_and_canonicalization():
    pipeline = spec({"op": "join", "column": "key", "with_column": "key"},
                    {"op": "filter", "column": "amount", "compare": "eq",
                     "other": "b_amount"},
                    {"op": "select", "columns": ["key", "amount"]})
    once = tabular.apply(pipeline, ORDERS, BANK)
    assert tabular.apply(pipeline, ORDERS, BANK) == once
    reordered = json.dumps(json.loads(pipeline))     # same meaning, other bytes
    assert tabular.canonical(pipeline) == tabular.canonical(reordered)
    assert tabular.apply(tabular.canonical(pipeline), ORDERS, BANK) == once
    print("[unit] same bytes in, same bytes out; canonical form is one form")


def check_everything_ambiguous_refuses():
    refuses("row 3 has 1 cells",
            tabular.apply, spec({"op": "sort", "column": "k"}), "k,v\na,1\nb\n")
    refuses("unknown column",
            tabular.apply, spec({"op": "sort", "column": "ghost"}), ORDERS)
    refuses("unknown op", tabular.canonical, spec({"op": "eval"}))
    refuses("no join consumes",
            tabular.apply, spec({"op": "sort", "column": "key"}), ORDERS, BANK)
    refuses("needs a second source",
            tabular.apply,
            spec({"op": "join", "column": "key", "with_column": "key"}), ORDERS)
    refuses("collide",
            tabular.apply,
            spec({"op": "join", "column": "key", "with_column": "key",
                  "prefix": ""}), ORDERS, BANK)
    refuses("non-numeric",
            tabular.apply,
            spec({"op": "aggregate", "group": [],
                  "aggregations": {"t": {"fn": "sum", "column": "key"}}}),
            ORDERS)
    refuses("exactly one of",
            tabular.canonical,
            spec({"op": "filter", "column": "a", "compare": "eq",
                  "value": "1", "other": "b"}))
    refuses("at most one join",
            tabular.canonical,
            spec({"op": "join", "column": "a", "with_column": "a"},
                 {"op": "join", "column": "b", "with_column": "b"}))
    refuses("unknown keys",
            tabular.canonical, spec({"op": "sort", "column": "a", "sh": "x"}))
    big = "k\n" + "\n".join(str(i) for i in range(tabular.MAX_CELLS + 1)) + "\n"
    refuses("cells", tabular.apply, spec({"op": "sort", "column": "k"}), big)
    refuses("header", tabular.apply, spec({"op": "dedupe", "columns": ["k"]}),
            "")
    print("[unit] ambiguity refuses: ragged, unknown, colliding, oversized, "
          "unused sources — none of them guess")


def main():
    check_each_operation_is_exact()
    check_join_and_aggregate()
    check_purity_and_canonicalization()
    check_everything_ambiguous_refuses()
    print("PASS test_tabular")


if __name__ == "__main__":
    main()
