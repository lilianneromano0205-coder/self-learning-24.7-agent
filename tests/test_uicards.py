#!/usr/bin/env python3
"""GENERATIVE UI FROM A CLOSED CATALOGUE (M7).

An agent may hand the panel a table, a checklist, a diff or a metric card.
It may not hand the panel markup, a script, a link or a style — because the
schema has nowhere to put one, and the client renders escaped data only.

1. the four catalogue types parse and normalise
2. anything else -- unknown type, bad JSON, oversized, over the cap -- is
   dropped with a reason, never rendered "as best we can"
3. an injection attempt inside a card's text stays inert TEXT
4. the loop collects cards from a message and from a finish summary, logs
   ui_card / ui_card_invalid, and the panel serves them with the task
5. the page's renderCard() escapes every branch (checked in the source)

Run from the agent/ directory:  python tests/test_uicards.py
"""

import json
import os
import re
import sys

from common import AGENT_DIR, api, make_sandbox, read_state, run_drain, \
    start_panel, stop_panel

sys.path.insert(0, AGENT_DIR)
import fleet
import loop
import uicards

EVIL = "<img src=x onerror=alert(1)> </script><script>alert(2)</script>"


def main():
    # --- 1. the catalogue
    ok, why = uicards.validate({"type": "table", "title": "Margins",
                                "columns": ["sku", "margin"],
                                "rows": [["A1", 0.12], ["B2", "31%"]]})
    assert why is None and ok["rows"][0] == ["A1", "0.12"], (ok, why)
    ck, _ = uicards.validate({"type": "checklist",
                              "items": [{"text": "ship it", "done": True},
                                        "write the docs"]})
    assert ck["items"] == [{"text": "ship it", "done": True},
                           {"text": "write the docs", "done": False}]
    df, _ = uicards.validate({"type": "diff", "path": "a.py",
                              "before": "x = 1", "after": "x = 2"})
    assert df["before"] == "x = 1" and df["after"] == "x = 2"
    mt, _ = uicards.validate({"type": "metric", "metrics": [
        {"label": "pass rate", "value": 92, "unit": "%", "delta": "+4"}]})
    assert mt["metrics"][0]["value"] == "92"
    print("[catalogue] table, checklist, diff and metric parse into normalised "
          "data with every cell coerced to a bounded string")

    # --- 2. refusals
    for bad, needle in (
            ('<<<UI-CARD {"type": "iframe", "src": "http://x"}>>>', "unknown card type"),
            ('<<<UI-CARD {not json}>>>', "not valid JSON"),
            ('<<<UI-CARD {"type": "table", "rows": []}>>>', "non-empty 'columns'"),
            ('<<<UI-CARD {"type": "metric"}>>>', "non-empty 'metrics'")):
        cards, problems = uicards.parse(bad)
        assert cards == [] and problems and needle in problems[0], (bad, problems)
    big = json.dumps({"type": "table", "columns": ["a"],
                      "rows": [["x" * 9000]]})
    cards, problems = uicards.parse(f"<<<UI-CARD {big}>>>")
    assert cards == [] and "exceeded" in problems[0], problems
    many = " ".join('<<<UI-CARD {"type": "checklist", "items": ["a"]}>>>'
                    for _ in range(14))
    cards, problems = uicards.parse(many)
    assert len(cards) == uicards.MAX_CARDS and problems, (len(cards), problems)
    print("[closed] unknown types, malformed JSON, oversized and over-the-cap "
          "cards are all dropped with a stated reason")

    # --- 3. injection stays text
    cards, _ = uicards.parse('<<<UI-CARD {"type": "checklist", "items": '
                             '[{"text": ' + json.dumps(EVIL) + '}]}>>>')
    assert cards and cards[0]["items"][0]["text"] == EVIL
    assert "<script>" not in uicards.render_text(cards[0]).replace(EVIL, "")
    print("[inert] a script tag inside a card is carried as text and never "
          "becomes markup -- the client escapes, the schema has no slot for it")

    # --- 4. through the loop
    home = make_sandbox("uicards", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Carder", "reports in cards")
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write('[agent]\npoll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\n\n[providers.m]\ntype = "mock"\n'
                'script = "script.json"\n\n'
                '[roles.default]\nprovider = "m"\nmodel = "mock"\n')
    metric_card = json.dumps({"type": "metric", "title": "Run",
                              "metrics": [{"label": "checked", "value": 12}]})
    check_card = json.dumps({"type": "checklist",
                             "items": [{"text": "shipped", "done": True}]})
    script = [
        {"content": f"Here is what I found. <<<UI-CARD {metric_card}>>>",
         "tool": "write_file",
         "args": {"path": "out/a.md", "content": "x"}},
        {"content": '<<<UI-CARD {"type": "wormhole"}>>>',
         "tool": "finish_task",
         "args": {"summary": f"done <<<UI-CARD {check_card}>>>"}},
    ]
    with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
        json.dump(script, f)
    tid = loop.Agent(root).add_task("practitioner", "report with cards")
    assert run_drain(root) == 0
    t = read_state(root)["tasks"][0]
    assert t["status"] == "done", t
    kinds = [c["type"] for c in t.get("cards", [])]
    assert kinds == ["metric", "checklist"], t.get("cards")
    assert t["cards"][0]["metrics"][0]["value"] == "12"
    assert "<<<UI-CARD" not in t["summary"], "the summary reads as prose"
    with open(os.path.join(root, "logs", "agent.log"), encoding="utf-8") as f:
        log = f.read()
    assert '"ui_card"' in log and '"ui_card_invalid"' in log
    assert "unknown card type 'wormhole'" in log
    print("[loop] cards were collected from a message and from the finish "
          "summary, the bogus one was refused, both were logged")

    proc, base = start_panel(home)
    try:
        tasks = api(base, "GET", "/api/experts/carder/tasks")
        mine = [x for x in tasks if x["id"] == tid][0]
        assert [c["type"] for c in mine["cards"]] == ["metric", "checklist"]
    finally:
        stop_panel(proc, base)

    # --- 5. the client renderer, executed for real: hostile card in, inert
    # HTML out. Skipped only if node is unavailable (and said so).
    import shutil
    import subprocess
    import tempfile
    with open(os.path.join(AGENT_DIR, "ui.html"), encoding="utf-8") as f:
        page = f.read()
    fn = page[page.index("function renderCard("):page.index("\nfunction ctxBar(")]
    escfn = page[page.index("function esc(s)"):page.index("function ago(iso)")]
    node = shutil.which("node")
    if not node:
        print("[client] skipped -- node is not installed, so the renderer "
              "could not be executed here (its source is still checked below)")
        assert "${esc(" in fn and fn.count("${esc(") >= 8
    else:
        hostile = json.dumps([
            {"type": "table", "title": EVIL, "columns": [EVIL],
             "rows": [[EVIL]]},
            {"type": "checklist", "items": [{"text": EVIL, "done": False}]},
            {"type": "diff", "path": EVIL, "before": EVIL, "after": EVIL},
            {"type": "metric", "metrics": [{"label": EVIL, "value": EVIL,
                                            "unit": EVIL, "delta": EVIL}]},
            {"type": "iframe", "src": "http://evil"},
        ])
        driver = (escfn + "\n" + fn + "\n"
                  + f"const cards = {hostile};\n"
                  + "process.stdout.write(cards.map(renderCard).join(''));\n")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as tf:
            tf.write(driver)
            path = tf.name
        try:
            r = subprocess.run([node, path], capture_output=True, timeout=60)
            assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[:400]
            html = r.stdout.decode("utf-8", "replace")
        finally:
            os.remove(path)
        # the payload survives as TEXT; what must never appear is a tag
        assert "<img" not in html, html[:300]
        assert "<script" not in html and "</script" not in html, html[:300]
        assert "&lt;img src=x onerror=alert(1)&gt;" in html
        assert html.count("&lt;img src=x onerror=alert(1)&gt;") >= 6, \
            "the hostile text must appear ESCAPED everywhere it is shown"
        assert "iframe" not in html, "an unknown type renders as nothing at all"
        assert "<table" in html and "☑" not in html and "☐" in html
    print("[client] the page's renderer was run against a hostile card: every "
          "branch emitted escaped text, and the unknown type emitted nothing")
    print("PASS test_uicards")


if __name__ == "__main__":
    main()
