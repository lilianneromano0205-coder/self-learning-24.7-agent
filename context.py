#!/usr/bin/env python3
"""The context compiler — what the model sees is a COMPILED VIEW, not a pile.

Google's ADK states it plainly: context is a compiled projection over
sessions, memory and artifacts, produced by processors — never the raw
transcript. Letta's Context Constitution adds the operational half: context
is a scarce resource, so every block must justify its tokens, and the owner
must be able to SEE the window the agent was given (their ADE calls it the
Context Window Viewer). Anthropic's context engineering work supplies the
budget discipline: pick the smallest set of high-signal tokens.

So this module compiles the first user message from named SOURCES, each with
its own token budget:

    commons  the fleet's shared lessons digest (+ owner pins)
    course   the mission and index of the course the task belongs to
    gotchas  environment failures this expert already paid for   (M4)
    premise  contradictions between the goal and verified memory (M4)
    skills   activated playbooks + a name-only index of the rest
    memory_files  the files the task was handed
    stop     the task's declared stop condition

Every compile writes a MANIFEST next to the transcript
(contexts/<task>.compile.json): which sources ran, what each was allowed,
what it used, which files were included, trimmed or dropped, and why the
router excluded a kind. Nothing about the window is hidden or guessed —
`python context.py --root <expert> --task <id>` prints it, and so does the
panel.

Trimming is explicit and recoverable: an over-budget file is cut at its
budget and marked with a pointer telling the agent to read the rest with
read_file. Content is never silently dropped.
"""

import json
import os
import re

DEFAULT_BUDGETS = {          # tokens (~4 chars each)
    # the mission contract goes FIRST and is never trimmed away: it is the
    # one thing whose loss makes every other token pointless (manual §11)
    "mission": 900,
    "self": 600,
    "commons": 1500,
    "course": 2500,
    "standards": 700,
    "authority": 400,
    "conflicts": 700,
    "cases": 700,
    "gotchas": 800,
    "premise": 400,
    "skills": 3000,
    "memory_files": 12000,
    "stop": 100,
}
# self first: an agent that knows what it has actually verified reads
# everything after it differently. Authority and conflicts ride with the
# course, because they are the rules for reading that material.
ORDER = ["mission", "self", "commons", "course", "standards", "authority",
         "conflicts", "cases", "gotchas", "premise", "skills", "memory_files"]

# ORDER is the BUDGET order — which source is filled first, and the order the
# manifest reports. EMIT_ORDER is the order the blocks are WRITTEN into the
# message. Splitting the two makes an important fact explicit: which blocks
# are the same for every task and which are chosen FOR this task.
#
# WHAT WAS MEASURED, INCLUDING THE PART THAT DISAPPOINTED
#
# Providers cache by PREFIX, and only a byte-identical one. So the intent was
# to put everything fleet-stable first and lengthen that prefix. Measured on
# an expert with 400 cited atoms and 6 skills, comparing two DIFFERENT goals:
#
#     original order       shared prefix 4,769 / 18,342 chars = 26%
#     stable-first order   shared prefix 4,769 / 18,342 chars = 26%
#     skills-last order    shared prefix 4,769 / 18,342 chars = 26%
#
# Identical. Reordering did NOT lengthen the cacheable prefix, and the reason
# is worth writing down rather than hiding:
#
#   * `skills` is 12,084 of those 18,342 chars — 66% of the window — and it
#     is ACTIVATED BY KEYWORD against the goal, so it differs per task by
#     design. It is not stable material and never was.
#   * `self` (the competence model) also differs: the shared prefix ends 642
#     chars into it. An earlier check compared byte COUNTS and file paths and
#     called it stable; comparing the actual text showed it is not.
#
# So the binding constraint on caching here is not the order of the blocks —
# it is that the two largest early blocks are both selected per task. That is
# a real and useful thing to know: the way to cut token cost on this platform
# is to make skill activation stable per (expert, course) rather than per
# goal, NOT to shuffle the window.
#
# The split is kept anyway, for the reason that did survive measurement: the
# task-specific material now sits immediately before the goal instead of at
# the top, and the middle of a long window is where retrieval is weakest.
# That is an attention argument, not a cost argument, and it is not claimed
# as a saving.
#
# Safe because trimming is strictly PER SOURCE: each _Source owns its own
# char budget and there is no global cap after assembly (`total_tokens` is
# reported, never enforced). "The mission contract is never trimmed" comes
# from its own budget and from `kinds.add("mission")`, not from its position.
# Which blocks are the same for every task in a fleet, and which are chosen
# FOR this task even when their names suggest otherwise. Recorded because it
# is the useful half of the experiment below; NOT used to reorder the window.
#   authority  = which SOURCES outrank which, rendered per COURSE
#   conflicts  = contradictions matched against this GOAL
#   self       = the competence model, which reads differently per task
#   skills     = activated by keyword against the goal — 66% of the window
STABLE_KINDS = ("standards", "commons", "gotchas")
TASK_KINDS = ("authority", "conflicts", "self", "course", "cases", "premise",
              "skills", "memory_files", "mission")

