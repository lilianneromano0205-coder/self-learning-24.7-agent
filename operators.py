"""Small observable operator algebra. Predictions never replace observation."""
import heapq
import itertools
import math
import os

import fileauth


class OperatorError(ValueError):
    pass


def bind(value, inputs):
    if isinstance(value, dict):
        if set(value) == {"input"}:
            if value["input"] not in inputs:
                raise OperatorError(f"missing input {value['input']}")
            return inputs[value["input"]]
        return {key: bind(item, inputs) for key, item in value.items()}
    if isinstance(value, list):
        return [bind(item, inputs) for item in value]
    return value


def check_inputs(root, schema, inputs):
    if not isinstance(inputs, dict) or set(inputs) != set(schema):
        raise OperatorError("inputs must exactly match typed schema")
    for key, kind in schema.items():
        value = inputs[key]
        good = ((kind in ("string", "path") and isinstance(value, str)) or
                (kind == "integer" and type(value) is int) or
                (kind == "number" and type(value) in (int, float) and math.isfinite(value)) or
                (kind == "boolean" and type(value) is bool))
        if not good:
            raise OperatorError(f"input {key} must be {kind}")
        if kind == "path":
            if not value or os.path.isabs(value) or ".." in value.replace("\\", "/").split("/"):
                raise OperatorError(f"input {key} must be a relative contained path")
            fileauth.resolve(root, value, "write", "agent")


def validate_predicate(item):
    if not isinstance(item, dict) or item.get("predicate") not in (
            "file_exists", "file_absent", "file_equals", "file_derives",
            "table_conforms", "table_satisfies", "db_satisfies_all") \
            or "path" not in item:
        raise OperatorError("unsupported mechanically observable predicate")
    if item["predicate"] == "file_equals" and "value" not in item:
        raise OperatorError("file_equals needs a value")
    if item["predicate"] == "file_derives" and (
            "spec" not in item or "source" not in item):
        raise OperatorError("file_derives needs a spec and a source")
    if item["predicate"] == "table_conforms" and "schema" not in item:
        raise OperatorError("table_conforms needs a schema")
    if item["predicate"] == "table_satisfies" and "constraint" not in item:
        raise OperatorError("table_satisfies needs a constraint")
    if item["predicate"] == "db_satisfies_all" and "assertions" not in item:
        raise OperatorError("db_satisfies_all needs assertions")


def observe(root, predicate):
    validate_predicate(predicate)
    path = fileauth.resolve(root, predicate["path"], "read", "agent")
    kind = predicate["predicate"]
    if kind == "file_absent":
        return not os.path.lexists(path)
    if not os.path.isfile(path) or os.path.islink(path):
        return False
    if kind == "file_exists":
        return True
    if kind == "file_derives":
        # The output IS the deterministic transform of its sources, RIGHT NOW
        # — re-derived through the trusted adapter, never remembered. A
        # source that moved, a spec that no longer parses, an output that
        # drifted: all of them are simply "no longer true".
        import tabular
        try:
            second = (fileauth.read_text(root, predicate["source2"])
                      if "source2" in predicate else None)
            derived = tabular.apply(predicate["spec"],
                                    fileauth.read_text(root, predicate["source"]),
                                    second)
        except (OSError, ValueError, fileauth.Denied):
            return False
        return fileauth.read_text(root, predicate["path"]) == derived
    if kind == "table_conforms":
        # The file IS a table of the declared types, re-checked now. An
        # unparseable file, a missing column, one bad cell: all read as
        # "no longer true", never as an exception a caller must guess at.
        import tabletypes
        try:
            tabletypes.conforms(predicate["schema"],
                                fileauth.read_text(root, predicate["path"]))
        except (OSError, ValueError, fileauth.Denied):
            return False
        return True
    if kind == "table_satisfies":
        import tabletypes
        try:
            other = (fileauth.read_text(root, predicate["other"])
                     if "other" in predicate else None)
            return bool(tabletypes.satisfies(
                predicate["constraint"],
                fileauth.read_text(root, predicate["path"]), other))
        except (OSError, ValueError, fileauth.Denied):
            return False
    if kind == "db_satisfies_all":
        # Every declared assertion re-observed against the database as it
        # stands — the SQL analog of file_derives.
        import dbstate
        try:
            ok, _why = dbstate.check_assertions(path, predicate["assertions"])
        except (OSError, ValueError, fileauth.Denied):
            return False
        return ok
    return fileauth.read_text(root, predicate["path"]) == predicate["value"]


