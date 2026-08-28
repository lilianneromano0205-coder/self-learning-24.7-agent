#!/usr/bin/env python3
"""THE UNIVERSAL AGENT — one goal in, a readiness verdict and real work out.

Every system in this platform already does one job well: `goal.py` pursues an
objective until mechanical checks pass, `curriculum.py` decides what to study
first, `sources.py` rates whether a source is worth believing, `acquire.py`
walks a capability from requested to trusted, `mission.py` classifies WHY a
thing is blocked, `candidates.py` spends inference compute to make a small
model behave like a larger one.

What did not exist was the thing that decides WHICH of them a goal needs, in
what order, and whether the fleet is honestly ready to start. Handing a goal
straight to `goal.pursue` assumes the expert already knows the domain and
already owns the tools. When it does not, the run fails several milestones
deep, in a way that reads like the model being weak — when the real answer
was "it needed a PDF reader" or "it had never studied this".

So this module adds one layer and no duplication. Every step below DELEGATES:

    ASSESS      what does this goal require that we do not have?
                -> mission.GAPS, the platform's own six-dimension router
    RESOLVE     each gap goes where its dimension says it goes:
                  knowledge   -> ingest from AUTHORITATIVE sources -> study
                  capability  -> acquire.py's ladder, in an isolated worker
                  authority   -> the OWNER. never attempted. see below.
                  strategy    -> replan, which goal.py already does per cycle
                  environment -> re-probe, then replan
                  execution   -> retry with the failure as evidence
    READY       a verdict that is EARNED, not asserted: every required
                capability probes READY, every knowledge area has cited atoms
                from tier<=2 sources, and nothing is waiting on a human
    PURSUE      hand to goal.pursue, which already refuses to call anything
                done until its checks exit 0

THE ONE THING THIS WILL NOT DO, AND WHY

Authority gaps are never self-resolved. A missing credential, a permission,
an account, a payment, a human decision — the router routes those to the
owner and this module stops and says so. That is not timidity, it is the
platform's own rule ("this one cannot be solved by trying harder"), and it is
the difference between an agent that is autonomous and one that is unowned.
An agent that could grant itself authority would have no boundary at all, and
every control in this repository would be advisory.

WHY A CHEAP MODEL IS ENOUGH HERE

Nothing in this module asks a model whether it is ready. Readiness is read
off the same mechanical probes the panel reads: toolbox capability scans,
cited-atom counts, tier ratings, and the gate. That is the platform's thesis
applied to itself — capability comes from the system around the model, so the
system, not the model, decides when it is ready.

    python universal.py ready   --expert <slug> --goal "..."
    python universal.py achieve --expert <slug> --goal "..." [--cycles 4]
    python universal.py explain --expert <slug> --goal "..."
"""

import argparse
import json
import os
import re
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

# A Windows console defaults to cp1252, which cannot encode the arrows in the
# panel paths route() prints. Same guard acquire.py, chief.py and ui.py use.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):        # pragma: no cover
    pass

# What a goal's words imply it will need. Deterministic and inspectable on
# purpose: a model asked "what tools do you need?" answers plausibly and
# unfalsifiably, and this platform does not accept plausible.
def _stems(*words):
    r"""A pattern matching any of these words AND their ordinary inflections.

    The previous version of this table was written as whole-word alternations
    and it FAILED OPEN on ordinary English. Measured, 9 everyday phrasings:

        MISSED     log into the supplier portal
        MISSED     log in to the dashboard
        MISSED     sign in to the console
        AUTHORITY  login to the portal
        MISSED     authenticate with the vendor
        MISSED     use my credentials
        AUTHORITY  sign up for an account
        MISSED     check out the cart
        AUTHORITY  send an email to the vendor

    Six of nine missed, for three reasons that are all the same reason:
      * `\blogin\b` matches "login" but not "log into" or "sign in"
      * `\bauth\b` cannot match "authenticate" — \b needs a boundary after
        "auth", and "authenticate" continues with a word character
      * `\bcredential\b` cannot match "credentialS", for the same reason

    That is the token-versus-substring mistake this codebase has now made
    four times, INVERTED: too strict in the one place whose own comment says
    it must be generous, because "a false 'go ahead' costs an account, a
    charge, or a breach".

    So the table is no longer hand-written regex. It is WORDS, and the
    pattern is generated: each stem matches its own inflections (-s, -ed,
    -ing, -ion...) and multi-word entries tolerate a space or a hyphen. A
    corpus of phrasings is asserted in tests/test_universal.py, so this can
    never quietly narrow again — the failure mode was silence, and only an
    enumeration turns silence into a red test.
    """
    parts = []
    for w in words:
        toks = w.split()
        # "log in" also appears as "login" and "log-in"; a stem may grow a
        # suffix, so "authenticate" is reached from "auth" + \w*
        parts.append(r"[\s\-]*".join(re.escape(t) for t in toks) + r"\w*")
    return r"\b(?:" + "|".join(parts) + r")"


