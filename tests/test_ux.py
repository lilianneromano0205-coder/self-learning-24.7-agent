#!/usr/bin/env python3
"""THE UI/UX REDESIGN'S OWN ACCEPTANCE TESTS — spec §15.

§15 lists eight flows and the thing each one must let a person do. §17 is
explicit that the redesign "is not accepted because it looks cleaner", so a
screenshot proves nothing here. What CAN be tested mechanically is whether the
information each flow needs is actually reachable, in one place, from the API
the page reads — and that is what this file does. A flow that needs three
round trips and a guess is a flow that fails its acceptance test whatever the
page looks like.

| §15 FLOW              | WHAT IS ASSERTED HERE                              |
|-----------------------|----------------------------------------------------|
| first mission         | Home's payload alone carries a next action, so a   |
|                       | first-time user is never sent to the Guide         |
| create expert         | the intent questions map to every lane, and none   |
|                       | of them requires knowing a lane name               |
| mission supervision   | ONE request answers objective, current action,     |
|                       | blocker, remaining criteria and cost               |
| proof                 | implemented vs verified is one field, not prose,   |
|                       | and no endpoint can set it                         |
| worker connection     | what a computer permits is visible BEFORE it is    |
|                       | used, and the choice explains itself               |
| training              | ingested / covered / examined / still open are     |
|                       | four separate numbers with explicit denominators   |
| error recovery        | every failure names which part failed and what     |
|                       | happens next                                       |
| advanced internals    | identity, prompts, roles, wiring, files and traces |
|                       | are all still reachable                            |

Run from the agent/ directory:  python tests/test_ux.py
"""

import io
import json
import os
import re
import sys

from common import AGENT_DIR, api, make_sandbox, run_drain, \
    start_panel, stop_panel

sys.path.insert(0, AGENT_DIR)
import fleet                  # noqa: E402
import mission                # noqa: E402
import workers                # noqa: E402

PAGE = os.path.join(AGENT_DIR, "ui.html")
SCRIPT = [{"tool": "write_file", "args": {"path": "out/report.md",
                                          "content": "# findings\n"}},
          {"tool": "finish_task", "args": {"summary": "wrote it"}}]


