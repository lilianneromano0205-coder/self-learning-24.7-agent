#!/usr/bin/env python3
"""THE PROOF SYSTEM — "finished" is a derived status, never a claim.

Manual §23: proof levels 0–5, a required Proof Pack per subsystem change, and
the rule that decides everything else here:

    "No engineer is allowed to change a status to Finished manually.
     The status is derived from evidence."
    "A developer cannot set proof status manually; the UI reads generated
     proof manifests. Any regression or expired live check downgrades the
     badge automatically."

So a feature does not carry a status field. It carries a CONTRACT — what the
user can now do, the invariants that must hold, the tests that hold them, and
the commands that reproduce them — and the level is computed from evidence
that exists on disk right now:

    0 SPEC                requirements written, no implementation
    1 IMPLEMENTED         the code path exists
    2 OFFLINE VERIFIED    its acceptance tests pass in controlled fixtures
    3 LIVE VERIFIED       the real external dependency path was exercised
    4 STRESS VERIFIED     alternate paths, failure, restart, concurrency,
                          security and budget were tested
    5 PRODUCTION PROVEN   sustained real workload met declared thresholds

Two rules keep this honest, and they are the whole point:

  * evidence EXPIRES. A live check from six months ago proves the path worked
    six months ago. `live_max_age_days` downgrades it automatically, so a
    badge cannot rot into a lie by sitting still.
  * evidence is BOUND TO CODE. Each observation records the hash of the files
    it covers. Change the code and the observation no longer describes it, so
    the level drops until the evidence is regenerated. This is what makes a
    regression downgrade a badge without anyone remembering to do it.

`REGISTRY` is the declared contract for every subsystem. `evaluate()` reads
the ledger and returns the level each one has EARNED. Nothing writes a level.
"""

import hashlib
import io
import json
import os
import time
import math

HOME = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join("proof", "observations.jsonl")
CRLF = bytes([13, 10])
LF = bytes([10])

SPEC, IMPLEMENTED, OFFLINE, LIVE, STRESS, PRODUCTION = 0, 1, 2, 3, 4, 5

LEVELS = {
    SPEC:        ("SPEC", "gray", "Requirements written; no implementation."),
    IMPLEMENTED: ("IMPLEMENTED", "yellow", "Code path exists; not proven."),
    OFFLINE:     ("OFFLINE VERIFIED", "blue",
                  "Controlled acceptance tests pass."),
    LIVE:        ("LIVE VERIFIED", "teal",
                  "Real external dependency path works."),
    STRESS:      ("ADVERSARIAL/STRESS VERIFIED", "green",
                  "Alternate paths, failure, restart, concurrency and "
                  "security tests pass."),
    PRODUCTION:  ("PRODUCTION PROVEN", "darkgreen",
                  "Sustained real workload meets declared thresholds."),
}

# How long each kind of evidence stays meaningful. Offline tests are pinned to
# a code hash instead of a clock, so they do not expire by time; anything that
# touched the outside world does, because the outside world moves.
MAX_AGE_DAYS = {"live": 30, "stress": 90, "production": 30}
MAX_AGE_DAYS.update({"benchmark": 90, "repeated": 90})
INTELLIGENCE_LEVELS = {
    0: LEVELS[SPEC], 1: LEVELS[IMPLEMENTED], 2: LEVELS[OFFLINE],
    3: ("EXTERNAL BENCHMARK VERIFIED", "teal", "External held-out benchmark evidence."),
    4: ("REPEATED EVALUATION VERIFIED", "green", "Repeated paired evaluation clears a preregistered statistical bar."),
    5: ("LIVE PROVIDER VERIFIED", "green", "Real provider evaluation under the same experimental protocol."),
    6: ("PRODUCTION WORKLOAD VERIFIED", "darkgreen", "Sustained measured production workload."),
}


# ------------------------------------------------------------- the registry
#
# One entry per user-visible capability. `code` is what the evidence is bound
# to: touch those files and the offline evidence stops describing them.

