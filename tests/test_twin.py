#!/usr/bin/env python3
"""Phase 10 exit benchmark — the owner's twin, held green.

docs/DESIGN-P10-twin.md preregistered exactly this: a Self Kernel of the
OWNER beneath every agent must show, before it becomes permanent, that

  1. CONTROL       twin/ is CONTROL (agent write refused, harness allowed),
                   the kernel is a harness ledger in the control zone and in
                   the leakage enumeration; consent refuses inside a task
  2. EPISODES      observe is hashed and idempotent; the harvester turns a
                   decided approval, a steering note and an answer into
                   attributed episodes exactly once; a worker cannot write
  3. LEARNING      a synthetic owner with a known policy yields >= 0.90
                   held-out choice fidelity from 150 episodes; the mined
                   habits contain the rule; attention ranks risk and margin
                   first; a random owner does not earn a confident verdict
  4. CALIBRATION   Brier/ECE on held-out rows only (a contaminated split is
                   refused); an unseen situation carries novelty, a lower
                   tier and ask mass; the high-confidence error rate exists
  5. SHADOW        a pending approval gets a sealed prediction; before the
                   decision the CLI/API show the hash and hide the body;
                   after it the prediction is resolved and scored; a
                   tampered body is TAMPER, never a score
  6. ELICITATION   a confident miss queues exactly one question with
                   candidate reasons; a second miss does not queue another;
                   answering stores the why; hits queue nothing
  7. DRIFT         a policy change trips the detector; the version stays;
                   confirm freezes a new one that predictions name; dismiss
                   keeps the old one
  8. STYLE         Burrows' Delta places the owner's held-out text nearer
                   the owner's profile than a stranger's
  9. CONSENT       no consent -> every output refuses; predict alone ->
                   superself/draft refuse; act refuses ungated work and
                   only queues a gated task; revoke returns to refusal;
                   every output carries the label
 10. SUPER-SELF    with a scripted model: SELF + SUPER-SELF, divergence
                   detected mechanically, a policy-update question queued,
                   the kernel hash unchanged, the call metered as `twin`
 11. CONTEXT       the OWNER block is in a compiled window when a kernel
                   exists and absent when none; the student never gets it
 12. LOOP          a --drain run seals a prediction from the idle tick; a
                   second drain seals nothing new
 13. REGISTRATION  run_all, evidence, proof, doctor, harness, fileauth, the
                   leakage enumeration, REFERENCE, MANUAL, settings

Run from the agent/ directory:  python tests/test_twin.py
"""
import io
import json
import os
import random
import subprocess
import sys

from common import AGENT_DIR, PY, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import approvals                # noqa: E402
import context                  # noqa: E402
import doctor                   # noqa: E402
import fileauth                 # noqa: E402
import fleet                    # noqa: E402
import harness                  # noqa: E402
import loop                     # noqa: E402
import modelgateway             # noqa: E402
import twin                     # noqa: E402
import twinmath as M            # noqa: E402
import twinmeasurement as TM    # noqa: E402

GRANT_DENY = [{"id": "grant", "text": "approve the offer"},
              {"id": "deny", "text": "reject the offer"}]


def _settings(root, super_script=None):
    s = ['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
         'poll_interval_seconds = 1', 'max_task_usd = 0', 'reflect_after = []',
         'max_done_rejects = 2', 'max_task_retries = 0', '',
         '[agent.twin]', 'role = "r_m"', '',
         '[providers.m]', 'type = "mock"', 'script = "scripts/m.json"', '',
         '[roles.default]', 'provider = "m"', 'model = "mock"', '',
         '[roles.r_m]', 'provider = "m"', 'model = "mock"', '',
         '[roles.student]', 'provider = "m"', 'model = "mock"', '']
    io.open(os.path.join(root, "settings.toml"), "w",
            encoding="utf-8").write("\n".join(s))
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    script = super_script or [{"tool": "finish_task", "args": {"summary": "ok"}}]
    json.dump(script, io.open(os.path.join(root, "scripts", "m.json"), "w",
                              encoding="utf-8"))


def _expert(home, name, super_script=None):
    root = fleet.create(home, name, "is modeled by its owner's twin")
    _settings(root, super_script)
    return root


