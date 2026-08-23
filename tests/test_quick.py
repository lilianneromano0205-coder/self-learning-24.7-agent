#!/usr/bin/env python3
"""Quick Specialists: spun up in seconds, still caged by every gate.

1. Kind auto-detection is deterministic and sensible.
2. Briefing files become instant grounded memory with ZERO model cost
   (text/html/vtt/pdf converted deterministically; an image queues a Ripper
   task ahead of the job); a briefing index is built.
3. The operator flow runs end to end: briefing in context, deliverable gated
   by done_check, and the finished job automatically chained into an
   independent Examiner review.
4. The advisor flow answers with its own gate, no shell in hand.

Run from the agent/ directory:  python tests/test_quick.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import quick

EXPERT_SETTINGS = """[agent]
poll_interval_seconds = 1
inbox_settle_seconds = 0
max_task_usd = 0
reflect_after = []

[providers.work]
type = "mock"
script = "scripts/work.json"

[providers.review]
type = "mock"
script = "scripts/review.json"

[providers.rip]
type = "mock"
script = "scripts/rip.json"

[roles.ripper]
provider = "rip"
model = "mock"

[roles.default]
provider = "work"
model = "mock"

[roles.practitioner]
provider = "work"
model = "mock"

[roles.consultant]
provider = "work"
model = "mock"
tools = ["read_file", "write_file", "finish_task", "ask_human"]

[roles.examiner]
provider = "review"
model = "mock"

