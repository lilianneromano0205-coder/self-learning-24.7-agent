#!/usr/bin/env python3
"""Goal pursuit + the commons: the smart loop that will not stop early.

1. A goal is planned into gated milestones, worked, judged by a different
   model family, and — crucially — the judge's verdict is RE-CHECKED against
   the mechanical checks: a judge that says ACHIEVED while a check still
   fails is OVERRULED, and the pursuit continues into another cycle.
2. Cycle 2 receives the previous assessment and the goal completes; a
   learning-shaped goal gets a study-shaped plan.
3. Failures become fleet LESSONS in the commons, deduplicated, and the
   commons digest reaches every expert's context.
4. Peer consultation: one expert asks another and gets its citation-gated
   answer back.

Run from the agent/ directory:  python tests/test_goal.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import commons
import fleet
import goal
import loop

PY = sys.executable

SETTINGS = """[agent]
sandbox = "host"
allow_unsafe_host = true
poll_interval_seconds = 1
inbox_settle_seconds = 0
max_task_usd = 0
reflect_after = []
max_done_rejects = 3

[providers.work]
type = "mock"
script = "scripts/work.json"

[providers.judge]
type = "mock"
script = "scripts/judge.json"

[roles.default]
provider = "work"
model = "mock"

[roles.practitioner]
provider = "work"
model = "mock"

[roles.examiner]
provider = "judge"
model = "mock"

