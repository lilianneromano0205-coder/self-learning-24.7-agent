#!/usr/bin/env python3
"""Consultant mode: the expert for fields no agent can execute.

1. citecheck unit contract: a real citation passes; a fabricated one fails
   with the ghost named; an uncited essay fails; the honest blank passes.
2. Full consultation flow: harness-side retrieval injects the right notes,
   the Consultant's FIRST answer cites a ghost atom -> the done gate REFUSES
   delivery -> the corrected, grounded answer ships. A hallucinated citation
   is structurally undeliverable.

Run from the agent/ directory:  python tests/test_consult.py
"""

import json
import os
import subprocess
import sys

from common import AGENT_DIR, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import citecheck
import consult

PY = sys.executable
NOTES = ("# L01 — Beta-blockers\n"
         "## Claims & procedures\n"
         "- C-0101 Beta-blockers reduce myocardial oxygen demand "
         "[src: lecture 12:40]\n"
         "- P-0102 Contraindicated in severe asthma [src: lecture 14:05]\n")


def write(sb, rel, text):
    p = os.path.join(sb, rel)
    os.makedirs(os.path.dirname(p) or sb, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    # --- 1. the citation gate, all four verdicts
    sb = make_sandbox("citegate", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []})
    write(sb, "courses/cardio/lessons/01/notes.md", NOTES)
    write(sb, "a1.md", "Beta-blockers lower oxygen demand [C-0101].")
    assert citecheck.check(sb, os.path.join(sb, "a1.md"))[0] == []
    probs, _, _ = citecheck.check(sb, os.path.join(sb, "a2.md")) \
        if write(sb, "a2.md", "Dosage is 5mg twice daily [C-9999].") is None else (None,)*3
    assert probs and "C-9999" in probs[0], "the ghost atom must be named"
    write(sb, "a3.md", "Just take some medicine, probably fine.")
    assert citecheck.check(sb, os.path.join(sb, "a3.md"))[0], \
        "an uncited essay must fail"
    write(sb, "a4.md", "Pediatric dosing: NOT IN MY TRAINING.")
    assert citecheck.check(sb, os.path.join(sb, "a4.md"))[0] == [], \
        "the honest blank must pass"
    print("[gate] real citation passes; ghost named and failed; uncited essay "
          "failed; honest blank passes")

    # --- 2. full flow: the first (hallucinated) answer cannot ship
    sb = make_sandbox("consultflow", providers={"m": {"script": "s.json"}},
                      roles={"consultant": "m"}, scripts={"s.json": []})
    write(sb, "courses/cardio/lessons/01/notes.md", NOTES)
    write(sb, "courses/cardio/index.md", "01 | beta-blockers: action and contraindications |\n")
    tid, answer_rel = consult.start_consult(
        sb, "When are beta-blockers contraindicated?")

    # the harness chose the evidence: index + the notes file with the answer
    with open(os.path.join(sb, "state.json"), encoding="utf-8") as f:
        task = next(t for t in json.load(f)["tasks"] if t["id"] == tid)
    assert "courses/cardio/index.md" in task["memory_files"]
    assert "courses/cardio/lessons/01/notes.md" in task["memory_files"], \
        "recall must have retrieved the notes containing the answer"
    assert task["done_check"] and "citecheck" in task["done_check"]

    # scripted consultant: hallucinates first, then corrects itself
    write(sb, "s.json", "")  # replaced below with proper json
    with open(os.path.join(sb, "s.json"), "w", encoding="utf-8") as f:
        json.dump([
            {"tool": "write_file", "args": {"path": answer_rel,
             "content": "Contraindicated whenever cortisol is high [C-7777]."}},
            {"tool": "finish_task", "args": {"summary": "answered"}},
            {"tool": "write_file", "args": {"path": answer_rel,
             "content": "Contraindicated in severe asthma [P-0102]; they act "
                        "by reducing myocardial oxygen demand [C-0101]. "
                        "Pediatric specifics: NOT IN MY TRAINING."}},
            {"tool": "finish_task", "args": {"summary": "grounded answer delivered"}},
        ], f)
    assert run_drain(sb) == 0
    t = read_state(sb)["tasks"][0]
    assert t["status"] == "done", (t["status"], t.get("error"))
    assert t["done_rejects"] == 1, \
        f"the hallucinated answer must be refused exactly once, got {t.get('done_rejects')}"
    with open(os.path.join(sb, t["context_ref"]), encoding="utf-8") as f:
        ctx = json.load(f)
    refusal = next(m["content"] for m in ctx if m.get("role") == "tool"
                   and "REFUSED" in (m.get("content") or ""))
    assert "C-7777" in refusal, "the refusal must name the fabricated citation"
    final = open(os.path.join(sb, answer_rel), encoding="utf-8").read()
    assert "P-0102" in final and "NOT IN MY TRAINING" in final
    listed = consult.list_consults(sb)
    assert listed and listed[0]["answered"] and "P-0102" in listed[0]["answer_text"]
    print("[flow] hallucinated citation blocked at the gate (C-7777 named), "
          "corrected answer shipped with real citations + honest blank")
    print("PASS test_consult")


if __name__ == "__main__":
    main()