# EMIT_ORDER IS ORDER. The experiment is written down rather than shipped.
#
# Providers cache by prefix and only a byte-identical one, so putting stable
# material first should lengthen the cacheable prefix. It does not:
#
#     original order       shared prefix 4,769 / 18,342 chars = 26%
#     stable-first order   shared prefix 4,769 / 18,342 chars = 26%
#     skills-last order    shared prefix 4,769 / 18,342 chars = 26%
#
# Identical, because `skills` is 12,084 of those chars and is activated by
# keyword against the goal, and `self` differs per task too — the two largest
# early blocks are both selected per task, so no permutation of them can be
# shared between tasks. The binding constraint is not the order.
#
# And the reorder has a real cost. tests/test_mission.py asserts
# `window.index("MISSION CONTRACT") < 250` for every role: manual §11 puts
# the contract at the LEAD of the window, because it is the one thing whose
# loss makes every other token pointless. Moving it to sit beside the goal
# broke that invariant, in exchange for a measured zero.
#
# So: no change to what the model sees. The way to cut token cost on this
# platform is to make skill activation stable per (expert, course) instead of
# per goal — which is a real piece of work with a real relevance trade-off,
# not a reshuffle.
EMIT_ORDER = list(ORDER)
# Two lists that must hold the same names, and a third thing comparing them —
# the lesson this codebase keeps relearning. A kind added to ORDER and
# forgotten here would be silently dropped from every context window.
assert set(EMIT_ORDER) == set(ORDER), (
    f"EMIT_ORDER and ORDER disagree: "
    f"{set(ORDER) ^ set(EMIT_ORDER)} is in one and not the other")
SKILL_INDEX_CAP = 30
SKILL_INDEX_TOKENS = 600

try:                                             # M4 — optional at import
    import gotchas as _gotchas
except Exception:                                # pragma: no cover
    _gotchas = None
try:
    import premise as _premise
except Exception:                                # pragma: no cover
    _premise = None
try:
    import memrouter as _memrouter
except Exception:                                # pragma: no cover
    _memrouter = None
try:
    import skills as _skills                     # the skill graph + discovery
except Exception:                                # pragma: no cover
    _skills = None
try:                                             # M9 — awareness + evidence
    import selfmodel as _selfmodel
except Exception:                                # pragma: no cover
    _selfmodel = None
try:
    import sources as _sources
except Exception:                                # pragma: no cover
    _sources = None
try:
    import conflicts as _conflicts
except Exception:                                # pragma: no cover
    _conflicts = None


def est_tokens(text):
    return len(text) // 4


def budgets(cfg):
    """[agent.context_budget] in settings.toml overrides any default."""
    out = dict(DEFAULT_BUDGETS)
    over = ((cfg or {}).get("agent", {}) or {}).get("context_budget", {}) or {}
    for k, v in over.items():
        try:
            out[k] = int(v)
        except (TypeError, ValueError):
            pass
    return out


def fence(rel, text):
    """Data marking (spotlighting), identical to the loop's own fence: the
    grounding contract forbids obeying instructions found inside it."""
    return (f"=== {rel} ===\n<<<FILE-CONTENT {rel}>>>\n{text}\n"
            f"<<<END-FILE-CONTENT {rel}>>>")