def _policy(risk, margin, cp):
    """The synthetic owner: alice always gets a yes; otherwise reject when
    risk is high and the margin thin."""
    if cp == "alice":
        return "grant"
    return "deny" if (risk > 0.5 and margin < 0.3) else "grant"


def _seed(root, n=150, seed=11, policy=_policy):
    rng = random.Random(seed)
    for i in range(n):
        risk = round(rng.random(), 2)
        margin = round(rng.random() * 0.6, 2)
        cp = rng.choice(["alice", "bob", "carol"])
        twin.observe(root, {"text": f"supplier offer number {i}",
                            "features": {"risk": risk, "margin": margin}},
                     GRANT_DENY, policy(risk, margin, cp), counterpart=cp,
                     source="test")


def _pending(root, key, server="risky-api", tool="post_order", reason="ship it"):
    return approvals.request(root, key, server, tool, {"k": key}, reason, "-")


# --------------------------------------------------------------- 1 control
def check_control(home, root):
    assert fileauth.zone_of("twin/kernel.json") == fileauth.ZONE_CONTROL
    assert fileauth.zone_of("twin/shadow/pr-1.json") == fileauth.ZONE_CONTROL
    try:
        fileauth.resolve(root, "twin/kernel.json", "write", "agent")
        raise AssertionError("agent could write the twin kernel")
    except fileauth.Denied:
        pass
    fileauth.resolve(root, "twin/kernel.json", "write", "harness")
    assert any(rel == "twin/kernel.json" for rel, _w in harness.LEDGERS)
    leak = io.open(os.path.join(AGENT_DIR, "tests", "test_promotion_leakage.py"),
                   encoding="utf-8").read()
    assert '"twin/kernel.json"' in leak and '"twin/predictions.jsonl"' in leak
    # consent is an OWNER action: it refuses from inside an agent task
    os.environ["AGENT_TASK_ID"], os.environ["AGENT_ROLE"] = "t-1", "r_m"
    try:
        twin.consent_grant(root, "predict", "worker")
        raise AssertionError("consent sealed from inside an agent task")
    except SystemExit:
        pass
    finally:
        os.environ.pop("AGENT_TASK_ID", None)
        os.environ.pop("AGENT_ROLE", None)
    assert twin.consent(root)["scope"] is None
    print("[control] twin/ is CONTROL (agent refused, harness allowed), the "
          "kernel is a harness ledger in the leakage enumeration, and consent "
          "refuses from inside an agent task")


# -------------------------------------------------------------- 2 episodes
def check_episodes(root):
    c = twin.consent_grant(root, "predict", "owner")
    assert c["scope"] == "predict" and c["verified"] and c["seq"] == 1
    ep, new = twin.observe(root, {"text": "buy the domain",
                                  "features": {"price": 40}},
                           ["yes", "no"], "no", counterpart="registrar")
    ep2, new2 = twin.observe(root, {"text": "buy the domain",
                                    "features": {"price": 40}},
                             ["yes", "no"], "no", counterpart="registrar")
    assert new and not new2 and ep["id"] == ep2["id"] and ep["hash"]
    try:
        twin.observe(root, "x", ["a", "b"], "c")
        raise AssertionError("a choice outside the options was accepted")
    except twin.Refused:
        pass
    # the ledgers the owner already writes into become episodes, once
    rec = _pending(root, "harvest-1")
    approvals.decide(root, rec["id"], False, "not this vendor")
    os.makedirs(os.path.join(root, "goals", "g-1"), exist_ok=True)
    io.open(os.path.join(root, "goals", "g-1", "steering.jsonl"), "a",
            encoding="utf-8").write(json.dumps(
                {"at": "2026-09-03T10:00:00", "by": "owner",
                 "text": "Keep the scope narrow. I want the review first."}) + "\n")
    os.makedirs(os.path.join(root, "contexts"), exist_ok=True)
    json.dump([{"role": "user", "content": "Task: x"},
               {"role": "user", "content": "Human answer to your blocked "
                "question: Use the cheaper supplier, we can wait a week."}],
              io.open(os.path.join(root, "contexts", "t-1.json"), "w",
                      encoding="utf-8"))
    n1, n2 = twin.harvest(root), twin.harvest(root)
    assert n1 == 3 and n2 == 0, (n1, n2)
    eps = twin.episodes(root)
    ap = next(e for e in eps if e["kind"] == "approval")
    assert ap["choice"] == "deny" and ap["why"] == "not this vendor" \
        and ap["counterpart"] == "risky-api" and ap["source"] == "harvest:approvals"
    assert {e["kind"] for e in eps} >= {"steer", "answer", "approval", "decision"}
    print("[episodes] observe is hashed and idempotent, a choice outside the "
          "options is refused, and one decided approval + one steering note "
          "+ one answer harvested into three attributed episodes exactly once")


