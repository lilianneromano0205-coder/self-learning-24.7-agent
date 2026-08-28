#!/usr/bin/env python3
"""THE UNIVERSAL AGENT — one goal in, an EARNED readiness verdict out.

`universal.py` is the layer the platform was missing: the thing that decides
which of its systems a goal needs before any work starts. Handing a goal
straight to `goal.pursue` assumes the expert already knows the domain and
already owns the tools; when it does not, the run dies several milestones
deep in a way that reads like a weak model, when the real answer was "it
needed a PDF reader" or "it had never studied this".

What is asserted here is the part that could quietly become theatre:

  1. the verdict is EARNED, not asserted — it moves only when the mechanical
     facts move (a capability appears, atoms get studied, a source improves)
  2. an AUTHORITY gap stops the run cold and never reaches goal.pursue,
     because that is the one dimension a machine must not resolve for itself
  3. knowledge learned from a WEAK source does not count as knowledge
  4. a dry run changes nothing on disk — a system that starts installing the
     moment you describe a goal is not one anybody leaves running

Run from the agent/ directory:  python tests/test_universal.py
"""

import io
import json
import os
import shutil
import sys
import tempfile

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import fleet          # noqa: E402
import universal      # noqa: E402


def _expert(home, slug="probe"):
    fleet.create(home, slug, "a test expert")
    return os.path.join(home, "experts", slug)


def _study(root, course, atoms):
    """Plant studied atoms with real citations, the way ingestion would."""
    d = os.path.join(root, "courses", course, "lessons", "01")
    os.makedirs(d, exist_ok=True)
    with io.open(os.path.join(d, "notes.md"), "w", encoding="utf-8") as f:
        for i, (text, src) in enumerate(atoms, 1):
            f.write(f"- C-{i:04d} {text} [src: {src}]\n")


def check_the_verdict_is_earned(home):
    """It must move only when a mechanical fact moves."""
    root = _expert(home, "earned")
    goal = "describe the screenshot and the diagram in this image"

    r1 = universal.ready(home, "earned", goal)
    assert r1["verdict"] != "READY", "a brand-new expert cannot be ready"
    dims = {g["dimension"] for g in r1["blocking"]}
    assert "knowledge" in dims, (
        "an expert that has studied nothing must report a knowledge gap")

    # study the subject from a NORMATIVE source
    _study(root, "vision", [
        ("image diagram screenshot analysis reads figures",
         "https://www.w3.org/TR/wcag2/"),
        ("screenshot diagram figures should carry alt text",
         "https://developer.mozilla.org/en-US/docs/Web/HTML"),
    ])
    r2 = universal.ready(home, "earned", goal)
    assert r2["knowledge"]["matched"] >= 1, r2["knowledge"]
    assert r2["knowledge"]["best_tier"] is not None, "citations were not rated"
    assert r2["knowledge"]["best_tier"] <= universal.MIN_LEARN_TIER, (
        f"w3.org/MDN should rate tier <= {universal.MIN_LEARN_TIER}, "
        f"got {r2['knowledge']['best_tier']}")
    assert "knowledge" not in {g["dimension"] for g in r2["blocking"]
                               if g["what"] == "the subject itself"}, \
        "studying the subject did not close the knowledge gap"
    print(f"[earned] the verdict moved only when the facts did: a new expert "
          f"reported a knowledge gap, and {r2['knowledge']['matched']} cited "
          f"atom(s) from tier-{r2['knowledge']['best_tier']} sources closed it")


