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
            granted.append({"what": what, "why": why, "grant": note})
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
    words = {w for w in re.findall(r"[a-z0-9]{4,}", f"{goal} {criteria}".lower())}
    atoms, courses, tiers = [], 0, []
    cdir = os.path.join(root, "courses")
    if not os.path.isdir(cdir):
        return {"atoms": [], "courses": 0, "matched": 0, "best_tier": None}
    try:
        import sources as _src
    except ImportError:                      # pragma: no cover
        _src = None
    for course in sorted(os.listdir(cdir)):
        cpath = os.path.join(cdir, course)
        if not os.path.isdir(cpath):
            continue
        courses += 1
        for dirpath, _d, names in os.walk(cpath):
            for fn in names:
                if fn != "notes.md":
                    continue
                try:
                    with open(os.path.join(dirpath, fn), encoding="utf-8",
                              errors="replace") as f:
                        body = f.read()
                except OSError:
                    continue
                for line in body.splitlines():
                    m = re.match(r"^\s*-\s*([CPU]-\d{2,}[\w.]*)\s+(.*)$", line)
                    if not m:
                        continue
                    text = m.group(2).lower()
                    if len({w for w in re.findall(r"[a-z0-9]{4,}", text)} & words) >= 2:
                        atoms.append({"id": m.group(1), "course": course,
                                      "text": m.group(2)[:120]})
                        src = re.search(r"\[src:\s*([^\]]+)\]", m.group(2))
                        if src and _src:
                            try:
                                _k, tier, _why = _src.classify(src.group(1).strip())
                                tiers.append(tier)
                            except Exception:
                                pass
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
    for g in r["blocking"]:
        if g["dimension"] == "authority":
            actions.append({"gap": g["what"], "action": "ask the owner",
                            "command": None, "done": False,
                            "why": "authority is the one dimension a machine "
                                   "must never resolve for itself"})
            continue
        if g["dimension"] == "capability":
            cmd = (f"python acquire.py request {g['what']} --root {root} "
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
                    rec = acquire.request(root, g["what"], "pypi",
                                          g["why"], version="")
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
            actions.append({"gap": g["what"], "action": "study the subject",
                            "command": cmd, "done": False,
                            "why": f"goal.py already seeds a study-shaped plan "
                                   f"for a learning goal: gather sources -> "
                                   f"ingest -> cited notes -> closed-book exam. "
                                   f"Sources are held to tier {MIN_LEARN_TIER} "
                                   f"or better."})
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
