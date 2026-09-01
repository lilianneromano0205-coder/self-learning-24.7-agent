# VISION CONTRACT

**A model is temporary intelligence. The system keeps the knowledge, tools,
experience, proof, procedures and capabilities.**

This platform is not a chatbot, an agent wrapper, a workflow builder, or a
multi-agent swarm. It is a persistent system that takes a hard objective,
figures out how to solve it, uses whatever intelligence, tools and computers
are appropriate, proves the result, remembers what happened, learns from it,
and makes similar future work cheaper and more reliable.

Everything below is enforced by `tests/test_vision_preservation.py` in the
acceptance suite. A change that breaks a rule here does not merge — the
vision is a CI invariant, not a preference.

## The non-negotiable rules

| Rule | Meaning |
| --- | --- |
| Novel work can always reach model reasoning | A missing procedure never makes a task impossible |
| Models never judge their own work | Independent gates remain authoritative |
| L0 mechanical truth stays supreme | No model verdict can overturn an objective failure |
| Memory survives model replacement | Intelligence is not trapped in one vendor |
| Procedures are additive | They make known work cheaper; they never constrain novel work |
| Workers cannot grant themselves authority | Permissions live outside cognition |
| Learning cannot promote itself | Candidate → independent fresh evaluation → trusted, always |
| Failures remain evidence | Mistakes are never erased from history |
| Unknown capabilities can be acquired | The tool universe is open-ended; a gap routes to acquisition, not a shrug |
| The sandbox stays fail-closed | No convenience downgrade to unsafe host execution |
| External information is untrusted until evaluated | Website and tool text never becomes instructions |
| Metrics cannot invent numbers | Unknown means unknown, and it says so |

## The loop the product exists to run

```
solve novel work with intelligence
→ prove it (independent, mechanical wherever possible)
→ remember it (memory, cases, skills, procedures)
→ stop paying full intelligence for what stops being novel
→ escalate only genuine novelty
```

Deterministic procedures are an **optimization**, never a replacement for
intelligence: the cheapest reliable strategy is tried first, and everything
falls back to model reasoning for what remains novel. That rule never
changes.

## Phase discipline

From this point on, every major phase gets:

**one branch → one design → one benchmark → one review → one merge.**

No phase lands inside an unrelated PR. The build order (Semantic Operator
Runtime → Verifier Factory → exact finance + SQL → Procedure Compiler V2 →
Capability Signatures → …) is deliberate: expand what the system can
*represent* before expanding what it can *learn*, and expand what it can
*prove* before expanding what it may *do*.

## Claim discipline

Nothing is claimed without the run that proved it. Candidate is not proven,
mock is not measured, green CI is not intelligence. The primary product
metric is **verified useful work per dollar**, and where a number cannot be
measured, no number is shown.