def _read(root, rel):
    try:
        with open(os.path.join(root, rel), "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


class _Source:
    """One named source with a char budget it may not exceed."""

    def __init__(self, name, token_budget):
        self.name = name
        self.budget = token_budget * 4          # chars
        self.used = 0
        self.blocks = []
        self.included = []
        self.dropped = []
        self.excluded = None                    # set by the memory router

    def room(self):
        return max(0, self.budget - self.used)

    def add(self, rel, text, annotate=None):
        """Add one file, trimming it to what the budget still allows."""
        raw = len(text)
        if self.room() <= 0:
            self.dropped.append({"path": rel, "chars": raw,
                                 "why": "source budget exhausted"})
            return False
        trimmed = False
        if raw > self.room():
            cut = self.room()
            text = (text[:cut] +
                    f"\n[...trimmed: {raw - cut} chars over budget; "
                    f"read_file {rel} for the rest]")
            trimmed = True
        block = fence(rel, text)
        if annotate:
            block = annotate(block)
        self.blocks.append(block)
        self.used += len(text)
        self.included.append({"path": rel, "chars": len(text),
                              "tokens": est_tokens(text), "trimmed": trimmed,
                              "of": raw})
        return True

    def add_text(self, label, text):
        """Add generated (not file-backed) content, e.g. a premise warning.

        HONEST ABOUT THE CUT, like add() beside it. This truncated with a
        bare slice and then recorded `"trimmed": False, "of": len(text)` —
        the length AFTER the cut — so the Context Window Viewer reported a
        block as fully included while the model had received it chopped
        mid-sentence, with no pointer to the rest. A gotchas block is a
        BINDING instruction; half of one is worse than none, and a manifest
        that cannot say so is worse than both.
        """
        raw = len(text)
        room = self.room()
        if room <= 0:
            self.dropped.append({"path": label, "chars": raw,
                                 "why": "source budget exhausted"})
            return False
        trimmed = False
        if raw > room:
            text = (text[:room]
                    + f"\n[...trimmed: {raw - room} chars over budget]")
            trimmed = True
        if not text.strip():
            return False
        self.blocks.append(text)
        self.used += len(text)
        self.included.append({"path": label, "chars": len(text),
                              "tokens": est_tokens(text), "trimmed": trimmed,
                              "of": raw})
        return True

    def report(self):
        return {"name": self.name, "budget_tokens": self.budget // 4,
                "used_tokens": est_tokens("x" * self.used),
                "used_chars": self.used, "included": self.included,
                "dropped": self.dropped, "excluded_by_router": self.excluded}


def compile(agent, task):
    """Build (messages, manifest) for a task's first model call."""
    root, goal = agent.root, task["goal"]
    tid = task.get("id") or "adhoc"
    course = task.get("course")
    role = task["role"]
    bud = budgets(getattr(agent, "cfg", {}))
    router = (_memrouter.decide(task, getattr(agent, "cfg", {}))
              if _memrouter else
              {"rule": "all", "kinds": list(ORDER), "excluded": [],
               "why": "no memory router installed"})
    kinds = set(router.get("kinds") or ORDER)
    # The mission contract is NOT a memory kind and is never routed away. It
    # is the assignment itself — what this task is FOR — so a role that may
    # see less MEMORY (the Student sits closed-book) must still see what it
    # was asked to do and by what standard it will be judged. Routing it
    # would reintroduce exactly the drift the contract exists to prevent.
    kinds.add("mission")
    src = {n: _Source(n, bud.get(n, 1000)) for n in ORDER}
    for n in ORDER:
        if n not in kinds:
            src[n].excluded = router.get("why") or "excluded by the memory router"

    # --- mission: the contract this task exists to serve. Recompiled from
    # disk on every call, so compaction, a restart or a model swap cannot
    # quietly soften the objective (manual §11 anti-drift).
    if src["mission"].excluded is None and task.get("mission"):
        try:
            import mission as _mission
            state = _mission.compile_state(root, task["mission"])
            block = _mission.render(state)
            if task.get("criterion"):
                block += ("\nTHIS TASK serves criterion "
                          f"{task['criterion']}. If what you are about to do "
                          f"does not advance it, stop and say so.")
            src["mission"].add_text("mission", block)
        except Exception:
            pass

    # --- self: what this agent has actually verified, and where it ends
    if src["self"].excluded is None and _selfmodel:
        try:
            model = _selfmodel.build(root, role, task, getattr(agent, "cfg", {}))
            src["self"].add_text("self", _selfmodel.render(model))
        except Exception:
            pass

    # --- commons: the fleet's shared lessons (owner pins ride first)
    if src["commons"].excluded is None:
        text = _read(root, "commons-digest.md")
        if text:
            src["commons"].add("commons-digest.md", text)

    # --- course: the mission and index of the material being worked
    if src["course"].excluded is None and course:
        for name in ("mission.md", "index.md"):
            rel = os.path.join("courses", course, name).replace(os.sep, "/")
            text = _read(root, rel)
            if text:
                src["course"].add(rel, text)

    # --- standards: the bar this course's own material demands
    if src["standards"].excluded is None and course:
        try:
            import standards as _standards
            block = _standards.render(root, course)
            if block:
                src["standards"].add_text("standards", block)
        except Exception:
            pass

    # --- authority: what this course rests on, and who outranks whom
    if src["authority"].excluded is None and _sources and course:
        try:
            block = _sources.render(root, course)
            if block:
                src["authority"].add_text("authority", block)
        except Exception:
            pass

    # --- conflicts: where this expert's own material disagrees with itself
    if src["conflicts"].excluded is None and _conflicts and course:
        try:
            _conflicts.refresh(root, course)     # only rescans when stale
            hits = _conflicts.matching(root, goal, course)
            if hits:
                src["conflicts"].add_text("conflicts", _conflicts.render(hits))
        except Exception:
            pass

    # --- cases: has this expert been here before, and what fixed it?
    if src["cases"].excluded is None:
        try:
            import cases as _cases
            hits = _cases.matching(root, goal)
            if hits:
                src["cases"].add_text("cases", _cases.render(hits))
        except Exception:
            pass

    # --- experience: what a SIBLING already paid to learn
    #
    # commons.py has always shared the fleet's lessons and corroborated
    # facts. Its cases and gotchas were per-expert and read by nobody else —
    # `grep -rn "experts" cases.py gotchas.py` returned nothing — so a second
    # expert doing similar work started blind to every wall the first one
    # walked into, and walked into them again at full price. Failure is the
    # expensive half of what a fleet knows; sharing only the conclusions and
    # not the scars is the most costly way to run one.
    #
    # It rides in the `cases` budget deliberately: a sibling's case competes
    # for room with this expert's OWN cases and loses ties to them, because
    # the expert's own history is the better evidence about its own
    # environment. Attribution is in the rendered text, never merged away.
    if src["cases"].excluded is None and src["cases"].room() > 0:
        try:
            import experience as _experience
            me = os.path.basename(os.path.abspath(root))
            sib = _experience.matching(
                os.path.dirname(os.path.dirname(os.path.abspath(root))),
                goal, exclude=me)
            if sib:
                src["cases"].add_text("experience", _experience.render(sib))
        except Exception:
            pass

    # --- gotchas: failures this expert already paid for (M4)
    if src["gotchas"].excluded is None and _gotchas:
        try:
            hits = _gotchas.matching(root, goal, course)
            if hits:
                src["gotchas"].add_text("gotchas", _gotchas.render(hits))
        except Exception:
            pass
        # A SIBLING's environment failures, after this expert's own and
        # inside the same budget. A gotcha is the cheapest knowledge in the
        # fleet to reuse and was the most private: "pandoc is not on PATH in
        # the container" was rediscovered, at full cost, by every expert on
        # the same machine. It rides second and loses ties on purpose — an
        # expert's own gotcha is binding on it, a stranger's is a warning,
        # and render_gotchas says which is which rather than blurring them.
        if src["gotchas"].room() > 0:
            try:
                import experience as _experience
                me = os.path.basename(os.path.abspath(root))
                sib = _experience.gotchas_matching(
                    os.path.dirname(os.path.dirname(os.path.abspath(root))),
                    goal, exclude=me, course=course)
                if sib:
                    src["gotchas"].add_text("sibling-gotchas",
                                            _experience.render_gotchas(sib))
            except Exception:
                pass

    # --- premise: does verified memory contradict the goal? (M4)
    warnings = []
    if src["premise"].excluded is None and _premise:
        try:
            warnings = _premise.check(root, goal, course)
            if warnings:
                src["premise"].add_text("premise", _premise.render(warnings))
                log = getattr(agent, "log", None)
                if log:
                    log.info(json.dumps({
                        "event": "premise_warning", "task": tid,
                        "kinds": sorted({w["kind"] for w in warnings}),
                        "subjects": [w["subject"] for w in warnings][:6]}))
        except Exception:
            warnings = []

    # --- skills: activated playbooks, plus a name-only index (disclosure)
    loaded = []
    if src["skills"].excluded is None:
        loaded = agent.matching_skills(goal)
        task["skills_used"] = loaded
        for rel in loaded:
            text = _read(root, rel)
            if text is None:
                continue
            ann = None
            if _skills:
                # two labels ride with every playbook: what it has EARNED
                # (the graph status) and where it CAME FROM (provenance)
                def _ann(block, r=rel):
                    block = _skills.annotate(root, r, block)
                    warn = _skills.banner(root, r)
                    return f"{warn}\n{block}" if warn else block
                ann = _ann
            src["skills"].add(rel, text, annotate=ann)
        idx = skill_index(agent, exclude=loaded)
        if idx:
            src["skills"].add_text("SKILL INDEX", idx)
    else:
        task["skills_used"] = []

    # --- memory_files: what the task was handed
    if src["memory_files"].excluded is None:
        for rel in task.get("memory_files", []):
            text = _read(root, rel)
            if text is None:
                src["memory_files"].blocks.append(f"=== {rel} === (unreadable)")
                src["memory_files"].dropped.append(
                    {"path": rel, "chars": 0, "why": "unreadable"})
                continue
            src["memory_files"].add(rel, text)
    if src["memory_files"].dropped:
        names = ", ".join(d["path"] for d in src["memory_files"].dropped[:6])
        src["memory_files"].blocks.append(
            f"[{len(src['memory_files'].dropped)} handed file(s) not loaded "
            f"into this window: {names} — read_file them if you need them]")

    blocks = []
    for n in EMIT_ORDER:            # stable-first, task-last: see EMIT_ORDER
        blocks.extend(src[n].blocks)
    user = ""
    if blocks:
        user += "\n\n".join(blocks) + "\n\n"
    user += f"Task: {goal}"
    if course:
        user += f"\nCourse: {course}"
    if task.get("stop"):
        import loop as _loop                     # late: avoids a cycle
        user += f"\nSTOP CONDITION: {_loop.stop_text(task['stop'])}"

    system = agent.system_prompt(role)
    sys_files, variant = agent.system_sources(role)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    manifest = {
        "task": tid, "role": role, "goal": goal[:300],
        "course": course,
        "system": {"files": [os.path.relpath(p, root).replace(os.sep, "/")
                             for p in sys_files],
                   "variant": variant, "chars": len(system),
                   "tokens": est_tokens(system)},
        "sources": [src[n].report() for n in ORDER],
        "router": router,
        "premise": warnings,
        "skills_activated": loaded,
        "user_chars": len(user), "user_tokens": est_tokens(user),
        "total_tokens": est_tokens(system) + est_tokens(user),
        "compactions": [],
    }
    if task.get("id"):        # ad-hoc compiles (previews, tests) leave no file
        save_manifest(root, tid, manifest)
    return messages, manifest


def skill_index(agent, exclude=()):
    """Progressive disclosure (the Agent Skills standard): skills that did
    NOT activate are still announced by name + one line, so the agent knows
    the playbook exists and can read it — at a fraction of the tokens."""
    root = agent.root
    rows = []
    try:
        found = _skills.discover(root)            # M5: folder + flat skills
    except Exception:
        found = []
        skills_dir = os.path.join(root, "skills")
        try:
            for fn in sorted(os.listdir(skills_dir)):
                if fn.endswith(".md"):
                    found.append({"rel": f"skills/{fn}", "name": fn[:-3],
                                  "description": ""})
        except OSError:
            return ""
    skip = {str(r).replace("\\", "/").lower() for r in exclude}
    for s in found:
        rel = s.get("rel")
        if str(rel).replace("\\", "/").lower() in skip or \
                len(rows) >= SKILL_INDEX_CAP:
            continue
        desc = (s.get("description") or "").strip().replace("\n", " ")
        if not desc:
            head = _read(root, rel) or ""
            for line in head.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and \
                        not line.upper().startswith(("KEYWORDS:", "TRIGGER:",
                                                     "USES:", "---")):
                    desc = line
                    break
        rows.append(f"- {s.get('name') or rel}: {desc[:140]}  ({rel})")
    if not rows:
        return ""
    body = "\n".join(rows)
    if est_tokens(body) > SKILL_INDEX_TOKENS:
        body = body[:SKILL_INDEX_TOKENS * 4]
    return ("SKILL INDEX — playbooks available but NOT loaded. Read one with "
            "read_file before inventing a procedure:\n" + body)


# --------------------------------------------------------------- manifests

def manifest_path(root, task_id, archived=False):
    d = os.path.join(root, "contexts", "archive" if archived else "")
    return os.path.join(d, f"{task_id}.compile.json")


def save_manifest(root, task_id, manifest):
    p = manifest_path(root, task_id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=1, ensure_ascii=False)
        import time
        for attempt in range(8):
            try:
                os.replace(tmp, p)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        os.replace(tmp, p)
    except OSError:
        pass


def load_manifest(root, task_id):
    for archived in (False, True):
        try:
            with open(manifest_path(root, task_id, archived), "r",
                      encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return None


def note_compaction(root, task_id, entry):
    """Record what a compaction did to the window (kept with the manifest)."""
    m = load_manifest(root, task_id)
    if not m:
        return
    m.setdefault("compactions", []).append(entry)
    save_manifest(root, task_id, m)


def recent(root, limit=20):
    d = os.path.join(root, "contexts")
    out = []
    try:
        names = [n for n in os.listdir(d) if n.endswith(".compile.json")]
    except OSError:
        return out
    names.sort(key=lambda n: os.path.getmtime(os.path.join(d, n)), reverse=True)
    for n in names[:limit]:
        try:
            with open(os.path.join(d, n), "r", encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        out.append({"task": m.get("task"), "role": m.get("role"),
                    "goal": m.get("goal"), "total_tokens": m.get("total_tokens"),
                    "sources": [{"name": s["name"], "used_tokens": s["used_tokens"],
                                 "budget_tokens": s["budget_tokens"],
                                 "excluded_by_router": s.get("excluded_by_router")}
                                for s in m.get("sources", [])],
                    "compactions": len(m.get("compactions", []))})
    return out


def render(manifest):
    """Human-readable context window report (the CLI half of the viewer)."""
    if not manifest:
        return "no context manifest for that task"
    out = [f"context window for task {manifest['task']} ({manifest['role']})",
           f"  goal: {manifest['goal']}",
           f"  system prompt: {manifest['system']['tokens']} tok from "
           f"{', '.join(manifest['system']['files']) or 'defaults'}"
           + (f" [variant {manifest['system']['variant']}]"
              if manifest["system"].get("variant") else ""),
           f"  router: {manifest['router'].get('rule')} — "
           f"{manifest['router'].get('why')}"]
    for s in manifest["sources"]:
        if s.get("excluded_by_router"):
            out.append(f"  {s['name']:<13} EXCLUDED ({s['excluded_by_router']})")
            continue
        bar = ""
        if s["budget_tokens"]:
            filled = min(20, int(20 * s["used_tokens"] / s["budget_tokens"]))
            bar = "#" * filled + "." * (20 - filled)
        out.append(f"  {s['name']:<13} {s['used_tokens']:>5}/"
                   f"{s['budget_tokens']:<5} {bar}")
        for inc in s["included"]:
            mark = " TRIMMED" if inc["trimmed"] else ""
            out.append(f"      {inc['path']} ({inc['tokens']} tok){mark}")
        for d in s["dropped"]:
            out.append(f"      DROPPED {d['path']} ({d['why']})")
    for w in manifest.get("premise", []):
        out.append(f"  premise warning: {w.get('warning', w)}")
    for c in manifest.get("compactions", []):
        out.append(f"  compaction: {c.get('turns')} turns archived, "
                   f"{c.get('cleared', 0)} tool result(s) cleared")
    out.append(f"  TOTAL {manifest['total_tokens']} tokens")
    return "\n".join(out)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="inspect compiled context windows")
    ap.add_argument("--root", default=".")
    ap.add_argument("--task")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.task:
        m = load_manifest(root, a.task)
        print(json.dumps(m, indent=1) if a.json else render(m))
        return
    rows = recent(root)
    if a.json:
        print(json.dumps(rows, indent=1))
        return
    if not rows:
        print("no compiled context windows yet")
    for r in rows:
        print(f"{r['task']:<14} {r['role']:<12} {r['total_tokens']:>6} tok  "
              f"{(r['goal'] or '')[:50]}")


if __name__ == "__main__":
    main()
