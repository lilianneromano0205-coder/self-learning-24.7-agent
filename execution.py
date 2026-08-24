#!/usr/bin/env python3
"""EXECUTION AUTHORITY — the one gateway every process must pass through.

Manual §19: *"Execution Authority — every caller must use it for any
process/shell/tool execution; mandatory controls: typed operation; role
capability; policy; sandbox; scrubbed env; approval; trace; timeout."*
Manual §25.3: *"Create one canonical Execution Authority; no alternate
shell/process execution path may exist."*

The audit's central finding was that controls guarded the path their author
was thinking about while other paths reached the same operation untouched:
`run_command` was screened and sandboxed, and five other `shell=True` sites
were not. Adding a sixth check to a sixth site would repeat the mistake. So
execution is now a TYPED operation, and the type decides the controls:

    OP                CONTROLS                                    ORIGIN
    model_command     policy + sandbox + scrub + approval + trace  the model
    gate              policy + sandbox + scrub + trace             the model
    capability_probe  policy + sandbox + scrub + trace             the workspace
    converter         argv only, no shell, timeout + trace         the platform
    platform_spawn    argv only, no shell, trace                   the platform

The distinction that matters is not "is this dangerous" but **who wrote the
string**. Anything a model influenced is `model_command` or `gate` and gets
the full stack. Anything the platform builds itself from an argv list cannot
carry shell syntax at all, so it gets containment appropriate to that.

`audit_sources()` makes the invariant checkable rather than asserted: it
scans the repository for raw subprocess use and reports every site that is
not either routed through here or on the declared platform allowlist. The
test suite fails when a new bypass appears — which is the only way a rule
like this survives contact with future features.
"""

import io
import json
import os
import re
import subprocess
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- operations

MODEL_AUTHORED = ("model_command", "gate", "capability_probe")

OPERATIONS = {
    "model_command": {
        "what": "a shell command the MODEL wrote (the run_command tool)",
        "shell": True, "policy": True, "sandbox": True, "approval": True,
    },
    "gate": {
        "what": "a verification command the MODEL wrote (done_check, a spec "
                "CHECK: line, a goal milestone check)",
        "shell": True, "policy": True, "sandbox": True, "approval": False,
    },
    "capability_probe": {
        # The probe string comes from a toolbox.json inside the expert root,
        # which is a file the agent can write. "Platform-authored" was the
        # wrong classification: anything read from the workspace is
        # model-influenceable, so it gets the model-authored stack.
        "what": "a readiness probe for a declared tool, read from a "
                "toolbox.json inside the workspace (model-influenceable)",
        "shell": True, "policy": True, "sandbox": True, "approval": False,
    },
    "converter": {
        "what": "a platform-authored call to an external converter "
                "(pandoc, ffmpeg, yt-dlp) with an argument vector",
        "shell": False, "policy": False, "sandbox": False, "approval": False,
    },
    "platform_spawn": {
        "what": "the platform launching one of its own entry points",
        "shell": False, "policy": False, "sandbox": False, "approval": False,
    },
}


class Refused(Exception):
    """A control said no. The message is what the caller shows the model."""


# ---------------------------------------------------------------- the gateway