# Every entry is a STEM, for the reason written at length on _stems below.
# This table had the identical plural blindness the authority table had, and
# it produced the same class of failure in the opposite direction — silent
# UNDER-detection. Measured before the fix:
#
#     summarise these PDFs          -> []            (no capability at all)
#     describe these screenshots    -> []
#     download these videos         -> []
#     convert these spreadsheets    -> []
#     read the images               -> []
#     summarise this PDF            -> ['pdf_text']  (singular worked)
#
# `\bpdf\b` cannot match "PDFs". So the most natural way anybody phrases a
# batch job — the plural — asked for nothing, the readiness check found no
# missing capability, and the goal was reported READY for work the fleet
# could not do. A requirements detector that only understands the singular is
# a false-READY generator, and READY is the one verdict this module exists to
# make honest.
CAPABILITY_HINTS = [
    (_stems("pdf", "paper", "whitepaper", "datasheet", "spec sheet"), "pdf_text"),
    (_stems("docx", "word doc", "powerpoint", "pptx", "xlsx", "spreadsheet",
            "epub", "ebook"), "docs_convert"),
    (_stems("video", "youtube", "lecture", "webinar", "screencast"),
     "video_download"),
    (_stems("podcast", "audio", "transcribe", "transcript", "recording",
            "interview"), "transcribe"),
    (_stems("image", "screenshot", "diagram", "chart", "photo", "figure",
            "scan"), "vision"),
    (_stems("website", "web page", "webpage", "scrape", "crawl", "online",
            "internet", "url", "docs site"), "web_fetch"),
    # A REAL BROWSER, not a fetcher. `web_fetch` is stdlib urllib: it cannot
    # log in, cannot run JavaScript, cannot click, cannot fill a form. Goals
    # phrased "log into the portal and download each invoice" matched
    # `website|online|url` above, were answered with web_fetch, and would
    # have been reported READY for work that cannot begin. Anything naming an
    # INTERACTION or an authenticated surface needs the browser capability,
    # which mcp.py's catalog has always been able to provide via playwright.
    (_stems("log in", "log into", "login", "sign in", "signed in", "logged in",
            "click", "fill in", "fill out", "submit", "portal", "dashboard",
            "web app", "webapp", "spa", "add to cart", "checkout",
            "browse to", "navigate to", "session", "captcha", "dropdown",
            "on the page", "in the browser"),
     "browser_control"),
    (_stems("repo", "repository", "git", "github", "clone", "commit",
            "pull request"), "git"),
    (_stems("npm", "node", "javascript", "typescript", "react", "frontend"),
     "node_js"),
    (_stems("container", "docker", "isolate", "sandbox", "untrusted"),
     "containers"),
]

# Words that mean the goal needs something only the owner can give. These are
# routed to the human immediately rather than attempted — see the module
# docstring. Matching is deliberately generous: a false "ask the owner" costs
# a question, a false "go ahead" costs an account, a charge, or a breach.
AUTHORITY_HINTS = [
    (_stems("sign up", "signup", "register", "registration", "create account",
            "create an account", "new account", "onboard", "enrol", "enroll"),
     "creating an account"),
    (_stems("pay", "payment", "purchase", "buy", "subscribe", "subscription",
            "billing", "invoice", "checkout", "check out", "card", "refund",
            "order"),
     "spending money"),
    (_stems("api key", "apikey", "credential", "token", "password", "passwd",
            "secret", "login", "log in", "log into", "sign in", "signin",
            "auth", "oauth", "sso", "2fa", "mfa", "session cookie",
            "access key"),
     "a credential only you can issue"),
    (_stems("publish", "deploy to production", "go live", "release to",
            "ship to production", "push to production"),
     "publishing something to the world"),
    (_stems("email", "e mail", "mailbox", "inbox", "reply to", "outreach",
            "contact", "dm", "message them", "send a message", "notify"),
     "sending something on your behalf"),
    (r"\b(?:delete|remove|drop|wipe|purge|destroy|terminate)\w*\b.*"
     r"\b(?:production|database|account|bucket|repo|repository|volume|cluster)\w*",
     "destroying something that cannot be restored"),
]

