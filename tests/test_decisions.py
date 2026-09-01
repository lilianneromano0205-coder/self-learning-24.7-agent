#!/usr/bin/env python3
"""DECISION OBSERVABILITY: a charter change must predict its own effect (M6).

Agentic Harness Engineering (arXiv 2604.25850) found that pairing every
harness edit with a self-declared prediction, then checking it against the
measured outcome, is what turned tinkering into improvement. Here:

1. a variant may declare a prediction (metric + expected delta)
2. the trial measures the observed delta and records whether it held
3. promotion is REFUSED when the prediction did not hold -- even though the
   variant strictly beat base on raw passes (better by accident is not
   understood)
4. a variant whose prediction held promotes normally
5. a prediction declared after the trial forces a re-trial
6. the panel accepts predictions and rejects malformed ones

Run from the agent/ directory:  python tests/test_decisions.py
"""

import json
import os
import sys

from common import AGENT_DIR, api, make_sandbox, seal_variant_protocol, \
    start_panel, stop_panel

sys.path.insert(0, AGENT_DIR)
import fleet
import variants as V


def trial_record(base_passes, var_passes, base_rej=0, var_rej=0, tasks=4):
    return {"base": {"tasks": tasks, "passes": base_passes,
                     "gate_rejects": base_rej, "task_ids": []},
            "variant": {"tasks": tasks, "passes": var_passes,
                        "gate_rejects": var_rej, "task_ids": []},
            "observed_delta": {"passes": var_passes - base_passes,
                               "gate_rejects": var_rej - base_rej},
            "at": "2026-08-21T00:00:00"}


def check_for(e, tr):
    """Apply the same prediction arithmetic trial() performs."""
    pred = e["prediction"]
    exp = float(pred["expected_delta"])
    obs = tr["observed_delta"][pred["metric"]]
    return {"metric": pred["metric"], "expected_delta": exp,
            "observed_delta": obs,
            "held": bool(obs >= exp if exp >= 0 else obs <= exp),
            "at": "2026-08-21T00:00:00"}


def main():
    home = make_sandbox("decisions", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Decider", "evolves on evidence")

    # --- 1. declaring a prediction
    e = V.spawn(root, "v-bold", "practitioner", "# ROLE: practitioner\nbe bold\n",
                "tighter checklist", {"metric": "passes", "expected_delta": 2})
    assert e["prediction"]["metric"] == "passes"
    assert e["prediction"]["expected_delta"] == 2.0
    for bad in ({"metric": "vibes", "expected_delta": 1},
                {"metric": "passes", "expected_delta": "lots"}):
        try:
            V.spawn(root, "v-bad", "practitioner", "x", "", bad)
            raise AssertionError(f"malformed prediction accepted: {bad}")
        except ValueError:
            pass
    print("[declare] a variant can state what it should improve and by how "
          "much; a vague prediction is refused outright")

    # --- 2/3. it beat base, but by less than it promised
    m = V.load_manifest(root)
    tr = trial_record(base_passes=1, var_passes=2)      # +1, predicted +2
    m["v-bold"]["trials"] = tr
    m["v-bold"]["prediction_check"] = check_for(m["v-bold"], tr)
    m["v-bold"]["status"] = "trialed"
    V.save_manifest(root, m)
    assert m["v-bold"]["prediction_check"]["held"] is False
    try:
        V.promote(root, "v-bold")
        raise AssertionError("a broken prediction must block promotion")
    except SystemExit as ex:
        msg = str(ex)
    assert "prediction did not hold" in msg, msg
    assert "predicted +2 passes, observed +1" in msg, msg
    assert V.load_manifest(root)["v-bold"]["status"] == "trialed"
    live = open(os.path.join(root, "prompts", "practitioner.md"),
                encoding="utf-8").read()
    assert "be bold" not in live, "the live charter must be untouched"
    print("[refused] the variant DID beat base, but missed the effect it "
          "predicted -- promotion refused and the live charter untouched")

    # --- 4. a prediction that holds promotes
    V.spawn(root, "v-careful", "practitioner",
            "# ROLE: practitioner\nverify before finishing\n", "fewer refusals",
            {"metric": "gate_rejects", "expected_delta": -2})
    # promotion additionally requires the sealed three-battery protocol;
    # the fixture seals it (and its hidden-phase receipts) through the same
    # owner authority production uses — see common.seal_variant_protocol
    seal_variant_protocol(root, "v-careful")
    m = V.load_manifest(root)
    tr2 = trial_record(base_passes=1, var_passes=3, base_rej=3, var_rej=0)
    m["v-careful"]["trials"] = tr2
    m["v-careful"]["prediction_check"] = check_for(m["v-careful"], tr2)
    m["v-careful"]["status"] = "trialed"
    V.save_manifest(root, m)
    assert m["v-careful"]["prediction_check"]["held"] is True
    V.promote(root, "v-careful")
    live = open(os.path.join(root, "prompts", "practitioner.md"),
                encoding="utf-8").read()
    assert "verify before finishing" in live
    assert V.load_manifest(root)["v-careful"]["status"] == "promoted"
    V.rollback(root, "v-careful")
    assert "verify before finishing" not in open(
        os.path.join(root, "prompts", "practitioner.md"), encoding="utf-8").read()
    print("[held] the variant that delivered exactly what it predicted was "
          "promoted, and rollback restored the previous charter byte for byte")

    # --- 5. a prediction added after the trial forces a re-trial
    V.spawn(root, "v-late", "practitioner", "# ROLE: practitioner\nlate\n")
    m = V.load_manifest(root)
    m["v-late"]["trials"] = trial_record(base_passes=1, var_passes=3)
    m["v-late"]["status"] = "trialed"
    V.save_manifest(root, m)
    V.spawn(root, "v-late", "practitioner", "# ROLE: practitioner\nlate\n", "",
            {"metric": "passes", "expected_delta": 1})
    try:
        V.promote(root, "v-late")
        raise AssertionError("a stale trial must not satisfy a new prediction")
    except SystemExit as ex:
        assert "predates it" in str(ex), str(ex)
    print("[stale] a prediction declared after the fact cannot be validated by "
          "the old trial -- the harness demands a fresh one")

    # --- 6. the panel
    proc, base = start_panel(home)
    try:
        r = api(base, "POST", "/api/experts/decider/variant",
                {"op": "spawn", "id": "v-panel", "role": "practitioner",
                 "prompt": "# ROLE: practitioner\nfrom the panel\n",
                 "note": "panel test",
                 "prediction": {"metric": "passes", "expected_delta": 3}})
        assert r["prediction"]["expected_delta"] == 3.0, r
        man = api(base, "GET", "/api/experts/decider/variants")
        assert man["v-panel"]["prediction"]["metric"] == "passes"
        assert man["v-bold"]["prediction_check"]["held"] is False
    finally:
        stop_panel(proc, base)
    print("[panel] predictions are declared and displayed from the control "
          "panel, with the verdict beside them")
    print("PASS test_decisions")


if __name__ == "__main__":
    main()
