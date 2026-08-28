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


def _words(*words):
    r"""Whole words only — the same table WITHOUT the inflection tail.

    `_stems` appends `\w*`, which is exactly right for reaching
    "authenticate" from "auth" and exactly wrong for anything short enough to
    be a PREFIX of an unrelated common word. Two shipped entries were, and
    both were found by measurement rather than by reading:

        \brepo\w*            matched "report"     -> every report needs git
        sign[\s\-]*in\w*     matched "signing"    -> code-signing needs a browser

    So an entry that inflects keeps `_stems`, and an entry whose danger is
    being a prefix uses this. Multi-word entries still tolerate a space or a
    hyphen, but no longer a ZERO-width separator, which is what let "sign in"
    swallow "signing".
    """
    parts = [r"[\s\-]?".join(re.escape(t) for t in w.split()) for w in words]
    return r"\b(?:" + "|".join(parts) + r")\b"


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
    # A PAGE COUNT is a document, whatever the document is called. "read the
    # 400-PAGE FDA guidance" named no format this table knew and so asked for
    # nothing at all — while being exactly the kind of goal that fails
    # without a reader.
    (r"\b\d{2,4}[\s\-]?page\b", "pdf_text"),
    (_stems("docx", "word doc", "powerpoint", "pptx", "xlsx", "spreadsheet",
            "epub", "ebook"), "docs_convert"),
    (_stems("video", "youtube", "lecture", "webinar", "screencast"),
     "video_download"),
    (_stems("podcast", "audio", "transcribe", "transcript", "recording",
            "interview", "customer call", "sales call", "live call",
            "phone call", "on the call", "standup", "stand-up", "voicemail",
            "dictation"), "transcribe"),
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
    # The sign-in family is matched as WORDS. `_stems("sign in")` compiles to
    # `sign[\s\-]*in\w*`, where the separator class can match ZERO characters
    # — so "code-signing" is "sign" + "" + "in" + "g" and matched. Measured:
    # "sign the release binaries with our code-signing certificate" was told
    # it needed a BROWSER. Requiring a word boundary after "in" keeps every
    # real phrasing and drops the signing family entirely.
    (_words("log in", "log into", "logs in", "logged in", "logging in",
            "login", "logins", "sign in", "sign into", "signed in", "signin"),
     "browser_control"),
    (_stems("click", "fill in", "fill out", "submit", "portal", "dashboard",
            "web app", "webapp", "spa", "add to cart", "checkout",
            "browse to", "navigate to", "session", "captcha", "dropdown",
            "on the page", "in the browser",
            # A product you EXPLORE is a product something must drive. Without
            # these, "explore my SaaS and record a walkthrough" asked for the
            # recorder and the voice and nothing that could operate the app.
            "user flow", "user journey", "onboarding flow", "sign-up flow",
            "signup flow", "web ui", "walk through the app"),
     "browser_control"),
    (_words("saas", "the ui", "the app", "our app", "my app", "the product",
            "front end", "frontend", "ehr", "emr", "web portal"),
     "browser_control"),
    # "DRIVE the hospital EHR sandbox end to end" needs something that can
    # operate a UI, and nothing here saw it. Kept narrow on purpose — "drive
    # the roadmap" must not demand a browser, so the object is spelled out
    # rather than matching "drive the" alone.
    (_stems("drive the app", "drive the ui", "drive the sandbox",
            "drive the site", "drive the portal", "drive the product",
            "exercise every screen", "step through the app"),
     "browser_control"),
    (r"\bdrive\s+(?:the|our|their|this)\s+\w+\s+sandbox\b", "browser_control"),
    # WORDS, not stems, and the reason is measured. `_stems("repo")` compiles
    # to `\brepo\w*`, which matches "report" — and "report" appears in a large
    # share of every goal anybody writes. Across a 25-goal corpus, "train a
    # classifier and report held-out accuracy" and "generate a spoken audio
    # summary of the weekly report" were BOTH told they needed `git`. That is
    # the same token-versus-substring mistake this file documents twice
    # already, in its third form: a stem short enough to be a prefix of an
    # unrelated common word.
    # `clone` and `commit` are NOT here, and their absence is measured. Both
    # are ordinary English words before they are git words: "CLONE the
    # founder's voice from the old webinars" and "when someone COMMITS to a
    # date" were both told they needed a version control system. A homonym
    # that is common in plain speech earns its git reading only from the
    # company it keeps, so the git phrasings are spelled out instead.
    (_words("repo", "repos", "repository", "repositories", "git", "github",
            "gitlab", "git clone", "clone the repo", "clone the repository",
            "git commit", "commit the code", "commit history", "commit hash",
            "pull request", "pull requests", "branch", "branches",
            "rebase", "cherry-pick", "monorepo"), "git"),
    (_stems("npm", "node", "javascript", "typescript", "react", "frontend"),
     "node_js"),
    (_stems("container", "docker", "isolate", "sandbox", "untrusted"),
     "containers"),

    # ---------------------------------------------------------------- 2026-08
    # EVERY ENTRY BELOW NAMES A CAPABILITY THIS PLATFORM DOES NOT SHIP, AND
    # THAT IS THE POINT.
    #
    # Until the capability frontier existed, a hint naming something
    # `toolbox.scan` could not report was silently DROPPED by assess(), so
    # the goal was told READY and failed several milestones deep. Now an
    # unreported name becomes an honest blocking row carrying the exact
    # `python frontier.py propose ...` command. So the floor is free to name
    # what a goal actually needs instead of only what we happen to have —
    # naming it is now the useful act, and obtaining it is a separate,
    # sealed, owner-gated ladder.
    #
    # Measured on a 25-goal corpus spanning media, manufacturing, data,
    # security, devops, mobile, IoT and documents: 14 of 25 goals derived
    # NOTHING before these existed.
    (_words("ocr", "scanned", "scanned copy", "handwritten", "receipt",
            "receipts", "invoice", "invoices"), "ocr"),
    (_stems("translate", "translation", "localise", "localize",
            "localisation", "localization", "multilingual"), "translate"),
    # Naming a language IS asking for translation, and nothing here saw it:
    # "our JAPANESE supplier faxes handwritten purchase orders" and "the app
    # is entirely in FARSI and nobody here reads Farsi" both derived no
    # translation capability at all.
    (_words("japanese", "chinese", "mandarin", "cantonese", "spanish",
            "french", "german", "arabic", "farsi", "persian", "korean",
            "portuguese", "russian", "hindi", "italian", "dutch", "turkish",
            "polish", "vietnamese", "thai", "hebrew", "swedish", "greek",
            "ukrainian", "indonesian"), "translate"),
    (_words("cad", "step file", "stl", "iges", "g-code", "gcode", "cnc",
            "3d model", "3d models", "solid model", "mesh", "assembly",
            "toolpath"), "cad_model"),
    (_stems("camera feed", "cctv", "rtsp", "webcam", "live feed",
            "video stream", "surveillance"), "video_stream"),
    (_words("camera", "cameras", "dashcam", "bodycam", "ip camera"),
     "video_stream"),
    (_words("code-sign", "code signing", "codesign", "notarize", "notarise",
            "authenticode", "gpg sign", "sigstore", "signing certificate",
            "signing key"), "code_signing"),
    # "warehouse" is deliberately absent and "data warehouse" is spelled out:
    # "watch the WAREHOUSE camera and flag when a pallet is stacked above the
    # safe line" was answered with a SQL engine.
    (_stems("postgres", "postgresql", "mysql", "sqlite", "bigquery",
            "snowflake", "data warehouse", "sql query", "sql", "redshift",
            "clickhouse", "the database"), "sql_query"),
    (_stems("classifier", "fine-tune", "finetune", "training set",
            "held-out", "hyperparameter", "embedding model"), "ml_train"),
    (_stems("redact", "anonymise", "anonymize", "pseudonymise",
            "de-identify", "deidentify"), "pii_detect"),
    (_words("pii", "phi", "ehr", "emr", "personal data", "customer name",
            "customer names", "personally identifiable", "medical record",
            "medical records", "licence plate", "license plate",
            "leaks a name", "data leak"), "pii_detect"),
    (_stems("e-signature", "esignature", "esign", "docusign", "countersign",
            "signature request"), "esign"),
    (_stems("cross-compile", "crosscompile", "toolchain", "cargo", "rustc",
            "linker", "wheel build"), "native_build"),
    (_words("rust crate", "arm64", "aarch64", "x86_64", "rust binary",
            "a driver", "device driver", "allocator", "profiler",
            "flamegraph", "p99", "binary protocol"), "native_build"),
    (_stems("modbus", "serial port", "gpio", "i2c", "plc", "smart meter",
            "firmware", "rs485", "rs-485", "thermocouple", "sensor",
            "actuator", "spindle", "feed rate", "setpoint", "set point",
            "heater", "valve", "inverter", "servo", "encoder", "relay",
            "canbus", "can bus", "opc ua", "scada", "telemetry"),
     "device_io"),
    (_words("ios app", "testflight", "xcode", "android app", "apk", "aab",
            "play store", "app store"), "mobile_build"),
    # "cluster" is deliberately ABSENT: "cluster the overnight stories" is a
    # verb meaning "group", and it was matching Kubernetes. An ambiguous word
    # that is also a common verb costs a wrong answer, and a wrong answer is
    # worse than a missing one.
    (_stems("kubernetes", "kubectl", "helm", "rollback", "rolling deploy",
            "kube"), "k8s_ops"),
    (_words("rss", "atom feed", "feeds", "feed reader", "8-k", "10-k", "10-q",
            "sec filing", "sec files", "ticker", "tickers", "press release",
            "newswire"), "feed_read"),
    (_stems("accessibility", "wcag", "screen reader", "aria"), "a11y_audit"),
    (_words("a11y"), "a11y_audit"),
]

