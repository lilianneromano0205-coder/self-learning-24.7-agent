#!/usr/bin/env python3
"""Charter evolution with a promotion gate — the Agent Selection Farm idea,
governed the way the fragility research demands.

The battery's done_check greps the task's own transcript for a marker that
only the VARIANT charter contains — so the base arm genuinely fails its
gates and the variant genuinely passes them, through two real drains of the
same loop. Proven:

1. A trial runs the same battery under both charters (variant selected by
   env var only — live prompts untouched during the trial) and scores both
   arms with identical mechanical gates.
2. promote() REFUSES a tie or a loss, refuses without a trial, and refuses
   tiny trials — evolution without evidence is superstition.
3. A strictly-better variant promotes: live prompts updated, base backed up.
4. rollback() restores the exact pre-promotion charter.

Run from the agent/ directory:  python tests/test_variants.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import variants as V

PY = sys.executable

# a check that passes only when the ACTIVE charter carried the marker into
# the task's context (context files are persisted every step)
# the marker is SPLIT in the check's own source — otherwise the gate's
# refusal message (which quotes the command) would leak the marker into the
# context and let the base arm pass its own gate. Found live.
CHECK = (f'"{PY}" -c "import glob,os,sys;'
         "fs=sorted(glob.glob('contexts/*.json'),key=os.path.getmtime);"
         "sys.exit(0 if fs and ('MARKER-'+'V2') in open(fs[-1],"
         "encoding='utf-8').read() else 1)\"")

FINISH = [{"tool": "finish_task", "args": {"summary": "attempted"}}]


def main():
    sb = make_sandbox("variants", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": FINISH})
    os.makedirs(os.path.join(sb, "prompts"), exist_ok=True)
    with open(os.path.join(sb, "prompts", "tester.md"), "w",
              encoding="utf-8") as f:
        f.write("# ROLE: tester — plain base charter, no marker.\n")
    with open(os.path.join(sb, "settings.toml"), "a", encoding="utf-8") as f:
        f.write("\n")  # settings already written by make_sandbox

    # keep the gate patient enough for the mock to re-finish after refusals
    battery = [{"role": "tester", "goal": f"job {i}", "done_check": CHECK}
               for i in range(2)]

    # --- guards fire before anything runs
    e = V.spawn(sb, "v2", "tester",
                "# ROLE: tester — improved charter. MARKER-V2\n",
                note="adds the marker discipline")
    assert e["status"] == "spawned" and e["roles"] == ["tester"]
    try:
        V.promote(sb, "v2")
        raise AssertionError("promotion without a trial must be refused")
    except SystemExit as ex:
        assert "no trial" in str(ex)
    try:
        V.trial(sb, "v2", battery[:1])
        raise AssertionError("a 1-task trial must be refused")
    except SystemExit as ex:
        assert "one task proves nothing" in str(ex)
    print("[guards] no promotion without a trial; no trial on a single task")

    # --- 1. the two-arm trial, both arms through REAL gated drains
    r = V.trial(sb, "v2", battery, timeout=240)
    assert r["base"]["passes"] == 0 and r["base"]["tasks"] == 2, r["base"]
    assert r["base"]["gate_rejects"] >= 2, \
        "the base arm must have been refused by the gate, not skipped"
    assert r["variant"]["passes"] == 2, r["variant"]
    # the live prompt was untouched during the trial
    with open(os.path.join(sb, "prompts", "tester.md"), encoding="utf-8") as f:
        assert "MARKER-V2" not in f.read(), \
            "trials must never touch the live charter"
    print(f"[trial] same battery, two real drains: base 0/2 "
          f"(gate refused {r['base']['gate_rejects']}x), variant 2/2; "
          f"live prompts untouched")

    # --- 2+3. promotion on strict evidence
    e = V.promote(sb, "v2")
    assert e["status"] == "promoted"
    with open(os.path.join(sb, "prompts", "tester.md"), encoding="utf-8") as f:
        assert "MARKER-V2" in f.read(), "promotion must install the winner"
    backup = os.path.join(sb, "variants", "v2", "backup-tester.md")
    with open(backup, encoding="utf-8") as f:
        assert "plain base charter" in f.read(), \
            "promotion must back up what it replaced"
    print("[promote] strictly-better variant installed; base charter backed up")

    # a tie must be refused: spawn a variant identical in outcome
    V.spawn(sb, "v3", "tester", "# ROLE: tester — also has MARKER-V2\n")
    r3 = V.trial(sb, "v3", battery, timeout=240)
    assert r3["variant"]["passes"] == r3["base"]["passes"] == 2, r3
    try:
        V.promote(sb, "v3")
        raise AssertionError("a tie must not promote")
    except SystemExit as ex:
        assert "strictly beat" in str(ex)
    print("[tie] equal performance refused — churn without evidence is rot")

    # --- 4. rollback restores the exact pre-promotion world
    V.rollback(sb, "v2")
    with open(os.path.join(sb, "prompts", "tester.md"), encoding="utf-8") as f:
        assert "plain base charter" in f.read()
    m = V.load_manifest(sb)["v2"]
    assert m["status"] == "rolled_back" and m["rolled_back_at"]
    try:
        V.rollback(sb, "v3")
        raise AssertionError("only promoted variants can roll back")
    except SystemExit:
        pass
    print("[rollback] the exact pre-promotion charter restored; "
          "un-promoted variants cannot roll back")
    print("PASS test_variants")


if __name__ == "__main__":
    main()