# -------------------------------------------------------------- 3 learning
def check_learning(home):
    root = _expert(home, "learner")
    twin.consent_grant(root, "predict")
    _seed(root)
    res = twin.learn(root)
    assert res["status"] == "fit" and res["version"] == 1, res
    rep = twin.fidelity(root)
    assert rep["n_holdout"] >= 20, rep["n_holdout"]
    assert rep["choice_fidelity"] >= 0.90, rep["choice_fidelity"]
    assert rep["verdict"] in ("high", "moderate"), rep["verdict"]
    v = twin.current_version(twin.load_kernel(root))
    top = [a["feature"] for a in v["attention"][:3]]
    assert "sit:risk" in top and "sit:margin" in top, top
    proven = [r for r in v["rules"] if r["status"] == "supported"]
    assert any("alice" in r["text"] and r["then"] == "grant" for r in proven), \
        [r["text"] for r in proven]
    assert any(("risk" in r["text"] or "margin" in r["text"]) for r in proven)
    # the same ledger fits to the same bytes: a version is a hash
    again = twin.learn(root)
    assert again["hash"] == res["hash"]
    # a random owner earns no confident verdict
    rroot = _expert(home, "random-owner")
    twin.consent_grant(rroot, "predict")
    rng = random.Random(5)
    _seed(rroot, policy=lambda r, m, c: rng.choice(["grant", "deny"]))
    twin.learn(rroot)
    rrep = twin.fidelity(rroot)
    assert rrep["verdict"] != "high" and rrep["choice_fidelity"] < 0.85, rrep
    print(f"[learning] a synthetic owner (alice always yes; deny when risk > "
          f"0.5 and margin < 0.3) gave held-out choice fidelity "
          f"{rep['choice_fidelity']:.2f} on {rep['n_holdout']} rows; "
          f"attention ranked {', '.join(top)}; {len(proven)} habits supported "
          f"including the alice rule; the fit is byte-stable; a random owner "
          f"scored {rrep['choice_fidelity']:.2f} and the verdict was "
          f"{rrep['verdict']!r}, not 'high'")
    return root


# ----------------------------------------------------------- 4 calibration
def check_calibration(root):
    rep = twin.fidelity(root)
    assert rep["brier"] is not None and rep["ece"] is not None
    assert rep["high_confidence_error_rate"] is not None
    assert len(rep["reliability"]) == 10
    # a contaminated split is refused: put a fit id among the held-out ids
    k = twin.load_kernel(root)
    v = twin.current_version(k)
    held = [e for e in twin.decisions(twin.episodes(root)) if TM.partition(e) == "test"]
    v["fit_ids"] = sorted(set(v["fit_ids"]) | {held[0]["id"]})
    twin.save_kernel(root, k)
    try:
        twin.fidelity(root)
        raise AssertionError("a contaminated split was scored")
    except twin.Refused as e:
        assert "contaminated" in str(e)
    twin.learn(root)                       # restores the honest fit_ids
    seen = twin.predict(root, {"text": "supplier offer number 7",
                               "features": {"risk": 0.9, "margin": 0.05}},
                        GRANT_DENY, "bob")
    unseen = twin.predict(root, {"text": "acquire a shipping company",
                                 "features": {"headcount": 300, "debt": 2.1}},
                          GRANT_DENY, "zed")
    assert seen["novelty"] < 0.3 and seen["tier"] == "high", seen
    assert unseen["novelty"] >= 0.5 and unseen["tier"] != "high", unseen
    assert unseen["ask"] > seen["ask"] and unseen["with_ask"]["ask"] == unseen["ask"]
    assert abs(sum(seen["probs"].values()) - 1.0) < 1e-6
    print(f"[calibration] Brier {rep['brier']}, ECE {rep['ece']} and a "
          f"high-confidence error rate are computed on held-out rows only "
          f"(a contaminated split is refused); an unseen situation carried "
          f"novelty {unseen['novelty']} (tier {unseen['tier']}) and ask mass "
          f"{unseen['ask']} against {seen['novelty']} / {seen['ask']} for a "
          f"known one")