# THE DIRECTION OF A MEDIA VERB, WHICH THE FLAT TABLE ABOVE CANNOT SEE.
#
# `_stems("audio")` cannot tell "transcribe the customer calls" from "produce
# a spoken audio summary". They need OPPOSITE capabilities — recognition and
# synthesis — and the flat table answered `transcribe` for both. Measured,
# that was three of five wrong derivations in the corpus, and it is the worst
# kind of wrong: not a gap, an answer, pointing the run at a tool that does
# the reverse of what was asked.
#
# So a media noun is resolved by whether a PRODUCTION verb governs the goal.
# Mechanical and deliberately crude — it reads word presence, not grammar —
# but it moves three goals from a confident wrong answer to a correct one,
# and a wrong answer is more expensive than a coarse one.
PRODUCE_RE = _stems("produce", "generate", "create", "make", "render",
                    "synthesise", "synthesize", "narrate", "narrated",
                    "compose", "dub", "voice over", "voiceover", "author",
                    "export", "draw", "plot", "record", "publish")
DIRECTIONAL = [
    (_stems("podcast", "voice", "voice-over", "narration", "spoken",
            "speech", "read aloud", "audio summary", "audiobook"),
     "speech_synthesis", "transcribe"),
    (_stems("artwork", "illustration", "thumbnail", "logo", "picture",
            "cover art"), "image_generate", "vision"),
    (_words("chart", "charts", "graph", "graphs", "plot", "plots"),
     "chart_render", "vision"),
    (_stems("screen recording", "screencast", "walkthrough", "demo video",
            "product video"), "screen_record", "video_download"),
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

    # ------------------------------------------------------------- 2026-08
    # THE CLASS THAT WAS MISSING ENTIRELY, and the one where being wrong is
    # not an inconvenience. Measured on 25 deliberately hard goals, FIVE
    # carried an irreversible physical or financial effect and NONE of them
    # stopped:
    #
    #   "if it drifts 2 degrees, CUT POWER TO THE HEATER"
    #   "work out why from the spindle audio and ADJUST THE FEED RATE"
    #   "OPEN A WARRANTY CLAIM when output drops fifteen percent"
    #   "keep the Terraform state and the REAL AWS ACCOUNT reconciled"
    #   "OPEN A PULL REQUEST per service"
    #
    # Every existing entry in this table is about a digital permission. None
    # of them is about a machine that moves, a claim that binds, or
    # infrastructure that costs money the moment it changes. A fleet that
    # will happily de-energise a heater because a rule matched is not
    # autonomous, it is unowned. Matching is deliberately generous here for
    # the reason stated at the top of this table: a false "ask the owner"
    # costs a question, and a false "go ahead" costs a fire.
    (_stems("cut power", "turn off", "turn on", "switch off", "switch on",
            "power down", "power off", "shut down", "shutdown", "actuate",
            "open the valve", "close the valve", "feed rate", "set point",
            "setpoint", "start the motor", "stop the line", "stop the motor",
            "unlock", "lock the", "arm the", "disarm", "throttle",
            "energise", "energize", "de-energise", "de-energize",
            "override the interlock", "move the axis", "jog the"),
     "acting on physical equipment, which cannot be undone by a retry"),
    (_stems("terraform", "pulumi", "cloudformation", "aws account",
            "cloud account", "reconcile the aws", "scale the cluster",
            "rotate the key", "change the dns", "update the firewall",
            "modify the security group", "resize the", "provision a",
            "spin up", "tear down"),
     "changing live infrastructure, which bills and breaks in the real world"),
    (_stems("open a claim", "file a claim", "warranty claim", "submit a claim",
            "file a complaint", "file a dispute", "raise a ticket with",
            "open a case with", "file with the"),
     "making a claim in your name to someone outside"),
    (_stems("open a pull request", "open a pr", "raise a pull request",
            "raise a pr", "merge the", "merge to", "push to main",
            "push to master", "force push", "tag a release"),
     "changing a shared repository other people depend on"),
    (_stems("clone the voice", "voice clone", "voice cloning", "impersonate",
            "their likeness", "his likeness", "her likeness", "deepfake",
            "synthetic voice of"),
     "using a real person's voice or likeness, which is theirs to consent to"),
]