REGISTRY = {
    "harness-loop": {
        "capability": "An expert runs gated tasks: compiled context, the "
                      "declared tool surface (loop.TOOL_DEFS — counting it "
                      "here went stale once already), a definition-of-done "
                      "that must pass, brakes, retries and a durable trace.",
        "invariants": ["a task is claimed exactly once",
                       "finish_task is refused until the gate passes",
                       "every step is traced with its cost"],
        "code": ["loop.py", "harness.py", "context.py", "memrouter.py"],
        "tests": ["test_harness.py", "test_layers.py", "test_e2e.py",
                  "test_context.py", "test_stop.py"],
        "stress_tests": ["test_chaos.py", "test_e2e_crash.py", "test_faults.py",
                         "test_reliability.py"],
        "live": "a real provider answers a real task",
    },
    "execution-authority": {
        "capability": "Every process the platform runs passes one typed "
                      "gateway, so a new feature cannot quietly add an "
                      "unguarded execution path.",
        "invariants": ["no raw subprocess use outside the authority",
                       "model-authored commands get policy + sandbox + scrub",
                       "argv operations cannot carry shell syntax"],
        "code": ["execution.py", "policy.py", "sandbox.py"],
        "tests": ["test_hardening.py", "test_secrets.py", "test_sandbox.py",
                  "test_invariants.py"],
        "stress_tests": ["test_invariants.py"],
        "live": "docker or a hosted sandbox backend executes a real command",
    },
    "file-authority": {
        # The claim used to read "…or rewrite the state that defines the
        # agent's permissions", full stop — which was true of the FILE TOOL
        # and false of the platform, because a shell-capable role reached the
        # same files through run_command. The capability now says what this
        # module actually proves, and the control plane, which spans two
        # authorities, has its own entry below.
        "capability": "Model-influenced PATHS cannot escape the workspace, "
                      "and the agent's file tools cannot write control, "
                      "runtime or credential state.",
        "invariants": ["traversal and symlink escapes refused",
                       "control and runtime zones are not agent-writable",
                       "credential files are never readable"],
        "code": ["fileauth.py", "credentials.py"],
        "tests": ["test_hardening.py", "test_paths.py", "test_guardrails.py",
                  "test_invariants.py"],
        "stress_tests": ["test_invariants.py", "test_material.py"],
        "live": None,
    },
    # NOT "control-plane": that key was already taken, 90 lines below, by the
    # PANEL's capability. A dict literal keeps the last of two identical keys,
    # so naming this one that deleted it at runtime while both read fine in
    # the source — the registry would have shown one green panel capability
    # and no worker-authority capability at all. Found by an audit sweep, not
    # by the suite; check_registry_keys_are_unique in test_invariants.py now
    # parses this file's AST so a third collision cannot be silent either.
    "worker-authority": {
        "capability": "A worker cannot durably change its own authority — "
                      "not through the file tool, and not by running a "
                      "program that does the same thing.",
        "invariants": ["the sealed set is derived from fileauth's zones, "
                       "never listed twice",
                       "a model-authored command that edits control state is "
                       "reverted and reported as failed",
                       "the docker backend mounts control state read-only",
                       "owner-level CLIs refuse to run inside an agent task"],
        # Deliberately spanning BOTH authorities plus the loop, because that
        # is where the defect lived: fileauth was right about the tool,
        # policy was right about the string, and the invariant that spans them
        # was owned by nobody.
        "code": ["controlplane.py", "fileauth.py", "execution.py",
                 "sandbox.py", "policy.py", "loop.py"],
        "tests": ["test_controlplane.py", "test_invariants.py",
                  "test_hardening.py", "test_guardrails.py"],
        "stress_tests": ["test_controlplane.py"],
        "live": "a docker container refuses a write to /work/settings.toml",
    },
    "credential-authority": {
        "capability": "One credential model: what the runtime resolves is what "
                      "backup, packaging and health checks all agree is secret.",
        "invariants": ["api_key_file and inline api_key are secrets everywhere",
                       "no credential is packaged or backed up in the clear",
                       "a working provider is never reported unfunded"],
        "code": ["credentials.py", "backup.py", "package.py", "providers.py"],
        "tests": ["test_hardening.py", "test_backup.py", "test_secrets.py"],
        "stress_tests": ["test_invariants.py"],
        "live": "a real provider key resolves and authenticates",
    },
    "model-gateway": {
        "capability": "Every provider call is metered and attributed per call, "
                      "so cost ceilings cannot be bypassed by a code path.",
        "invariants": ["compaction, replay and benchmark calls are metered",
                       "attribution is per call, not per task",
                       "the daily breaker sees every call",
                       "every function that reaches a provider meters it, "
                       "or is declared free with a reason"],
        # THE BOUNDARY MUST CONTAIN THE CALL SITES. It listed modelgateway.py
        # and modelrouter.py — neither of which calls a provider — so the
        # capability could stay "verified" while unmetered spending was added
        # anywhere else. It was: ingest.py's transcription and vision rails
        # billed real money outside every ledger, and loop._probe billed a
        # live token per role, all with this proof green. A proof hash that
        # does not cover the code that can break the invariant proves the
        # wrong thing.
        "code": ["modelgateway.py", "modelrouter.py", "loop.py", "ingest.py",
                 "providers.py"],
        "tests": ["test_guardrails.py", "test_modelrouter.py",
                  "test_invariants.py"],
        "stress_tests": ["test_invariants.py"],
        "live": "a real provider call is metered end to end",
    },
    "effect-authority": {
        "capability": "An external side effect is recorded before it happens, "
                      "so a crash cannot cause a silent duplicate.",
        "invariants": ["intent is written before the call",
                       "an unresolved effect is never repeated automatically",
                       "one effect reads as one ledger entry"],
        "code": ["effects.py", "mcp.py", "approvals.py"],
        "tests": ["test_effects.py", "test_approvals.py", "test_hardening.py"],
        "stress_tests": ["test_chaos.py"],
        "live": "a real MCP server performs a real effect",
    },
    "memory-institution": {
        "capability": "What an expert knows is cited, ordered by source "
                      "authority, and checkable — not a pile of text.",
        "invariants": ["every claim carries a resolvable citation",
                       "a contested point cannot become a standard",
                       "an unknown source cannot rank itself"],
        # memcheck.py resolves the citations; "every claim carries a
        # resolvable citation" is its verdict, not this list's.
        "code": ["memory.py", "sources.py", "conflicts.py", "standards.py",
                 "curriculum.py", "recall.py", "premise.py", "memcheck.py"],
        "tests": ["test_memory.py", "test_conflicts.py", "test_curriculum.py",
                  "test_memory_kinds.py", "test_recall.py"],
        "stress_tests": ["test_faults.py"],
        "live": None,
    },
    "skills-provenance": {
        "capability": "A procedure is trusted because the owner recorded that "
                      "decision, never because the file says so.",
        "invariants": ["a skill file cannot self-declare trust",
                       "community scripts stay disabled until promoted",
                       "earned status requires a matched held-out ablation "
                       "pinned to the exact skill bytes"],
        # fileauth.py is in this boundary because CONTROL_PATHS is what
        # actually enforces "trust comes from the graph, which only the owner
        # writes" — delete that one line and an agent marks its own skill
        # proven while this badge stays green. The same reasoning that moved
        # loop.py and ingest.py into the model-gateway boundary.
        "code": ["skills.py", "routines.py", "fileauth.py"],
        "tests": ["test_skillgraph.py", "test_skillmd.py", "test_hardening.py"],
        "stress_tests": ["test_invariants.py"],
        "live": None,
    },
    "control-plane": {
        "capability": "The owner drives the whole fleet from one page without "
                      "exposing it to any web page they happen to visit.",
        "invariants": ["cross-origin writes are refused",
                       "the network names a gate, never a shell command",
                       "destructive UI actions match CLI semantics"],
        "code": ["ui.py", "ui.html", "gates.py"],
        "tests": ["test_ui.py", "test_csrf.py", "test_frontend.py",
                  "test_panel_v2.py"],
        "stress_tests": ["test_csrf.py", "test_remote.py"],
        "live": "the panel drives a real expert against a real provider",
    },
    "mission-engine": {
        "capability": "A mission keeps its objective across context resets, "
                      "restarts and model swaps, and every action traces back "
                      "to a success criterion.",
        "invariants": ["the mission contract lives outside the transcript",
                       "every action references an unresolved criterion",
                       "completed evidence is monotonic unless invalidated"],
        "code": ["mission.py", "goal.py"],
        "tests": ["test_mission.py"],
        "stress_tests": ["test_mission.py"],
        "live": "a real long-horizon mission completes with evidence",
    },
    "workers": {
        "capability": "Work runs on the cheapest safe computer that can do it, "
                      "and the user can see why that one was chosen.",
        "invariants": ["a worker advertises capability and trust zone",
                       "an unavailable backend fails closed",
                       "selection is explainable"],
        "code": ["workers.py", "sandbox.py"],
        "tests": ["test_workers.py"],
        "stress_tests": ["test_sandbox.py"],
        "live": "a docker or cloud worker executes real work",
    },
    "capability-acquisition": {
        "capability": "An agent can acquire a capability it lacks without "
                      "gaining uncontrolled authority.",
        "invariants": ["no install on the host or control plane",
                       "exact version and provenance recorded",
                       "a capability test must pass before registration"],
        # sandbox.py: acquire.install REFUSES without a containment
        # boundary, so the module that decides whether one exists is inside
        # the trusted computing base of this capability.
        "code": ["acquire.py", "toolbox.py", "sandbox.py"],
        "tests": ["test_acquire.py"],
        "stress_tests": ["test_acquire.py"],
        "live": "a real package installs in a disposable worker and passes "
                "its capability test",
    },
    "proof-system": {
        "capability": "Every capability's status is derived from evidence, so "
                      "nobody can mark a feature finished by hand.",
        "invariants": ["no level is stored, only computed",
                       "evidence expires and downgrades automatically",
                       "changed code invalidates its own offline evidence"],
        "code": ["proof.py"],
        "tests": ["test_proof.py"],
        "stress_tests": ["test_proof.py"],
        "live": None,
    },
    "training-lab": {
        "capability": "Verified trajectories can be exported and a candidate "
                      "policy promoted only through an isolated, benchmarked, "
                      "reversible gate.",
        "invariants": ["production state is immutable during a run",
                       "train and eval sets are separated",
                       "promotion requires a passing eval and a rollback path"],
        "code": ["training.py"],
        "tests": ["test_training.py"],
        "stress_tests": [],
        "live": "a real training run produces a promotable checkpoint",
    },
    "organization": {
        "capability": "Several people share a fleet with roles, budgets and "
                      "an audit trail that names who did what.",
        "invariants": ["every mutation is attributable to a user",
                       "a role cannot exceed its granted permissions",
                       "secrets are organization-scoped"],
        "code": ["org.py"],
        "tests": ["test_org.py"],
        "stress_tests": [],
        "live": "two real users operate the same fleet with distinct rights",
    },
}


