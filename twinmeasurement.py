"""Retrospective evaluation artifacts, not prospective human validation.

DESIGN-twin-measurement-integrity.md. No model, network or process calls.
"""
import copy
import hashlib
import json
import os
import platform

SCHEMA = "twin-retrospective-v2"
RECEIPTS = os.path.join("twin", "evaluations")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def group(row):
    # Inferred exact-scenario grouping, never described as pre-outcome enrollment.
    import twin
    return digest({"situation": twin._norm_situation(row["situation"]),
                   "options": sorted(twin._norm_options(row["options"]), key=lambda o: o["id"]),
                   "counterpart": str(row.get("counterpart") or "").lower()})


def partition(row):
    bucket = int(group(row), 16) % 5
    return "train" if bucket < 3 else "validation" if bucket == 3 else "test"


def split(rows):
    out = {"train": [], "validation": [], "test": []}
    seen = set()
    for row in rows:
        if row["id"] in seen:
            raise ValueError("duplicate decision ID")
        seen.add(row["id"])
        if str(row["choice"]) not in {str(o["id"]) for o in row["options"]}:
            raise ValueError("decision choice outside options")
        out[partition(row)].append(copy.deepcopy(row))
    for values in out.values():
        values.sort(key=lambda row: row["id"])
    return out


def fitted_digest(version):
    return digest({k: v for k, v in version.items()
                   if k not in {"hash", "v", "at", "note", "refreshed"}})


def runtime():
    import twin
    import twinmath
    paths = (twin.__file__, twinmath.__file__, __file__)
    sources = {}
    for path in paths:
        with open(path, "rb") as stream:
            sources[os.path.basename(path)] = hashlib.sha256(
                stream.read().replace(b"\r\n", b"\n")).hexdigest()
    return {"sources": sources, "python": platform.python_version(),
            "constants": {name: getattr(twin, name) for name in
                          ("RULE_BONUS", "NEIGHBOR_BONUS", "NEIGHBORS",
                           "MIN_NEIGHBOR_SIM", "MIN_HOLDOUT", "NOVEL")}}


def binding(kernel, dataset):
    return {"kernel": digest(kernel), "dataset": digest(dataset),
            "runtime": digest(runtime())}


def read(root, receipt_id):
    if not isinstance(receipt_id, str) or len(receipt_id) != 64 or any(
            c not in "0123456789abcdef" for c in receipt_id):
        raise ValueError("invalid evaluation receipt ID")
    with open(os.path.join(root, RECEIPTS, receipt_id + ".json"), encoding="utf-8") as stream:
        body = json.load(stream)
    if digest(body) != receipt_id:
        raise ValueError("TAMPER: evaluation receipt changed")
    return body


def archive(root, kernel, dataset, scored, report, auxiliary, evaluation_runtime):
    import locks
    import twin
    directory = os.path.join(root, RECEIPTS)
    os.makedirs(directory, exist_ok=True)
    # Bind the captured inputs, never newly read state to already computed scores.
    # Changes after this check still make current_report stale against this snapshot.
    if (kernel != twin.load_kernel(root) or evaluation_runtime != runtime() or
            auxiliary != {"episodes": twin.episodes(root),
                          "predictions": twin.predictions(root)}):
        raise twin.Refused("inputs changed during evaluation; rerun fidelity")
    current_binding = {"kernel": digest(kernel), "dataset": digest(dataset),
                       "runtime": digest(evaluation_runtime)}
    current_binding["auxiliary"] = digest(auxiliary)
    final_groups = sorted({group(e) for e in dataset if partition(e) == "test"})
    # Reserve history and install the receipt under one lock. A changed
    # predictor cannot erase prior use by merely changing its dataset hash.
    with locks.holding(os.path.join(directory, "history")):
        reused = False
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".json"):
                continue
            prior = read(root, name[:-5])
            changed = any(prior["binding"][key] != current_binding[key]
                          for key in ("kernel", "runtime"))
            if changed and set(final_groups).intersection(prior["final_groups"]):
                reused = True
        body = {"schema": SCHEMA, "binding": current_binding,
                "kernel": copy.deepcopy(kernel), "dataset": copy.deepcopy(dataset),
                "auxiliary": auxiliary,
                "runtime": evaluation_runtime, "final_groups": final_groups,
                "scored": copy.deepcopy(scored), "report": copy.deepcopy(report),
                "test_groups_reused": reused,
                "generalization_established": False}
        receipt_id = digest(body)
        path = os.path.join(directory, receipt_id + ".json")
        if os.path.exists(path):
            read(root, receipt_id)
        else:
            twin._write_json(path, body)
    return {"receipt": receipt_id, "binding": current_binding,
            "test_groups_reused": reused, "generalization_established": False}


def replay(root, receipt_id):
    import twin
    twin.need_scope(root, "predict")
    body = read(root, receipt_id)
    if body["runtime"] != runtime():
        raise ValueError("evaluation runtime changed; historical replay unavailable")
    kernel = body["kernel"]
    version = twin.current_version(kernel)
    actual = []
    for row in body["dataset"]:
        if partition(row) != "test":
            continue
        pred = twin.predict(root, row["situation"], row["options"], row.get("counterpart"),
                            kernel=kernel, version=version)
        result = twin._score(pred, str(row["choice"]))
        actual.append({"id": row["id"], "probs": pred["probs"], "score": result})
    if actual != body["scored"]:
        raise ValueError("evaluation replay differs from receipt")
    return body["report"]


def current_report(root):
    import twin
    report = twin._read_json(twin._p(root, twin.FIDELITY), None)
    if not report:
        return report
    try:
        kernel = twin.load_kernel(root)
        version = twin.current_version(kernel)
        dataset = sorted(twin.decisions(twin.episodes(root)[int(version.get("since") or 0):]),
                         key=lambda row: row["id"])
        # Missing receipts and legacy reports fail closed, as do edited projections.
        receipt = read(root, report.get("receipt"))
        authoritative = dict(receipt["report"], receipt=report["receipt"],
                             binding=receipt["binding"],
                             test_groups_reused=receipt["test_groups_reused"],
                             generalization_established=False)
        expected = binding(kernel, dataset)
        expected["auxiliary"] = digest({"episodes": twin.episodes(root),
                                       "predictions": twin.predictions(root)})
        if report != authoritative or report["binding"] != expected:
            raise ValueError("evaluation binding mismatch")
        return report
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        return {"verdict": "STALE", "why": "kernel, data, runtime or receipt changed; rerun fidelity",
                "generalization_established": False}