MIN_LEARN_TIER = 2          # tier 1 normative, 2 professional. 3-4 is context.


def _root(home, expert):
    return os.path.join(home, "experts", expert)


# ------------------------------------------------------------------ routing

def route(goal, criteria=""):
    """WHICH SYSTEM FITS THIS ASK — the systems map's picking rule as code.

    The platform has nine work systems and one law under them all; what a
    newcomer (or an orchestrator) lacks is the reflex for which one a given
    sentence wants. This is that reflex, MECHANICAL like everything that
    routes here: shape cues, not model opinions. It returns the best-fit
    system with the exact command and panel path, plus honest alternatives
    — and it says plainly that it is a keyword floor the owner can
    override. Changing systems mid-flight stays a first-class move: steer
    a goal, interrupt it to blocked and resume, lift a task into a goal by
    giving it graders — the router picks a starting door, never a cage."""
    t = f"{goal or ''} {criteria or ''}".strip()
    low = " " + t.lower() + " "
    first = (t.split() or [""])[0].lower().rstrip(",:;")
    note = ("routed by shape cues (a mechanical floor, not understanding) "
            "— override freely; every system ends the same way: a check "
            "the worker cannot edit")

    def R(system, why, how_cli, how_panel, alts=None):
        return {"system": system, "why": why, "how_cli": how_cli,
                "how_panel": how_panel, "alternatives": alts or [],
                "note": note}

    if t.rstrip().endswith("?") or first in (
            "what", "why", "how", "when", "who", "which", "where",
            "should", "is", "are", "can", "does", "do", "did"):
        return R("consult",
                 "a question, not an action — every claim in the answer "
                 "must cite the expert's own notes or say NOT IN MY TRAINING",
                 'python consult.py ask <root> "the question"',
                 "agent → Access → Ask")
    if re.search(r"\b(when(ever)?|if|each time)\b[^.]{3,120}\b(then|alert|"
                 r"notify|re-?run|redo|update|do|start|tell)\b", low):
        return R("prospective intention",
                 "a future action tied to a condition — held in the "
                 "intention ledger and fired by the scheduler, never left "
                 "to a model's memory",
                 'python prospective.py add --root <root> --goal "..." '
                 '--when-check "<probe that exits 0 when it is time>"',
                 "agent → Work (intentions)")
    if re.search(r"\b(every|each)\s+(day|week|month|morning|evening|night|"
                 r"hour|monday|friday|\d)", low) or re.search(
                 r"\b(daily|weekly|monthly|nightly|hourly)\b", low):
        return R("routine",
                 "recurring work on a schedule — the loop wakes it; nobody "
                 "has to remember",
                 'python routines.py add --root <root> ...',
                 "agent → Work (routines)")
    if re.search(r"\bthen\b[^.]{3,160}\bthen\b", low) or "->" in t \
            or "→" in t or re.search(r"\bstages?\b|\bpipeline\b", low):
        return R("workflow",
                 "fixed stages with a gate between each — a pipeline where "
                 "predictability beats autonomy, and a failed gate stops "
                 "the line",
                 'python workflows.py run <root> ...',
                 "Work → Workflows")
    if re.search(r"\b(prove|certif\w*|examin\w*|competence)\b", low) and \
            re.search(r"\b(unseen|sealed|pack|exam\w*|prove|certif\w*)\b",
                      low):
        return R("mastery",
                 "competence proven on SEALED unseen tasks — the exam the "
                 "student can neither read nor edit, with the pretest → "
                 "exam lift measured",
                 'python mastery.py run <home> <expert> <pack> --drive',
                 "agent → Mastery")
    learn_words = ("learn", "study", "master", "understand",
                   "become expert", "training on", "get good at")
    if any(w in low for w in learn_words):
        return R("goal (learning-shaped)",
                 "building durable expertise — the goal engine seeds the "
                 "study plan: sources → cited notes → spec → closed-book "
                 "exam → re-study what was missed",
                 'python goal.py pursue "learn ..." --expert <slug> --drive',
                 "Work → New goal",
                 alts=[{"system": "mastery",
                        "why": "add a capability pack when the competence "
                               "must be PROVEN on unseen work"}])
    if first in ("keep", "maintain", "monitor", "watch", "ensure", "stay",
                 "track") or re.search(r"\b(ongoing|standing|at all times|"
                                       r"continuously)\b", low):
        return R("mission",
                 "a standing responsibility, not a single deliverable — an "
                 "objective with criteria held on disk, served by many "
                 "tasks and goals over time",
                 'python mission.py new "objective" --criterion "..."',
                 "Home bar → New mission",
                 alts=[{"system": "routine",
                        "why": "if the work repeats on a fixed schedule "
                               "rather than needing judgment"}])
    if re.search(r"\bteam\b", low):
        return R("team",
                 "work too broad for one agent — 2–4 specialists and a "
                 "lead, handoffs as files, constraints hashed",
                 "Work → New team (panel)", "Work → New team")
    if len(t) < 90 and re.search(r"\b(fix|write|create|produce|add|update|"
                                 r"rename|convert|delete|fetch|download)\b",
                                 low) \
            and " and " not in low:
        return R("task",
                 "one small deliverable — a single gated job is cheaper "
                 "and faster than a pursuit",
                 'python loop.py add --role practitioner --goal "..." '
                 '--done-check "<command>"',
                 "agent → Work → ＋ task",
                 alts=[{"system": "goal",
                        "why": "promote it by adding graders (--accept) if "
                               "\"done\" needs more than one check"}])
    return R("goal",
             "an outcome that can carry frozen graders — the default for "
             "anything testable, pursued until the graders pass",
             'python goal.py pursue "..." --expert <slug> --drive '
             '--accept "what::command"',
             "Work → New goal",
             alts=[{"system": "task",
                    "why": "if it is really one small artifact"},
                   {"system": "mission",
                    "why": "if it is a responsibility that never ends"}])


