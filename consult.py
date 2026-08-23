#!/usr/bin/env python3
"""Consult an expert — the mode for fields an agent cannot execute.

A cardiology expert can't operate, but it can be the consultation-grade
companion that knows its trained material better than anyone: ask it a
question, get an answer grounded ONLY in what it studied.

How a consultation stays hallucination-free, structurally:
  1. Retrieval is done by the HARNESS, not the model: recall.py searches the
     expert's whole mind for the question's terms, and the top source files
     (plus every course index) are injected into context as fenced data.
  2. The Consultant role holds no shell — it can only read, write, finish.
  3. The answer's done_check is citecheck.py: every atom ID cited must be
     DEFINED in the notes, and uncovered ground must say NOT IN MY TRAINING.
     finish_task is refused until that passes — an answer with a fabricated
     citation is impossible to deliver, whatever the model claims.

Usage:
  python consult.py ask "question…" [--root EXPERT_DIR] [--drive] [--wait]
  python consult.py list [--root EXPERT_DIR]
"""

import argparse
import json
import os
import secrets
import subprocess
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)
import loop           # noqa: E402
import recall         # noqa: E402

MAX_SOURCE_FILES = 5


def start_consult(root, question):
    """Prepare and queue one consultation. Returns (task_id, answer_relpath)."""
    agent = loop.Agent(root)
    # a second-resolution id collides when two questions arrive inside the
    # same second (two peers asking at once, or a burst from one) — the second
    # consultation would then overwrite the first one's question and answer.
    # The suffix makes every consultation its own directory, always.
    cid = time.strftime("c-%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
    cdir = os.path.join(root, "consults", cid)
    os.makedirs(cdir, exist_ok=True)
    with open(os.path.join(cdir, "question.md"), "w", encoding="utf-8") as f:
        f.write(question.strip() + "\n")

    # harness-side retrieval: the model never chooses its own evidence
    memory = []
    courses_dir = os.path.join(root, "courses")
    if os.path.isdir(courses_dir):
        for c in sorted(os.listdir(courses_dir)):
            idx = os.path.join(courses_dir, c, "index.md")
            if os.path.exists(idx):
                memory.append(f"courses/{c}/index.md")
    for score, loc, snippet in recall.search(root, question, limit=24):
        path = loc.rsplit(":", 1)[0]
        if path.startswith("contexts/") or not path.endswith((".md", ".txt")):
            continue
        if path not in memory:
            memory.append(path)
        if len(memory) >= len([m for m in memory if "index.md" in m]) + MAX_SOURCE_FILES:
            break
    memory.append(f"consults/{cid}/question.md")

    # AGENTIC RETRIEVAL: establish the facts the question rests on BEFORE it
    # is answered, one sub-question at a time, and hand the consultant what
    # was found AND what was not. A gap it can see is a gap it declares
    # instead of filling. Never fatal: a failed brief just means the old
    # single-shot path.
    brief_rel = None
    try:
        import research
        brief = research.investigate(root, question)
        if brief.get("subs"):
            brief_rel = research.save(root, question, brief)
            memory.insert(0, brief_rel)
    except Exception:
        brief_rel = None

    answer_rel = f"consults/{cid}/answer.md"
    done = (f'"{sys.executable}" "{os.path.join(HOME, "citecheck.py")}" '
            f'"{answer_rel}" --root .')
    tid = agent.add_task(
        "consultant",
        f"CONSULTATION {cid}: answer the question in consults/{cid}/question.md "
        f"and write your COMPLETE answer to {answer_rel}. Ground every claim in "
        f"your training: cite the atom IDs (C-/P-nnnn) from your notes beside "
        f"each claim, exactly as they appear there. Structure the answer for a "
        f"professional reader. For anything the question asks that your "
        f"training does not cover, write exactly: NOT IN MY TRAINING — an "
        f"honest gap outranks a guess, always. The done gate mechanically "
        f"verifies every citation resolves; fabricated citations cannot ship."
        + (f"\nA RESEARCH BRIEF is in your context ({brief_rel}): the "
           f"question was decomposed and each part retrieved separately. "
           f"Anything it marks NOTHING FOUND is a gap you must declare, not "
           f"fill." if brief_rel else ""),
        memory_files=memory, done_check=done)
    with open(os.path.join(cdir, "consult.json"), "w", encoding="utf-8") as f:
        json.dump({"id": cid, "task": tid, "question": question,
                   "answer": answer_rel, "sources": memory,
                   "asked": time.strftime("%Y-%m-%dT%H:%M:%S")}, f, indent=2)
    return tid, answer_rel


def list_consults(root, limit=10):
    base = os.path.join(root, "consults")
    out = []
    task_status = {}
    try:
        with open(os.path.join(root, "state.json"), "r", encoding="utf-8") as f:
            for t in json.load(f)["tasks"]:
                task_status[t["id"]] = (t["status"], (t.get("error") or "")[:200])
    except (OSError, json.JSONDecodeError):
        pass
    if os.path.isdir(base):
        for cid in sorted(os.listdir(base), reverse=True)[:limit]:
            meta = os.path.join(base, cid, "consult.json")
            try:
                with open(meta, "r", encoding="utf-8") as f:
                    m = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            ans = os.path.join(root, m["answer"])
            m["answered"] = os.path.exists(ans) and \
                task_status.get(m.get("task"), ("", ""))[0] == "done"
            st, err = task_status.get(m.get("task"), ("pending", ""))
            m["status"], m["error"] = st, err
            if os.path.exists(ans):
                with open(ans, "r", encoding="utf-8", errors="replace") as f:
                    m["answer_text"] = f.read()[:6000]
            out.append(m)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ask")
    p.add_argument("question")
    p.add_argument("--root", default=".")
    p.add_argument("--drive", action="store_true",
                   help="run the expert's loop to completion right now")
    p = sub.add_parser("list")
    p.add_argument("--root", default=".")
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    if args.cmd == "ask":
        tid, answer_rel = start_consult(root, args.question)
        print(f"consultation queued: task {tid} -> {answer_rel}")
        if args.drive:
            subprocess.run([sys.executable, os.path.join(HOME, "loop.py"),
                            "run", "--drain", "--root", root],
                           env={**os.environ, "PYTHONUTF8": "1"})
            p = os.path.join(root, answer_rel)
            if os.path.exists(p):
                print("\n" + open(p, encoding="utf-8").read())
    elif args.cmd == "list":
        for m in list_consults(root):
            mark = "answered" if m["answered"] else "pending"
            print(f"{m['id']}  [{mark}]  {m['question'][:70]}")


if __name__ == "__main__":
    main()
