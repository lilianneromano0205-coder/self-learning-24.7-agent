#!/usr/bin/env python3
"""Taste is not enforceable; SPECIFICS are (M10).

The promise "professional work, no generic AI slop" only means something if
something mechanical refuses the slop. This test proves it does:

1. the design gate catches what can be checked without an opinion --
   unreadable contrast, no breakpoint, a fixed width that overflows a phone,
   missing lang/alt/label, a div with onclick, lorem ipsum
2. it catches the FINGERPRINTS of unconsidered output: the default
   indigo/violet palette, emoji as icons, everything centred, stock copy
3. a considered page passes cleanly -- the gate is not just "reject
   everything"
4. STANDARDS are extracted from the expert's own verified material, a
   CONTESTED point is refused as a standard, and a numeric standard raises
   the gate's bar for that course
5. through the platform: a quick-launched interface deliverable is gated by
   designcheck, so finish_task on slop is REFUSED

Run from the agent/ directory:  python tests/test_design.py
"""

import json
import os
import sys

from common import AGENT_DIR, PY, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import conflicts
import designcheck
import quick
import sources
import standards

SLOP = """<!DOCTYPE html>
<html>
<head><style>
  .hero { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #a5b4fc;
          text-align: center; border-radius: 9999px; }
  .card { text-align: center; border-radius: 9999px; padding: 13px; }
  .b { text-align: center; } .c { text-align: center; } .d { text-align: center; }
  .e { text-align: center; } .f { text-align: center; }
  .wrap { width: 1200px; padding: 17px; margin: 23px; gap: 7px; }
  .g { padding: 19px; margin: 11px; gap: 3px; }
</style></head>
<body>
  <div class="hero"><h1>🚀 Unlock the power of your workflow</h1></div>
  <img src="a.png">
  <div class="wrap">
    <p>Lorem ipsum dolor sit amet, consectetur.</p>
    <input type="email">
    <div onclick="go()">Get started</div>
    <button></button>
  </div>
</body></html>
"""

GOOD = """<!DOCTYPE html>
<html lang="en">
<head><style>
  :root { --ink: #14161a; --paper: #ffffff; --muted: #5b6270; --line: #e4e7ec; }
  body { color: var(--ink); background: var(--paper); font-size: 16px; }
  h1 { font-size: 32px; }
  h2 { font-size: 24px; }
  .note { color: #6b7280; background: #ffffff; font-size: 14px; }
  .panel { max-width: 72ch; padding: 16px; margin: 24px; gap: 8px;
           border: 1px solid var(--line); border-radius: 8px; }
  @media (max-width: 640px) { .panel { padding: 12px; margin: 16px; } }
</style></head>
<body>
  <header><h1>Invoice 2043</h1></header>
  <main>
    <section class="panel">
      <h2>Line items</h2>
      <img src="chart.png" alt="Spend by month, rising from March">
      <label for="q">Quantity</label>
      <input id="q" type="number">
      <button type="submit">Recalculate</button>
    </section>
  </main>
  <footer><p class="note">Totals exclude tax.</p></footer>
</body></html>
"""