def run(op, command, root, cfg=None, role="default", task=None, timeout=300,
        env=None, reason=""):
    """Execute `command` as operation `op`. Returns (rc, out, err).

    `command` is a STRING for shell operations and a LIST for argv ones —
    the type is checked against the operation, so a caller cannot smuggle a
    shell string into an argv-only operation by accident.
    """
    spec = OPERATIONS.get(op)
    if spec is None:
        raise Refused(f"unknown execution operation {op!r}; the catalogue is: "
                      f"{', '.join(sorted(OPERATIONS))}")
    cfg = cfg or {}
    started = time.time()

    if spec["shell"]:
        if not isinstance(command, str):
            raise Refused(f"operation {op!r} takes a command string")
    else:
        if isinstance(command, str):
            raise Refused(
                f"operation {op!r} takes an ARGUMENT VECTOR, not a string. "
                f"A platform-authored call has no reason to invoke a shell, "
                f"and passing a string here would reintroduce shell syntax "
                f"into a path that is meant to be free of it.")

    # ---- policy: what the model may run at all
    if spec["policy"]:
        try:
            import policy
            verdict = policy.check(command, role, cfg.get("agent", {}))
        except ImportError:
            verdict = None
        if verdict:
            _trace(root, op, command, role, task, refused=verdict)
            raise Refused(verdict)

    # ---- approval: the control this module DECLARED and did not enforce
    # OPERATIONS has carried "approval": True for model_command since it was
    # written, describe() exported the flag, and the docstring's control table
    # promised it — while nothing in this module ever imported `approvals`.
    # The invariant that enumerates this catalogue checked `policy` and
    # `sandbox` and skipped the one flag nobody implemented.
    #
    # Non-blocking, matching mcp.guarded_call exactly: a 24/7 loop must never
    # sleep on a human. The command is refused with an approval id and an
    # instruction to ask_human; when the owner grants it and the task retries,
    # it runs once.
    if spec.get("approval"):
        try:
            import policy as _pol
            needs, why = _pol.review(command, cfg.get("agent", {}))
        except ImportError:                  # pragma: no cover — defensive
            needs, why = False, ""
        if needs:
            import approvals
            key = approvals.approval_id(f"cmd:{root}:{command}")
            st = approvals.status_of(root, key)
            if st == "denied":
                _trace(root, op, command, role, task,
                       refused=f"owner denied: {why}")
                raise Refused(
                    f"DENIED by the owner: this command ({why}) will not run. "
                    f"Do not retry it; choose another route or finish with "
                    f"what you have.")
            if st != "granted":
                rec = approvals.request(
                    root, key, server="execution", tool=op,
                    arguments={"command": command if isinstance(command, str)
                               else list(command)},
                    reason=why, task_id=str((task or {}).get("id", "-")))
                _trace(root, op, command, role, task,
                       refused=f"approval required ({rec['id']}): {why}")
                raise Refused(
                    f"APPROVAL REQUIRED ({rec['id']}): this command {why}, so "
                    f"the owner must approve it first. Do NOT retry it. Call "
                    f"ask_human now with exactly: \"Approve {rec['id']}: "
                    f"{str(command)[:160]} ?\" — the owner decides in the "
                    f"panel, and when this task is retried it runs once.")

    # ---- bundled third-party skill scripts stay disabled until promoted
    if op in MODEL_AUTHORED:
        try:
            import skills as _sk
            guard = _sk.script_guard(root, command)
        except Exception:
            guard = None
        if guard:
            _trace(root, op, command, role, task, refused=guard)
            raise Refused(guard)

    # ---- execute, contained according to the operation
    try:
        if spec["sandbox"] and spec["shell"]:
            import sandbox
            rc, out, err = sandbox.run(command, root, env=env,
                                       timeout=timeout, cfg=cfg)
        elif spec["sandbox"]:
            import sandbox
            scrubbed, _dropped = sandbox.scrub_env(
                {**os.environ, **(env or {})}, cfg, " ".join(map(str, command)))
            r = subprocess.run(command, cwd=root, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, env=scrubbed)
            rc, out, err = r.returncode, r.stdout, r.stderr
        else:
            r = subprocess.run(command, cwd=root, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=timeout,
                               env={**os.environ, **(env or {})})
            rc, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", f"timed out after {timeout}s"
    except (OSError, ValueError) as e:
        rc, out, err = 127, "", f"could not run: {e}"

    _trace(root, op, command, role, task, rc=rc,
           ms=int((time.time() - started) * 1000), reason=reason)
    return rc, out, err