def check_a_weak_source_is_not_knowledge(home):
    """The same sentence, believed or not depending on where it came from."""
    root = _expert(home, "sourced")
    goal = "explain caching strategy for the retrieval layer"
    claim = "caching strategy for a retrieval layer should bound staleness"

    _study(root, "c", [(claim, "https://www.rfc-editor.org/rfc/rfc9111")])
    good = universal.ready(home, "sourced", goal)

    _study(root, "c", [(claim, "https://random-content-farm.example.com/top-10")])
    weak = universal.ready(home, "sourced", goal)

    assert good["knowledge"]["best_tier"] <= universal.MIN_LEARN_TIER, \
        f"an RFC should be normative, got tier {good['knowledge']['best_tier']}"
    assert weak["knowledge"]["best_tier"] > universal.MIN_LEARN_TIER, \
        f"a content farm must not rate <= {universal.MIN_LEARN_TIER}"
    weak_reasons = [g for g in weak["blocking"] if g["what"] == "source quality"]
    assert weak_reasons, (
        "identical knowledge from a junk source must be refused, or 'learn "
        "only from reputable sources' is a slogan rather than a control")
    assert not [g for g in good["blocking"] if g["what"] == "source quality"]
    print(f"[sources] the same claim was accepted at tier "
          f"{good['knowledge']['best_tier']} from an RFC and refused at tier "
          f"{weak['knowledge']['best_tier']} from a content farm — what is "
          f"believed depends on where it came from, decided by rule and never "
          f"by a model")


