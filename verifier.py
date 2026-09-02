"""VERIFIER FACTORY — mechanical gates as governed objects.

The platform's strongest rule is that the worker never decides when work is
done. This module industrializes the other side of that rule: where gates
come from. A verifier here is DATA — typed params plus predicate templates
over the observable algebra (file_*, table_*, db_satisfies_all) — never
code, never shell, never a model's opinion. Its verdict is what
operators.observe re-derives at gate time.

The lifecycle is the same shape as every trust path in this repository:

  propose    anyone, including a WORKER TASK, may file a spec. It lands as
             CANDIDATE with its provenance recorded and grants nothing. A
             worker cannot take over an existing name.
  calibrate  owner-only, and FALSIFIABLE by construction: the calibration
             set must contain cases the verifier is required to REJECT as
             well as cases it must accept. A verifier that cannot fail
             anything is not a verifier — the same rule that refuses an
             acquisition probe that passes before the install. Cases run in
             fresh arenas (text fixtures via fileauth, .db fixtures from
             SQL scripts via dbstate.run_script).
  promote    owner-only, and only over a DISCRIMINATING calibration —
             every positive accepted, every negative rejected — that is
             hash-bound to the exact spec bytes. Edit the spec and the
             trust evaporates back to candidate.
  gate       only TRUSTED verifiers gate tasks. Anything else — unknown
             name, candidate status, stale hash, bad params, unobservable
             predicate — fails closed with the reason named.

State lives beside the procedural authority ledger, in the org seal
boundary a worker's file tools cannot reach.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

import fileauth
import locks
import operators


class VerifierError(ValueError):
    pass


_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_KINDS = ("path", "string", "integer", "number", "boolean")
MAX_CHECKS = 32
MAX_CASES = 64


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def state_path(root):
    import contract
    seal, _ = contract.seal_path(root)
    return os.path.join(os.path.dirname(seal), "verifiers",
                        digest(os.path.abspath(root)) + ".json")


def _read(root):
    try:
        return json.loads(Path(state_path(root)).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"specs": {}}
    except (OSError, ValueError) as exc:
        raise VerifierError("invalid verifier authority state") from exc


def _update(root, change):
    path = state_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with locks.holding(path, timeout=10, stale=8):
        state = _read(root)
        result = change(state)
        temporary = path + "." + uuid.uuid4().hex + ".tmp"
        Path(temporary).write_text(json.dumps(state, ensure_ascii=False,
                                              indent=1), encoding="utf-8")
        os.replace(temporary, path)
        return result


def spec_hash(spec):
    """The bytes trust binds to: everything except lifecycle bookkeeping."""
    return digest({k: v for k, v in spec.items()
                   if k not in ("status", "calibration", "provenance")})


def validate_spec(spec):
    if not isinstance(spec, dict):
        raise VerifierError("a verifier spec must be an object")
    unknown = set(spec) - {"name", "version", "criteria", "params", "checks",
                           "status", "provenance", "calibration"}
    if unknown:
        raise VerifierError(f"unknown spec keys {sorted(unknown)}")
    if not isinstance(spec.get("name"), str) or not _SLUG.match(spec["name"]):
        raise VerifierError("verifier name must be a contained short slug")
    if not isinstance(spec.get("criteria"), str) or not spec["criteria"].strip():
        raise VerifierError("a verifier must state the criteria it mechanizes")
    params = spec.get("params")
    if not isinstance(params, dict) or any(
            not isinstance(k, str) or not k or v not in _KINDS
            for k, v in params.items()):
        raise VerifierError(f"params must map names to one of {_KINDS}")
    checks = spec.get("checks")
    if not isinstance(checks, list) or not checks or len(checks) > MAX_CHECKS:
        raise VerifierError(f"checks must be 1..{MAX_CHECKS} predicates")
    for check in checks:
        operators.validate_predicate(check)
        for value in _placeholders(check):
            if value not in params:
                raise VerifierError(
                    f"check references undeclared param {value!r}")


def _placeholders(value):
    if isinstance(value, dict):
        if set(value) == {"input"}:
            yield value["input"]
        else:
            for item in value.values():
                yield from _placeholders(item)
    elif isinstance(value, list):
        for item in value:
            yield from _placeholders(item)


def propose(root, spec, proposed_by, actor="agent"):
    """File a CANDIDATE. Grants nothing; a worker cannot claim a taken name,
    and even the owner re-proposing over a TRUSTED name demotes it — trust
    never survives an edit."""
    spec = copy.deepcopy(spec)
    spec.pop("status", None)
    spec.pop("calibration", None)
    spec.setdefault("version", 1)
    validate_spec(spec)
    spec["status"] = "candidate"
    spec["provenance"] = {"proposed_by": str(proposed_by)[:200],
                          "actor": actor,
                          "at": time.strftime("%Y-%m-%dT%H:%M:%S")}

    def write(state):
        existing = state["specs"].get(spec["name"])
        if existing:
            if spec_hash(existing) == spec_hash(spec):
                return copy.deepcopy(existing)      # idempotent re-file
            if actor != "owner":
                raise VerifierError(
                    f"name {spec['name']!r} is taken; a worker proposes "
                    f"under a new name, never over someone else's")
        state["specs"][spec["name"]] = spec
        return copy.deepcopy(spec)
    return _update(root, write)


def _materialize(arena, files):
    if not isinstance(files, list) or any(
            not isinstance(item, dict) or set(item) != {"path", "content"}
            or not isinstance(item["path"], str)
            or not isinstance(item["content"], str) for item in files):
        raise VerifierError("case files must be path/content records")
    for item in files:
        if item["path"].endswith(".db"):
            import dbstate
            dbstate.run_script(
                fileauth.resolve(arena, item["path"], "write", "agent"),
                item["content"])
        else:
            fileauth.write_text(arena, item["path"], item["content"])


def _observe_all(workspace, spec, params):
    operators.check_inputs(workspace, spec["params"], params)
    results = []
    for check in spec["checks"]:
        bound = operators.bind(check, params)
        try:
            ok = bool(operators.observe(workspace, bound))
        except (OSError, ValueError, fileauth.Denied) as exc:
            ok, bound = False, {**bound, "error": str(exc)[:120]}
        results.append({"predicate": bound.get("predicate"),
                        "path": bound.get("path"), "ok": ok})
    return all(r["ok"] for r in results), results


def calibrate(root, name, cases, actor="owner"):
    """Owner-only discrimination trial. The set MUST contain rejects."""
    if actor != "owner":
        raise VerifierError("only the owner calibrates a verifier")
    state = _read(root)
    spec = state["specs"].get(name)
    if not spec:
        raise VerifierError(f"unknown verifier {name!r}")
    if not isinstance(cases, list) or not cases or len(cases) > MAX_CASES:
        raise VerifierError(f"calibration needs 1..{MAX_CASES} cases")
    ids = [c.get("id") for c in cases]
    if len(set(ids)) != len(ids) or not all(isinstance(x, str) and x for x in ids):
        raise VerifierError("case identities must be distinct")
    expects = {c.get("expect") for c in cases}
    if not expects <= {"accept", "reject"}:
        raise VerifierError('every case declares expect: "accept" or "reject"')
    if "reject" not in expects or "accept" not in expects:
        raise VerifierError(
            "unfalsifiable calibration: the set must contain at least one "
            "case the verifier is REQUIRED to reject and one it must "
            "accept — a verifier that cannot fail anything is not a verifier")
    receipts = []
    for case in cases:
        with tempfile.TemporaryDirectory(prefix="verifier-cal-") as arena:
            _materialize(arena, case.get("initial_files") or [])
            ok, results = _observe_all(arena, spec, case.get("params") or {})
        verdict = "accept" if ok else "reject"
        receipts.append({"id": case["id"], "expect": case["expect"],
                         "observed": verdict,
                         "matched": verdict == case["expect"],
                         "checks": results})
    discriminating = all(r["matched"] for r in receipts)
    record = {"spec_hash": spec_hash(spec), "cases": len(cases),
              "accepted_positives": sum(1 for r in receipts
                                        if r["expect"] == "accept" and r["matched"]),
              "rejected_negatives": sum(1 for r in receipts
                                        if r["expect"] == "reject" and r["matched"]),
              "discriminating": discriminating,
              "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "receipts": receipts}

    def write(state):
        live = state["specs"].get(name)
        if not live or spec_hash(live) != record["spec_hash"]:
            raise VerifierError("spec changed during calibration; re-run")
        live["calibration"] = record
        return copy.deepcopy(record)
    return _update(root, write)


def promote(root, name, actor="owner"):
    if actor != "owner":
        raise VerifierError("only the owner promotes a verifier")

    def write(state):
        spec = state["specs"].get(name)
        if not spec:
            raise VerifierError(f"unknown verifier {name!r}")
        calibration = spec.get("calibration")
        if not calibration or calibration.get("spec_hash") != spec_hash(spec):
            raise VerifierError(
                "no calibration for these exact spec bytes — calibrate first")
        if not calibration.get("discriminating"):
            raise VerifierError(
                "calibration was not discriminating: a verifier that "
                "accepted a case it was required to reject (or vice versa) "
                "buys no trust")
        spec["status"] = "trusted"
        return copy.deepcopy(spec)
    return _update(root, write)


def status(root, name):
    spec = _read(root)["specs"].get(name)
    if not spec:
        return None
    if spec.get("status") == "trusted":
        calibration = spec.get("calibration") or {}
        if calibration.get("spec_hash") != spec_hash(spec):
            return "candidate"          # trust never survives an edit
    return spec.get("status", "candidate")


def gate(root, name, params):
    """The L0 verdict for a task gated by this verifier. Fail-closed on
    every path that is not 'trusted verifier observed all checks true'."""
    try:
        state = _read(root)
    except VerifierError as exc:
        return False, str(exc)
    spec = state["specs"].get(name)
    if not spec:
        return False, f"unknown verifier {name!r}"
    if status(root, name) != "trusted":
        return False, (f"verifier {name!r} is {spec.get('status', 'candidate')}"
                       f" — candidates cannot gate; the owner must calibrate "
                       f"with accept AND reject cases, then promote")
    try:
        ok, results = _observe_all(root, spec, params or {})
    except (OSError, ValueError, fileauth.Denied) as exc:
        return False, f"verifier {name!r} could not observe: {exc}"
    detail = "; ".join(f"{r['predicate']}({r['path']})="
                       f"{'ok' if r['ok'] else 'FAIL'}" for r in results)
    return ok, detail


def names(root):
    return sorted(_read(root)["specs"])


def show(root, name):
    spec = _read(root)["specs"].get(name)
    return copy.deepcopy(spec) if spec else None


# ------------------------------------------------------------- templates
# The deterministic FLOOR: skeletons for the recurring gate families,
# selected by word stems. The model may propose far beyond these; the
# lifecycle prices everything identically.

def suggest(criteria):
    text = (criteria or "").lower()
    out = []
    if any(w in text for w in ("reconcil", "conserv", "totals", "balance")):
        out.append({
            "name": "conserved-report",
            "criteria": "the report's totals exactly equal the ledger's",
            "params": {"report": "path", "ledger": "path"},
            "checks": [
                {"predicate": "file_exists", "path": {"input": "report"}},
                {"predicate": "table_satisfies", "path": {"input": "report"},
                 "constraint": json.dumps({"kind": "sum_equals",
                                           "column": "total",
                                           "other_column": "amount"},
                                          sort_keys=True,
                                          separators=(",", ":")),
                 "other": {"input": "ledger"}}]})
    if any(w in text for w in ("typed", "schema", "conform", "column")):
        out.append({
            "name": "typed-table",
            "criteria": "the output conforms to its declared column types",
            "params": {"path": "path", "schema": "string"},
            "checks": [{"predicate": "table_conforms",
                        "path": {"input": "path"},
                        "schema": {"input": "schema"}}]})
    if any(w in text for w in ("migrat", "row count", "keys preserved",
                               "database")):
        out.append({
            "name": "db-asserted-state",
            "criteria": "the database satisfies its declared assertions",
            "params": {"database": "path", "assertions": "string"},
            "checks": [{"predicate": "db_satisfies_all",
                        "path": {"input": "database"},
                        "assertions": {"input": "assertions"}}]})
    return out


# --------------------------------------------------------------- owner CLI

def main():
    import argparse
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose", help="file a spec (candidate; no authority)")
    p.add_argument("--root", required=True)
    p.add_argument("--spec", required=True, help="path to a spec JSON file")
    c = sub.add_parser("calibrate", help="owner: run accept/reject cases")
    c.add_argument("--root", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--cases", required=True, help="path to a cases JSON file")
    t = sub.add_parser("promote", help="owner: trust a discriminating verifier")
    t.add_argument("--root", required=True)
    t.add_argument("--name", required=True)
    ls = sub.add_parser("list", help="names and statuses")
    ls.add_argument("--root", required=True)
    sh = sub.add_parser("show", help="one spec, verbatim")
    sh.add_argument("--root", required=True)
    sh.add_argument("--name", required=True)
    sg = sub.add_parser("suggest", help="deterministic template skeletons")
    sg.add_argument("--criteria", required=True)
    args = ap.parse_args()
    if args.cmd == "propose":
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        record = propose(args.root, spec, proposed_by="owner CLI",
                         actor="owner")
        print(f"filed {record['name']!r} as CANDIDATE — calibrate with "
              f"accept AND reject cases, then promote")
    elif args.cmd == "calibrate":
        cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
        record = calibrate(args.root, args.name, cases)
        print(json.dumps({k: record[k] for k in
                          ("cases", "accepted_positives", "rejected_negatives",
                           "discriminating")}, indent=1))
    elif args.cmd == "promote":
        promote(args.root, args.name)
        print(f"{args.name}: TRUSTED (hash-bound to the calibrated bytes)")
    elif args.cmd == "list":
        for name in names(args.root):
            print(f"{status(args.root, name):9} {name}")
    elif args.cmd == "show":
        print(json.dumps(show(args.root, args.name), indent=1,
                         ensure_ascii=False))
    elif args.cmd == "suggest":
        print(json.dumps(suggest(args.criteria), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
