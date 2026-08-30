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

    check_arms_do_not_inherit_each_others_world()
    print("PASS test_variants")


def check_arms_do_not_inherit_each_others_world():
    """The variant arm must not be scored on work the BASE arm did.

    Both arms used to run sequentially against the same root, base always
    first, with nothing reset in between — so every file the base arm wrote
    was still there when the variant started. That is not a subtle
    contamination: the ordinary battery gate is `test -f out/<thing>`, and
    the base arm creates exactly that file. The variant then passes on the
    base's artifact and the trial reports "the variant beat the base", which
    is what an arm running SECOND looks like.

    The confound was also systematic rather than noisy — the order was fixed
    — so it pointed the same way every time and read as a result.

    The battery here makes the leak decisive: both arms run the SAME
    charter (no variant marker anywhere), and the gate passes only if
    out/base-artifact.txt exists. The base arm creates it. On a shared root
    the variant arm would then score 2/2 against the base's 2/2 or better;
    with independent clones it must score exactly what the base scored,
    because the two arms did identical work in identical worlds.
    """
    sb = make_sandbox("variants_isolation",
                      providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"},
                      scripts={"s.json": [
                          {"tool": "write_file",
                           "args": {"path": "out/base-artifact.txt",
                                    "content": "made by whichever arm ran"}},
                          {"tool": "finish_task", "args": {"summary": "ok"}}]})
    os.makedirs(os.path.join(sb, "prompts"), exist_ok=True)
    with open(os.path.join(sb, "prompts", "tester.md"), "w",
              encoding="utf-8") as f:
        f.write("# ROLE: tester\n")
    # NOTE: the variant charter is deliberately identical in effect. Any
    # difference between the arms is then leakage, not capability.
    V.spawn(sb, "iso", "tester", "# ROLE: tester (variant, same behaviour)\n")

    gate = f'"{PY}" -c "import os,sys;sys.exit(0 if os.path.exists(' \
           "os.path.join('out','base-artifact.txt')) else 1)\""
    battery = [{"role": "tester", "goal": f"produce artifact {i}",
                "done_check": gate} for i in range(2)]
    r = V.trial(sb, "iso", battery, timeout=240)

    assert r["base"]["root"] != r["variant"]["root"], (
        "the two arms shared a root — everything the base arm wrote is "
        "still on disk when the variant starts")
    assert r["variant"]["passes"] == r["base"]["passes"], (
        f"identical charters produced different scores: base "
        f"{r['base']['passes']}/{r['base']['tasks']}, variant "
        f"{r['variant']['passes']}/{r['variant']['tasks']} — the only "
        f"difference between the arms is what the other arm left behind")
    # and the trial left the real expert alone: no arm's artifacts here
    assert not os.path.exists(os.path.join(sb, "out", "base-artifact.txt")), \
        "a trial must not write its arms' work into the live expert"
    print(f"[isolation] each arm ran in its own clone of the expert; two "
          f"identical charters scored identically "
          f"({r['base']['passes']} = {r['variant']['passes']}), and neither "
          f"arm's artifacts reached the live root")


if __name__ == "__main__":
    main()