# ---------------------------------------------------------------- 5 shadow
def check_shadow(home):
    root = _expert(home, "shadow")
    twin.consent_grant(root, "predict")
    # the owner's approval policy: safe-api yes, risky-api no
    for i in range(30):
        rec = _pending(root, f"warm-{i}", server=("safe-api" if i % 2 else "risky-api"))
        approvals.decide(root, rec["id"], i % 2 == 1, "")
    res = twin.tick(root)
    assert res["harvested"] == 30 and res["learned"], res
    pend = _pending(root, "live-1", server="risky-api")
    res = twin.tick(root)
    assert res["sealed"] == 1, res
    p = twin.predictions(root)[-1]
    assert p["status"] == "sealed" and len(p["sealed"]) == 64
    hidden = twin.reveal(root, p["id"])
    assert hidden["hidden"] and "probs" not in hidden and "body" not in hidden
    cli = subprocess.run([PY, os.path.join(AGENT_DIR, "twin.py"), "--root", root,
                          "shadow", "--reveal", p["id"]],
                         capture_output=True, text=True, encoding="utf-8")
    assert '"hidden": true' in cli.stdout and "probs" not in cli.stdout, cli.stdout
    approvals.decide(root, pend["id"], False, "")
    res = twin.tick(root)
    assert res["resolved"] == 1, res
    p = twin.predictions(root)[-1]
    assert p["status"] == "resolved" and p["actual"] == "deny" and p["hit"] \
        and p["brier"] is not None, p
    shown = twin.reveal(root, p["id"])
    assert not shown["hidden"] and shown["body"]["argmax"] == "deny" \
        and shown["body"]["label"] == twin.LABEL
    # a tampered body is TAMPER, never a score
    pend2 = _pending(root, "live-2", server="safe-api")
    twin.tick(root)
    p2 = twin.predictions(root)[-1]
    body_path = os.path.join(root, twin.SHADOW, p2["id"] + ".json")
    body = json.load(io.open(body_path, encoding="utf-8"))
    body["probs"] = {"grant": 0.01, "deny": 0.99}
    json.dump(body, io.open(body_path, "w", encoding="utf-8"))
    approvals.decide(root, pend2["id"], True, "")
    twin.tick(root)
    p2 = twin.predictions(root)[-1]
    assert p2["status"] == "tamper", p2
    print("[shadow] a pending approval got a sealed prediction from the tick; "
          "before the decision the API and CLI showed the hash and hid the "
          "body; after it the prediction resolved as a scored hit; a body "
          "edited under its seal resolved as TAMPER, not a score")
    return root


# ----------------------------------------------------------- 6 elicitation
def check_elicitation(root):
    assert not twin.questions(root, "open")
    # a hit queues nothing
    rec = _pending(root, "hit-1", server="risky-api")
    twin.tick(root)
    approvals.decide(root, rec["id"], False, "")
    twin.tick(root)
    assert not twin.questions(root, "open")
    # a confident miss queues exactly one question
    rec = _pending(root, "miss-1", server="risky-api")
    twin.tick(root)
    approvals.decide(root, rec["id"], True, "")
    twin.tick(root)
    qs = twin.questions(root, "open")
    assert len(qs) == 1 and qs[0]["reason"] == "confident miss", qs
    q = qs[0]
    assert "something else" in q["candidates"] and q["episode"]
    rec = _pending(root, "miss-2", server="risky-api")
    twin.tick(root)
    approvals.decide(root, rec["id"], True, "")
    twin.tick(root)
    assert len(twin.questions(root, "open")) == 1, "a second question opened"
    try:
        twin.ask(root, q["episode"], "manual", "another?")
        raise AssertionError("a second question was accepted while one was open")
    except twin.Refused:
        pass
    twin.answer(root, q["id"], "The vendor is fine now; they fixed their SLA.")
    assert not twin.questions(root, "open")
    ep = next(e for e in twin.episodes(root) if e["id"] == q["episode"])
    assert ep["why"].startswith("The vendor is fine now")
    print("[elicitation] a hit queued nothing; a confident miss queued exactly "
          "one question with candidate reasons; a second miss and a manual "
          "ask were refused while it was open; the answer landed on the "
          "episode as its why")


