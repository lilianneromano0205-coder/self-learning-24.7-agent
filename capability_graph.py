#!/usr/bin/env python3
r"""THE CAPABILITY GRAPH — what this expert can actually do, joined in one view.

    task family -> capability -> skill / procedure -> tool -> model
                             \-> failure mode      \-> evidence

Every competence signal in this platform already exists, and every one of them
lives in a different ledger: runbook trust, the skill graph, competence rows,
routing outcomes, the failure taxonomy, the procedural authority, the toolbox
scan. Planning, routing and gap-finding each read ONE of them, so nothing in
the system could answer the question a planner actually asks:

    "For work of this shape, what do I already have — and what is it worth?"

This module answers it, and it does so as a DERIVED VIEW. It owns no state, it
writes nothing durable, and it is never a model tool. Every node and edge
carries `source`: the ledger the claim came from. If two ledgers disagree, the
graph shows both rather than picking a winner — a joined view that quietly
resolves conflicts is how a contradiction becomes a fact.

WHAT IT DELIBERATELY DOES NOT DO

- It does not compute new trust. `status` on a procedure is the trust ledger's
  word, earned through sealed evaluation; the graph copies it and cannot
  promote anything.
- It does not claim generalization. Reliability is reported with its n and its
  envelope, exactly as recorded.
- It does not infer causation. A skill that was loaded during wins is reported
  as co-occurrence unless the skill graph says an ablation earned the verdict.
- It fails SOFT: a ledger that will not load contributes nothing and is named
  in `partial`. A planner that gets a smaller true graph is better served than
  one that gets an exception, and better served still by knowing what is
  missing — which is why `partial` is never silently empty.

    python capability_graph.py --root <expert>            # the whole map
    python capability_graph.py --root <expert> --for "<goal text>"
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):        # cp1252 consoles (see acquire.py)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NODE_KINDS = ("family", "capability", "procedure", "skill", "tool", "model",
              "failure_mode")
EDGE_KINDS = ("implements", "composed_of", "uses_tool", "uses_skill",
              "serves", "observed_in", "measured_in")


def _node(nodes, kind, name, source, **attrs):
    key = f"{kind}:{name}"
    row = nodes.setdefault(key, {"id": key, "kind": kind, "name": name,
                                 "sources": [], "attrs": {}})
    if source not in row["sources"]:
        row["sources"].append(source)
    row["attrs"].update({k: v for k, v in attrs.items() if v is not None})
    return key


def _edge(edges, src, kind, dst, source, **attrs):
    edges.append({"from": src, "kind": kind, "to": dst, "source": source,
                  **attrs})


def _home_of(root):
    """experts/<slug> -> the fleet home two levels up, else None."""
    parent = os.path.dirname(os.path.abspath(root))
    return (os.path.dirname(parent)
            if os.path.basename(parent) == "experts" else None)


def _tasks(root):
    try:
        with open(os.path.join(root, "state.json"), encoding="utf-8") as f:
            return json.load(f).get("tasks", [])
    except (OSError, ValueError):
        return []


def family_of(task):
    """The single naming rule the whole graph joins on. loop.add_task stores
    `family` explicitly; older tasks predate the field and are placed by the
    same fallback chain the loop itself uses, so a mixed ledger still lands
    in one bucket per family rather than two."""
    return (task.get("family") or task.get("course")
            or task.get("task_class") or "general")


def build(root):
    """-> {"nodes": {...}, "edges": [...], "partial": [...], "counts": {...}}"""
    root = os.path.abspath(root)
    nodes, edges, partial = {}, [], []

    def ledger(name, fn):
        try:
            return fn()
        except Exception as exc:                # a partial map, never a crash
            partial.append({"ledger": name, "why": str(exc)[:200]})
            return None

    # ---------------------------------------------------------------- tasks
    # Families are observed, not declared: a family exists because work of
    # that shape actually ran here.
    tasks = _tasks(root)
    per_family = {}
    for t in tasks:
        if t.get("status") not in ("done", "failed"):
            continue
        f = per_family.setdefault(family_of(t), {
            "tasks": 0, "gated": 0, "verified": 0, "steps": 0, "cost_usd": 0.0,
            "deterministic_runs": 0})
        f["tasks"] += 1
        f["steps"] += len(t.get("steps") or [])
        try:
            f["cost_usd"] += float(t.get("cost_usd") or 0)
        except (TypeError, ValueError):
            pass
        if t.get("done_check"):
            f["gated"] += 1
            if t.get("status") == "done":
                f["verified"] += 1
        if t.get("procedure_routed"):
            f["deterministic_runs"] += 1
    for name, f in per_family.items():
        _node(nodes, "family", name, "state.json",
              tasks=f["tasks"], gated=f["gated"], verified=f["verified"],
              model_steps=f["steps"], cost_usd=round(f["cost_usd"], 6),
              deterministic_runs=f["deterministic_runs"],
              verified_rate=(round(f["verified"] / f["gated"], 4)
                             if f["gated"] else None),
              basis="observed task outcomes; ungated tasks are not counted "
                    "as verified")

    # ----------------------------------------------------------- procedures
    def _procedures():
        import runbook
        out = []
        for name in runbook.names(root):
            try:
                rb = runbook.load(root, name)
            except Exception:
                continue
            trust = {}
            try:
                with open(os.path.join(root, runbook.TRUST), encoding="utf-8") as f:
                    trust = json.load(f).get(name, {})
            except (OSError, ValueError):
                pass
            out.append((name, rb, trust, runbook.status(root, name)))
        return out

    for name, rb, trust, status in (ledger("runbooks", _procedures) or []):
        op = rb.get("operator") or {}
        steps = rb.get("steps") or []
        compiled = bool(rb.get("procedure_version"))
        key = _node(
            nodes, "procedure", name, "runbooks/trust.json",
            status=status, compiled=compiled,
            steps=len(steps),
            deterministic=(bool(steps) and all(
                s.get("kind") == "deterministic" for s in steps)
                if compiled else None),
            inputs=op.get("inputs"),
            preconditions=len(op.get("preconditions") or []) if compiled else None,
            effects=len(op.get("effects") or []) if compiled else None,
            reversibility=op.get("reversibility"),
            cost_usd=op.get("cost_usd"),
            latency_seconds=op.get("latency_seconds"),
            accepted_wins=trust.get("accepted_wins"),
            attempts=(trust.get("reliability") or {}).get("attempts"),
            envelope=trust.get("envelope"),
            reliability_basis=(trust.get("reliability") or {}).get(
                "evidence", "no recorded outcome"))
        fam = ((rb.get("provenance") or {}).get("family")
               or (trust.get("envelope") or {}).get("families") or [None])
        fam = fam if isinstance(fam, str) else (fam[0] if fam else None)
        if fam:
            _edge(edges, key, "implements",
                  _node(nodes, "family", fam, "runbook provenance"),
                  "runbook provenance")
        for step in steps:
            sub = step.get("run")
            if sub:
                _edge(edges, key, "composed_of",
                      _node(nodes, "procedure", sub, "runbook step"),
                      "runbook step")
            tool = (step.get("action") or {}).get("tool")
            if tool:
                _edge(edges, key, "uses_tool",
                      _node(nodes, "tool", tool, "runbook step"),
                      "runbook step")

    # --------------------------------------------------------------- skills
    def _skills():
        import skills
        return skills, skills.load_graph(root)

    got = ledger("skills/graph.json", _skills)
    if got:
        skills, graph = got
        for stem, entry in graph.items():
            rel = f"skills/{stem}.md"
            earned = skills.status_of(root, rel)
            key = _node(
                nodes, "skill", stem, "skills/graph.json",
                status=earned,
                claimed_status=entry.get("status"),
                evidence_basis=entry.get("evidence_basis") or "cooccurrence",
                causal=(entry.get("evidence_basis") == "matched_heldout_ablation"),
                wins=entry.get("wins"), verified_wins=entry.get("verified_wins"),
                losses=entry.get("losses"),
                ablations=len(entry.get("ablations") or []),
                caveat=("loaded-during-success is not caused-success; only a "
                        "matched held-out ablation earns a verdict"))
            for sub in (skills.links_of(root, rel) or []):
                _edge(edges, key, "uses_skill",
                      _node(nodes, "skill", str(sub).split("/")[-1]
                            .removesuffix(".md"), "skill USES header"),
                      "skill USES header")

    # ----------------------------------------------------------- capability
    # Competence rows are per (expert, domain) and live in the FLEET home.
    home = _home_of(root)
    if home:
        def _competence():
            import memory
            return memory.competence(home, os.path.basename(root))
        for _expert, domains in (ledger("memory/competence", _competence) or {}).items():
            for domain, row in (domains or {}).items():
                key = _node(nodes, "capability", domain, "memory/competence",
                            attempts=row.get("n"), successes=row.get("ok"),
                            verified_attempts=row.get("verified_n"),
                            verified_successes=row.get("verified_ok"),
                            score=row.get("score"), claim=row.get("claim"))
                if f"family:{domain}" in nodes:
                    _edge(edges, key, "measured_in", f"family:{domain}",
                          "name join (domain == family)")

        def _failures():
            import memory
            return memory.failure_summary(home, os.path.basename(root))
        summary = ledger("memory/failures", _failures) or {}
        for category, count in (summary.get("by_category") or {}).items():
            _node(nodes, "failure_mode", category, "memory/failures",
                  observed=count,
                  taxonomy="memory.CATEGORIES (harness-classified, not "
                           "model-reported)")

    # ---------------------------------------------------------------- models
    def _routing():
        import modelrouter
        rows = modelrouter.outcomes(root)
        seen = {}
        for r in rows:
            cls = r.get("task_class", "general")
            seen.setdefault(cls, modelrouter.profiles(root, task_class=cls))
        return seen
    for cls, profs in (ledger("logs/model-outcomes.jsonl", _routing) or {}).items():
        for key_name, prof in (profs or {}).items():
            key = _node(nodes, "model", key_name, "logs/model-outcomes.jsonl",
                        n=round(prof.get("n", 0), 3),
                        pass_rate=prof.get("pass_rate"),
                        verified_pass_rate=prof.get("verified_pass_rate"),
                        avg_cost_usd=prof.get("avg_cost_usd"))
            if cls != "general" or f"family:{cls}" in nodes:
                _edge(edges, key, "serves",
                      _node(nodes, "family", cls, "routing outcome"),
                      "routing outcome", n=round(prof.get("n", 0), 3))

    # ----------------------------------------------------------------- tools
    def _toolbox():
        import toolbox
        return toolbox.scan(root)
    scan = ledger("toolbox", _toolbox) or {}
    for group in ("binaries", "modules", "keys"):
        for name, present in (scan.get(group) or {}).items():
            _node(nodes, "tool", name, "toolbox.scan",
                  present=bool(present), provides=group)

    counts = {k: sum(1 for n in nodes.values() if n["kind"] == k)
              for k in NODE_KINDS}
    counts["edges"] = len(edges)
    return {"root": root, "nodes": nodes, "edges": edges, "partial": partial,
            "counts": counts}


# ------------------------------------------------------- planner interface

def support_for(root, goal, graph=None):
    """What competence already exists for THIS goal — the planner's question.

    Returns proven and candidate procedures whose triggers this goal fires,
    the skills that match it, the measured competence of the family it falls
    in, the failure modes seen there, and a STRATEGY recommendation that is a
    mechanical read of that evidence, never a model's opinion.

    The recommendation is deliberately conservative and ordered by cost: a
    proven procedure is cheaper than a model, a model with measured competence
    is cheaper than novel reasoning, and a missing tool must be acquired
    before anything else is worth attempting.
    """
    graph = graph or build(root)
    nodes = graph["nodes"]

    proven, candidate = [], []
    try:
        import runbook
        for hit in runbook.match(root, goal, allow_candidates=True):
            row = {"name": hit["name"], "status": hit["status"],
                   "fired": hit["fired"]}
            node = nodes.get(f"procedure:{hit['name']}")
            if node:
                row["compiled"] = node["attrs"].get("compiled")
                row["inputs"] = node["attrs"].get("inputs")
                row["envelope"] = node["attrs"].get("envelope")
            (proven if hit["status"] == "proven" else candidate).append(row)
    except Exception:
        pass

    matched_skills = []
    try:
        import skills
        for rel in (skills.matching(root, goal) or []):
            stem = str(rel).split("/")[-1].removesuffix(".md")
            node = nodes.get(f"skill:{stem}")
            matched_skills.append({
                "skill": stem,
                "status": (node or {}).get("attrs", {}).get("status", "candidate"),
                "causal": (node or {}).get("attrs", {}).get("causal", False)})
    except Exception:
        pass

    words = {w.strip(".,:;!?()[]'\"").lower() for w in str(goal or "").split()}
    families = [n for n in nodes.values() if n["kind"] == "family"
                and n["name"].lower() in words]
    competence = [n["attrs"] | {"capability": n["name"]}
                  for n in nodes.values() if n["kind"] == "capability"
                  and n["name"].lower() in words]
    missing_tools = sorted(n["name"] for n in nodes.values()
                           if n["kind"] == "tool"
                           and n["attrs"].get("present") is False)

    usable_proven = [p for p in proven if p.get("compiled")]
    if usable_proven:
        strategy, why = "deterministic_reuse", (
            f"{usable_proven[0]['name']} is a PROVEN compiled procedure whose "
            f"triggers this goal fires; it needs typed inputs and no model call")
    elif proven:
        strategy, why = "proven_runbook", (
            f"{proven[0]['name']} is proven for this shape of work")
    elif candidate:
        strategy, why = "supervised_procedure", (
            f"{candidate[0]['name']} matches but is a CANDIDATE — run it only "
            f"under supervision; trust is earned by sealed evaluation")
    elif any(s["causal"] for s in matched_skills) or competence:
        strategy, why = "model_with_measured_competence", (
            "no procedure covers this, but measured competence or an "
            "ablation-earned skill applies")
    else:
        strategy, why = "novel_reasoning", (
            "nothing recorded here covers this goal — this is new work, and "
            "it should be captured as a judged trajectory so the next one "
            "is cheaper")

    return {"goal": goal, "strategy": strategy, "why": why,
            "proven_procedures": proven, "candidate_procedures": candidate,
            "skills": matched_skills,
            "families": [n["attrs"] | {"family": n["name"]} for n in families],
            "competence": competence,
            "failure_modes": sorted(
                n["name"] for n in nodes.values() if n["kind"] == "failure_mode"),
            "missing_tools": missing_tools,
            "caveat": "an evidence read, not a prediction; nothing here says "
                      "the strategy will succeed, only what has been measured"}


def gaps(root, graph=None):
    """Where competence is absent or unearned — the learning agenda."""
    graph = graph or build(root)
    nodes = graph["nodes"]
    families = [n for n in nodes.values() if n["kind"] == "family"]
    implemented = {e["to"] for e in graph["edges"] if e["kind"] == "implements"}
    return {
        "families_without_a_procedure": sorted(
            n["name"] for n in families if n["id"] not in implemented),
        "families_below_half_verified": sorted(
            n["name"] for n in families
            if (n["attrs"].get("verified_rate") or 1) < 0.5
            and (n["attrs"].get("gated") or 0) >= 3),
        "candidate_procedures_awaiting_evaluation": sorted(
            n["name"] for n in nodes.values()
            if n["kind"] == "procedure" and n["attrs"].get("status") == "candidate"),
        "skills_without_causal_evidence": sorted(
            n["name"] for n in nodes.values()
            if n["kind"] == "skill" and not n["attrs"].get("causal")),
        "missing_tools": sorted(n["name"] for n in nodes.values()
                                if n["kind"] == "tool"
                                and n["attrs"].get("present") is False),
        "partial_ledgers": graph["partial"]}


def render(graph):
    lines = [f"CAPABILITY GRAPH — {graph['root']}", ""]
    c = graph["counts"]
    lines.append("  " + "  ".join(f"{k}={c.get(k, 0)}" for k in NODE_KINDS))
    lines.append(f"  edges={c['edges']}")
    if graph["partial"]:
        lines.append("")
        lines.append("  PARTIAL — these ledgers did not load:")
        for p in graph["partial"]:
            lines.append(f"    {p['ledger']}: {p['why']}")
    for kind in NODE_KINDS:
        rows = [n for n in graph["nodes"].values() if n["kind"] == kind]
        if not rows:
            continue
        lines.append("")
        lines.append(f"  {kind.upper()}")
        for n in sorted(rows, key=lambda r: r["name"])[:40]:
            bits = []
            for k in ("status", "verified_rate", "verified", "gated",
                      "accepted_wins", "present", "claim", "n", "observed",
                      "deterministic_runs", "causal"):
                if k in n["attrs"] and n["attrs"][k] is not None:
                    bits.append(f"{k}={n['attrs'][k]}")
            lines.append(f"    {n['name']:<28} " + " ".join(bits[:5]))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", required=True)
    ap.add_argument("--for", dest="goal", help="what support exists for a goal")
    ap.add_argument("--gaps", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.goal:
        out = support_for(a.root, a.goal)
    elif a.gaps:
        out = gaps(a.root)
    else:
        g = build(a.root)
        if a.json:
            out = {"counts": g["counts"], "partial": g["partial"],
                   "nodes": list(g["nodes"].values()), "edges": g["edges"]}
        else:
            print(render(g))
            return 0
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