def validate(op):
    if not isinstance(op, dict):
        raise OperatorError("operator must be an object")
    if not isinstance(op.get("inputs"), dict) or any(
            value not in ("path", "string", "integer", "number", "boolean")
            for value in op["inputs"].values()):
        raise OperatorError("operator needs typed inputs")
    for key in ("preconditions", "effects", "invariants"):
        if not isinstance(op.get(key), list):
            raise OperatorError(f"operator needs {key}")
        for item in op[key]:
            validate_predicate(item)
    for key in ("cost_usd", "latency_seconds"):
        if type(op.get(key)) not in (float, int) or not math.isfinite(op[key]) or op[key] < 0:
            raise OperatorError(f"invalid {key}")
    if op.get("reversibility") not in ("reversible", "irreversible", "conditional"):
        raise OperatorError("operator needs explicit reversibility")
    if not isinstance(op.get("authority"), list) or not all(isinstance(x, str) for x in op["authority"]):
        raise OperatorError("operator needs authority list")


def plan(root, goals, bindings, authority=None, max_steps=8, max_states=256):
    """Uniform-cost search over explicitly grounded PROVEN runbooks.

    bindings is [{name, inputs}]. No invented bindings, open-world facts or
    model calls. Search is bounded and dry; execute_plan reobserves every step.
    """
    import json
    import runbook
    authority = set(["workspace-write"] if authority is None else authority)
    for predicate in goals:
        validate_predicate(predicate)
    grounded = []
    atoms = {json.dumps(item, sort_keys=True) for item in goals}
    for entry in bindings:
        name, inputs = entry["name"], entry.get("inputs", {})
        if runbook.status(root, name) != "proven":
            continue
        rb = runbook.load(root, name)
        op = rb.get("operator")
        if not op or any(step.get("kind") == "model" for step in rb["steps"]):
            continue
        validate(op)
        check_inputs(root, op["inputs"], inputs)
        if not set(op["authority"]) <= authority:
            continue
        bound = bind(op, inputs)
        grounded.append((entry, bound))
        for key in ("preconditions", "effects", "invariants"):
            atoms.update(json.dumps(x, sort_keys=True) for x in bound[key])
    predicates = {atom: json.loads(atom) for atom in atoms}
    start = frozenset(atom for atom, item in predicates.items() if observe(root, item))
    required = {json.dumps(item, sort_keys=True) for item in goals}
    queue, seen, counter = [(0.0, 0, start, [])], {}, itertools.count(1)
    while queue and len(seen) < max_states:
        cost, _, state, steps = heapq.heappop(queue)
        if required <= state:
            return {"ok": True, "steps": steps, "estimated_cost": cost,
                    "evidence": "predicted; execute_plan must reobserve"}
        if state in seen or len(steps) >= max_steps:
            continue
        seen[state] = cost
        for entry, op in grounded:
            needed = {json.dumps(x, sort_keys=True) for x in op["preconditions"] + op["invariants"]}
            if not needed <= state:
                continue
            following = set(state)
            for effect in op["effects"]:
                for atom, predicate in predicates.items():
                    if predicate["path"] != effect["path"]:
                        continue
                    if effect["predicate"] == "file_equals":
                        truth = predicate["predicate"] == "file_exists" or predicate == effect
                    elif effect["predicate"] == "file_absent":
                        truth = predicate["predicate"] == "file_absent"
                    else:
                        # file_exists and file_derives effects: the file is
                        # there; a derives GOAL is predicted true only for the
                        # identical derivation, and reobserved either way
                        truth = predicate["predicate"] == "file_exists" or predicate == effect
                    if truth:
                        following.add(atom)
                    else:
                        following.discard(atom)
            if not {json.dumps(x, sort_keys=True) for x in op["invariants"]} <= following:
                continue
            next_state = frozenset(following)
            if next_state != state:
                heapq.heappush(queue, (cost + op["cost_usd"] + op["latency_seconds"] / 1000000,
                                      next(counter), next_state, steps + [entry]))
    return {"ok": False, "steps": [], "why": "no proven observable composition within search bounds"}


def execute_plan(root, planned, goals, authority=None):
    import runbook
    if not planned.get("ok"):
        return {"ok": False, "steps": [], "why": "plan is not executable"}
    results = []
    for step in planned["steps"]:
        result = runbook.run(root, step["name"], inputs=step.get("inputs", {}), authority=authority)
        results.append(result)
        if not result["ok"]:
            return {"ok": False, "steps": results, "why": result["why"]}
    return {"ok": all(observe(root, item) for item in goals), "steps": results}
