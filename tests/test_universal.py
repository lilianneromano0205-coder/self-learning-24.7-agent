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

    # THE THREE FAMILIES. The front door folds to three; the machinery does
    # not. Every routed system must carry a family from exactly that set,
    # with its one-line "what you walk away with" — and every system the
    # router can name must be classified, because an unclassified lane is a
    # tenth door wearing no sign.
    assert set(universal.FAMILIES) == {"work", "competence", "answers"}, (
        "the family set changed; the door is supposed to have THREE choices")
    for goal, want in cases:
        r = universal.route(goal)
        assert r["family"] in universal.FAMILIES, (
            f"{want!r} routed with family {r.get('family')!r}, which is not "
            f"one of the three")
        assert r["family_why"] == universal.FAMILIES[r["family"]], (
            "the family's one-line meaning drifted from the single table")
    assert universal.FAMILY["mastery"] == "competence"
    assert universal.FAMILY["goal (learning-shaped)"] == "competence"
    assert universal.FAMILY["consult"] == "answers"
    fams = {universal.route(g)["family"] for g, _ in cases}
    assert fams == {"work", "competence", "answers"}, (
        f"the corpus no longer exercises all three families: {fams}")
    print(f"[route] {len(cases)} goal shapes each landed on the declared "
          f"system, every verdict carrying a why, a CLI path and a panel "
          f"path — and the note still says it is a mechanical floor, not "
          f"understanding")


def check_a_wild_goal_is_never_silently_capable(home):
    """25 GOALS FROM 25 UNRELATED TRADES. NONE MAY DERIVE NOTHING.

    "Ready for any goal" is a claim, and this is the measurement behind it.
    The corpus deliberately spans media, manufacturing, data, security,
    devops, mobile, IoT, legal and documents, because a derivation tuned on
    one trade looks excellent until it meets another.

    Three outcomes look identical from outside and are not:

        SILENT  nothing derived -> the goal can be reported READY and then
                fail several milestones deep. THE WORST ONE, and it is
                banned outright below.
        WRONG   a capability derived that does the reverse of what was asked
                — recognition where synthesis was needed. Worse than a gap,
                because a gap stops and a wrong answer proceeds.
        OK      what was derived is at least a real part of what is needed.

    Measured before the fixes this check now pins: 6 OK, 5 WRONG, 14 SILENT.
    Every one of those 14 was a goal the platform would have called READY.

    A capability named here need NOT exist on this machine. Since the
    capability frontier landed, an unreported name becomes an honest blocking
    row carrying the exact `frontier.py propose` command instead of being
    silently dropped — so naming what a goal actually needs is the useful
    act, and obtaining it is a separate, sealed, owner-gated ladder.
    """
    CORPUS = [
        ("explore my SaaS end to end and produce a narrated screen-recorded "
         "walkthrough with voice", ("speech_synthesis", "screen_record")),
        ("generate a spoken audio summary of the weekly report",
         ("speech_synthesis",)),
        ("render a 3D CAD model of the bracket and export it as STEP",
         ("cad_model",)),
        ("watch the factory camera feed and alert on anomalies",
         ("video_stream",)),
        ("sign the release binaries with our code-signing certificate",
         ("code_signing",)),
        ("OCR the scanned supplier invoices and post them into the ledger",
         ("ocr",)),
        ("translate the product docs into Japanese and keep them in sync",
         ("translate",)),
        ("run a Monte Carlo simulation on the portfolio and chart the "
         "distribution", ("chart_render",)),
        ("transcribe the customer calls and label who is speaking",
         ("transcribe",)),
        ("generate album artwork variants and upscale them to print "
         "resolution", ("image_generate",)),
        ("query the production Postgres and publish a weekly metrics digest",
         ("sql_query",)),
        ("log into the competitor portal and diff their pricing page weekly",
         ("browser_control",)),
        ("convert the CAD assembly into printable G-code for the shop floor",
         ("cad_model",)),
        ("detect personal data in the support tickets and redact it before "
         "export", ("pii_detect",)),
        ("train a small classifier on the labelled tickets and report "
         "held-out accuracy", ("ml_train",)),
        ("send the signed contract for e-signature and track completion",
         ("esign",)),
        ("cross-compile the Rust crate for ARM and publish the artifact",
         ("native_build",)),
        ("read the smart meter Modbus registers and alert on drift",
         ("device_io",)),
        ("build the iOS app and upload it to TestFlight", ("mobile_build",)),
        ("summarise a 900-page deposition PDF with page citations",
         ("pdf_text",)),
        ("produce a podcast episode from the weekly notes with a music bed",
         ("speech_synthesis",)),
        ("watch the Kubernetes cluster and roll back a bad deploy",
         ("k8s_ops",)),
        ("extract the tables from these scanned PDFs into a spreadsheet",
         ("pdf_text", "ocr")),
        ("cluster the overnight RSS stories and publish a daily brief",
         ("feed_read",)),
        ("run an accessibility audit on the web app and file the issues",
         ("a11y_audit",)),
    ]
    silent, missing = [], []
    for goal, expected in CORPUS:
        derived = {c for c, _ in universal.required_capabilities(goal)}
        if not derived:
            silent.append(goal)
            continue
        absent = [e for e in expected if e not in derived]
        if absent:
            missing.append((goal, absent, sorted(derived)))
    assert not silent, (
        f"{len(silent)} goal(s) derived NO capability at all, so each would "
        f"be reported READY and then fail mid-run: {silent[:4]}")
    assert not missing, (
        f"{len(missing)} goal(s) lost the capability they are about: "
        f"{missing[:4]}")

    # THE DIRECTION BUGS, PINNED SEPARATELY. Each of these was a confident
    # WRONG answer that sent a run at a tool doing the reverse of the task.
    for goal, banned, why in (
            ("produce a spoken audio summary", "transcribe",
             "synthesis answered with recognition"),
            ("chart the distribution of returns", "vision",
             "drawing a chart answered with image understanding"),
            ("train a classifier and report held-out accuracy", "git",
             "the stem repo\\w* matching the word 'report'"),
            ("sign the release binaries with a code-signing certificate",
             "browser_control",
             "the stem sign[\\s-]*in\\w* matching 'signing'")):
        got = {c for c, _ in universal.required_capabilities(goal)}
        assert banned not in got, (
            f"{goal!r} derived {banned!r} again — {why}. A wrong capability "
            f"is more expensive than a missing one, because a gap stops the "
            f"run and an answer proceeds with it")
    print(f"[corpus] {len(CORPUS)} goals across 25 unrelated trades: none "
          f"derives nothing, each keeps the capability it is about, and the "
          f"four measured direction bugs (report->git, signing->browser, "
          f"spoken->transcribe, chart->vision) all stay fixed. Before: 6 OK, "
          f"5 WRONG, 14 SILENT")