[agent.chain]
"""


def wire(root, work, review=None, rip=None):
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write(EXPERT_SETTINGS)
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    for name, script in (("work.json", work), ("review.json", review or []),
                         ("rip.json", rip or [])):
        with open(os.path.join(root, "scripts", name), "w", encoding="utf-8") as f:
            json.dump(script, f)


def brief(root, fn, content, binary=False):
    p = os.path.join(root, "briefing", fn)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb" if binary else "w",
              **({} if binary else {"encoding": "utf-8"})) as f:
        f.write(content)


def main():
    # --- 1. the classifier
    assert quick.classify("build and deploy the scraper script") == "operator"
    assert quick.classify("answer questions and review contracts") == "advisor"
    assert quick.classify("draft the launch report") == "maker"
    assert quick.classify("bonjour") == "maker", "no signal -> safest kind"
    print("[kind] operator/advisor/maker detected; unknown defaults to maker")

    # --- 2 & 3. operator end to end
    home = make_sandbox("quick", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = quick.create(home, "Page Surgeon", "conversion-focused frontend")
    with open(os.path.join(root, "identity.md"), encoding="utf-8") as f:
        idn = f.read()
    assert "Quick Specialist" in idn and "UNVERIFIED" in idn \
        and "conversion-focused frontend" in idn
    brief(root, "style-guide.md", "# Style\nBoutons: toujours arrondis.\n")
    brief(root, "notes.html", "<html><title>T</title><script>x=1</script>"
                              "<body><p>Palette: teal only.</p></body></html>")
    brief(root, "talk.vtt", "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n"
                            "Keep pages under 100KB\n")
    brief(root, "logo.png", b"\x89PNG fake image bytes", binary=True)
    wire(root,
         # an interface deliverable is gated by designcheck.py, so the page
         # the mock "builds" has to actually clear the floor: a language, a
         # breakpoint, described images, labelled controls
         work=[{"tool": "write_file", "args": {"path": "out/landing.html",
                "content": '<!DOCTYPE html>\n<html lang="en"><head><style>\n'
                           '  body { color: #14161a; background: #ffffff; }\n'
                           '  .panel { max-width: 60ch; padding: 16px; }\n'
                           '  @media (max-width: 640px) { .panel { padding: 12px; } }\n'
                           '</style></head><body><main class="panel">\n'
                           '<h1>Teal, rounded, light</h1>\n'
                           '<img src="logo.png" alt="Teal circle with a white glyph">\n'
                           '<label for="e">Email</label><input id="e" type="email">\n'
                           '<button type="submit">Join</button>\n'
                           '</main></body></html>\n'}},
               {"tool": "finish_task", "args": {"summary": "page built per briefing"}}],
         review=[{"tool": "finish_task", "args": {"summary": "reviewed against briefing"}}],
         rip=[{"tool": "write_file",
               "args": {"path": "courses/briefing/lessons/01/lesson.md",
                        "content": "SOURCE-FILE: briefing/logo.png\n\nLogo: teal circle, white glyph."}},
              {"tool": "finish_task", "args": {"summary": "image described"}}])
    kind, tid = quick.launch(root, "build the landing page per the briefing",
                             "auto", deliverable="out/landing.html")
    assert kind == "operator"

    tasks = read_state(root)["tasks"]
    ripper = [t for t in tasks if t["role"] == "ripper"]
    job = next(t for t in tasks if t["id"] == tid)
    assert len(ripper) == 1 and "logo.png" in ripper[0]["goal"], \
        "the image (model-needing) must queue a Ripper"
    assert tasks.index(ripper[0]) < tasks.index(job), \
        "the Ripper must be queued AHEAD of the job (FIFO)"
    assert "out/landing.html" in (job["done_check"] or ""), "deliverable must gate done"
    mem = job["memory_files"]
    assert sum(1 for m in mem if m.startswith("courses/briefing/lessons/")) == 4, mem
    # deterministic conversions really happened, model-free — look lessons up
    # through the index, the way any reader (or the agent) would
    idx = open(os.path.join(root, "courses/briefing/index.md"), encoding="utf-8").read()
    nn_of = {line.split("|")[1].strip(): line.split("|")[0].strip()
             for line in idx.splitlines() if "|" in line}
    def lesson(fn):
        return open(os.path.join(root, "courses/briefing/lessons",
                                 nn_of[fn], "lesson.md"), encoding="utf-8").read()
    lhtml = lesson("notes.html")
    assert "teal only" in lhtml and "x=1" not in lhtml, "html stripped deterministically"
    assert "[00:00:01] Keep pages under 100KB" in lesson("talk.vtt"), \
        "vtt parsed deterministically"
    assert idx.count("|") >= 8 and "logo.png" in idx, "briefing index built"
    st = open(os.path.join(root, "settings.toml"), encoding="utf-8").read()
    assert 'practitioner = "examiner"' in st, "operator must get the review chain"
    print("[briefing] 3 files converted with zero model cost, image routed to a "
          "Ripper queued ahead of the job, index built, deliverable gated")

    assert run_drain(root) == 0
    tasks = read_state(root)["tasks"]
    def done(role):
        return any(t["role"] == role and t["status"] == "done" for t in tasks)
    assert done("practitioner")
    assert os.path.exists(os.path.join(root, "out", "landing.html"))
    assert done("examiner"), \
        "the operator's finished job must be independently reviewed"
    assert done("ripper"), "the image briefing must be ripped through its gate"
    assert "teal circle" in lesson("logo.png"), \
        "the ripped image description must land in the briefing memory"
    print("[operator] job done through its gate, Examiner review chained and done")

    # --- 4. advisor: gated answer, no shell role
    root2 = quick.create(home, "Contract Sage", "commercial contract review")
    brief(root2, "playbook.md", "Clause 7: indemnity is capped at fees paid.\n")
    wire(root2,
         work=[{"tool": "write_file", "args": {"path": "answers/a.md",
                "content": "Indemnity is capped at fees paid "
                           "[src: briefing/playbook.md]. Governing law: UNVERIFIED."}},
               {"tool": "finish_task", "args": {"summary": "advised"}}])
    kind, tid = quick.launch(root2, "answer: what does clause 7 cap?",
                             "auto", deliverable="answers/a.md")
    assert kind == "advisor"
    t = next(x for x in read_state(root2)["tasks"] if x["id"] == tid)
    assert t["role"] == "consultant"
    assert run_drain(root2) == 0
    ans = open(os.path.join(root2, "answers", "a.md"), encoding="utf-8").read()
    assert "[src: briefing/playbook.md]" in ans and "UNVERIFIED" in ans
    print("[advisor] question answered by the shell-less Consultant, briefing "
          "cited, unknown marked UNVERIFIED, delivery gated")
    print("PASS test_quick")


if __name__ == "__main__":
    main()