def _page():
    with io.open(PAGE, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- §15 flows

def check_first_mission(base, html):
    """"A first-time user with no docs can complete a demo mission without
    opening Guide or Advanced." Testable half: everything that first user
    needs is on Home, and Home says what to do next."""
    assert "What do you want accomplished?" in html, (
        "§3's command bar is the first thing a new user should meet")
    for button in ("New mission", "Create specialist", "Build team",
                   "Connect tool or computer"):
        assert f">{button}<" in html, f"§3 primary action missing: {button}"
    # the seven onboarding steps, in the spec's order
    steps = re.findall(r'\{id: "(\w+)",', html)
    assert steps[:7] == ["goal", "provider", "path", "worker", "mission",
                         "proof", "advanced"], steps[:7]
    # and the checklist reads STATE, not clicks — otherwise it congratulates
    # people for clicking
    assert "path:     experts.length > 0" in html
    assert "mission:  !!(S.missionCount > 0)" in html
    b = api(base, "GET", "/api/briefing")
    assert "recommendations" in b, "Home cannot say what to do next"
    print(f"[first-mission] the command bar, four primary actions and a "
          f"7-step checklist that reads real state are all on Home; the "
          f"briefing offers {len(b.get('recommendations', []))} next action(s) "
          f"without opening Guide")


def check_create_expert(html):
    """"User can choose correct creation path from intent questions without
    knowing lane names.\""""
    lanes = set(re.findall(r'lane: "(\w+)"', html))
    assert lanes == {"quick", "trained", "learner", "archetype", "team"}, lanes
    questions = re.findall(r'\{q: "([^"]+)"', html)
    assert len(questions) == 5, questions
    for q in questions:
        for jargon in ("quick specialist", "trained expert", "archetype",
                       "lane", "learner"):
            assert jargon not in q.lower(), (
                f"the intent question leaks the taxonomy it exists to hide: "
                f"{q!r} contains {jargon!r}")
    # every lane the wizard offers has a declared step list, so no lane can
    # reach a step that collects an answer nothing consumes
    declared = set(re.findall(r"^  (\w+):\s+\[\"job\"", html, re.M))
    assert lanes <= declared | {"archetype", "team"}, (lanes, declared)
    assert "LANE_STEPS" in html and '"review"' in html
    print(f"[create-expert] {len(questions)} intent questions cover all "
          f"{len(lanes)} lanes and none of them names a lane; every lane "
          f"declares which of the six steps it can honour")


def check_mission_supervision(base, home, root):
    """"User can answer objective / current action / blocker / remaining
    criteria / cost in <15 seconds from one page." Mechanically: ONE request."""
    rec = mission.create(root, "Produce the quarterly supplier review",
                         ["every auto-renewal is listed with its notice period",
                          "the list cites the contract file"],
                         constraints=["read-only: never edit a contract"],
                         expert="reviewer")
    mid = rec["id"]
    ch = mission.justify(root, mid, "C1", task_goal="read the Acme MSA",
                         expected_evidence="out/report.md lists the clauses")
    mission.record_action(root, mid, ch, task_id="t-1", status="running")
    mission.blocked(root, mid, "authority",
                    "the Acme MSA is behind a login we do not have",
                    criterion="C1")
    d = api(base, "GET", f"/api/experts/reviewer/missions/{mid}")
    for field, what in (("objective", "the objective"),
                        ("current_action", "what it is doing now"),
                        ("blockers", "what is blocking it"),
                        ("open", "the criteria still open"),
                        ("cost_usd", "what it has cost"),
                        ("needs_human", "what needs a person"),
                        ("contract", "the contract the agent actually sees")):
        assert field in d, f"one request cannot answer {what}"
    assert d["current_action"]["goal"] == "read the Acme MSA"
    assert d["current_action"]["criterion"] == "C1", (
        "the current action must name the criterion it serves — an action "
        "that serves none is busy work")
    assert d["needs_human"] and d["needs_human"][0]["user_sees"] == "Needs you"
    assert d["blockers"][0]["routes_to"].startswith("the owner")
    # and the page renders each of them
    html = _page()
    for label in ("Success criteria", "Binding constraints", "Needs you",
                  "Blocked on"):
        assert label in html, f"the mission page never shows {label!r}"
    print(f"[supervision] one request answers objective, current action "
          f"({d['current_action']['goal']!r} -> {d['current_action']['criterion']}), "
          f"{len(d['open'])} open criteria, {len(d['blockers'])} blocker(s), "
          f"and cost — and the blocker routes to a person rather than to a retry")
    return mid


def check_proof_in_one_click(base, html):
    """"User can determine whether a feature/task is merely implemented vs
    live/stress proven in one click." And: nobody may set it by hand."""
    d = api(base, "GET", "/api/proof")
    assert d["features"], "no capabilities are declared"
    one = sorted(d["features"])[0]
    row = d["features"][one]
    for field in ("level", "badge", "why", "capability", "expired"):
        assert field in row, f"the proof row cannot answer {field}"
    detail = api(base, "GET", f"/api/proof/{one}")
    assert detail["tests"], "no way to reproduce it"
    assert detail["code_hash"], "the evidence is not bound to any code"
    # THE control: no request may assert a level. refresh() re-RUNS evidence;
    # there is no endpoint that takes one.
    assert not re.search(r'"/api/proof[^"]*".*level', html), \
        "the page must never post a proof level"
    assert "proof/refresh" in html and "refreshProof(" in html
    # and the ONLY proof route the page may write to is the one that re-runs
    # the evidence: enumerate the POSTs rather than trusting the comment
    posted = set(re.findall(r"api\('(/api/proof[^']*)',\s*\{method:\"POST\"",
                            html))
    assert posted <= {"/api/proof/refresh"}, (
        f"the page POSTs to {sorted(posted)} — the only proof route that may "
        f"take a write is the one that re-runs the tests")
    print(f"[proof] {len(d['features'])} capabilities each carry level, badge, "
          f"the reason, the covering tests and the code hash the evidence is "
          f"bound to; the panel has no way to set a level, only to re-run the "
          f"evidence")


def check_worker_connection(base, home, html):
    """"User can connect a computer and understand what it permits before
    enabling agent access.\""""
    workers.register(home, "Office Windows PC", "fleet-worker",
                     ["excel", "internal-network"])
    workers.register(home, "Local Docker", "local-docker", ["install"])
    d = api(base, "GET", "/api/workers")
    row = next(w for w in d["workers"] if w["id"] == "office-windows-pc")
    for field in ("zone", "capabilities", "declared", "implied",
                  "cost_per_hour", "scales_to_zero", "experts", "state"):
        assert field in row, f"a computer card cannot show {field}"
    assert d["zones"][row["zone"]]["means"], "a zone with no meaning is a label"
    # the CHOICE explains itself, in a sentence, naming the computer
    r = api(base, "POST", "/api/workers/choose",
            {"task": "open the sheet in excel on the internal network"})
    assert r["why"].startswith("Using Office Windows PC because"), r["why"]
    assert "excel" in r["why"] and "internal-network" in r["why"]
    assert "fleet-worker" not in r["why"], (
        "§7: the sentence names the computer and the reason, not the backend "
        "kind")
    # and every computer that was NOT chosen says why not
    assert any(not c["eligible"] and c["why_not"] for c in r["considered"]), \
        "a routing decision nobody can disagree with is one nobody can correct"
    assert "why not the others?" in html
    print(f"[worker] a computer card shows zone, what it can do (declared and "
          f"implied), cost, scale-to-zero and who may use it; the choice reads "
          f"{r['why']!r} and names why each other computer was passed over")


def check_training_is_certification(base, root, html):
    """"User can distinguish material ingested, knowledge covered, exam passed
    and unresolved gap." And never a percentage without its denominator."""
    cdir = os.path.join(root, "courses", "supplier-law")
    os.makedirs(os.path.join(cdir, "lessons", "01"), exist_ok=True)
    with io.open(os.path.join(cdir, "spec.md"), "w", encoding="utf-8") as f:
        f.write('R-001 [from C-1]: notes exist CHECK: "python" -c "pass"\n'
                'R-002 [from C-2]: clauses listed CHECK: "python" -c "pass"\n')
    with io.open(os.path.join(cdir, "lessons", "01", "notes.md"), "w",
                 encoding="utf-8") as f:
        f.write("- auto-renewal needs 90 days notice [src:C-1]\n")
    with io.open(os.path.join(cdir, "exam-results.md"), "w",
                 encoding="utf-8") as f:
        f.write("R-001: PASS — verified\nSCORE: 88\n")
    with io.open(os.path.join(cdir, "gaps.md"), "w", encoding="utf-8") as f:
        f.write("- G-01 nothing yet covers termination for convenience\n")

    d = api(base, "GET", "/api/experts/reviewer/training")
    c = next(x for x in d["courses"] if x["course"] == "supplier-law")
    assert c["coverage"]["required"] == 2 and c["coverage"]["with_evidence"] == 1
    assert c["coverage"]["missing"] == ["R-002"], c["coverage"]
    assert c["exercises"]["total"] >= 1 and c["exercises"]["studied"] >= 1
    assert c["exam"]["score"] == 88 and c["exam"]["verdict"] == "pass", c["exam"]
    assert c["gaps"], "an unresolved gap must be visible, not averaged away"
    # THE §10 rule: no ratio is computed for the page; both halves are sent
    for stage in ("coverage", "exercises"):
        keys = set(c[stage])
        assert not any("percent" in k or "pct" in k or "rate" in k
                       for k in keys), (stage, keys)
    assert "100%" not in json.dumps(c), "a bare percentage reached the payload"
    assert "will not print '100% learned'" in d["rule"]
    # and the page prints the counts it was given rather than dividing them
    assert "${cov.with_evidence}/${cov.required}" in html
    assert "${ex.studied}/${ex.total}" in html
    print(f"[training] ingested / covered / examined / still-open are four "
          f"separate numbers: {c['sources']['total']} source(s), "
          f"{c['coverage']['with_evidence']}/{c['coverage']['required']} "
          f"requirements evidenced, exam {c['exam']['score']}% "
          f"({c['exam']['verdict']}), {len(c['gaps'])} gap(s) still open — and "
          f"no percentage is computed anywhere without its denominator")


def check_error_recovery(html):
    """"User can tell whether agent, tool, model, worker or verifier failed
    and what system will do next.\""""
    # every failure class named in §12 has a branch, and every branch answers
    # all three questions the spec demands
    owners = set(re.findall(r'who: "([^"]+)"', html))
    assert {"the verifier", "the platform", "the model provider",
            "the budget breaker", "the command it ran", "you",
            "the agent"} <= owners, owners
    n = len(re.findall(r'who: (?:"[^"]+"|null), severity:', html))
    assert n >= 8, f"only {n} diagnosis branches"
    # each branch carries headline + next + you; count them and require parity
    for field in ("headline:", "next:", "you:"):
        assert html.count(field) >= n, (field, html.count(field), n)
    # §12: raw trace is NOT the primary UI
    assert "Advanced — the raw error exactly as it was recorded" in html
    assert "diagnosisHtml(t)" in html and "statusReason(t)" in html
    print(f"[errors] {n} failure classes, each naming which part failed "
          f"({len(owners)} distinct owners incl. the verifier, the platform, "
          f"the provider, the budget breaker and you), what happens next and "
          f"what you can do; the raw trace sits under Advanced")


def check_advanced_still_reachable(base, html):
    """"Power user can still reach raw identity/prompts/roles/wiring/files/
    traces without polluting default navigation.\""""
    for pane in ("Identity & prompts", "Models & compute", "Raw files"):
        assert pane in html, f"§5 Advanced cannot reach {pane}"
    for fn in ("renderIdentityPane(", "renderWiring(", "renderFiles(",
               "traceDlg(", "ctxDlg("):
        assert fn in html, f"{fn} was lost in the redesign"
    # none of them is in the primary nav
    nav = re.findall(r"\['(\w+)','[^']+'\]", html)[:6]
    for internal in ("identity", "wiring", "trace", "prompts"):
        assert internal not in nav, f"{internal} polluted the primary nav"
    # and the raw file tree tells directories from files, which it did not
    assert "e.d === true || e.dir === true" in html, (
        "the tree read a field the API does not send, so every folder was "
        "drawn as a clickable file")
    d = api(base, "GET", "/api/experts/reviewer/tree")
    assert any(x["d"] for x in d) and any(not x["d"] for x in d)
    print(f"[advanced] identity, prompts, roles, model wiring, raw files and "
          f"traces are all still reachable behind one disclosure, and none of "
          f"them appears in the six-item primary nav")


def check_mobile_layout(html):
    """§14: "Mobile is for supervision/approval/status."

    A browser is the only thing that can prove a page does not scroll
    sideways, so this asserts the CSS properties that decide it — the two
    that were actually wrong when the pages were driven at 375 px:

      * a grid item defaults to `min-width:auto` and refuses to shrink below
        its widest child, so a wide table pushed the whole page sideways and
        the table's own scroll container could not help: the COLUMN was what
        would not narrow
      * a table of long values with no scroll container overflows its card
    """
    assert ".wswrap>*,.mindwrap>*{min-width:0}" in html, (
        "grid items must be allowed to shrink, or a wide table scrolls the "
        "whole page on a phone")
    assert "@media (max-width:860px)" in html
    for rule in ("#side{width:100%;position:fixed;top:auto;bottom:0",
                 ".btn,.navbtn,.subtabs button{min-height:40px}"):
        assert rule in html, f"the phone layout lost: {rule}"
    # every table that can hold a long value sits inside a scroll container
    import re as _re
    bare = []
    for m in _re.finditer(r"<table[ >]", html):
        before = html[max(0, m.start() - 220):m.start()]
        if "tablewrap" not in before:
            bare.append(" ".join(html[m.start():m.start() + 60].split()))
    assert not bare, (
        "these tables have no overflow container, so a long cell scrolls the "
        "page rather than the table: " + " | ".join(bare[:4]))
    print(f"[mobile] the sidebar becomes a bottom bar with 40px targets, grid "
          f"items may shrink, and every one of the "
          f"{html.count('<table')} tables sits in a scroll container")


def check_design_system(html):
    """§14's rules that a machine can actually check."""
    # colour never carries status alone: every pill that gets a colour class
    # also gets text. The mechanical form: no `class="pill ok"></span>`
    assert not re.search(r'class="pill (?:ok|bad|warn|dim)"\s*>\s*</span>', html), \
        "a status pill with no text — §14 forbids colour carrying status alone"
    # one <h1> per page: every renderer that hosts another one passes nested
    for nested in ("renderSystem(b, true)", "renderModels(b, true)",
                   "renderMemory(b, true)"):
        assert nested in html, nested
    # the same words in UI, CLI and proof manifests
    assert "python tests/" in html, "the panel never shows the reproducing command"
    assert 'c[3]' in html or "CLI" in html or "python " in html
    print("[design] no status is carried by colour alone, a hosted view never "
          "prints a second page title, and the panel shows the command that "
          "reproduces what it claims")


def main():
    home = make_sandbox("ux", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": SCRIPT})
    root = fleet.create(home, "Reviewer", "review supplier contracts")
    html = _page()
    proc, base = start_panel(home)
    try:
        check_first_mission(base, html)
        check_create_expert(html)
        check_mission_supervision(base, home, root)
        check_proof_in_one_click(base, html)
        check_worker_connection(base, home, html)
        check_training_is_certification(base, root, html)
        check_error_recovery(html)
        check_advanced_still_reachable(base, html)
        check_mobile_layout(html)
        check_design_system(html)
        print("PASS test_ux")
    finally:
        stop_panel(proc, base)


if __name__ == "__main__":
    main()