def _trace(root, op, command, role, task, rc=None, ms=0, refused="", reason=""):
    """Every execution leaves a line, refused or not. An execution nobody can
    see afterwards is an execution nobody governs."""
    try:
        d = os.path.join(root, "logs")
        os.makedirs(d, exist_ok=True)
        cmd = command if isinstance(command, str) else " ".join(map(str, command))
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "op": op,
               "role": role, "task": task, "cmd": cmd[:400], "ms": ms}
        if refused:
            rec["refused"] = refused[:300]
        else:
            rec["rc"] = rc
        if reason:
            rec["why"] = reason[:200]
        with open(os.path.join(d, "execution.jsonl"), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass                      # tracing must never break the work


def history(root, limit=200):
    out = []
    try:
        with open(os.path.join(root, "logs", "execution.jsonl"),
                  encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out[-limit:]


# ------------------------------------------------------- the invariant audit
#
# Manual §25.11: "Convert tests from primary-path examples into invariant
# tests that enumerate every reachable path to protected operations."
#
# Every raw subprocess call site in the repository is either routed through
# this module or declared here with the reason it does not need to be. A new
# call site that is neither shows up as a violation, and the test suite fails.

ALLOWED_RAW = {
    "sandbox.py": "IS the execution backend this authority delegates to",
    "execution.py": "IS the authority",
    "bootstrap.py": "one-command installer: launches ui.py/loop.py by argv "
                    "before an expert (and therefore a root) exists",
    "demo.py": "self-contained demo runner; builds its own world and calls "
               "loop.py/verify.py/memcheck.py by argv",
    "evidence.py": "runs the TEST SUITE by argv to harvest its own evidence",
    "mutate_check.py": "the mutation harness: deliberately breaks a module, "
                       "runs one test by argv, and reverts. A developer tool "
                       "that never runs in production and never sees model "
                       "input — but it is declared here rather than exempted "
                       "silently, because an audit with an undeclared "
                       "exception is an audit with a hole",
    "ui.py": "control plane: spawns loop.py/goal.py/team.py by argv on the "
             "owner's explicit action; no model input reaches the argv",
    "commons.py": "peer consultation drives a loop by argv",
    "consult.py": "--drive runs the expert's own loop by argv",
    "quick.py": "--drive runs the new expert's loop by argv",
    "team.py": "drives each specialist's loop by argv",
    "goal.py": "drives the expert's loop by argv (its MILESTONE CHECKS go "
               "through the authority as op='gate')",
    "variants.py": "trial arms drive the loop by argv with an env selector",
    "doctor.py": "health check probes the interpreter by argv",
    "mcp.py": "starts a stdio MCP server process by argv (governed by "
              "policy/approvals inside mcp.py itself)",
    "benchmark.py": "ARM A deliberately runs a bare model with no harness; "
                    "its CHECK commands go through the authority as op='gate'",
}

_SUBPROC_RE = re.compile(r"subprocess\.(run|Popen|call|check_output)\(|os\.system\(")


def audit_sources(tree=HOME):
    """-> {"violations": [...], "checked": n, "allowed": [...]}.

    A violation is a module that calls subprocess directly and is neither the
    authority, the sandbox, nor on the declared allowlist above.
    """
    violations, checked = [], 0
    for fn in sorted(os.listdir(tree)):
        if not fn.endswith(".py"):
            continue
        checked += 1
        try:
            src = io.open(os.path.join(tree, fn), encoding="utf-8",
                          errors="replace").read()
        except OSError:
            continue
        hits = _SUBPROC_RE.findall(src)
        if not hits:
            continue
        if fn in ALLOWED_RAW:
            continue
        for m in _SUBPROC_RE.finditer(src):
            line = src.count("\n", 0, m.start()) + 1
            violations.append({
                "file": fn, "line": line, "call": m.group(0).rstrip("("),
                "why": "raw process execution outside the Execution Authority. "
                       "Route it through execution.run(op=...), or declare it "
                       "in execution.ALLOWED_RAW with the reason it is safe."})
    return {"checked": checked, "violations": violations,
            "allowed": sorted(ALLOWED_RAW)}


def describe():
    return [{"op": k, "what": v["what"],
             "shell": v["shell"], "policy": v["policy"],
             "sandbox": v["sandbox"], "approval": v["approval"],
             "model_authored": k in MODEL_AUTHORED}
            for k, v in OPERATIONS.items()]


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audit", action="store_true",
                    help="find raw subprocess use outside this authority")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.audit:
        rep = audit_sources()
        if a.json:
            print(json.dumps(rep, indent=1))
        else:
            print(f"EXECUTION AUTHORITY AUDIT — {rep['checked']} module(s)")
            for v in rep["violations"]:
                print(f"  VIOLATION {v['file']}:{v['line']} {v['call']}")
            print(f"  {len(rep['violations'])} violation(s); "
                  f"{len(rep['allowed'])} module(s) declared platform-internal")
        raise SystemExit(1 if rep["violations"] else 0)
    for row in describe():
        flags = [k for k in ("policy", "sandbox", "approval") if row[k]]
        print(f"{row['op']:<18} {'shell' if row['shell'] else 'argv ':<6} "
              f"{'+'.join(flags) or 'trace only':<24} {row['what'][:60]}")


if __name__ == "__main__":
    main()