def check_authority_stops_the_run(home):
    """The boundary that makes every other control meaningful."""
    _expert(home, "bounded")
    for goal in ("create an account on example.com and publish the report",
                 "buy the dataset and email the summary to the team",
                 "get an api key for the vendor and deploy to production"):
        r = universal.achieve(home, "bounded", goal, learn=False)
        assert r["started"] is False, f"it started work on: {goal}"
        assert "pursuit" not in r, "goal.pursue was reached despite the block"
        assert r["needs_owner"], f"no authority gap detected in: {goal}"
        assert "NEEDS YOU" in r["verdict"] or r["needs_owner"], r["verdict"]
        for g in r["needs_owner"]:
            assert g["routes_to"].startswith("the owner"), g
    # and an ordinary goal is NOT falsely routed to the owner
    ok = universal.ready(home, "bounded", "summarise the notes into a report")
    assert not ok["needs_owner"], (
        f"an ordinary goal was sent to the owner: {ok['needs_owner']}")
    print("[authority] three goals implying an account, a payment, a "
          "credential, a deployment and an email all stopped BEFORE any work "
          "began and routed to the owner; goal.pursue was never reached; and "
          "an ordinary goal was not falsely escalated")

    # ---- THE CORPUS. Three examples proved the mechanism; they could not
    # prove its COVERAGE, and coverage was where it was broken.
    #
    # The table used to be hand-written whole-word alternations, and it failed
    # open on ordinary English: `\blogin\b` misses "log into" and "sign in",
    # `\bauth\b` cannot match "authenticate", `\bcredential\b` cannot match
    # "credentialS" — \b needs a boundary and the plural's "s" is a word
    # character. Six of nine everyday phrasings walked straight past the one
    # boundary this platform says a machine must never cross by itself.
    #
    # A test with three examples cannot see that. Only an enumeration can, so
    # the phrasings are enumerated, and BOTH directions are asserted: a guard
    # that flags everything is as useless as one that flags nothing, because
    # a fleet that asks permission to summarise a PDF gets its permissions
    # turned off.
    MUST_FLAG = [
        "log into the supplier portal", "log in to the dashboard",
        "sign in to the console", "login to the portal",
        "authenticate with the vendor", "use my credentials",
        "sign up for an account", "check out the cart",
        "send an email to the vendor", "register for the service",
        "pay the invoice", "buy the domain", "publish the report",
        "deploy to production", "reply to their message",
        "subscribe to the plan", "get an api key", "store the password",
        "use oauth", "enable 2fa", "purchase a licence",
        "delete the production database", "wipe the bucket",
        "onboarding flow", "create an account on github",
        "order the parts", "refund the customer", "access keys for s3",
    ]
    MUST_NOT_FLAG = [
        "summarise these PDFs", "write a briefing on HTTP caching",
        "learn about exponential backoff", "count the rows in this csv",
        "draw a chart of revenue", "explain the architecture",
        "refactor the parser", "translate this page",
        "compare two sorting algorithms", "extract the tables from this report",
    ]
    missed = [g for g in MUST_FLAG if not universal.authority_gaps(g)]
    assert not missed, (
        f"the authority guard FAILED OPEN on {len(missed)} phrasing(s): "
        f"{missed[:6]}. Every one of these asks for an account, a payment, a "
        f"credential, a publication or a deletion, and the guard let it "
        f"through — which is the only failure here that costs anything.")
    false_pos = [(g, universal.authority_gaps(g)[0][0])
                 for g in MUST_NOT_FLAG if universal.authority_gaps(g)]
    assert not false_pos, (
        f"ordinary work was escalated to the owner: {false_pos[:4]}. A guard "
        f"that stops everything gets switched off, and then it stops nothing.")
    # ---- the CAPABILITY table had the same blindness, inverted ----------
    # `\bpdf\b` cannot match "PDFs", so the most natural way anyone phrases a
    # batch job asked for NOTHING: "summarise these PDFs" -> [], "download
    # these videos" -> [], "read the images" -> []. Under-detection here does
    # not stop the run, it does something worse — the readiness check finds no
    # missing capability and reports READY for work the fleet cannot do.
    # Singular and plural must resolve identically, and prose must still
    # resolve to nothing.
    import re as _re

    def _caps(goal):
        return sorted(c for p, c in universal.CAPABILITY_HINTS
                      if _re.search(p, goal.lower()))

    for one, many in [("summarise this PDF", "summarise these PDFs"),
                      ("describe this screenshot", "describe these screenshots"),
                      ("download this video", "download these videos"),
                      ("convert this spreadsheet", "convert these spreadsheets"),
                      ("clone this repo", "clone these repos"),
                      ("read the image", "read the images"),
                      ("run it in a container", "run them in containers"),
                      ("check the website", "check the websites")]:
        a, b = _caps(one), _caps(many)
        assert a and a == b, (
            f"singular/plural disagree: {one!r} -> {a}, {many!r} -> {b}. A "
            f"requirements detector that only understands the singular "
            f"reports READY for work it cannot do.")
    for prose in ("write a summary of the meeting", "explain recursion",
                  "learn about caching"):
        assert not _caps(prose), f"{prose!r} demanded {_caps(prose)}"

    # a goal that needs a real BROWSER must not be answered with a fetcher:
    # web_fetch is stdlib urllib and cannot log in, run JS, click or submit
    for goal in ("log into the supplier portal and download each invoice",
                 "click through the dashboard and export the report",
                 "fill in the vendor form and submit it",
                 "add the item to cart and checkout"):
        assert "browser_control" in _caps(goal), (
            f"{goal!r} resolved to {_caps(goal)} — an interactive goal "
            f"answered with a static fetcher is a promise that cannot be kept")
    assert "browser_control" not in _caps("crawl the docs site for the API"), (
        "a plain crawl was escalated to a full browser")
    print("[capabilities-corpus] singular and plural resolve identically "
          "across 8 capability families (they did not: 'these PDFs' asked for "
          "nothing), prose asks for nothing, and interactive goals now "
          "require browser_control instead of being answered by urllib")

    print(f"[authority-corpus] {len(MUST_FLAG)} phrasings that must reach the "
          f"owner all do — including 'log into', 'sign in to', 'authenticate' "
          f"and 'credentials', which the hand-written whole-word table missed "
          f"— and {len(MUST_NOT_FLAG)} ordinary goals are still not escalated")


def check_a_dry_run_changes_nothing(home):
    """Describing a goal must not start installing things."""
    root = _expert(home, "dry")
    before = _tree(root)
    plan = universal.resolve(home, "dry",
                             "read the pdf papers and the video lecture",
                             apply=False)
    after = _tree(root)
    assert before == after, (
        f"a dry run wrote to disk: {sorted(set(after) - set(before))[:5]}")
    assert plan["applied"] is False
    assert plan["actions"], "a blocked goal must produce a plan of action"
    for a in plan["actions"]:
        assert a["why"], f"action {a['action']!r} has no stated reason"
        if a["action"] != "ask the owner":
            assert a["command"], f"{a['action']} is not reproducible by hand"
    print(f"[dry-run] describing a goal produced {len(plan['actions'])} routed "
          f"action(s), each with a reason and a command you can run yourself, "
          f"and wrote nothing to the expert")


