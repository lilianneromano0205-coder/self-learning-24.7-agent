#!/usr/bin/env python3
"""Quick Specialists — spin up a working expert in seconds, not study-days.

A quick agent is NOT a lighter system. It is a full expert in the same
harness — same five tools, same done-gates, same budget brakes, same fenced
context, same memory, escalation, and recall — that skips the deep training.
Instead of studied courses it gets a BRIEFING: the files you hand it become
instant grounded memory (converted deterministically, no model cost), its
kind decides its tools, and operators get an automatic Examiner review
chained after their work. One verification layer fewer than a trained
expert; every other guarantee identical. That is the honest difference
between the trained experts' bar and the quick tier's.

Kinds (auto-detected from the work, or chosen):
  advisor   answers/reviews/recommends — Consultant role, no shell
  maker     writes/drafts/designs/plans — Practitioner doing document work
  operator  builds/runs/deploys/fixes — Practitioner with shell, and every
            finished job is independently reviewed by the Examiner (chained)

Usage:
  python quick.py spin "Name" --specialty "…" --goal "…"
        [--kind auto|advisor|maker|operator] [--file PATH …]
        [--deliverable REL_PATH] [--home DIR] [--drive]
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)
import fleet          # noqa: E402
import ingest         # noqa: E402
import loop           # noqa: E402
import templates      # noqa: E402
import toolbox        # noqa: E402

KIND_WORDS = {
    "operator": ("build", "code", "deploy", "run", "execute", "script",
                 "install", "fix", "automate", "scrape", "test", "implement",
                 "configure", "migrate", "debug"),
    "advisor": ("advise", "answer", "review", "explain", "consult",
                "recommend", "diagnose", "assess", "evaluate", "question",
                "compare", "audit"),
    "maker": ("write", "draft", "design", "plan", "create", "compose",
              "translate", "summarize", "report", "outline", "produce",
              "document", "brief"),
}
CHARTER = """# IDENTITY — {name} (Quick Specialist)
You are {name}, a rapid-deployment specialist.
Specialty and mission: {specialty}

OPERATING CHARTER (quick mode):
- Your BRIEFING (courses/briefing/) is your primary truth. Your general
  knowledge may fill gaps but NEVER contradicts the briefing; where they
  conflict, the briefing wins and you say so explicitly.
- Claims drawn from the briefing cite their file: [src: briefing/<file>].
- What neither the briefing nor solid knowledge supports is marked
  UNVERIFIED — flagged uncertainty beats confident error, every time.
- You carry the same gates as every expert here: your work must pass its
  definition of done, your claims are hints, and only artifacts are proof.
