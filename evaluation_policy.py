"""Owner-controlled experiment switches. Mandatory authorities are never ablated."""
MODULES = frozenset({"memory", "skills", "runbooks", "candidates", "routing",
                     "confidence", "repair", "research_brief", "swarm", "verification_tiers",
                     # induction + deterministic reuse of compiled procedures.
                     # Ablatable because "the compiler earns its keep" is a
                     # measurable claim, and an arm that cannot be switched
                     # off cannot be credited with a delta.
                     "procedures"})
PERSISTENCE = frozenset({"memory", "skills", "runbooks", "procedures"})


def disabled(cfg, module):
    if module not in MODULES:
        raise ValueError("unknown ablation module: " + str(module))
    experiment = (cfg or {}).get("evaluation", {})
    disabled_modules = experiment.get("disabled_modules", [])
    if not isinstance(disabled_modules, list) or set(disabled_modules) - MODULES:
        raise ValueError("invalid evaluation ablation policy")
    return module in disabled_modules


def policy(arm, ablations=()):
    names = set(ablations)
    if names - MODULES:
        raise ValueError("unknown or unsafe ablation")
    if arm in ("raw", "minimal"):
        names |= MODULES
    elif arm == "no_persistence":
        names |= PERSISTENCE
    elif arm not in ("full", "reference"):
        raise ValueError("unknown experiment arm")
    return {"disabled_modules": sorted(names), "single_provider_attempt": arm == "raw"}