def check_every_gap_routes_somewhere_real(home):
    """A dimension with no route is a dead end wearing a label."""
    import mission
    _expert(home, "routed")
    r = universal.resolve(home, "routed",
                          "sign up, read the pdf papers, watch the lecture "
                          "video and publish the findings", apply=False)
    seen = {g["dimension"] for g in r["blocking"]}
    assert seen, "a goal needing everything reported no gaps at all"
    for g in r["blocking"]:
        assert g["dimension"] in mission.GAPS, (
            f"{g['dimension']} is not one of the platform's own dimensions")
        assert g["routes_to"] == mission.GAPS[g["dimension"]]["routes_to"], (
            f"{g['dimension']} routes somewhere the gap router does not know "
            f"about — two answers to one question is how they drift apart")
        assert g["user_sees"], f"{g['what']} has no plain-language label"
    print(f"[routing] {len(r['blocking'])} gap(s) across {len(seen)} dimension(s), "
          f"every one classified by mission.GAPS itself rather than by a "
          f"second opinion, and every one carrying the route the platform "
          f"already declared for it")


def check_the_router_reads_shape_not_vibes(home):
    """route() is the one answer to "which system?" — the same classifier
    behind `universal.py route` and the panel's readiness card. It is
    deterministic on purpose: a model asked "which system fits?" answers
    plausibly and unfalsifiably, and a routing rule that cannot be pinned in
    a test cannot be trusted to stay put. So every shape cue is enumerated
    here; if the classifier quietly narrows, this goes red, not silent."""
    cases = [
        # a question is answered from cited notes, never pursued
        ("what is the cheapest rail for a summarizer?", "consult"),
        ("how does the exam sealing work", "consult"),
        # condition + consequence = an intention the scheduler holds
        ("whenever the error rate rises then alert me", "prospective intention"),
        ("if the feed goes quiet for a day then open a goal", "prospective intention"),
        # a schedule word = the loop wakes it
        ("every day at 9 summarize new arxiv papers", "routine"),
        ("weekly digest of retractions", "routine"),
        # staged hand-offs = a pipeline with gates
        ("ingest the papers then extract claims then draft the survey", "workflow"),
        # proof on sealed unseen work = mastery
        ("prove competence on a sealed unseen exam pack for log parsing", "mastery"),
        # durable expertise = the learning-shaped goal
        ("learn distributed consensus deeply with citations", "goal (learning-shaped)"),
        # a responsibility that never ends = mission
        ("keep the docs site consistent with the code", "mission"),
        ("monitor the mirrors for drift", "mission"),
        # explicit team ask
        ("assemble a team to ship the quarterly review", "team"),
        # one small artifact = a single gated task
        ("fetch the readme", "task"),
        ("fix the typo in ARCHITECTURE.md", "task"),
        # the default: an outcome that can carry graders
        ("build a citation-checked survey of memory architectures", "goal"),
    ]
    for goal, want in cases:
        got = universal.route(goal)
        assert got["system"] == want, (
            f"{goal!r} routed to {got['system']!r}, expected {want!r} — "
            f"the shape cue for {want} has quietly narrowed")
        for k in ("why", "how_cli", "how_panel", "note"):
            assert got.get(k), f"{goal!r} routed with no {k} — a verdict "\
                               f"with no path is a dead end wearing a label"
    # the route must be honest about being mechanical
    assert "mechanical" in universal.route("anything")["note"], (
        "the router stopped disclosing that it reads shape, not meaning")
    print(f"[route] {len(cases)} goal shapes each landed on the declared "
          f"system, every verdict carrying a why, a CLI path and a panel "
          f"path — and the note still says it is a mechanical floor, not "
          f"understanding")


def _tree(root):
    out = []
    for dirpath, _d, names in os.walk(root):
        for n in names:
            out.append(os.path.relpath(os.path.join(dirpath, n), root))
    return sorted(out)