for _name in ("harness-loop", "memory-institution", "skills-provenance", "mission-engine", "training-lab"):
    REGISTRY[_name]["intelligence"] = True
REGISTRY["training-lab"]["code"] = ["training.py", "trainer_integration.py", "learning_authority.py"]
REGISTRY["training-lab"]["tests"] = ["test_training.py", "test_advanced_learning.py"]
for _name, _code, _description in (
    # The flagship capability of the procedural-learning release: verified
    # work becomes an executable procedure, and a matching task then runs it
    # with no model call. It is registered here so its evidence LEVEL is
    # tracked like every other capability — and so editing its code drops it
    # out of OFFLINE VERIFIED until the suite is re-run, which is the whole
    # point of the proof system.
    ("procedural-learning",
     ["procedure.py", "operators.py", "runbook.py", "tabular.py",
      "tabletypes.py", "dbstate.py", "verifier.py", "capability_graph.py"],
     "Independently judged trajectories compile into an executable procedure "
     "that a later matching task runs deterministically, with the task's own "
     "gate still deciding acceptance."),
    ("variant-learning", ["variants.py", "learning_authority.py"], "Prompt variants earn owner promotion through independent batteries."),
    ("experimental-adaptation", ["adaptation.py"], "Opt-in memory adaptation distinguishes local logits from closed API approximation."),
):
    REGISTRY[_name] = {"capability": _description, "code": _code,
                      "intelligence": True,
                      "tests": (["test_procedural_learning.py",
                                 "test_loop_learning_controls.py",
                                 "test_capability_graph.py",
                                 "test_tabular.py", "test_use_cases.py",
                                 "test_operator_runtime.py",
                                 "test_verifier_factory.py",
                                 "test_procedure_v2.py"]
                                if _name == "procedural-learning"
                                else ["test_advanced_learning.py"]),
                      "invariants": ["offline tests never establish model lift", "judges remain independent"],
                      "stress_tests": [], "live": "preregistered real-provider paired evaluation"}

