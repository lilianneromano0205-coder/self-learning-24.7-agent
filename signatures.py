"""CAPABILITY SIGNATURES — structure as identity, in shadow.

Matching is lexical today: trigger words, filename tokens, a hand-authored
phrase table. Two requests with different words and the same structure
cannot find the same proven procedure. But the structure already exists on
one side — every compiled procedure declares typed inputs, a closed set of
operator leaves, effect predicate kinds and (since V2) its control shape.
This module makes that structure a first-class, computed identity and asks
one question in SHADOW: which proven procedures does this task fit
STRUCTURALLY, regardless of words?

Authority, stated up front because it is the whole point: this module
routes NOTHING. The loop logs a `signature_shadow` event beside every
lexical match and changes no decision. The deterministic lexical floor
keeps sole routing authority until a preregistered measured comparison
(SIG-001, docs/DESIGN-P4-capability-signatures.md) shows the structural
lens is at least as reliable — augment, shadow, compare, only then switch.

A signature is COMPUTED, never authored: triggers, names and prose never
enter the hash, so rewording a procedure changes nothing; changing its
schema or steps changes everything.
"""
import hashlib
import io
import json
import os

import operators


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def _walk_leaves(steps):
    for step in steps or []:
        kind = step.get("kind")
        if kind == "deterministic":
            yield "leaf", step
        elif kind == "if":
            yield "control", "if"
            yield from _walk_leaves(step.get("then"))
            yield from _walk_leaves(step.get("else"))
        elif kind in ("foreach", "retry"):
            yield "control", kind
            yield from _walk_leaves(step.get("body"))
        elif kind == "compensate":
            yield "control", "compensate"
            yield from _walk_leaves(step.get("body"))
            yield from _walk_leaves(step.get("on_failure"))
        elif kind == "call":
            yield "control", "call"
        elif kind == "check":
            yield "control", "check"
        elif kind == "model":
            yield "control", "model"


def of_runbook(rb):
    """The structural identity of a procedure. Deterministic; ignores every
    word a human or model wrote about it."""
    schema = dict((rb.get("operator") or {}).get("inputs") or {})
    tools, effects, control = set(), set(), set()
    for kind, item in _walk_leaves(rb.get("steps")):
        if kind == "control":
            control.add(item)
            continue
        tool = (item.get("action") or {}).get("tool")
        if tool:
            tools.add(tool)
        for effect in item.get("effects") or []:
            if isinstance(effect, dict) and effect.get("predicate"):
                effects.add(effect["predicate"])
    body = {"input_schema": schema,
            "input_kinds": sorted(schema.values()),
            "operators": sorted(tools),
            "effect_kinds": sorted(effects),
            "control": sorted(control),
            "writes_db": "db_transaction" in tools}
    body["signature_hash"] = _digest(body)
    return body


def compatible(root, rb, inputs):
    """Structural fit: the procedure's typed schema accepts these inputs.
    The exact test the live route applies AFTER words matched — asked here
    regardless of words."""
    try:
        operators.check_inputs(root, (rb.get("operator") or {})
                               .get("inputs") or {}, inputs or {})
        return True
    except (ValueError, OSError):
        return False


def shadow_match(root, task):
    """Every PROVEN procedure this task fits structurally, sorted. Reads
    the same trust ledger the route reads; proposes to a LOG, never to a
    scheduler."""
    import runbook
    inputs = task.get("inputs") if isinstance(task.get("inputs"), dict) \
        else {}
    out = []
    for name in runbook.names(root):
        try:
            if runbook.status(root, name) != "proven":
                continue
            rb = runbook.load(root, name)
            if not rb.get("procedure_version"):
                continue
            if compatible(root, rb, inputs):
                out.append(name)
        except (ValueError, OSError):
            continue
    return sorted(out)


def agreement(lexical, structural):
    lexical, structural = set(lexical), set(structural)
    if not lexical and not structural:
        return "both_empty"
    if lexical & structural:
        return "same"
    return "lexical_only" if lexical else "structural_only"


def report(root):
    """Aggregate the shadow ledger from the loop's event log. This report
    is the phase's product: how often words and structure agree, and what
    the words missed."""
    path = os.path.join(root, "logs", "agent.log")
    counts = {"same": 0, "structural_only": 0, "lexical_only": 0,
              "both_empty": 0}
    found_by_structure = {}
    try:
        lines = io.open(path, encoding="utf-8", errors="replace").readlines()
    except OSError:
        lines = []
    for line in lines:
        if '"signature_shadow"' not in line:
            continue
        try:
            event = json.loads(line[line.index("{"):])
        except ValueError:
            continue
        kind = event.get("agreement")
        if kind in counts:
            counts[kind] += 1
        if kind == "structural_only":
            for name in event.get("structural") or []:
                found_by_structure[name] = found_by_structure.get(name, 0) + 1
    total = sum(counts.values())
    return {"events": total, "agreement": counts,
            "structural_only_procedures": dict(sorted(
                found_by_structure.items())),
            "authority": "lexical (shadow changed no routing decision; "
                         "SIG-001 gates any switch)"}


def main():
    import argparse
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="aggregate the shadow ledger")
    r.add_argument("--root", required=True)
    s = sub.add_parser("show", help="signature of one runbook")
    s.add_argument("--root", required=True)
    s.add_argument("--name", required=True)
    args = ap.parse_args()
    if args.cmd == "report":
        print(json.dumps(report(args.root), indent=1, ensure_ascii=False))
    else:
        import runbook
        print(json.dumps(of_runbook(runbook.load(args.root, args.name)),
                         indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
