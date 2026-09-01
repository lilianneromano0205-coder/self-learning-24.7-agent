"""Conservative workflow induction from harness-observed, independently graded actions.

Only file write/copy semantics have deterministic adapters. Unknown tools remain
model-required barriers. A candidate never authors its graders or its receipts.
Authority state uses the same external org boundary as goal-contract seals.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

import fileauth
import locks
import operators


class ProcedureError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def authority_path(root):
    import contract
    seal, _ = contract.seal_path(root)
    return os.path.join(os.path.dirname(seal), "procedures", digest(os.path.abspath(root)) + ".json")


def _read(root):
    try:
        return json.loads(Path(authority_path(root)).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"judges": {}, "suites": {}, "trajectories": {}, "receipts": {}}
    except (OSError, ValueError) as exc:
        raise ProcedureError("invalid procedural authority state") from exc


def _update(root, change):
    path = authority_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with locks.holding(path, timeout=10, stale=8):
        state = _read(root)
        result = change(state)
        temporary = path + "." + uuid.uuid4().hex + ".tmp"
        Path(temporary).write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, path)
        return result


def _seal(root, section, identity, value, actor):
    if actor != "owner":
        raise ProcedureError("only owner may seal independent graders")
    if not isinstance(identity, str) or not identity:
        raise ProcedureError("invalid grader identity")
    sealed = {"value": copy.deepcopy(value), "hash": digest(value), "sealed_at": time.time()}
    def write(state):
        old = state[section].get(identity)
        if old and old["hash"] != sealed["hash"]:
            raise ProcedureError("seal conflict: use a new independent grader identity")
        state[section].setdefault(identity, sealed)
        return state[section][identity]["hash"]
    return _update(root, write)


def seal_judge(root, identity, checks, actor="owner"):
    if not isinstance(checks, list) or not checks:
        raise ProcedureError("independent judge must contain mechanical checks")
    for check in checks:
        operators.validate_predicate(check)
        if not isinstance(check["path"], str):
            raise ProcedureError("trajectory judges must have concrete paths")
        fileauth.resolve(root, check["path"], "read", "agent")
    return _seal(root, "judges", identity, checks, actor)


def seal_suite(root, identity, suite, actor="owner"):
    if not isinstance(suite, dict) or not suite.get("cases") or not suite.get("checks"):
        raise ProcedureError("suite needs fresh cases and independent checks")
    ids = [case.get("id") for case in suite["cases"]]
    if not all(isinstance(x, str) and x for x in ids) or len(set(ids)) != len(ids):
        raise ProcedureError("case identities must be distinct")
    for check in suite["checks"]:
        operators.validate_predicate(check)
    return _seal(root, "suites", identity, suite, actor)


def _sealed(state, section, identity):
    record = state[section].get(identity)
    if not record or digest(record["value"]) != record["hash"]:
        raise ProcedureError("missing or tampered independent seal")
    return record


GATE_ACCEPTANCE = "harness_gate"


def begin_trajectory(root, task_id, judge_id=None, inputs=None, family="unspecified",
                     gate=None):
    """Open a trajectory. Acceptance comes from ONE of two external judges.

    `judge_id` names an owner-sealed grader — the strongest basis, and the
    only one that existed at first. It required the owner to hand-write a
    judge and typed inputs for every task, which meant that on ordinary work
    — a task from the panel, a goal, a mission, a routine — no trajectory was
    ever opened and the whole induction path was unreachable outside a demo.

    `gate` is the task's OWN definition of done: the mechanical command the
    harness runs through the execution authority to decide whether the work
    counted. It is not the worker's opinion — a worker cannot write or edit
    its `done_check`, which is set when the task is created and lives in
    CONTROL-zoned state. So it is an external verdict, and it is already the
    thing this platform trusts to say a task succeeded.

    What a gate-based trajectory may NOT do is earn trust. It can produce a
    CANDIDATE procedure and nothing more; `proven` still requires
    `evaluate()` against an owner-sealed suite of fresh instances. That is
    the division that makes automatic capture safe: the system may now teach
    itself cheaply, and still cannot decide that it has learned.
    """
    inputs = {} if inputs is None else inputs
    def begin(state):
        basis, judge_hash = GATE_ACCEPTANCE, None
        if judge_id is not None:
            judge_hash = _sealed(state, "judges", judge_id)["hash"]
            basis = "sealed_judge"
        elif not gate:
            raise ProcedureError("a trajectory needs a sealed judge or a task gate")
        if task_id in state["trajectories"]:
            raise ProcedureError("trajectory identity already used")
        state["trajectories"][task_id] = {
            "task_id": task_id, "judge_id": judge_id, "judge_hash": judge_hash,
            "acceptance_basis": basis, "gate_hash": digest(gate) if gate else None,
            "inputs": copy.deepcopy(inputs), "input_hash": digest(inputs),
            "environment": digest(os.path.realpath(root)), "family": family,
            "started": time.time(), "actions": [], "accepted": False, "closed": False}
    _update(root, begin)


def active_trajectory(root, task_id):
    """Loop-safe opt-in check; absence is ordinary and never opens a trace."""
    row = _read(root).get("trajectories", {}).get(task_id)
    return bool(row and not row.get("closed"))


def _normalize(action):
    if not isinstance(action, dict) or not isinstance(action.get("tool"), str):
        raise ProcedureError("action must identify a tool and structured arguments")
    action = copy.deepcopy(action)
    action.setdefault("args", {})
    if action["tool"] in ("write_file", "copy_file", "read_file"):
        required = {"write_file": ("path", "content"), "copy_file": ("source", "path"),
                    "read_file": ("path",)}[action["tool"]]
        if any(not isinstance(action["args"].get(key), str) for key in required):
            raise ProcedureError("file actions require string arguments")
        for key in ("path", "source"):
            if key in action["args"]:
                action["args"][key] = action["args"][key].replace("\\", "/")
    return action


def _snapshot(root, action):
    result = {}
    for key in ("path", "source"):
        value = action["args"].get(key)
        if action["tool"] not in ("write_file", "copy_file", "read_file") or not value:
            continue
        mode = "write" if key == "path" and action["tool"] != "read_file" else "read"
        path = fileauth.resolve(root, value, mode, "agent")
        exists = os.path.isfile(path)
        result[key] = {"exists": exists, "hash": digest(fileauth.read_text(root, value)) if exists else None}
    return result


def begin_action(root, task_id, tool, args):
    """Harness hook called immediately BEFORE a real tool invocation."""
    action = _normalize({"tool": tool, "args": args})
    before = _snapshot(root, action)
    token = uuid.uuid4().hex
    def add(state):
        trajectory = state["trajectories"].get(task_id)
        if not trajectory or trajectory["closed"]:
            raise ProcedureError("no open independently judged trajectory")
        trajectory["actions"].append({"token": token, "action": action, "before": before,
                                      "started": time.time(), "complete": False})
    _update(root, add)
    return token


def finish_action(root, task_id, token, succeeded):
    """Harness hook after invocation; read back effects instead of trusting tool prose."""
    def finish(state):
        trajectory = state["trajectories"].get(task_id)
        if not trajectory or trajectory["closed"]:
            raise ProcedureError("no open trajectory")
        matches = [a for a in trajectory["actions"] if a["token"] == token]
        if len(matches) != 1 or matches[0]["complete"]:
            raise ProcedureError("unknown or replayed action token")
        item = matches[0]
        action = item["action"]
        after = _snapshot(root, action)
        success = succeeded is True
        if action["tool"] == "write_file":
            success = success and after["path"]["hash"] == digest(action["args"]["content"])
        if action["tool"] == "copy_file":
            success = success and after["path"]["exists"] and after["path"]["hash"] == item["before"]["source"]["hash"]
        item.update({"complete": True, "succeeded": success, "after": after,
                     "latency_seconds": max(0, time.time() - item["started"])})
        return success
    return _update(root, finish)


def _perform(root, action):
    args = action["args"]
    if action["tool"] == "write_file":
        fileauth.write_text(root, args["path"], args["content"])
    elif action["tool"] == "copy_file":
        fileauth.write_text(root, args["path"], fileauth.read_text(root, args["source"]))
    elif action["tool"] == "read_file":
        fileauth.read_text(root, args["path"])
    else:
        raise ProcedureError("model-required or unsupported action has no deterministic executor")


def perform(root, task_id, action):
    action = _normalize(action)
    token = begin_action(root, task_id, action["tool"], action["args"])
    try:
        _perform(root, action)
    except Exception:
        finish_action(root, task_id, token, False)
        raise
    return finish_action(root, task_id, token, True)


def finish_trajectory(root, task_id, gate_passed=None):
    def finish(state):
        trajectory = state["trajectories"].get(task_id)
        if not trajectory or trajectory["closed"]:
            raise ProcedureError("trajectory missing or already closed")
        if trajectory.get("acceptance_basis") == GATE_ACCEPTANCE:
            # The harness's own gate verdict, passed in by the caller that
            # ran it. `None` is not a pass: a trajectory whose gate never
            # ran is closed unaccepted rather than given the benefit of the
            # doubt, because "nobody checked" and "it worked" must never
            # collapse into the same record.
            checks = [gate_passed is True]
        else:
            judge = _sealed(state, "judges", trajectory["judge_id"])
            if judge["hash"] != trajectory["judge_hash"]:
                raise ProcedureError("grader changed after execution began")
            checks = [operators.observe(root, check) for check in judge["value"]]
        trajectory["accepted"] = bool(trajectory["actions"]) and all(checks) and all(
            item.get("complete") and item.get("succeeded") for item in trajectory["actions"])
        # WHAT THE WORK ACTUALLY WAS. Two trajectories that performed byte-
        # identical actions are one piece of evidence, not two, however many
        # times they ran. For auto-captured work this is the independence
        # signal, because such tasks declare no typed inputs to differ by.
        trajectory["work_hash"] = digest(
            [[i["action"]["tool"], i["action"]["args"]] for i in trajectory["actions"]])
        trajectory["closed"] = True
        trajectory["checks"] = checks
        trajectory["digest"] = digest({k: v for k, v in trajectory.items() if k != "digest"})
        return copy.deepcopy(trajectory)
    return _update(root, finish)


_KINDS = {str: "string", bool: "boolean", int: "integer", float: "number"}


def _infer(values, trajectories, schema, hint, minted=None):
    """Constant, declared parameter, or — for auto-captured work — a new one.

    Identical across every trajectory means CONSTANT: the step always did
    that, so the procedure always will.

    Otherwise the variation must be explained. A declared typed input that
    tracks it exactly is the strongest explanation and is preferred.

    Failing that, the value is PARAMETERISED: this is what varied, so it
    becomes an argument the caller must supply. Refusing here instead — the
    original behaviour — is why nothing captured from ordinary work could
    ever compile: such tasks declare no typed inputs, so no declared input
    could explain anything, and every induction died on the first argument
    that differed.

    Minting is deliberately narrow. It requires a value that genuinely
    varies, of one simple type across every trajectory, and it names what it
    invented so the owner can read the generalisation back. And it buys
    nothing on its own: the result is a CANDIDATE, and only a sealed suite
    of fresh instances can make it proven.
    """
    if all(value == values[0] and type(value) is type(values[0]) for value in values):
        return copy.deepcopy(values[0])
    for key in schema:
        if all(t["inputs"].get(key) == value and type(t["inputs"].get(key)) is type(value)
               for t, value in zip(trajectories, values)):
            return {"input": key}
    if minted is None:
        raise ProcedureError(f"unaligned {hint}: no declared typed input explains variation")
    kind = _KINDS.get(type(values[0]))
    if kind is None or any(type(v) is not type(values[0]) for v in values):
        raise ProcedureError(
            f"unaligned {hint}: the values vary and are not one simple type, "
            f"so what changed cannot be named")
    if len(set(values)) < len(values):
        raise ProcedureError(
            f"unaligned {hint}: the values vary but repeat across trajectories, "
            f"so the variation is not explained by one argument per run")
    name = hint if hint not in schema else f"{hint}_{len(schema) + 1}"
    schema[name] = kind
    minted.append(name)
    return {"input": name}


def compile(root, name, trajectory_ids, triggers):
    """Align complete repeated action sequences; never discard an unmatched mutation."""
    import runbook
    if not isinstance(trajectory_ids, list) or not all(isinstance(x, str) for x in trajectory_ids):
        raise ProcedureError("compiler takes harness trajectory IDs, not author supplied evidence")
    if len(set(trajectory_ids)) < 2:
        raise ProcedureError("need multiple independent trajectories")
    state, trajectories = _read(root), []
    for identity in dict.fromkeys(trajectory_ids):
        trajectory = state["trajectories"].get(identity)
        if not trajectory or not trajectory.get("accepted") or not trajectory.get("closed"):
            raise ProcedureError("unverified trajectory")
        if trajectory.get("digest") != digest({k: v for k, v in trajectory.items() if k != "digest"}):
            raise ProcedureError("tampered trajectory")
        if trajectory.get("acceptance_basis") != GATE_ACCEPTANCE:
            _sealed(state, "judges", trajectory["judge_id"])
        trajectories.append(trajectory)
    # INDEPENDENCE, read differently for the two acceptance bases.
    #
    # A sealed-judge induction must span two distinct judges: the guarantee
    # being bought is that no single grader can mint a procedure alone.
    #
    # Auto-captured work has no typed inputs to differ by and one gate per
    # task, so that rule would refuse everything and the capture path would
    # be decorative. What it can show instead is that the RUNS DIFFERED —
    # distinct work, separately accepted by the harness's own mechanical
    # gate. That is weaker, and it is priced accordingly: this route can
    # only ever produce a candidate, and `evaluate()` against an owner's
    # sealed suite of fresh instances remains the sole path to proven.
    auto = all(t.get("acceptance_basis") == GATE_ACCEPTANCE for t in trajectories)
    if auto:
        if len({t.get("work_hash") for t in trajectories}) < 2:
            raise ProcedureError("identical work repeated is not independent induction")
    elif len({t["input_hash"] for t in trajectories}) < 2 or \
            len({t["judge_id"] for t in trajectories}) < 2:
        raise ProcedureError("repeated identical evidence is not independent induction")
    if len({t["family"] for t in trajectories}) != 1:
        raise ProcedureError("cannot infer across unrelated task families")
    schema = {}
    for key, value in trajectories[0]["inputs"].items():
        kind = {str: "string", bool: "boolean", int: "integer", float: "number"}.get(type(value))
        if kind is None or any(set(t["inputs"]) != set(trajectories[0]["inputs"]) or
                               type(t["inputs"][key]) is not type(value) for t in trajectories):
            raise ProcedureError("incompatible typed input schemas")
        schema[key] = kind
    minted = []
    # Reads are observations; all mutating/unknown tools must align in order.
    sequences = [[item for item in t["actions"] if item["action"]["tool"] != "read_file"] for t in trajectories]
    if not sequences[0] or any(len(s) != len(sequences[0]) for s in sequences):
        raise ProcedureError("unaligned action sequence; refusing to drop mutations")
    steps, preconditions, effects, invariants = [], [], [], []
    touched = []
    for index, aligned in enumerate(zip(*sequences)):
        actions = [item["action"] for item in aligned]
        tools = {a["tool"] for a in actions}
        if len(tools) != 1 or any(set(a["args"]) != set(actions[0]["args"]) for a in actions):
            raise ProcedureError("unaligned tool/argument sequence")
        tool = actions[0]["tool"]
        args = {key: _infer([a["args"][key] for a in actions], trajectories, schema,
                            key, minted if auto else None)
                for key in actions[0]["args"]}
        identity = f"step-{index + 1}"
        step = {"id": identity, "depends_on": [steps[-1]["id"]] if steps else [],
                "kind": "deterministic" if tool in ("write_file", "copy_file") else "model",
                "action": {"tool": tool, "args": args}, "preconditions": [], "effects": []}
        if step["kind"] == "model":
            step["reason"] = "tool has no trusted deterministic semantic adapter"
        else:
            for key in ("path", "source"):
                if isinstance(args.get(key), dict):
                    schema[args[key]["input"]] = "path"
            before = {item["before"]["path"]["exists"] for item in aligned}
            if len(before) != 1:
                raise ProcedureError("mixed overwrite/create preconditions require separate operators")
            guard = {"predicate": "file_exists" if True in before else "file_absent", "path": args["path"]}
            step["preconditions"].append(guard)
            if args["path"] not in touched:
                preconditions.append(guard)
            if tool == "copy_file":
                source = {"predicate": "file_exists", "path": args["source"]}
                step["preconditions"].append(source)
                if args["source"] not in touched:
                    preconditions.append(source)
                    invariants.append(source)
                effect = {"predicate": "file_exists", "path": args["path"]}
            else:
                effect = {"predicate": "file_equals", "path": args["path"], "value": args["content"]}
            step["effects"].append(effect)
            effects = [e for e in effects if e["path"] != args["path"]] + [effect]
            touched.append(args["path"])
        steps.append(step)
    rb = {"name": name, "triggers": triggers, "procedure_version": 1, "steps": steps,
          "operator": {"inputs": schema, "preconditions": preconditions, "effects": effects,
                       "invariants": invariants, "cost_usd": 0.0,
                       "cost_basis": "deterministic local file adapters; no provider calls",
                       "latency_seconds": sum(sum(i["latency_seconds"] for i in seq) for seq in sequences) / len(sequences),
                       "reversibility": "conditional", "authority": ["workspace-write"],
                       "reliability": {"source": "induction only; independent evaluation required"}},
          "provenance": {"compiled": True, "trajectory_ids": trajectory_ids,
                         "acceptance_basis": ("harness_gate" if auto else "sealed_judge"),
                         "inferred_parameters": list(minted),
                         "input_hashes": [t["input_hash"] for t in trajectories],
                         "family": trajectories[0]["family"], "alignment": "ordered complete mutating sequence"}}
    problems = runbook.validate(rb)
    if problems:
        raise ProcedureError("invalid compiled procedure: " + "; ".join(problems))
    os.makedirs(os.path.dirname(runbook.path(root, name)), exist_ok=True)
    Path(runbook.path(root, name)).write_text(json.dumps(rb, indent=1, ensure_ascii=False), encoding="utf-8")
    return rb


def validate(rb):
    try:
        operators.validate(rb.get("operator"))
        seen = set()
        for step in rb.get("steps", []):
            identity = step.get("id")
            if not isinstance(identity, str) or not identity or identity in seen:
                raise ProcedureError("DAG step needs a distinct id")
            if not isinstance(step.get("depends_on"), list) or not set(step["depends_on"]) <= seen:
                raise ProcedureError("DAG dependency is missing, cyclic, or not topologically ordered")
            if step.get("kind") not in ("deterministic", "model"):
                raise ProcedureError("step must be explicit deterministic or model-required")
            if step["kind"] == "deterministic":
                if step.get("action", {}).get("tool") not in ("write_file", "copy_file"):
                    raise ProcedureError("unknown deterministic adapter")
                if not step.get("effects"):
                    raise ProcedureError("step must have mechanically observable effects")
                for item in step.get("preconditions", []) + step["effects"]:
                    operators.validate_predicate(item)
            seen.add(identity)
        return []
    except (ValueError, TypeError, KeyError) as exc:
        return [str(exc)]


def execute(root, rb, inputs, workspace=None, authority=None):
    workspace = workspace or root
    authority = set(["workspace-write"] if authority is None else authority)
    done = []
    try:
        operators.check_inputs(workspace, rb["operator"]["inputs"], inputs)
        bound = operators.bind(rb, inputs)
        op = bound["operator"]
        if not set(op["authority"]) <= authority:
            raise ProcedureError("required authority was not granted")
        # Check all arguments before any side effect, including constants.
        for step in bound["steps"]:
            if step["kind"] == "model":
                raise ProcedureError("model-required step; deterministic execution stops")
            _snapshot(workspace, _normalize(step["action"]))
        if not all(operators.observe(workspace, item) for item in op["preconditions"] + op["invariants"]):
            raise ProcedureError("operator precondition or invariant is not satisfied")
        for step in bound["steps"]:
            if not all(operators.observe(workspace, item) for item in step["preconditions"]):
                raise ProcedureError("step precondition changed")
            before = _snapshot(workspace, step["action"])
            _perform(workspace, step["action"])
            after = _snapshot(workspace, step["action"])
            if step["action"]["tool"] == "copy_file" and after["path"]["hash"] != before["source"]["hash"]:
                raise ProcedureError("copy effect content differs from observed source")
            if not all(operators.observe(workspace, item) for item in step["effects"] + op["invariants"]):
                raise ProcedureError("step effect or invariant did not verify")
            done.append({"id": step["id"], "ok": True})
        if not all(operators.observe(workspace, item) for item in op["effects"]):
            raise ProcedureError("final effects did not verify")
        return {"ok": True, "accepted": False, "steps": done, "why": "", "stopped_at": 0, "subs": []}
    except (OSError, ValueError, fileauth.Denied) as exc:
        return {"ok": False, "accepted": False, "steps": done, "why": str(exc),
                "stopped_at": len(done) + 1, "subs": []}


def accepted_trajectories(root, family):
    """Closed, accepted trajectories in one family — the compiler's raw
    material, summarized without exposing action payloads."""
    rows = []
    for identity, t in _read(root).get("trajectories", {}).items():
        if (t.get("closed") and t.get("accepted")
                and t.get("family") == family
                and t.get("digest") == digest({k: v for k, v in t.items()
                                               if k != "digest"})):
            rows.append({"task_id": identity, "input_hash": t["input_hash"],
                         "judge_id": t["judge_id"],
                         "work_hash": t.get("work_hash"),
                         "acceptance_basis": t.get("acceptance_basis")})
    return rows


def sealed_suites(root, family=None):
    """Identities of owner-sealed evaluation suites, optionally per family."""
    out = []
    for identity, record in _read(root).get("suites", {}).items():
        value = record.get("value") or {}
        if digest(value) != record.get("hash"):
            continue
        if family is None or value.get("family") == family:
            out.append(identity)
    return out


def accepted_evidence(root, name, evidence):
    import runbook
    if not isinstance(evidence, str):
        return None
    receipt = _read(root)["receipts"].get(evidence)
    if not receipt or not receipt["accepted"] or receipt["name"] != name:
        return None
    if receipt["runbook_hash"] != digest(runbook.load(root, name)):
        return None
    return copy.deepcopy(receipt)


def evaluate(root, name, suite_id):
    """Generate fresh workspaces from owner-sealed cases; grader stays outside."""
    import runbook
    rb = runbook.load(root, name)
    sealed = _sealed(_read(root), "suites", suite_id)
    suite = sealed["value"]
    if suite.get("family") != rb["provenance"]["family"]:
        raise ProcedureError("evaluation outside declared task family")
    if not any(case.get("edge") is True for case in suite["cases"]):
        raise ProcedureError("independent edge-case coverage is required")
    training = set(rb["provenance"]["input_hashes"])
    if any(digest(case["inputs"]) in training or case["id"] in rb["provenance"]["trajectory_ids"] for case in suite["cases"]):
        raise ProcedureError("evaluation instance overlaps induction data")
    results = []
    for case in suite["cases"]:
        identity = digest({"runbook": digest(rb), "suite": sealed["hash"], "case": case["id"]})
        existing = _read(root)["receipts"].get(identity)
        if existing:
            results.append(existing)
            continue
        if runbook.status(root, name) == "quarantined":
            break
        with tempfile.TemporaryDirectory(prefix="procedure-eval-") as arena:
            initial = operators.bind(suite.get("initial_files", []), case["inputs"])
            if isinstance(initial, dict):
                initial = [{"path": path, "content": content}
                           for path, content in initial.items()]
            if not isinstance(initial, list) or any(
                    not isinstance(item, dict) or set(item) != {"path", "content"}
                    or not isinstance(item["path"], str) or not isinstance(item["content"], str)
                    for item in initial):
                raise ProcedureError("initial_files must be path/content records")
            for item in initial:
                fileauth.write_text(arena, item["path"], item["content"])
            result = execute(root, rb, case["inputs"], workspace=arena)
            checks = operators.bind(suite["checks"], case["inputs"])
            accepted = result["ok"] and all(operators.observe(arena, check) for check in checks)
            receipt = {"id": identity, "name": name, "runbook_hash": digest(rb),
                       "suite_hash": sealed["hash"], "task_id": case["id"],
                       "input_hash": digest(case["inputs"]), "environment": digest(arena),
                       "parameter_hashes": {k: digest(v) for k, v in case["inputs"].items()},
                       "family": suite["family"], "edge": bool(case.get("edge")),
                       "accepted": bool(accepted), "execution": result}
        _update(root, lambda state: state["receipts"].setdefault(identity, receipt))
        runbook.record(root, name, bool(accepted), accepted=bool(accepted), evidence=identity,
                       why="fresh sealed procedural evaluation")
        results.append(receipt)
    return {"accepted": len(results) == len(suite["cases"]) and all(r["accepted"] for r in results),
            "results": results, "status": runbook.status(root, name)}


# --------------------------------------------------------------- owner CLI
# WITHOUT THIS THE COMPILER CANNOT BE REACHED. Every function above was
# callable only from a test: the loop's capture hooks are guarded by
# `active_trajectory`, and nothing outside tests/ could open one, because
# opening one needs a SEALED JUDGE and only the owner may seal. A learning
# mechanism with no way in is not a mechanism, it is a plan — which is the
# exact defect this repository keeps finding in its own code.
#
# Sealing is owner work by construction (`_seal` refuses any other actor), so
# these are operator commands, never model tools.
#
#   python procedure.py seal-judge  --root R --id j1 --checks '[{...}]'
#   python procedure.py seal-suite  --root R --id s1 --suite suite.json
#   python procedure.py trajectories --root R --family invoices
#   python procedure.py compile     --root R --name proc-x --family invoices
#   python procedure.py evaluate    --root R --name proc-x --suite s1

def main():
    import argparse
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("seal-judge", help="freeze a mechanical judge (owner)")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True, dest="identity")
    p.add_argument("--checks", required=True,
                   help='JSON list of predicates, e.g. '
                        '\'[{"predicate":"file_exists","path":"out/x.txt"}]\'')

    p = sub.add_parser("seal-suite", help="freeze fresh evaluation cases (owner)")
    p.add_argument("--root", required=True)
    p.add_argument("--id", required=True, dest="identity")
    p.add_argument("--suite", required=True, help="path to the suite JSON file")

    p = sub.add_parser("trajectories", help="accepted trajectories in a family")
    p.add_argument("--root", required=True)
    p.add_argument("--family", required=True)

    p = sub.add_parser("compile", help="induce a candidate procedure")
    p.add_argument("--root", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--family", required=True)
    p.add_argument("--trigger", action="append", default=[],
                   help="goal words that summon it (default: the family name)")

    p = sub.add_parser("evaluate", help="run a sealed suite against a procedure")
    p.add_argument("--root", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--suite", required=True, dest="suite_id")

    a = ap.parse_args()
    try:
        if a.cmd == "seal-judge":
            h = seal_judge(a.root, a.identity, json.loads(a.checks))
            print(f"sealed judge {a.identity} ({h[:12]}…) — a task may now cite "
                  f"it: loop.py add --judge-id {a.identity} --inputs '{{...}}'")
        elif a.cmd == "seal-suite":
            with open(a.suite, encoding="utf-8") as f:
                suite = json.load(f)
            h = seal_suite(a.root, a.identity, suite)
            print(f"sealed suite {a.identity} ({h[:12]}…), "
                  f"{len(suite.get('cases') or [])} fresh case(s)")
        elif a.cmd == "trajectories":
            rows = accepted_trajectories(a.root, a.family)
            for r in rows:
                print(f"{r['task_id']}  judge={r['judge_id']}  "
                      f"inputs={r['input_hash'][:12]}…")
            inputs = len({r["input_hash"] for r in rows})
            judges = len({r["judge_id"] for r in rows})
            print(f"\n{len(rows)} accepted, {inputs} distinct input(s), "
                  f"{judges} distinct judge(s) — induction needs 2 of each")
        elif a.cmd == "compile":
            rows = accepted_trajectories(a.root, a.family)
            rb = compile(a.root, a.name, [r["task_id"] for r in rows],
                         a.trigger or [a.family])
            print(f"compiled {a.name}: {len(rb['steps'])} step(s), "
                  f"inputs={rb['operator']['inputs']}\n"
                  f"It is a CANDIDATE until a sealed suite says otherwise: "
                  f"python procedure.py evaluate --root {a.root} "
                  f"--name {a.name} --suite <id>")
        elif a.cmd == "evaluate":
            out = evaluate(a.root, a.name, a.suite_id)
            print(f"{a.name}: accepted={out['accepted']} "
                  f"status={out['status']} "
                  f"({len(out['results'])} case(s))")
    except (ProcedureError, OSError, ValueError) as e:
        raise SystemExit(f"REFUSED: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