def main():
    home = tempfile.mkdtemp(prefix="universal-")
    try:
        check_the_verdict_is_earned(home)
        check_a_weak_source_is_not_knowledge(home)
        check_authority_stops_the_run(home)
        check_a_dry_run_changes_nothing(home)
        check_every_gap_routes_somewhere_real(home)
        check_the_router_reads_shape_not_vibes(home)
        check_the_unified_entry_point_is_reachable()
        print("PASS test_universal")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def check_the_unified_entry_point_is_reachable():
    """A unified entry point nothing can reach is not an entry point.

    `universal.achieve` is the layer whose whole claim is "hand it a goal and
    it orchestrates the rest". It shipped with exactly ONE caller: its own
    CLI. The panel could reach `universal.resolve(apply=False)`, which is a
    READ — it assesses and routes and does nothing. loop.py never imported
    universal at all. So from the platform's point of view the unified layer
    was an orphan, and "give it a goal and it figures the rest out" was true
    only for someone typing at a terminal.

    Two things are asserted here, over real HTTP against a real panel:

      1. POST /api/achieve exists, is permissioned deliberately rather than
         by inheriting the unlisted-route default, and reaches the layer;
      2. when a gap routes to the OWNER, it returns started=False and names
         the blockers. Authority is the one dimension a machine must not
         resolve for itself, and that is enforced by refusing to begin — not
         by asking a model to behave.
    """
    import subprocess
    import time
    import urllib.error
    import urllib.request

    import ui as uimod

    assert uimod.POST_PERMISSION.get("/api/achieve") == "run", (
        "the unified entry point has no declared permission, so it inherits "
        "the unlisted-route default — a route this powerful should be a "
        "decision somebody made")

    home = tempfile.mkdtemp(prefix="achieve-panel-")
    os.makedirs(os.path.join(home, "experts"), exist_ok=True)
    with io.open(os.path.join(home, "settings.toml"), "w",
                 encoding="utf-8") as f:
        f.write('[agent]\npoll_interval_seconds = 1\nreflect_after = []\n\n'
                '[providers.m]\ntype = "mock"\nscript = "s.json"\n\n'
                '[roles.default]\nprovider = "m"\nmodel = "mock"\n')
    with io.open(os.path.join(home, "s.json"), "w", encoding="utf-8") as f:
        f.write("[]")
    fleet.create(home, "Probe", "a probe expert")

    port = 7911
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, os.path.join(AGENT_DIR, "ui.py"),
         "--home", home, "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def call(method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method)
        req.add_header("Origin", base)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8"))
            except Exception:
                return e.code, {}

    try:
        for _ in range(80):
            try:
                if call("GET", "/api/experts")[0] == 200:
                    break
            except Exception:
                time.sleep(0.25)
        else:
            raise AssertionError("panel did not start")

        # the route exists and validates its inputs rather than 404ing
        code, r = call("POST", "/api/achieve", {"expert": "", "goal": ""})
        assert code == 400 and "required" in json.dumps(r), (code, r)
        code, r = call("POST", "/api/achieve",
                       {"expert": "nosuchexpert", "goal": "do a thing"})
        assert code == 404, (code, r)

        # a goal whose gap routes to the OWNER must not start work
        code, r = call("POST", "/api/achieve", {
            "expert": "probe",
            "goal": "log into the vendor portal with my credentials and "
                    "download every invoice",
            "learn": False})
        assert code == 200, (code, r)
        assert r.get("started") is False, (
            f"work was STARTED on a goal that needs the owner's authority: "
            f"{r}. Refusing to begin is the enforcement; anything else is a "
            f"request that a model behave.")
        assert r.get("needs_owner"), r
        assert "authority" in (r.get("message") or "").lower(), r
        print(f"[unified] POST /api/achieve is reachable, permissioned 'run' "
              f"by declaration, validates its inputs, and REFUSED to start a "
              f"goal needing the owner — naming "
              f"{len(r['needs_owner'])} blocker(s) instead of beginning. The "
              f"layer that orchestrates everything is no longer reachable "
              f"only from a terminal.")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