# ----------------------------------------------------------------- 7 drift
def check_drift(home):
    def drive(root, n, flip, tag):
        for i in range(n):
            server = "safe-api" if i % 2 else "risky-api"
            rec = _pending(root, f"{tag}-{i}", server=server)
            twin.tick(root)
            grant = (server == "safe-api") != flip
            approvals.decide(root, rec["id"], grant, "")
            twin.tick(root)

    root = _expert(home, "drifter")
    twin.consent_grant(root, "predict")
    drive(root, 30, False, "era1")
    v_before = twin.current_version(twin.load_kernel(root))["v"]
    assert not twin.drift_status(root)["notice"]
    drive(root, 20, True, "era2")
    d = twin.drift_status(root)
    assert d["notice"] and d["notice"]["status"] == "open", d
    assert d["notice"]["estimates"]["recent"]["choice_rates"]
    assert twin.current_version(twin.load_kernel(root))["v"] == v_before
    held = twin.learn(root)
    assert held["status"] == "held", held
    n = twin.drift_confirm(root, "owner")
    assert n["status"] == "confirmed" and n["version"] == v_before + 1
    k = twin.load_kernel(root)
    assert k["current"] == v_before + 1 and len(k["versions"]) == 2
    rec = _pending(root, "era3-0", server="risky-api")
    twin.tick(root)
    assert twin.predictions(root)[-1]["kernel_version"] == v_before + 1
    approvals.decide(root, rec["id"], True, "")
    twin.tick(root)
    # dismiss keeps the old policy
    root2 = _expert(home, "dismisser")
    twin.consent_grant(root2, "predict")
    drive(root2, 30, False, "e1")
    drive(root2, 20, True, "e2")
    assert twin.drift_status(root2)["notice"]["status"] == "open"
    twin.drift_dismiss(root2, "owner")
    assert twin.drift_status(root2)["notice"]["status"] == "dismissed"
    assert twin.load_kernel(root2)["current"] == 1
    assert twin.learn(root2)["status"] == "fit"
    print("[drift] a flipped approval policy tripped the detector after the "
          "change; the version stayed and learn was HELD; confirm froze v2 "
          "and the next sealed prediction named it; on a second expert "
          "dismiss kept v1 and learning resumed")


# ----------------------------------------------------------------- 8 style
def check_style(home):
    root = _expert(home, "writer")
    twin.consent_grant(root, "predict")
    own = ["I think we should hold. The margin is thin, and the risk is not "
           "worth it. Let me check the numbers first.",
           "We can do this, but only if the price comes down. I want the "
           "downside capped. Let me see the contract before we sign.",
           "Not yet. I need the supplier history before I decide anything. "
           "Let me look at it tomorrow and we can talk.",
           "Fine, but keep it small. I do not want a second vendor until the "
           "first one has shipped twice. Let me know when they have."]
    for i, t in enumerate(own):
        twin.observe(root, {"text": t}, [], None, kind="steer",
                     origin=f"style:{i}")
    _seed(root, n=40)
    twin.learn(root)
    rep = twin.fidelity(root)
    w = rep["writing"]
    assert w["owner_delta"] is not None and w["closer_to_owner"], w
    prof = M.style_profile(own[:-1])
    assert M.burrows_delta(prof, own[-1]) < M.burrows_delta(prof, twin.STRANGER)
    block = twin.render(root)
    assert "how they write" in block
    print(f"[style] Burrows' Delta put the owner's held-out note at "
          f"{w['owner_delta']} from the owner's profile against "
          f"{w['stranger_delta']} for a stranger's; the OWNER block carries "
          f"the writing line")


