#!/usr/bin/env python3
"""The Skill Graph: procedural memory with a promotion gate (HyperSkill +
the Fragility-of-Self-Improving-Agents correction).

1. One success NEVER makes a canonical skill: promotion to PROVEN requires
   >= 3 DISTINCT winning tasks, at least one gate-verified, wins > losses.
   The same task retried is one piece of evidence, not three.
2. Repeat losers are QUARANTINED — excluded from auto-injection but kept on
   disk (a verdict, not a deletion); one later verified win redeems them.
3. Selection is graph-aware: proven outranks candidate, quarantined never
   loads, and a skill's declared USES pull its sub-skills in (one hop).
4. Injected skill blocks are stamped with their earned status, and the LOOP
   files each task's outcome against the skills it loaded — automatically.

Run from the agent/ directory:  python tests/test_skillgraph.py
"""

import json
import os
import sys

from common import AGENT_DIR, add_task, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import skills as sg

PY = sys.executable


def write_skill(sb, name, body, keywords=""):
    os.makedirs(os.path.join(sb, "skills"), exist_ok=True)
    with open(os.path.join(sb, "skills", f"{name}.md"), "w",
              encoding="utf-8") as f:
        if keywords:
            f.write(f"KEYWORDS: {keywords}\n")
        f.write(body)