[roles.consultant]
provider = "work"
model = "mock"
tools = ["read_file", "write_file", "finish_task", "ask_human"]
"""


def wire(root, work, judge):
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write(SETTINGS)
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    for name, s in (("work.json", work), ("judge.json", judge)):
        with open(os.path.join(root, "scripts", name), "w", encoding="utf-8") as f:
            json.dump(s, f)


def main():
    home = make_sandbox("goal", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Goal Runner", "pursuing objectives")
    GD = "goals/g-test"
    trophy = os.path.join(root, "trophy.txt").replace("\\", "/")
    check = f'"{PY}" -c "import os,sys;sys.exit(0 if os.path.exists(r\'{trophy}\') else 1)"'

    # Every task replays its provider's script from the start, so one script
    # serves all of them; what differs is each task's GATE, which decides how
    # far it must get. Cycle 1's milestone is given an unsatisfiable check —
    # it fails, yet the judge lies and says ACHIEVED, so the harness must
    # overrule and force cycle 2, whose check the work really does satisfy.
    impossible = (f'"{PY}" -c "import os,sys;'
                  f"sys.exit(0 if os.path.exists(r'{root}/never-exists') else 1)\"")
    work = [
        {"tool": "write_file", "args": {"path": f"{GD}/plan-1.md",
         "content": f"- M1: claim the trophy CHECK: {impossible}\n"}},
        {"tool": "write_file", "args": {"path": f"{GD}/plan-2.md",
         "content": f"- M1: actually create the trophy CHECK: {check}\n"}},
        {"tool": "write_file", "args": {"path": "trophy.txt", "content": "real"}},
        {"tool": "write_file", "args": {"path": f"{GD}/m1-1.md",
         "content": "cycle 1 evidence (the claim was hollow)\n"}},
        {"tool": "write_file", "args": {"path": f"{GD}/m2-1.md",
         "content": "cycle 2 evidence: trophy.txt exists\n"}},
        {"tool": "finish_task", "args": {"summary": "step done"}},
        {"tool": "finish_task", "args": {"summary": "retry finish"}},
        {"tool": "finish_task", "args": {"summary": "retry finish"}},
    ]
    judge = [
        {"tool": "write_file", "args": {"path": f"{GD}/assessment-1.md",
         "content": "Everything looks great to me.\nVERDICT: ACHIEVED\n"}},
        {"tool": "finish_task", "args": {"summary": "judged c1"}},
        {"tool": "write_file", "args": {"path": f"{GD}/assessment-2.md",
         "content": "trophy.txt verified on disk.\nVERDICT: ACHIEVED\n"}},
        {"tool": "finish_task", "args": {"summary": "judged c2"}},
    ]
    wire(root, work, judge)

    rec = goal.pursue(home, "goal-runner", "produce the trophy artifact",
                      criteria="trophy.txt exists", cycles=3, drive=True,
                      timeout=240, gid="g-test")

    assert rec["status"] == "achieved", rec
    assert len(rec["cycles"]) == 2, \
        f"the lying judge must have forced a second cycle, got {len(rec['cycles'])}"
    assert rec["cycles"][0]["verdict"] == "NOT ACHIEVED", \
        "cycle 1's ACHIEVED must have been overruled by the failing check"
    assert rec["cycles"][1]["verdict"] == "ACHIEVED"
    ov = rec["cycles"][0].get("overruled")
    assert ov and ov["claimed"] == "ACHIEVED" and ov["failing"] == ["M1"], \
        f"the overrule must be recorded durably in the goal record: {ov}"
    assert not rec["cycles"][1].get("overruled"), \
        "a truthful ACHIEVED must stand un-overruled"
    # the record survives on disk for the UI and for forensics
    saved = json.load(open(os.path.join(root, GD, "goal.json"), encoding="utf-8"))
    assert saved["cycles"][0]["overruled"]["failing"] == ["M1"]
    assert os.path.exists(os.path.join(root, "trophy.txt"))
    print("[judge] a judge claiming ACHIEVED while a check failed was OVERRULED; "
          "the pursuit continued and finished the work for real")

    # cycle 2's planner received cycle 1's assessment
    tasks = json.load(open(os.path.join(root, "state.json"),
                           encoding="utf-8"))["tasks"]
    plan2 = [t for t in tasks if "PLAN cycle 2" in t["goal"]][0]
    assert f"{GD}/assessment-1.md" in plan2["memory_files"], plan2["memory_files"]
    assert "attack exactly what it found missing" in plan2["goal"]
    print("[replan] cycle 2 planned WITH the previous assessment in hand")

    # a learning goal gets the study-shaped plan
    assert goal._is_learning("learn hypertension pharmacology")
    assert goal._is_learning("master the Shopify API")
    assert not goal._is_learning("rebuild the pricing page")
    plan1 = [t for t in tasks if "PLAN cycle 1" in t["goal"]][0]
    assert "closed-book" not in plan1["goal"], "a build goal must not get the study shape"
    print("[shape] learning goals detected; build goals keep a build-shaped plan")

    # --- the commons: failures became binding fleet lessons, deduplicated
    lessons = open(os.path.join(home, "commons", "lessons.md"),
                   encoding="utf-8").read()
    assert "evaluator declared a goal ACHIEVED" in lessons, lessons
    assert commons.learn(home, "a brand new lesson", "x") is True
    assert commons.learn(home, "a brand new lesson", "y") is False, \
        "an identical lesson must not be written twice"
    assert "hit again" in open(os.path.join(home, "commons", "lessons.md"),
                               encoding="utf-8").read()
    commons.refresh_directory(home)
    d = commons.digest(home)
    assert "FLEET LESSONS" in d and "goal-runner" in d, d[:200]
    print("[commons] the overruled-judge failure became a binding fleet lesson; "
          "duplicates collapse into repeat markers; the directory lists who knows what")

    # the digest reaches an expert's context as the FIRST block
    commons.write_digest(home, root)
    a = loop.Agent(root)
    msgs = a.initial_messages({"role": "practitioner", "goal": "x",
                               "memory_files": [], "course": None})
    # the window opens with the agent's own self-model, then the commons —
    # both ahead of the task line, and both ahead of any material
    head = msgs[1]["content"][:1600]
    assert head.startswith("SELF —"), head[:120]
    assert "COMMONS" in head, \
        "the commons must be injected at the top of every task's context"
    assert head.index("SELF —") < head.index("COMMONS") < \
        msgs[1]["content"].index("Task: x")
    print("[share] every task now opens with what the agent has verified about "
          "itself, then the fleet's shared memory")

    # --- peer consultation: one expert asks another
    peer = fleet.create(home, "Peer Sage", "answering peers")
    wire(peer, [{"tool": "write_file",
                 "args": {"path": "ANSWER", "content": "see below"}},
                {"tool": "finish_task", "args": {"summary": "x"}}], [])
    tid, rel, _ = commons.ask(home, "peer-sage", "what is the retry limit?",
                              from_expert="goal-runner")
    ptasks = json.load(open(os.path.join(peer, "state.json"),
                            encoding="utf-8"))["tasks"]
    t = next(x for x in ptasks if x["id"] == tid)
    assert t["role"] == "consultant" and "citecheck" in (t["done_check"] or ""), t
    q = open(os.path.join(peer, os.path.dirname(rel), "question.md"),
             encoding="utf-8").read()
    assert "from goal-runner" in q and "NOT IN MY TRAINING" in q
    print("[peer] one expert asked another; the answer runs through the peer's "
          "own citation gate, attributed to the asker")
    print("PASS test_goal")


if __name__ == "__main__":
    main()