# --------------------------------------------------------------- 9 consent
def check_consent(home):
    root = _expert(home, "consent", super_script=[
        {"content": json.dumps({"choice": "grant", "reason": "the SLA is fixed",
                                "disputed_assumption": "risky-api still fails",
                                "evidence": ["uptime 99.9% for 90 days"]})},
        {"content": "A short note in the owner's voice. Let me check first."}])
    _seed(root, n=40)
    for fn in (lambda: twin.learn(root),
               lambda: twin.predict(root, "x", GRANT_DENY),
               lambda: twin.fidelity(root),
               lambda: twin.declare(root, "keep it small"),
               lambda: twin.act(root, "g", done_check="true")):
        try:
            fn()
            raise AssertionError("an output was produced without consent")
        except twin.Refused as e:
            assert "consent" in str(e)
    assert twin.tick(root).get("skipped") == "no consent"
    assert twin.render(root) == ""
    twin.consent_grant(root, "predict")
    twin.learn(root)
    p = twin.predict(root, {"text": "supplier offer number 3",
                            "features": {"risk": 0.2, "margin": 0.5}},
                     GRANT_DENY, "bob")
    assert p["label"] == twin.LABEL
    agent = loop.Agent(root)
    for fn, scope in ((lambda: twin.superself(root, agent, "x", GRANT_DENY), "advise"),
                      (lambda: twin.draft(root, agent, "say no"), "draft"),
                      (lambda: twin.act(root, "g", done_check="true"), "act")):
        try:
            fn()
            raise AssertionError(f"{scope} ran on predict consent")
        except twin.Refused as e:
            assert scope in str(e)
    c = twin.consent_grant(root, "act")
    assert c["scope"] == "act" and c["seq"] == 2
    try:
        twin.act(root, "renew the domain")
        raise AssertionError("ungated work was queued")
    except twin.Refused as e:
        assert "gated" in str(e)
    out = twin.act(root, "renew the domain", done_check=f'"{PY}" -c "exit(0)"')
    assert out["label"] == twin.LABEL and out["gated"] and not out["executed_by_twin"]
    task = next(t for t in loop.Agent(root).load_state()["tasks"]
                if t["id"] == out["task"])
    assert task["status"] == "queued" and task["done_check"] \
        and task["goal"].startswith("TWIN (on behalf of the owner")
    d = twin.draft(root, agent, "tell the vendor no")
    assert d["label"] == twin.LABEL and d["sent"] is False and d["draft"]
    twin.consent_revoke(root)
    c = twin.consent(root)
    assert c["scope"] is None and c["verified"] and c["seq"] == 3
    try:
        twin.predict(root, "x", GRANT_DENY)
        raise AssertionError("predicted after revoke")
    except twin.Refused:
        pass
    # a consent record edited on disk verifies as TAMPER: no scope at all
    twin.consent_grant(root, "predict")
    path = twin._record_path(root, 4)
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["scope"] = "act"
    path.write_text(json.dumps(rec, sort_keys=True), encoding="utf-8")
    c = twin.consent(root)
    assert c["scope"] is None and not c["verified"] and "TAMPER" in c["why"]
    print("[consent] without consent learn/predict/fidelity/declare/act/tick/"
          "render all refused; with predict, superself/draft/act refused by "
          "scope; act refused ungated work and queued a gated task it did not "
          "execute; every output carried the label; revoke returned to "
          "refusal; a consent record edited under its seal verified as TAMPER")


# ------------------------------------------------------------ 10 super-self
def check_superself(home):
    root = _expert(home, "superself", super_script=[
        {"content": "Thinking... " + json.dumps(
            {"choice": "grant", "reason": "the SLA was fixed last quarter",
             "disputed_assumption": "risky-api still misses deadlines",
             "evidence": ["uptime 99.9% for 90 days"]})}])
    twin.consent_grant(root, "advise")
    _seed(root, n=60)
    twin.learn(root)
    before = twin.current_version(twin.load_kernel(root))["hash"]
    agent = loop.Agent(root)
    out = twin.superself(root, agent, {"text": "supplier offer number 9",
                                       "features": {"risk": 0.9, "margin": 0.1}},
                         GRANT_DENY, "bob")
    assert out["label"] == twin.SUPER_LABEL and out["self"]["label"] == twin.LABEL
    assert out["self"]["argmax"] == "deny" and out["super"]["choice"] == "grant"
    assert out["diverges"] and out["question"] and out["kernel_unchanged"]
    q = twin.questions(root, "open")[0]
    assert q["kind"] == "policy_update" and q["id"] == out["question"]
    assert twin.current_version(twin.load_kernel(root))["hash"] == before
    rows = [r for r in modelgateway.calls(root) if r.get("purpose") == "twin"]
    assert len(rows) == 1, rows
    n_before = len(twin.episodes(root))
    twin.answer(root, q["id"], "adopt")
    assert len(twin.episodes(root)) == n_before + 1
    adopted = twin.episodes(root)[-1]
    assert adopted["source"] == "owner:policy_update" and adopted["choice"] == "grant"
    print("[super-self] SELF said deny and the scripted SUPER-SELF said grant; "
          "the divergence was detected mechanically, a policy-update question "
          "was queued, the kernel hash did not move, the call was metered "
          "under purpose 'twin', and 'adopt' recorded the owner's new "
          "decision as an episode rather than editing the kernel")