def write(root, rel, text):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def main():
    sb = make_sandbox("design", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []})

    # --- 1 + 2. the gate catches the checkable failures and the tells
    slop_path = write(sb, "out/slop.html", SLOP)
    found = designcheck.check_path(slop_path)
    rules = {f["rule"] for f in found}
    for expected in ("contrast", "responsive", "fixed-width", "a11y-lang",
                     "a11y-alt", "a11y-label", "a11y-interactive",
                     "a11y-button", "tell-lorem", "tell-palette", "tell-emoji",
                     "tell-centered", "tell-copy", "spacing-scale"):
        assert expected in rules, f"the gate missed {expected}: {sorted(rules)}"
    blockers = [f for f in found if f["severity"] == "blocker"]
    assert blockers, "slop must produce blockers, not just warnings"
    assert all(f["fix"] for f in found), "every finding must say what to do"
    text = designcheck.report(found)
    assert "design gate: FAIL" in text and "FIX:" in text
    print(f"[catches] the gate refused the generated-filler page on "
          f"{len(rules)} distinct rules, each with a concrete fix")

    # --- 3. a considered page passes
    good_path = write(sb, "out/good.html", GOOD)
    ok = designcheck.check_path(good_path)
    blockers_ok = [f for f in ok if f["severity"] == "blocker"]
    assert not blockers_ok, [f"{f['rule']}: {f['message']}" for f in blockers_ok]
    assert "design gate: PASS" in designcheck.report(ok)
    print("[fair] a page with real contrast, one scale, tokens, a breakpoint "
          "and labelled controls passed with no blockers")

    # --- 4. standards come from the expert's own material
    W3C = "https://www.w3.org/TR/WCAG22/"
    BLOG = "https://medium.com/@x/ui-takes"
    DEV = "https://dev.to/y/ui-takes"
    write(sb, "courses/design/notes.md",
          f"- C-0101 Body text contrast must be at least 7:1 [src: {W3C}]\n"
          f"- C-0102 Touch targets must be at least 44px [src: {W3C}]\n"
          f"- C-0103 Card shadows should always be soft [src: {BLOG}]\n"
          f"- C-0104 Card shadows should never be soft [src: {DEV}]\n"
          f"- C-0105 The grid is twelve columns wide [src: {W3C}]\n")
    for ref in (W3C, BLOG, DEV):
        sources.record(sb, "design", ref)
    conflicts.write(sb, "design")
    rep = standards.extract(sb, "design")
    rules_out = standards.load(sb, "design")
    texts = " ".join(r["text"] for r in rules_out)
    assert "contrast must be at least 7:1" in texts, texts
    assert "44px" in texts
    assert "shadows" not in texts, "a CONTESTED point may never become a standard"
    assert rep["skipped_contested"] >= 2, rep
    # ...and neither may a DEFEATED one: the tier-3 "3:1" claim lost to the
    # spec, so it must not come back as a rule -- least of all one whose
    # [check:] would lower the gate below the winner's 7:1
    assert "3:1" not in texts, f"a defeated claim became a standard: {texts}"
    assert all(r["check"] != {"key": "min_contrast", "value": 3.0}
               for r in rules_out), rules_out
    assert "twelve columns" not in texts, "only normative atoms become rules"
    contrast_rule = next(r for r in rules_out if "7:1" in r["text"])
    assert contrast_rule["tier"] == 1, contrast_rule
    assert contrast_rule["check"] == {"key": "min_contrast", "value": 7.0}, \
        contrast_rule
    block = standards.render(sb, "design")
    assert "STANDARDS" in block and "gate-checked" in block
    print("[standards] normative atoms became the bar, the contested point was "
          "refused, and the numeric rule carries a gate check")

    # --- the course's own standard raises the gate
    t = designcheck.thresholds_for(sb, "design")
    assert t["min_contrast"] == 7.0, t
    # a rule that would LOOSEN a threshold can never win, whatever the file
    # order says
    standards.add(sb, "design", "Body text contrast must be at least 2:1",
                  tier=4)
    assert designcheck.thresholds_for(sb, "design")["min_contrast"] == 7.0, \
        "a weaker rule must never lower the bar"
    strict = designcheck.check_path(good_path, t)
    assert any(f["rule"] == "contrast" for f in strict), \
        "at a 7:1 bar the same page must now be flagged"
    assert not any(f["rule"] == "contrast"
                   for f in designcheck.check_path(good_path)), \
        "...and at the 4.5:1 default it must not"
    print("[owner-bar] raising the course's own standard to 7:1 raised the "
          "gate: the same page passes at the default and fails at the bar")

    # --- 5. end to end: a launched interface deliverable is gated
    sb2 = make_sandbox("design_lane", providers={"m": {"script": "s.json"}},
                       roles={"practitioner": "m", "consultant": "m",
                              "reflector": "m"},
                       scripts={"s.json": [
                           {"tool": "write_file",
                            "args": {"path": "out/page.html", "content": SLOP}},
                           {"tool": "finish_task", "args": {"summary": "shipped"}},
                       ] * 3})
    kind, tid = quick.launch(sb2, "build the pricing page", kind="operator",
                             deliverable="out/page.html")
    task = [t for t in read_state(sb2)["tasks"] if t["id"] == tid][0]
    assert "designcheck.py" in (task["done_check"] or ""), task["done_check"]
    assert run_drain(sb2) == 0
    after = [t for t in read_state(sb2)["tasks"] if t["id"] == tid][0]
    assert after["status"] != "done", \
        "the gate must refuse slop even when the model says it is finished"
    assert after.get("done_rejects", 0) >= 1, after
    with open(os.path.join(sb2, "logs", "agent.log"), encoding="utf-8") as f:
        assert '"done_refused"' in f.read()
    print("[lane] a launched interface deliverable was gated by designcheck: "
          "the model called it shipped, the harness did not")
    print("PASS test_design")


if __name__ == "__main__":
    main()