# ---------------------------------------------------------------- evidence

def _path(root):
    return os.path.join(root, LEDGER)


def code_hash(files, tree=HOME):
    """One hash over the files a capability is built from. Evidence records
    this, so changing the code invalidates the evidence that described it.

    Line endings are NORMALISED before hashing. Git's autocrlf rewrites them
    on checkout, and a badge that downgraded because someone cloned the repo
    on Windows would be crying wolf — the one failure mode that teaches people
    to ignore a status light. Real content changes still change the hash.
    """
    h = hashlib.sha256()
    for rel in sorted(files):
        p = os.path.join(tree, rel)
        try:
            with io.open(p, "rb") as stream:
                body = stream.read().replace(CRLF, LF)
            h.update(rel.encode("utf-8"))
            h.update(body)
        except OSError:
            h.update(b"<missing>")
    return h.hexdigest()[:16]


def observe(root, feature, kind, ok, detail="", command="", tree=HOME,
            artifacts=None, metrics=None):
    """Record ONE observation. `kind` is offline | live | stress | production.

    This is the only way evidence enters the system, and it records what the
    code looked like at the time — which is what makes a later regression
    downgrade the badge without anyone deciding to.
    """
    import controlplane
    controlplane.owner_only("record proof evidence")
    if feature not in REGISTRY or kind not in {"offline", "live", "stress", "production", "benchmark", "repeated"}:
        raise ValueError("unknown proof feature or evidence kind")
    entry = REGISTRY[feature]
    rec = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "feature": feature, "kind": kind, "ok": bool(ok),
        "detail": str(detail)[:500], "command": str(command)[:300],
        "code_hash": code_hash(entry.get("code", []), tree),
        "artifacts": list(artifacts or []),
        "metrics": metrics or {},
        "artifact_hashes": _artifact_hashes(artifacts or []),
    }
    try:
        os.makedirs(os.path.dirname(_path(root)), exist_ok=True)
        with open(_path(root), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return rec


def observations(root, feature=None):
    out = []
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if feature and r.get("feature") != feature:
                    continue
                out.append(r)
    except OSError:
        pass
    return out


def _age_days(at):
    try:
        t = time.mktime(time.strptime(at[:19], "%Y-%m-%dT%H:%M:%S"))
        return (time.time() - t) / 86400.0
    except (ValueError, TypeError):
        return 1e9


def _latest(rows, kind, current_hash, max_age=None):
    """The newest PASSING observation of this kind that still describes the
    code as it is now, and has not expired. Returns None when the evidence
    no longer supports a claim — which is how a badge goes down by itself."""
    best = None
    for r in rows:
        if r.get("kind") != kind:
            continue
        if r.get("code_hash") != current_hash:
            continue                     # the code moved; this no longer describes it
        if max_age is not None and _age_days(r.get("at", "")) > max_age:
            continue                     # true once, not evidence now
        if best is None or r.get("at", "") >= best.get("at", ""):
            best = r
    return best if best and best.get("ok") is True else None


def _artifact_hashes(paths):
    out = {}
    for path in paths:
        if not isinstance(path, str):
            continue
        try:
            with open(path, "rb") as stream:
                out[os.path.abspath(path)] = hashlib.sha256(stream.read()).hexdigest()
        except OSError:
            continue
    return out


def _intelligence_evidence(row, kind):
    if not row:
        return False
    metrics = row.get("metrics", {})
    pins = row.get("artifact_hashes", {})
    if not pins or _artifact_hashes(list(pins)) != pins or not metrics.get("protocol_id"):
        return False
    if metrics.get("simulated") is not False or metrics.get("holdout_sealed") is not True:
        return False
    if kind == "benchmark":
        return bool(metrics.get("external_benchmark") and metrics.get("task_count", 0) >= 20)
    if kind == "repeated":
        return paired_evidence(metrics).get("meaningful", False)
    if kind == "live":
        return bool(metrics.get("provider") and metrics.get("model_revision") and metrics.get("provider_calls", 0) > 0)
    if kind == "production":
        return (metrics.get("days", 0) >= 7 and metrics.get("verified_tasks", 0) >= 100
                and metrics.get("thresholds_preregistered") is True
                and metrics.get("thresholds_met") is True)
    return False


def paired_evidence(metrics):
    """Exact sign test across distinct tasks, averaging repeated seeds per task.

    Repeated measurements of one task are not independent task evidence.
    This conservative acceptance policy is not a universal power guarantee.
    """
    rows = metrics.get("paired_results", [])
    grouped, identities, seeds = {}, set(), set()
    try:
        for row in rows:
            identity = (row["task"], row["seed"])
            if identity in identities or type(row["base"]) is not bool or type(row["candidate"]) is not bool:
                return {"meaningful": False}
            identities.add(identity); seeds.add(row["seed"])
            grouped.setdefault(row["task"], []).append(int(row["candidate"]) - int(row["base"]))
        if len(seeds) < 3 or len(grouped) < 20 or any(len(values) != len(seeds) for values in grouped.values()):
            return {"meaningful": False}
        wins = sum(sum(v) > 0 for v in grouped.values())
        losses = sum(sum(v) < 0 for v in grouped.values())
        n = wins + losses
        p = sum(math.comb(n, i) for i in range(wins, n + 1)) / (2 ** n) if n else 1
        alpha = metrics.get("alpha", 0.05)
        meaningful = (type(alpha) in (int, float) and math.isfinite(alpha)
                      and 0 < alpha <= 0.05 and wins > losses and p <= alpha
                      and metrics.get("preregistered") is True)
        return {"meaningful": meaningful, "p_value": p, "independent_tasks": len(grouped),
                "seeds": len(seeds), "wins": wins, "losses": losses}
    except (KeyError, TypeError, ValueError):
        return {"meaningful": False}


def evaluate(root, feature, tree=HOME):
    """-> the level this capability has EARNED, and exactly why.

    Nothing is stored. Ask again after changing code and the answer changes.
    """
    entry = REGISTRY.get(feature)
    if not entry:
        raise KeyError(feature)
    files = entry.get("code", [])
    present = [f for f in files if os.path.exists(os.path.join(tree, f))]
    h = code_hash(files, tree)
    rows = observations(root, feature)

    # IMPLEMENTED means the code path EXISTS — all of it. Counting a
    # half-present module as implemented is exactly the kind of generous
    # rounding this system is built to refuse.
    level, why = SPEC, "no implementation on disk"
    if present and len(present) < len(files):
        missing = [f for f in files if f not in present]
        why = f"partial implementation: {', '.join(missing)} not written yet"
    elif present:
        level = IMPLEMENTED
        why = ("the code exists; no passing acceptance evidence for this "
               "version of it")

    off = _latest(rows, "offline", h)
    if off:
        level, why = OFFLINE, f"acceptance tests passed ({off['detail'][:120]})"
    stress = _latest(rows, "stress", h, MAX_AGE_DAYS["stress"])
    live = _latest(rows, "live", h, MAX_AGE_DAYS["live"])
    prod = _latest(rows, "production", h, MAX_AGE_DAYS["production"])

    # LIVE outranks OFFLINE, STRESS outranks LIVE — but each still needs the
    # one below it, because "the real path worked" means little if the
    # controlled tests do not pass.
    if off and live:
        level, why = LIVE, f"real dependency exercised ({live['detail'][:120]})"
    if off and stress and live:
        level, why = STRESS, f"adversarial suite passed ({stress['detail'][:120]})"
    if off and stress and live and prod:
        level, why = PRODUCTION, f"sustained workload ({prod['detail'][:120]})"

    # say plainly what is MISSING for the next level — a badge that does not
    # tell you how to raise it is decoration
    nxt = None
    if level == IMPLEMENTED:
        nxt = "run the acceptance tests for this capability"
    elif level == OFFLINE:
        nxt = (f"exercise the real path: {entry.get('live')}"
               if entry.get("live") else
               "no live dependency; stress evidence is the next level")
    elif level == LIVE:
        nxt = "run the adversarial/stress suite"
    elif level == STRESS:
        nxt = "record sustained production workload against declared thresholds"

    expired = []
    for kind, key in (("live", "live"), ("stress", "stress"),
                      ("production", "production")):
        newest = [r for r in rows if r.get("kind") == kind and r.get("ok")]
        if newest and not _latest(rows, kind, h, MAX_AGE_DAYS[key]):
            last = max(newest, key=lambda r: r.get("at", ""))
            expired.append({
                "kind": kind, "at": last.get("at"),
                "why": ("the code changed since" if last.get("code_hash") != h
                        else f"older than {MAX_AGE_DAYS[key]} days")})

    intelligence = entry.get("intelligence", False)
    intelligence_tiers = {}
    if intelligence:
        level = OFFLINE if off and len(present) == len(files) else (IMPLEMENTED if len(present) == len(files) else SPEC)
        protocol = None
        for rank, kind in enumerate(("benchmark", "repeated", "live", "production"), 3):
            row = _latest(rows, kind, h, MAX_AGE_DAYS[kind])
            valid = _intelligence_evidence(row, kind)
            candidate_protocol = row.get("metrics", {}).get("protocol_id") if row else None
            if protocol is not None and candidate_protocol != protocol:
                valid = False
            intelligence_tiers[kind] = "VERIFIED" if valid else "NOT_PROVEN"
            if level == rank - 1 and valid:
                level = rank
                protocol = candidate_protocol
        why = ("intelligence evidence is separate from green CI; "
               + INTELLIGENCE_LEVELS[level][2])
        nxt = "supply the next independent experiment tier with pinned artifacts and the same protocol"
    name, colour, meaning = (INTELLIGENCE_LEVELS if intelligence else LEVELS)[level]
    return {
        "feature": feature, "level": level, "badge": name, "colour": colour,
        "meaning": meaning, "why": why, "next": nxt,
        "capability": entry["capability"], "invariants": entry["invariants"],
        "code": files, "code_present": present, "code_hash": h,
        "tests": entry.get("tests", []),
        "stress_tests": entry.get("stress_tests", []),
        "live_requires": entry.get("live"),
        "expired": expired,
        "observations": len(rows),
        "intelligence": intelligence,
        "intelligence_tiers": intelligence_tiers,
        "intelligence_claims_proven": bool(intelligence and level >= 4),
        "claim_scope": "paired verified task success on the recorded protocol only; no automatic transfer or cost superiority claim",
    }


def evaluate_all(root, tree=HOME):
    return {k: evaluate(root, k, tree) for k in sorted(REGISTRY)}


def summary(root, tree=HOME):
    all_ = evaluate_all(root, tree)
    counts = {}
    for r in all_.values():
        counts[r["badge"]] = counts.get(r["badge"], 0) + 1
    return {"features": all_, "counts": counts,
            "total": len(all_),
            "at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def record_offline(root, feature, tree=HOME, timeout=900):
    """Run this capability's declared acceptance tests and record the result.

    This is the loop that makes the level move: evidence is not typed in, it
    is produced by running the thing. A failing test records a FAILING
    observation, which is why a regression downgrades the badge instead of
    leaving yesterday's green in place.
    """
    entry = REGISTRY.get(feature)
    if not entry:
        raise KeyError(feature)
    tests = entry.get("tests", [])
    if not tests:
        return observe(root, feature, "offline", False,
                       "no acceptance tests are declared for this capability",
                       tree=tree)
    import execution
    passed, failed = [], []
    for t in tests:
        path = os.path.join(tree, "tests", t)
        if not os.path.exists(path):
            failed.append(f"{t} (missing)")
            continue
        rc, _out, _err = execution.run(
            "platform_spawn", [os.sys.executable, path], os.path.join(tree, "tests"),
            timeout=timeout, reason=f"proof: {feature}")
        (passed if rc == 0 else failed).append(t)
    ok = not failed
    detail = (f"{len(passed)}/{len(tests)} acceptance test(s) passed"
              + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    return observe(root, feature, "offline", ok, detail,
                   command="python tests/run_all.py", tree=tree,
                   metrics={"passed": len(passed), "failed": len(failed)})


def record_stress(root, feature, tree=HOME, timeout=900):
    """Same, for the adversarial/alternate-path suite."""
    entry = REGISTRY.get(feature) or {}
    tests = entry.get("stress_tests", [])
    if not tests:
        return None
    import execution
    passed, failed = [], []
    for t in tests:
        path = os.path.join(tree, "tests", t)
        if not os.path.exists(path):
            failed.append(f"{t} (missing)")
            continue
        rc, _o, _e = execution.run(
            "platform_spawn", [os.sys.executable, path],
            os.path.join(tree, "tests"), timeout=timeout,
            reason=f"proof stress: {feature}")
        (passed if rc == 0 else failed).append(t)
    ok = not failed
    return observe(root, feature, "stress", ok,
                   f"{len(passed)}/{len(tests)} adversarial test(s) passed"
                   + (f"; FAILED: {', '.join(failed)}" if failed else ""),
                   command="python tests/run_all.py", tree=tree)


def refresh(root, tree=HOME, features=None, stress=True):
    """Regenerate offline (and adversarial) evidence for every capability."""
    out = {}
    for name in (features or sorted(REGISTRY)):
        entry = REGISTRY[name]
        present = [f for f in entry.get("code", [])
                   if os.path.exists(os.path.join(tree, f))]
        if len(present) < len(entry.get("code", [])):
            out[name] = "skipped: not fully implemented yet"
            continue
        rec = record_offline(root, name, tree)
        out[name] = rec["detail"]
        if stress and rec["ok"]:
            record_stress(root, name, tree)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--feature")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--observe", nargs=3, metavar=("FEATURE", "KIND", "DETAIL"),
                    help="record one observation (kind: offline|live|stress|production)")
    ap.add_argument("--failed", action="store_true",
                    help="with --observe: record it as a FAILING observation")
    ap.add_argument("--refresh", action="store_true",
                    help="run every capability's declared tests and record "
                         "the evidence (this is how a level goes up)")
    ap.add_argument("--no-stress", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.observe:
        feature, kind, detail = a.observe
        rec = observe(root, feature, kind, not a.failed, detail)
        print(f"recorded {kind} observation for {feature} "
              f"(code {rec['code_hash']})")
        return
    if a.refresh:
        rep = refresh(root, features=[a.feature] if a.feature else None,
                      stress=not a.no_stress)
        for k, v in rep.items():
            print(f"  {k:<26} {v}")
        return
    if a.feature:
        r = evaluate(root, a.feature)
        print(json.dumps(r, indent=1) if a.json else _render_one(r))
        return
    s = summary(root)
    if a.json:
        print(json.dumps(s, indent=1))
        return
    print(f"PROOF CENTER — {s['total']} capabilities\n")
    for name, r in s["features"].items():
        exp = "  (expired evidence)" if r["expired"] else ""
        print(f"  {r['level']} {r['badge']:<28} {name}{exp}")
    print()
    for badge, n in sorted(s["counts"].items()):
        print(f"  {n:>2} x {badge}")
    print("\nNo level is stored anywhere. Each is computed from evidence that "
          "is bound to the current code hash and expires with age.")


def _render_one(r):
    lines = [f"{r['feature']} — LEVEL {r['level']}: {r['badge']}",
             f"  {r['meaning']}",
             f"  user capability: {r['capability']}",
             f"  why this level : {r['why']}"]
    if r["next"]:
        lines.append(f"  to raise it    : {r['next']}")
    lines.append(f"  code           : {', '.join(r['code'])} (hash {r['code_hash']})")
    lines.append(f"  invariants     :")
    for inv in r["invariants"]:
        lines.append(f"      - {inv}")
    lines.append(f"  reproduce      : python tests/run_all.py  (or: "
                 + ", ".join(f"python tests/{t}" for t in r["tests"][:3]) + ")")
    for e in r["expired"]:
        lines.append(f"  EXPIRED        : {e['kind']} evidence from {e['at']} "
                     f"— {e['why']}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