def main():
    sb = make_sandbox("skillgraph", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []})

    # --- 1. the promotion gate. Co-occurrence — however many wins — never
    # promotes: loaded-when-it-worked is not caused-it-to-work. Only a
    # matched held-out ablation, where the same cases run WITH and WITHOUT
    # the skill and an independent grader scores both, earns "proven".
    write_skill(sb, "seo-audit", "steps...\n", "audit, seo")
    rel = "skills/seo-audit.md"
    sg.record_use(sb, [rel], "t1", success=True, verified=True)
    sg.record_use(sb, [rel], "t2", success=True, verified=False)
    sg.record_use(sb, [rel], "t2", success=True, verified=False)
    changed = sg.record_use(sb, [rel], "t3", success=True, verified=False)
    assert changed == {}, changed
    assert sg.status_of(sb, rel) == "candidate", \
        "co-occurrence wins must NOT promote — that is how superstitions form"

    def helps(case, workdir, injected, seed):
        return case["input"]["x"] * (2 if injected else 1)

    def grade(case, out):
        return out == case["expected"]

    held = [{"id": f"held-{i}", "input": {"x": i}, "expected": i * 2}
            for i in range(1, 7)]
    rec = sg.run_ablation(sb, rel, held, helps, grade, seed=7)
    assert rec["status"] == "COMPLETE", rec
    assert sg.status_of(sb, rel) == "proven"
    print("[gate] co-occurrence wins stayed candidate; only a matched "
          "held-out ablation (6 discordant pairs, sign test) earned PROVEN")

    # --- 2. quarantine and redemption — both are ablation verdicts now
    write_skill(sb, "flaky-trick", "bad advice\n", "flaky")
    frel = "skills/flaky-trick.md"
    for i in range(3):
        sg.record_use(sb, [frel], f"f{i}", success=False)
    assert sg.status_of(sb, frel) == "candidate", \
        "co-occurrence losses do not quarantine — same rule as promotion"

    def harms(case, workdir, injected, seed):
        return case["input"]["x"] * (1 if injected else 2)

    harm_cases = [{"id": f"harm-{i}", "input": {"x": i}, "expected": i * 2}
                  for i in range(1, 7)]
    sg.run_ablation(sb, frel, harm_cases, harms, grade, seed=11)
    assert sg.status_of(sb, frel) == "quarantined"
    assert os.path.exists(os.path.join(sb, frel)), \
        "quarantine is a verdict, not a deletion"

    def tie(case, workdir, injected, seed):
        return case["input"]["x"] * 2

    tie_cases = [{"id": f"tie-{i}", "input": {"x": i}, "expected": i * 2}
                 for i in range(1, 7)]
    sg.run_ablation(sb, frel, tie_cases, tie, grade, seed=13)
    assert sg.status_of(sb, frel) == "candidate", \
        "a contradictory (non-significant) ablation redeems to candidate"
    harm2 = [{"id": f"again-{i}", "input": {"x": i}, "expected": i * 2}
             for i in range(1, 7)]
    sg.run_ablation(sb, frel, harm2, harms, grade, seed=17)
    assert sg.status_of(sb, frel) == "quarantined"
    print("[quarantine] a harm-showing ablation quarantined the skill; a "
          "contradictory one redeemed it; fresh harm evidence re-quarantined")

    # --- 3. graph-aware selection: order, exclusion, one-hop composition
    write_skill(sb, "find-competitors", "how to find them\n", "competitors")
    write_skill(sb, "competitive-analysis",
                "USES: find-competitors\nfull procedure\n", "analysis")
    picked = sg.select(sb, ["skills/competitive-analysis.md",
                            "skills/flaky-trick.md",
                            "skills/seo-audit.md"], cap=3)
    assert "skills/flaky-trick.md" not in picked, \
        "a quarantined skill must never auto-inject"
    assert picked[0] == "skills/seo-audit.md", \
        f"PROVEN must outrank candidates, got {picked}"
    assert "skills/find-competitors.md" in picked, \
        "a selected skill must pull its declared sub-skill (one hop)"
    i_parent = picked.index("skills/competitive-analysis.md")
    i_sub = picked.index("skills/find-competitors.md")
    assert i_sub == i_parent + 1, "the sub-skill loads right after its parent"
    print("[select] proven first, quarantined excluded, USES pulled the "
          "sub-skill in directly after its parent")

    # --- status banners on injected blocks
    b = sg.annotate(sb, rel, "=== skills/seo-audit.md ===\nsteps...")
    assert "PROVEN" in b and "matched held-out ablation" in b, b
    b2 = sg.annotate(sb, "skills/competitive-analysis.md",
                     "=== skills/competitive-analysis.md ===\nx")
    assert "CANDIDATE" in b2 and "verify each step" in b2, b2
    print("[banner] injected skills carry their earned status — the model "
          "knows hypothesis from proven procedure")

    # --- 4. the loop files skill outcomes automatically
    sb2 = make_sandbox("skillgraph_loop", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"},
                       scripts={"s.json": [
                           {"tool": "write_file",
                            "args": {"path": "out/a.txt", "content": "x"}},
                           {"tool": "finish_task", "args": {"summary": "ok"}}]})
    write_skill(sb2, "write-things", "how to write files\n", "write, deploy")
    add_task(sb2, "tester", "write the deploy artifact")   # matches KEYWORDS
    # give it a real gate so the win counts as verified
    st = read_state(sb2)
    st["tasks"][0]["done_check"] = f'"{PY}" -c "import sys;sys.exit(0)"'
    with open(os.path.join(sb2, "state.json"), "w", encoding="utf-8") as f:
        json.dump(st, f)
    assert run_drain(sb2) == 0
    t = read_state(sb2)["tasks"][0]
    assert t["status"] == "done"
    assert t.get("skills_used") == ["skills/write-things.md"], \
        f"the task must record which skills it loaded: {t.get('skills_used')}"
    g = sg.load_graph(sb2)["write-things"]
    assert g["wins"] == 1 and g["verified_wins"] == 1 and \
        g["win_tasks"] == [t["id"]], g
    assert g["status"] == "candidate", "one win is still just a candidate"
    # the injected block carried the candidate banner
    with open(os.path.join(sb2, t["context_ref"]), "r", encoding="utf-8") as f:
        ctx = json.load(f)
    first_user = next(m["content"] for m in ctx if m["role"] == "user")
    assert "CANDIDATE" in first_user and "verify each step" in first_user, \
        "the status banner must reach the model's context"
    print("[loop] a drained task recorded its loaded skills, filed a verified "
          "win, stayed candidate at n=1, and its context carried the banner")
    print("PASS test_skillgraph")


if __name__ == "__main__":
    main()