def check_a_wild_goal_stops_before_it_moves_something(home):
    """25 HARD GOALS. THE CAPABILITY ANSWER MATTERS; THE AUTHORITY ANSWER
    MATTERS MORE.

    The corpus in the previous check is broad. This one is ADVERSARIAL: every
    goal is multi-capability, cross-domain, and phrased the way an operator
    actually speaks rather than the way a keyword table hopes. Several carry
    an irreversible physical or financial effect, and for those the question
    is not "did it find the right tool" but "did it stop".

    Measured before the entries this check pins, on these exact 25 goals:

        derived nothing at all       : 5
        lost a needed capability     : 12
        FAILED TO STOP FOR THE OWNER : 5     <- the one that burns something

    The five that did not stop were: cutting power to a heater, adjusting a
    CNC feed rate, opening a warranty claim, reconciling a live AWS account,
    and opening a pull request per service. Every existing authority entry
    was about a digital permission; none was about a machine that moves, a
    claim that binds, or infrastructure that bills. A fleet that will
    de-energise a heater because a rule matched is not autonomous, it is
    unowned.

    Three homonyms are pinned here too, each of which produced a confident
    wrong answer: "when someone COMMITS to a date" asking for git, "CLONE the
    founder's voice" asking for git, and "watch the WAREHOUSE camera" asking
    for a SQL engine.
    """
    WILD = [
        ("reverse-engineer the undocumented binary protocol our label "
         "printer speaks over RS485 and emit a working driver",
         ("device_io", "native_build"), False),
        ("sit in on the Thursday standup recording, and when someone commits "
         "to a date, add it to the roadmap", ("transcribe",), False),
        ("watch the fermentation tank thermocouple and if it drifts 2 "
         "degrees for ten minutes, cut power to the heater",
         ("device_io",), True),
        ("we only have 1998 blueprints as scanned tiff, produce a printable "
         "STL from them", ("ocr", "cad_model"), False),
        ("clone the founder's voice from the old webinars and narrate the "
         "new onboarding video", ("speech_synthesis",), True),
        ("find every place in the monorepo that leaks a customer name into "
         "logs and open a pull request per service",
         ("git", "pii_detect"), True),
        ("when the SEC files a new 8-K for any ticker we hold, summarise the "
         "material change before the market opens", ("feed_read",), False),
        ("drive the hospital EHR sandbox end to end and confirm no PHI "
         "crosses the boundary", ("browser_control", "pii_detect"), False),
        ("our Japanese supplier faxes handwritten purchase orders — turn "
         "them into NetSuite line items", ("ocr", "translate"), True),
        ("produce a 30-second ad in nine aspect ratios with a localised "
         "voiceover for each market",
         ("speech_synthesis", "translate"), False),
        ("profile the Rust binary under load and prove the p99 regression "
         "came from the allocator change", ("native_build",), False),
        ("sign and notarise the macOS build, then verify Gatekeeper accepts "
         "it on a clean container", ("code_signing", "containers"), False),
        ("read the 400-page FDA guidance and tell me which of our twelve "
         "claims are now non-compliant", ("pdf_text",), False),
        ("watch the warehouse camera and flag when a pallet is stacked "
         "above the safe line", ("video_stream",), False),
        ("recover the rows deleted from the production Postgres between "
         "14:02 and 14:09", ("sql_query",), True),
        ("run our SaaS through a screen reader and file every WCAG AA "
         "violation with a repro screen recording",
         ("a11y_audit", "browser_control", "screen_record"), False),
        ("in sixty hours of bodycam footage, find every frame showing a "
         "licence plate and redact it", ("pii_detect",), False),
        ("the CNC finish is chattering — work out why from the spindle "
         "audio and adjust the feed rate",
         ("transcribe", "device_io"), True),
        ("keep the Terraform state and the real AWS account reconciled and "
         "tell me what drifted overnight", (), True),
        ("build a digital twin of the packaging line from the PLC tag list "
         "and simulate a twenty percent throughput increase",
         ("device_io",), False),
        ("prove our LLM feature does not leak the system prompt across five "
         "hundred adversarial inputs", (), False),
        ("the app is entirely in Farsi and nobody here reads Farsi — map "
         "every screen and tell me what each one does",
         ("browser_control", "translate"), False),
        ("monitor the roof solar inverter over Modbus and open a warranty "
         "claim when output drops fifteen percent for three days",
         ("device_io",), True),
        ("migrate the twelve-year-old Access database into Postgres without "
         "losing the report logic", ("sql_query",), False),
        ("during a live customer call, when the customer names a "
         "competitor, surface the battlecard on screen",
         ("transcribe",), False),
    ]
    unowned, silent, missing = [], [], []
    for goal, want_caps, want_owner in WILD:
        caps = {c for c, _ in universal.required_capabilities(goal)}
        if want_owner and not universal.authority_gaps(goal):
            unowned.append(goal)
        if want_caps and not caps:
            silent.append(goal)
        absent = [c for c in want_caps if c not in caps]
        if absent:
            missing.append((goal[:48], absent))
    assert not unowned, (
        f"{len(unowned)} goal(s) carrying an irreversible physical or "
        f"financial effect did NOT stop for the owner: {unowned[:3]}. This "
        f"is the only failure in this file that costs something that cannot "
        f"be retried.")
    assert not silent, (
        f"{len(silent)} wild goal(s) derived nothing, so each would be "
        f"reported READY: {silent[:3]}")
    assert not missing, (
        f"{len(missing)} wild goal(s) lost a capability they are about: "
        f"{missing[:4]}")

    # the homonyms, each of which was a confident wrong answer
    for goal, banned, why in (
            ("when someone commits to a date, add it to the roadmap", "git",
             "'commits' is a promise here, not a revision"),
            ("clone the founder's voice from the old webinars",
             "git", "'clone' is a voice here, not a repository"),
            ("watch the warehouse camera for unsafe stacking", "sql_query",
             "a physical warehouse is not a data warehouse")):
        got = {c for c, _ in universal.required_capabilities(goal)}
        assert banned not in got, (
            f"{goal!r} derived {banned!r} — {why}")
    owner_goals = sum(1 for _g, _c, o in WILD if o)
    print(f"[wild] {len(WILD)} adversarial goals across manufacturing, "
          f"medical, legal, finance, media and infrastructure: none derives "
          f"nothing, none loses a capability it is about, and all "
          f"{owner_goals} carrying an irreversible physical or financial "
          f"effect stop for the owner. Before: 5 silent, 12 incomplete, 5 "
          f"that would have acted")


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
        check_a_wild_goal_is_never_silently_capable(home)
        check_a_wild_goal_stops_before_it_moves_something(home)
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