MIN_LEARN_TIER = 2          # tier 1 normative, 2 professional. 3-4 is context.


def _root(home, expert):
    return os.path.join(home, "experts", expert)


# ------------------------------------------------------------------ routing

# THE THREE FAMILIES — the front door, folded without folding the machinery.
#
# Nine work systems is a lot of doors, and several genuinely resemble each
# other: a task is a goal with one grader, a runbook is a workflow that
# earned zero-model trust, mastery is learning with a sealed proof. The
# request "merge them into 3-4" was examined seriously, and the honest
# answer has two halves:
#
#   THE FRONT DOOR MERGES. Every system belongs to one of three families,
#   named by what you walk away with — an OUTCOME, a COMPETENCE, or an
#   ANSWER. Three choices cover every ask, and the router picks the lane
#   inside the family mechanically, so a newcomer never faces nine options.
#
#   THE MACHINERY DOES NOT. The resemblances are real but the differences
#   are load-bearing, and each is a tested law rather than a naming
#   accident: a workflow's stages are executed by a MODEL behind a gate
#   while a runbook's steps run with ZERO model calls under trust earned
#   from three verified wins — merging them erases the platform's central
#   safety boundary (who executes). Learning produces cited notes; mastery
#   is an exam the student cannot read — merging them lets the student
#   grade itself. A task's one done-check and a goal's frozen graders
#   differ exactly where TAMPER detection lives. All nine already share
#   one engine (every lane enqueues into loop.py's single task queue, one
#   authority stack, one memory), so a code merge would buy no power —
#   only the risk of rewriting 119 tests' worth of proven behaviour.
#
# So: three families at the door, nine proven lanes behind it, and the
# router as the concierge in between.
FAMILIES = {
    "work": "you walk away with an OUTCOME — something done, verified by "
            "checks the worker cannot edit",
    "competence": "you walk away with a CAPABILITY — the fleet is durably "
                  "better at something, and can prove it on unseen work",
    "answers": "you walk away with an ANSWER — cited from what the fleet "
               "actually knows, or an honest NOT IN MY TRAINING",
}
FAMILY = {
    "task": "work", "goal": "work", "mission": "work", "workflow": "work",
    "team": "work", "routine": "work", "prospective intention": "work",
    "goal (learning-shaped)": "competence", "mastery": "competence",
    "consult": "answers",
}


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
        return {"system": system,
                "family": FAMILY.get(system, "work"),
                "family_why": FAMILIES[FAMILY.get(system, "work")],
                "why": why, "how_cli": how_cli,
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

def required_capabilities(goal, criteria="", root=None):
    """-> [(capability, why)] the goal's own words imply.

    The hint table below is the FLOOR: free, deterministic, and finite. Being
    finite is the whole reason `root` exists. A goal needing something the
    table never anticipated — speech synthesis, screen recording, a CAD
    kernel — matched nothing, so the platform reported READY and failed the
    run several milestones deep. With `root`, this also asks the capability
    frontier what THIS fleet has learned it needs, which is a ledger of
    capabilities it has actually met, proved or been refused — never a model's
    guess. `root=None` reproduces the shipped behaviour exactly.
    """
    text = f"{goal} {criteria}".lower()
    out, seen = [], set()
    # Direction first: a media noun under a production verb needs the OPPOSITE
    # capability from the same noun under a reading verb, and the flat table
    # below cannot tell them apart.
    producing = re.search(PRODUCE_RE, text) is not None
    for pattern, make_cap, read_cap in DIRECTIONAL:
        m = re.search(pattern, text)
        if not m:
            continue
        # "chart the distribution" is a VERB; "describe the chart" is a noun.
        # A determiner immediately after the word is the cheapest mechanical
        # signal that separates them, and without it "chart the distribution"
        # asked for image UNDERSTANDING to draw a graph.
        verb = re.match(r"\s+(the|a|an|it|them|these|those|all|our|my)\b",
                        text[m.end():m.end() + 7]) is not None
        makes = producing or verb
        cap = make_cap if makes else read_cap
        if cap not in seen:
            out.append((cap, f"the goal mentions {m.group(0)!r} and "
                             f"{'produces' if makes else 'reads'} it"))
        # BOTH sides are marked seen, not just the winner. Once the direction
        # is decided, the flat table below must not quietly add the opposite
        # capability on the strength of the same noun — which it did:
        # "produce a spoken audio summary" came back asking for synthesis AND
        # recognition, and a run handed both picks whichever it likes.
        seen.add(make_cap)
        seen.add(read_cap)
    for pattern, cap in CAPABILITY_HINTS:
        m = re.search(pattern, text)
        if m and cap not in seen:
            seen.add(cap)
            out.append((cap, f"the goal mentions {m.group(0)!r}"))
    if root:
        try:
            import frontier
            for cap, why in frontier.implied(root, goal, criteria):
                if cap not in seen:
                    seen.add(cap)
                    out.append((cap, why))
        except (OSError, ValueError, ImportError):
            pass
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
    for cap, why in required_capabilities(goal, criteria, root=root):
        row = caps.get(cap)
        if row is None:
            # THE FALSE-READY HOLE, CLOSED. This used to `continue`, so a
            # capability the hint table named and this machine could not
            # report was silently DROPPED — and a goal needing it was told
            # READY, then failed several milestones deep. A named capability
            # nothing reports is a gap, and the fix is a command, not a shrug.
            gaps.append({"dimension": "capability", "what": cap, "why": why,
                         "detail": f"this capability is named by the goal but "
                                   f"nothing on this machine reports it — "
                                   f"`python frontier.py propose {cap} "
                                   f"--root {root} --need \"...\" "
                                   f"--quote \"...\" --goal \"...\"`",
                         "routes_to": mission.GAPS["capability"]["routes_to"],
                         "user_sees": mission.GAPS["capability"]["user_sees"]})
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
                                      required_capabilities(goal, criteria,
                                                            root=root)]}


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
        print(f"FAMILY: {r['family'].upper()} — {r['family_why']}")
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