# --------------------------------------------------------------- assessment

def required_capabilities(goal, criteria=""):
    """-> [(capability, why)] the goal's own words imply."""
    text = f"{goal} {criteria}".lower()
    out, seen = [], set()
    for pattern, cap in CAPABILITY_HINTS:
        m = re.search(pattern, text)
        if m and cap not in seen:
            seen.add(cap)
            out.append((cap, f"the goal mentions {m.group(0)!r}"))
    return out


def authority_gaps(goal, criteria=""):
    """-> [(what, why)] this goal needs from the OWNER and cannot self-serve."""
    text = f"{goal} {criteria}".lower()
    out, seen = [], set()
    for pattern, what in AUTHORITY_HINTS:
        m = re.search(pattern, text)
        if m and what not in seen:
            seen.add(what)
            out.append((what, f"{m.group(0)!r} in the goal implies {what}"))
    return out


def _scope_of(goal):
    """The concrete TARGET a goal acts on, for matching against a grant.

    A grant is only a decision if it names something: "may spend money" is a
    surrender, "may spend up to $200 at acme.com" is a permission somebody
    can actually reason about. So the scope is taken from the goal's own
    words — a hostname if it has one, otherwise the most specific noun
    phrase available — and an owner grants against exactly that string.

    Deliberately narrow and deliberately literal. If this guessed broadly, a
    grant for one vendor would silently cover another, which is the failure
    mode that makes standing permissions dangerous in the first place.
    """
    text = str(goal or "")
    m = re.search(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b", text.lower())
    if m:
        return m.group(1)
    m = re.search(r"\b(?:the|our|my)\s+([a-z0-9][a-z0-9 -]{2,30}?)\s+"
                  r"(?:portal|account|dashboard|vendor|supplier|site|service|"
                  r"console|inbox|mailbox)\b", text.lower())
    if m:
        return re.sub(r"\s+", "-", m.group(1).strip())
    return "unscoped"


def assess(home, expert, goal, criteria=""):
    """What stands between this expert and this goal, by gap dimension.

    Reads the same probes the panel reads. Nothing here is a model's opinion.
    """
    import mission
    import toolbox
    root = _root(home, expert)
    caps = toolbox.scan(root)["capabilities"]

    gaps = []
    granted = []                 # authority the owner has already answered
    for cap, why in required_capabilities(goal, criteria):
        row = caps.get(cap)
        if row is None:
            continue
        if not row["ready"]:
            gaps.append({"dimension": "capability", "what": cap, "why": why,
                         "detail": row["how"],
                         "routes_to": mission.GAPS["capability"]["routes_to"],
                         "user_sees": mission.GAPS["capability"]["user_sees"]})
    # An authority gap the OWNER HAS ALREADY ANSWERED is not a gap.
    #
    # The rule that authority is never self-resolved is right, and it stopped
    # every single time — so a fleet meant to run all night parked on a human
    # at the first invoice, and an owner asked the same question forty times
    # stops reading the questions. grants.py adds the middle that authority
    # actually has between people: a scoped, expiring, revocable, logged
    # permission the owner gives ONCE. Nothing self-grants — grants.grant()
    # requires owner authority and refuses even an admin — and the moment a
    # grant expires or is revoked this reverts to asking, with no code change.
    _grants = None
    try:
        import grants as _grants
    except Exception:                        # pragma: no cover — optional
        _grants = None
    for what, why in authority_gaps(goal, criteria):
        covered, note = (False, "")
        if _grants is not None:
            kind = next((k for k, v in _grants.KINDS.items() if v == what), None)
            if kind:
                covered, note = _grants.check(home, kind, _scope_of(goal))
        if covered:
            # `kind` and `scope` travel with the entry so resolve() can log
            # the USE later. They are not decoration: grants.record_use needs
            # both, and without them the only thing that could be recorded is
            # "something happened", which is not an audit trail.
            granted.append({"what": what, "why": why, "grant": note,
                            "kind": kind, "scope": _scope_of(goal)})
            continue
        gaps.append({"dimension": "authority", "what": what, "why": why,
                     "detail": ("only the owner can grant this"
                                + (f" — {note}" if note else "")),
                     "routes_to": mission.GAPS["authority"]["routes_to"],
                     "user_sees": mission.GAPS["authority"]["user_sees"]})

    known = knowledge_on_hand(root, goal, criteria)
    if not known["atoms"]:
        gaps.append({"dimension": "knowledge", "what": "the subject itself",
                     "why": "no studied atom in this expert matches the goal",
                     "detail": f"searched {known['courses']} course(s)",
                     "routes_to": mission.GAPS["knowledge"]["routes_to"],
                     "user_sees": mission.GAPS["knowledge"]["user_sees"]})
    return {"expert": expert, "goal": goal, "criteria": criteria,
            "gaps": gaps, "knowledge": known, "granted": granted,
            "capabilities_required": [c for c, _ in
                                      required_capabilities(goal, criteria)]}


def knowledge_on_hand(root, goal, criteria=""):
    """How much of this goal the expert has ALREADY studied, with citations.

    Counted from cited atoms on disk rather than asked of a model, for the
    same reason every other number here is: an expert that believes it knows
    a subject and an expert that knows it look identical from the inside.
    """
    # THE THIRD COPY OF ONE WALKER, now removed.
    #
    # This function used to os.walk the course tree itself and re-declare the
    # atom regex `^\s*-\s*([CPU]-\d{2,}[\w.]*)\s+(.*)$` inline. citecheck.py
    # had one, knowledge.py had another, and this was the third — three
    # descriptions of "what an atom is and where atoms live", which is the
    # defect this codebase finds more often than any other. It had already
    # bitten once: knowledge.py's copy joined a flat path the platform never
    # writes, so the knowledge graph was empty against every real expert.
    #
    # There is now one definition of an atom (citecheck.ATOM_DEF_RE), one
    # walker (citecheck.notes_files), and one parser (knowledge.atoms). This
    # asks knowledge.py, which is also the production caller that module was
    # missing — it had shipped with a CLI and no consumer.
    words = {w for w in re.findall(r"[a-z0-9]{4,}", f"{goal} {criteria}".lower())}
    cdir = os.path.join(root, "courses")
    if not os.path.isdir(cdir):
        return {"atoms": [], "courses": 0, "matched": 0, "best_tier": None}
    try:
        import knowledge as _kn
        rows = _kn.atoms(root)
    except Exception:                        # pragma: no cover
        return {"atoms": [], "courses": 0, "matched": 0, "best_tier": None}
    atoms, tiers = [], []
    for a in rows:
        claim = a.get("claim") or ""
        # the same rule as before: at least TWO substantive words shared, so
        # a single incidental word does not count as having studied a subject
        if len({w for w in re.findall(r"[a-z0-9]{4,}", claim.lower())}
               & words) < 2:
            continue
        atoms.append({"id": a["id"], "course": a.get("course", ""),
                      "text": claim[:120]})
        if a.get("source"):
            tier, _why = _kn._tier_of(a["source"])
            tiers.append(tier)
    courses = len({a.get("course") for a in rows if a.get("course")}) or len(
        [d for d in os.listdir(cdir) if os.path.isdir(os.path.join(cdir, d))])
    return {"atoms": atoms[:40], "courses": courses, "matched": len(atoms),
            "best_tier": min(tiers) if tiers else None}


# ------------------------------------------------------------- the verdict

def ready(home, expert, goal, criteria=""):
    """-> a readiness verdict that had to be EARNED.

    "Ready" means: every capability the goal implies is READY on this machine,
    nothing is waiting on the owner, and the subject has been studied to
    cited atoms from sources worth believing. Any one of those failing is a
    reason, not a score — the caller is told which, and where it routes.
    """
    a = assess(home, expert, goal, criteria)
    blocking = [g for g in a["gaps"] if g["dimension"] in
                ("capability", "authority", "knowledge")]
    needs_owner = [g for g in a["gaps"] if g["dimension"] == "authority"]
    tier = a["knowledge"]["best_tier"]
    weak_sources = (tier is not None and tier > MIN_LEARN_TIER)
    if weak_sources:
        blocking.append({
            "dimension": "knowledge", "what": "source quality",
            "why": f"the best source behind what this expert knows is tier "
                   f"{tier}; learning is held to tier {MIN_LEARN_TIER} or better",
            "detail": "study normative or professional sources before relying "
                      "on this",
            "routes_to": "research → sources → curriculum → study → exam",
            "user_sees": "Needs better sources"})
    verdict = "READY" if not blocking else (
        "NEEDS YOU" if needs_owner else "NOT READY")
    return {**a, "verdict": verdict, "blocking": blocking,
            "needs_owner": needs_owner,
            "why": _explain(verdict, blocking, a)}


def _explain(verdict, blocking, a):
    if verdict == "READY":
        return (f"every capability this goal implies is present, nothing is "
                f"waiting on you, and {a['knowledge']['matched']} studied "
                f"atom(s) already cover the subject")
    parts = []
    for dim in ("authority", "capability", "knowledge"):
        rows = [g for g in blocking if g["dimension"] == dim]
        if rows:
            parts.append(f"{len(rows)} {dim} gap(s): "
                         + ", ".join(sorted({r["what"] for r in rows})))
    return "; ".join(parts)


# -------------------------------------------------------------- resolution

def resolve(home, expert, goal, criteria="", apply=False):
    """Route every non-authority gap to the system that owns it.

    Returns the plan. With apply=False (the default) it is a dry run and
    changes nothing — because a system that starts installing packages the
    moment you describe a goal is not one anybody would leave running.
    """
    r = ready(home, expert, goal, criteria)
    root = _root(home, expert)
    actions = []

    # A STANDING GRANT WITHOUT A USAGE LOG IS A BLANK CHEQUE.
    #
    # grants.py says exactly that in record_use's own docstring — and nothing
    # in the platform called it. Grants worked: a covered authority gap was
    # suppressed and the run proceeded. But the owner who wrote "yes, this
    # expert may send email about invoices, for 90 days" had no way to see
    # what had been done in their name, and `python grants.py uses` printed
    # an empty ledger no matter how much work a grant had authorised. The
    # module documented the failure mode and then committed it.
    #
    # Recorded HERE and only when apply=True, deliberately. assess() runs on
    # every read — the panel calls it while somebody is typing a sentence —
    # and logging a "use" for each of those would fill the ledger with
    # readings and make the real ones unfindable. apply=True is the moment
    # the platform is acting rather than looking.
    if apply and r.get("granted"):
        try:
            import grants as _g
            for gr in r["granted"]:
                if not gr.get("kind"):
                    continue
                try:
                    _g.record_use(home, gr["kind"], gr.get("scope") or "",
                                  detail=f"{expert}: {goal[:160]}",
                                  task=expert)
                except Exception as e:
                    # A grant that has expired between assess() and here is a
                    # REFUSAL, not a crash — and it must be visible rather
                    # than swallowed, because "the grant lapsed mid-run" is
                    # exactly what an auditor needs to see.
                    actions.append({
                        "gap": gr["what"], "action": "ask the owner",
                        "command": None, "done": False,
                        "why": f"the grant covering this stopped applying "
                               f"before the work started: {e}"})
        except Exception:                    # pragma: no cover — optional
            pass
    for g in r["blocking"]:
        if g["dimension"] == "authority":
            actions.append({"gap": g["what"], "action": "ask the owner",
                            "command": None, "done": False,
                            "why": "authority is the one dimension a machine "
                                   "must never resolve for itself"})
            continue
        if g["dimension"] == "capability":
            # A CAPABILITY IS NOT A PACKAGE NAME. This used to pass the
            # capability label straight to PyPI with an empty version, so
            # every request was refused ("no version pinned") before it
            # reached a network, and the ones that got past that would have
            # asked PyPI for a project called `pdf_text`. toolbox.recipe()
            # is the map from what is MISSING to what can be DONE about it.
            import toolbox as _tb
            rx = _tb.recipe(g["what"])
            if rx is None:
                actions.append({
                    "gap": g["what"], "action": "ask the owner",
                    "command": None, "done": False,
                    "why": f"no acquisition route is known for "
                           f"{g['what']!r}. The platform will not improvise "
                           f"an installer for a capability it cannot name."})
                continue
            if "owner" in rx:
                # The honest answer for a missing key or system binary:
                # this is not something an installer can fix.
                actions.append({
                    "gap": g["what"], "action": "ask the owner",
                    "command": rx.get("command"), "done": False,
                    "why": rx["owner"]})
                continue
            cmd = (f"python acquire.py request {rx['package']} --root {root} "
                   f"--source {rx['source']} --version {rx['version']} "
                   f"--why {json.dumps(g['why'])}")
            rec = None
            if apply:
                # `acquire.request(root, name, source, need, ...)` — the
                # first version of this omitted `source`, so every call
                # raised TypeError, and the broad `except` below recorded it
                # as an error nobody read. The acquisition path was dead the
                # day it was written: exactly the silent-failure shape this
                # platform keeps finding, committed while fixing another one.
                #
                # The exception is still caught, because an acquisition that
                # cannot start must not take the whole assessment down with
                # it — but the reason is now surfaced in the returned action
                # rather than swallowed, and the test asserts a real record
                # comes back rather than merely that nothing raised.
                try:
                    import acquire
                    rec = acquire.request(root, rx["package"], rx["source"],
                                          g["why"], version=rx["version"])
                except Exception as e:
                    rec = {"error": f"{type(e).__name__}: {e}"}
            actions.append({"gap": g["what"], "action": "acquire the capability",
                            "command": cmd, "done": bool(rec and "error" not in rec),
                            "result": rec,
                            "why": "the acquisition ladder installs into an "
                                   "isolated worker and must pass a capability "
                                   "test before anything is trusted"})
            continue
        if g["dimension"] == "knowledge":
            cmd = (f"python goal.py pursue {json.dumps('learn: ' + goal)} "
                   f"--expert {expert}")
            # THE FIRST STEP OF STUDYING IS FINDING SOMETHING TO STUDY, and
            # until discover.py existed this branch could not take it. It
            # emitted a command string with done=False and stopped — the
            # study plan's own first milestone reads "gather real sources
            # (… / search results the …)", assuming a search nothing
            # implemented. So "learn it yourself" ended at a human pasting
            # links, which is the opposite of the claim.
            #
            # Discovery is READ-ONLY and free: it queries public catalogues
            # and fetches nothing. That is why it is safe to run under
            # apply=True while ingestion — which writes to the expert and
            # costs a fetch per document — stays an explicit separate act
            # with its commands printed for the operator.
            found, cmds, why_more = [], [], ""
            if apply:
                try:
                    import discover
                    res = discover.search(goal, limit=8)
                    found = res.get("hits") or []
                    cmds = discover.add_url_commands(res, root=root)
                    if not found:
                        why_more = (
                            f" Discovery ran and found nothing above tier "
                            f"{MIN_LEARN_TIER} across {len(res.get('rails') or [])} "
                            f"catalogue(s) — {res.get('found', 0)} candidate(s) "
                            f"were seen and {res.get('filtered', 0)} were below "
                            f"the bar. These catalogues do not index "
                            f"everything; the alternative, a web search, is "
                            f"what the platform refuses on purpose.")
                    else:
                        why_more = (
                            f" Discovery found {len(found)} source(s) at tier "
                            f"{min(h['tier'] for h in found)} or better, "
                            f"ready to ingest.")
                except Exception as e:
                    why_more = (f" Discovery could not run: "
                                f"{type(e).__name__}: {str(e)[:120]}")
            actions.append({"gap": g["what"], "action": "study the subject",
                            "command": cmd,
                            # done means "this step produced something real",
                            # and finding the reading list is real progress.
                            # It does not mean the expert has LEARNED it —
                            # only a passed closed-book exam means that.
                            "done": bool(found),
                            "sources": found,
                            "ingest_commands": cmds,
                            "why": f"goal.py already seeds a study-shaped plan "
                                   f"for a learning goal: gather sources -> "
                                   f"ingest -> cited notes -> closed-book exam. "
                                   f"Sources are held to tier {MIN_LEARN_TIER} "
                                   f"or better.{why_more}"})
    return {**r, "actions": actions, "applied": bool(apply)}


def achieve(home, expert, goal, criteria="", cycles=4, drive=False,
            learn=True):
    """Assess, resolve what can be resolved, then pursue — refusing to start
    while the owner is the blocker.

    This is the one entry point the whole platform was missing: a goal in, and
    either real work or a precise statement of what is standing in the way.
    """
    plan = resolve(home, expert, goal, criteria, apply=learn)
    if plan["needs_owner"]:
        return {**plan, "started": False,
                "message": "STOPPED before starting: this goal needs you. "
                           + "; ".join(g["what"] for g in plan["needs_owner"])
                           + ". Nothing was attempted, because authority is "
                             "the one gap a machine must not resolve for "
                             "itself."}
    import goal as goalmod
    res = goalmod.pursue(home, expert, goal, criteria=criteria,
                         cycles=cycles, drive=drive)
    return {**plan, "started": True, "pursuit": res}


# --------------------------------------------------------------------- CLI

def _print_verdict(r):
    print(f"GOAL     {r['goal']}")
    print(f"EXPERT   {r['expert']}")
    print(f"VERDICT  {r['verdict']}")
    print(f"WHY      {r['why']}")
    if r.get("capabilities_required"):
        print(f"NEEDS    {', '.join(r['capabilities_required'])}")
    k = r["knowledge"]
    print(f"KNOWS    {k['matched']} matching atom(s) across {k['courses']} "
          f"course(s)"
          + (f", best source tier {k['best_tier']}" if k["best_tier"] else ""))
    for g in r.get("blocking", []):
        print(f"  [{g['user_sees']}] {g['what']} — {g['why']}")
        print(f"      routes to: {g['routes_to']}")
    for a in r.get("actions", []):
        mark = "done" if a.get("done") else "todo"
        print(f"  ({mark}) {a['action']}: {a['gap']}")
        if a.get("command"):
            print(f"      {a['command']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("route", help="which system fits this goal, and why")
    pr.add_argument("--goal", required=True)
    pr.add_argument("--criteria", default="")
    pr.add_argument("--json", action="store_true")
    for name in ("ready", "explain", "achieve"):
        p = sub.add_parser(name)
        p.add_argument("--expert", required=True)
        p.add_argument("--goal", required=True)
        p.add_argument("--criteria", default="")
        p.add_argument("--home", default=HOME)
        p.add_argument("--json", action="store_true")
        if name == "achieve":
            p.add_argument("--cycles", type=int, default=4)
            p.add_argument("--drive", action="store_true")
            p.add_argument("--no-learn", action="store_true",
                           help="assess only; do not open acquisitions")
    a = ap.parse_args()

    if a.cmd == "route":
        r = route(a.goal, a.criteria)
        if a.json:
            print(json.dumps(r, indent=2))
            return
        print(f"SYSTEM: {r['system'].upper()}")
        print(f"  why:   {r['why']}")
        print(f"  cli:   {r['how_cli']}")
        print(f"  panel: {r['how_panel']}")
        for alt in r["alternatives"]:
            print(f"  or {alt['system']}: {alt['why']}")
        print(f"  ({r['note']})")
        return

    if a.cmd == "ready":
        r = ready(a.home, a.expert, a.goal, a.criteria)
    elif a.cmd == "explain":
        r = resolve(a.home, a.expert, a.goal, a.criteria, apply=False)
    else:
        r = achieve(a.home, a.expert, a.goal, a.criteria, cycles=a.cycles,
                    drive=a.drive, learn=not a.no_learn)
    if a.json:
        print(json.dumps(r, indent=1, default=str))
    else:
        _print_verdict(r)
        if r.get("message"):
            print("\n" + r["message"])
    return 0 if r.get("verdict") == "READY" or r.get("started") else 1


if __name__ == "__main__":
    sys.exit(main())