"""


def classify(goal, specialty=""):
    """Deterministic, transparent kind detection — no model, no surprises."""
    words = set(re.findall(r"[a-z]+", (goal + " " + specialty).lower()))
    scores = {k: len(words & set(v)) for k, v in KIND_WORDS.items()}
    best = max(scores, key=lambda k: (scores[k], k == "maker"))
    return best if scores[best] > 0 else "maker"


def create(home, name, specialty):
    """Mint the quick expert: a normal fleet expert with the quick charter."""
    dest = fleet.create(home, name, specialty)
    with open(os.path.join(dest, "identity.md"), "w", encoding="utf-8") as f:
        f.write(CHARTER.format(name=name, specialty=specialty
                               or "whatever the briefing and goal define"))
    os.makedirs(os.path.join(dest, "briefing"), exist_ok=True)
    return dest


def _enable_review_chain(root):
    """Operators get their work independently reviewed: chain the Examiner
    after every Practitioner task, in this expert's own settings."""
    p = os.path.join(root, "settings.toml")
    with open(p, "r", encoding="utf-8-sig") as f:
        text = f.read()
    if re.search(r'^\s*practitioner\s*=\s*"examiner"', text, re.M):
        return
    if "[agent.chain]" in text:
        text = text.replace("[agent.chain]",
                            '[agent.chain]\npractitioner = "examiner"', 1)
    else:
        text += '\n[agent.chain]\npractitioner = "examiner"\n'
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def ingest_briefing(root):
    """Turn briefing/ files into instant memory — deterministically where the
    format allows (text, html, subtitles, pdf, docs: zero model cost), via a
    queued Ripper only where a model is unavoidable (images, audio, video).
    Returns (memory_files, ripper_task_ids)."""
    src_dir = os.path.join(root, "briefing")
    course_dir = os.path.join(root, "courses", "briefing")
    lessons_dir = os.path.join(course_dir, "lessons")
    os.makedirs(os.path.join(course_dir, "source"), exist_ok=True)
    os.makedirs(lessons_dir, exist_ok=True)
    agent = loop.Agent(root)
    memory, rippers, index_lines = [], [], []
    files = sorted(f for f in os.listdir(src_dir)
                   if os.path.isfile(os.path.join(src_dir, f))) \
        if os.path.isdir(src_dir) else []
    for fn in files:
        path = os.path.join(src_dir, fn)
        kind = ingest.classify(fn)
        nn = f"{len(index_lines) + 1:02d}"
        ldir = os.path.join(lessons_dir, nn)
        os.makedirs(ldir, exist_ok=True)
        dst = os.path.join(ldir, "lesson.md")
        rel = f"courses/briefing/lessons/{nn}/lesson.md"
        shutil.copy(path, os.path.join(course_dir, "source", fn))
        try:
            if kind in ("text", "html", "subs"):
                with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                    raw = f.read()
                body = (ingest.html_to_text(raw) if kind == "html"
                        else ingest.subs_to_text(raw) if kind == "subs" else raw)
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(f"SOURCE-FILE: briefing/{fn}\n\n{body}")
            elif kind == "pdf":
                ingest.pdf_text(path, dst)
            elif kind == "docx":
                ingest.docx_convert(path, dst)
            else:
                raise ValueError(f"needs a model ({kind})")
            memory.append(rel)
        except SystemExit as e:      # converter missing → let the Ripper try
            rippers.append(_queue_ripper(agent, fn, nn, rel, str(e)))
            memory.append(rel)
        except Exception as e:       # images/audio/video → Ripper with a model
            rippers.append(_queue_ripper(agent, fn, nn, rel, str(e)))
            memory.append(rel)
        index_lines.append(f"{nn} | {fn} | briefing |")
    with open(os.path.join(course_dir, "index.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(index_lines) + ("\n" if index_lines else ""))
    return memory, rippers


def _queue_ripper(agent, fn, nn, rel, why):
    return agent.add_task(
        "ripper",
        f"Ingest briefing file courses/briefing/source/{fn} into {rel} "
        f"(deterministic conversion unavailable: {why}). Use the ingest.py "
        f"helpers via run_command (vision for images, chunk-audio+transcribe "
        f"for audio/video, pdf-pages+vision for scanned pdf). End state: {rel} "
        f"holds the content as text.",
        course="briefing",
        done_check=(f'"{sys.executable}" -c "import os,sys;'
                    f"sys.exit(0 if os.path.exists(r'{rel}') else 1)\""))


def launch(root, goal, kind="auto", deliverable=None, specialty=""):
    """Arm the quick agent: briefing → memory, kind → role and tools, goal →
    its first gated task. Returns (resolved_kind, task_id)."""
    if kind in (None, "", "auto"):
        kind = classify(goal, specialty)
    memory, _rippers = ingest_briefing(root)
    # the agent is TOLD what tools exist on this machine — it never guesses
    caps_rel = "courses/briefing/capabilities.md"
    caps_path = os.path.join(root, caps_rel)
    os.makedirs(os.path.dirname(caps_path), exist_ok=True)
    with open(caps_path, "w", encoding="utf-8") as f:
        f.write(toolbox.capability_note(root))
    memory = [caps_rel] + memory
    agent = loop.Agent(root)
    if kind == "operator":
        _enable_review_chain(root)
    done = None
    if deliverable:
        deliverable = deliverable.replace("\\", "/")
        done = (f'"{sys.executable}" -c "import os,sys;'
                f"sys.exit(0 if os.path.exists(r'{deliverable}') else 1)\"")
        # An INTERFACE deliverable must also survive the design gate. "Make
        # it beautiful, not generic" is not enforceable as a prompt; the
        # specific failures are (contrast, scale, semantics, the filler
        # tells). designcheck also fails on a missing file, so it subsumes
        # the existence check above.
        design_gate = (loop.Agent(root).cfg.get("agent", {})
                       .get("design_gate", True))
        if design_gate and deliverable.lower().endswith(
                (".html", ".htm", ".css", ".jsx", ".tsx", ".vue", ".svelte")):
            gate = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "designcheck.py")
            done = f'"{sys.executable}" "{gate}" "{deliverable}"'
    if kind == "advisor":
        out_rel = deliverable or f"answers/quick-{time.strftime('%Y%m%d-%H%M%S')}.md"
        done = done or (f'"{sys.executable}" -c "import os,sys;'
                        f"sys.exit(0 if os.path.exists(r'{out_rel}') else 1)\"")
        tid = agent.add_task(
            "consultant",
            f"QUICK CONSULTATION: {goal}\nGround your answer in the briefing "
            f"in your context, citing [src: briefing/<file>] per claim; mark "
            f"anything beyond it UNVERIFIED. Write the complete answer to "
            f"{out_rel}, then finish_task.",
            memory_files=memory, course="briefing", done_check=done)
    else:
        tid = agent.add_task(
            "practitioner",
            f"QUICK JOB ({kind}): {goal}\nYour briefing is in context — it "
            f"outranks your general knowledge wherever they touch. "
            + (f"The deliverable that defines done: {deliverable}. "
               if deliverable else "")
            + "Produce real artifacts; your claims are hints, files are proof.",
            memory_files=memory, course="briefing", done_check=done)
    return kind, tid


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("templates", help="list the pre-built specialists")
    p = sub.add_parser("spin")
    p.add_argument("name")
    p.add_argument("--template", default=None,
                   help="start from a pre-built specialist (see: templates)")
    p.add_argument("--specialty", default="")
    p.add_argument("--goal", required=True)
    p.add_argument("--kind", default="auto",
                   choices=["auto", "advisor", "maker", "operator"])
    p.add_argument("--file", action="append", default=[],
                   help="briefing file (repeatable): docs, pdf, html, images…")
    p.add_argument("--deliverable", default=None,
                   help="path that must exist for the job to count as done")
    p.add_argument("--home", default=HOME)
    p.add_argument("--drive", action="store_true",
                   help="run the agent to completion right now")
    args = ap.parse_args()

    if args.cmd == "templates":
        for t in templates.all_templates():
            print(f"{t['slug']:<20} {t['kind']:<9} {t['name']}")
        return

    if args.template:
        t = templates.get(args.template)
        args.specialty = args.specialty or t["specialty"]
        if args.kind == "auto":
            args.kind = t["kind"]
        args.deliverable = args.deliverable or t["deliverable_hint"]
    dest = create(args.home, args.name, args.specialty)
    for f in args.file:
        shutil.copy(f, os.path.join(dest, "briefing", os.path.basename(f)))
    kind, tid = launch(dest, args.goal, args.kind,
                       args.deliverable, args.specialty)
    slug = os.path.basename(dest)
    print(f"quick specialist '{slug}' armed: kind={kind}, task={tid}")
    if args.drive:
        subprocess.run([sys.executable, os.path.join(HOME, "loop.py"),
                        "run", "--drain", "--root", dest],
                       env={**os.environ, "PYTHONUTF8": "1"})
    else:
        print(f"run it:  python loop.py run --root {dest}   (or Start in the panel)")


if __name__ == "__main__":
    main()