# --------------------------------------------------------------- 11 context
def _task(agent, role, goal):
    tid = agent.add_task(role, goal)
    tid = tid["id"] if isinstance(tid, dict) else tid
    return next(t for t in agent.load_state()["tasks"] if t["id"] == tid)


def check_context(home, kernel_root):
    agent = loop.Agent(kernel_root)
    task = _task(agent, "r_m", "review the next supplier offer")
    msgs, man = context.compile(agent, task)
    user = msgs[-1]["content"]
    assert "OWNER — how the person you work for actually decides" in user
    owner = next(s for s in man["sources"] if s["name"] == "owner")
    assert owner["used_chars"] > 0, owner
    student = _task(agent, "student", "study the course")
    msgs, man = context.compile(agent, student)
    assert "OWNER —" not in msgs[-1]["content"]
    assert next(s for s in man["sources"] if s["name"] == "owner")["excluded_by_router"]
    bare = _expert(home, "bare")
    a2 = loop.Agent(bare)
    msgs, man = context.compile(a2, _task(a2, "r_m", "anything"))
    assert "OWNER —" not in msgs[-1]["content"]
    assert next(s for s in man["sources"] if s["name"] == "owner")["used_chars"] == 0
    print("[context] a compiled window carried the OWNER block where a kernel "
          "exists, the manifest named the source, the closed-book student "
          "never received it, and an expert without a kernel got nothing")


# ------------------------------------------------------------------ 12 loop
def check_loop(home):
    root = _expert(home, "looper")
    twin.consent_grant(root, "predict")
    _seed(root, n=40)
    pend = _pending(root, "loop-1", server="risky-api")
    assert run_drain(root, timeout=120) == 0
    preds = twin.predictions(root)
    assert len(preds) == 1 and preds[0]["status"] == "sealed", preds
    log = io.open(os.path.join(root, "logs", "agent.log"), encoding="utf-8").read()
    assert '"event": "twin_tick"' in log
    assert run_drain(root, timeout=120) == 0
    assert len(twin.predictions(root)) == 1
    assert pend["status"] == "pending"
    print("[loop] a --drain run sealed one shadow prediction for the pending "
          "approval from the idle tick and logged it; a second drain sealed "
          "nothing new")


# ---------------------------------------------------------- 13 registration
def check_registration():
    me = os.path.basename(__file__)
    for name in ("tests/run_all.py", "evidence.py", "proof.py"):
        text = io.open(os.path.join(AGENT_DIR, name), encoding="utf-8").read()
        assert me in text, f"{me} is not declared in {name}"
    assert "twin" in doctor.CORE_MODULES and "twinmath" in doctor.CORE_MODULES
    assert "twin" in modelgateway.PURPOSES
    ref = io.open(os.path.join(AGENT_DIR, "REFERENCE.md"), encoding="utf-8").read()
    assert "`twin.py`" in ref and "DESIGN-P10" in ref
    manual = io.open(os.path.join(AGENT_DIR, "MANUAL.md"), encoding="utf-8").read()
    assert "python twin.py" in manual
    settings = io.open(os.path.join(AGENT_DIR, "settings.toml"), encoding="utf-8").read()
    assert "[agent.twin]" in settings
    print("[registration] the benchmark is declared in run_all, evidence and "
          "proof; the doctor imports the twin; the gateway meters purpose "
          "'twin'; REFERENCE, MANUAL and settings.toml name it")


def main():
    home = make_sandbox("twin", providers={"m": {"script": "s.json"}},
                        roles={"r_m": "m"}, scripts={"s.json": []})
    root = _expert(home, "owner-of-record")
    check_control(home, root)
    check_episodes(root)
    kernel_root = check_learning(home)
    check_calibration(kernel_root)
    shadow_root = check_shadow(home)
    check_elicitation(shadow_root)
    check_drift(home)
    check_style(home)
    check_consent(home)
    check_superself(home)
    check_context(home, kernel_root)
    check_loop(home)
    check_registration()
    print("PASS test_twin")


if __name__ == "__main__":
    main()
