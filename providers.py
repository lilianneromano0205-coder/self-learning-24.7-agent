#!/usr/bin/env python3
"""Plug in any model, from anywhere — and point any role at it.

Any OpenAI-compatible endpoint works: OpenRouter (500+ models), NVIDIA Build,
Hugging Face's router, Groq, DeepSeek, Together, Fireworks, Mistral, a
company gateway, or something self-hosted behind a URL. This module adds the
provider, fetches its live model catalog, assigns models to roles, and
rewrites settings.toml safely — never touching key material, which stays in
agent.env.

Usage:
  python providers.py list                     [--root DIR]
  python providers.py add <name> --base-url URL --key-env VAR
        [--native-tools false] [--header K=V]  [--root DIR]
  python providers.py models <name> [--filter text] [--free] [--limit 40]
  python providers.py set-role <role> --provider P --model M
        [--fallback-provider P2 --fallback-model M2] [--escalate-model M3]
  python providers.py test [--role ROLE]
"""

import argparse
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

# well-known rails, so "add" is one word instead of a URL hunt
KNOWN = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "tokenrouter": ("https://api.tokenrouter.io/v1", "TOKENROUTER_API_KEY"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
    "huggingface": ("https://router.huggingface.co/v1", "HF_TOKEN"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "together": ("https://api.together.xyz/v1", "TOGETHER_API_KEY"),
    "fireworks": ("https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
}


# ------------------------------------------------------------ settings i/o

def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def load(root):
    with open(os.path.join(root, "settings.toml"), "rb") as f:
        return tomllib.loads(f.read().decode("utf-8-sig"))


def save(root, cfg):
    """Write settings.toml from the parsed structure. The schema is ours and
    small (tables of scalars, one nested table per provider, [agent.chain]),
    so this round-trips safely — and it is written atomically."""
    lines = ["# ----------------------------------------------------------------- agent",
             "[agent]"]
    agent = cfg.get("agent", {})
    for k, v in agent.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_fmt(v)}")
    for k, v in agent.items():
        if isinstance(v, dict):
            lines += ["", f"[agent.{k}]"] + [f"{ik} = {_fmt(iv)}"
                                             for ik, iv in v.items()]
    lines += ["", "# ------------------------------------------------------------- providers",
              "# Keys live in agent.env (api_key_env) — never in this file."]
    for name, p in cfg.get("providers", {}).items():
        lines += ["", f"[providers.{name}]"]
        for k, v in p.items():
            if not isinstance(v, dict):
                lines.append(f"{k} = {_fmt(v)}")
        for k, v in p.items():
            if isinstance(v, dict):
                lines += [f"[providers.{name}.{k}]"] + [f"{ik} = {_fmt(iv)}"
                                                        for ik, iv in v.items()]
    lines += ["", "# ----------------------------------------------------------------- roles"]
    for name, r in cfg.get("roles", {}).items():
        lines += ["", f"[roles.{name}]"] + [f"{k} = {_fmt(v)}"
                                            for k, v in r.items()]
    text = "\n".join(lines) + "\n"
    # validate before replacing: a broken settings.toml would stop the expert
    tomllib.loads(text)
    p = os.path.join(root, "settings.toml")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, p)
    return text


# ------------------------------------------------------------ operations

def add(root, name, base_url=None, key_env=None, native_tools=None,
        headers=None, prices=None):
    cfg = load(root)
    if not base_url and name in KNOWN:
        base_url, key_env = KNOWN[name]
    if not base_url:
        raise SystemExit(f"ERROR: --base-url required (or use a known rail: "
                         f"{', '.join(sorted(KNOWN))})")
    p = {"base_url": base_url.rstrip("/"),
         "api_key_env": key_env or f"{name.upper()}_API_KEY"}
    if native_tools is False:
        p["native_tools"] = False
    if prices:
        p.update(prices)
    if headers:
        p["extra_headers"] = headers
    cfg.setdefault("providers", {})[name] = p
    save(root, cfg)
    return p


def catalog(root, name, filt="", free_only=False, limit=40):
    """Fetch the provider's live model list from its /models endpoint."""
    cfg = load(root)
    p = cfg.get("providers", {}).get(name)
    if not p:
        raise SystemExit(f"ERROR: no provider '{name}' — add it first")
    if p.get("type") == "mock":
        return [{"id": "mock", "note": "scripted provider"}]
    # ONE resolution for the whole platform. This used to model only
    # api_key_env + agent.env, so a provider configured with api_key_file
    # worked at runtime and was reported here as having no key at all.
    import credentials
    key = credentials.resolve(p, root)
    req = urllib.request.Request(
        p["base_url"].rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {key}"} if key else {})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = data.get("data", data if isinstance(data, list) else [])
    out = []
    for m in items:
        mid = m.get("id") or m.get("name") or ""
        if filt and filt.lower() not in mid.lower():
            continue
        pricing = m.get("pricing") or {}
        is_free = mid.endswith(":free") or (
            str(pricing.get("prompt", "")).strip() in ("0", "0.0", "0.00"))
        if free_only and not is_free:
            continue
        out.append({"id": mid, "free": is_free,
                    "context": m.get("context_length") or
                               (m.get("top_provider") or {}).get("context_length")})
        if len(out) >= limit:
            break
    return out


def set_role(root, role, provider, model, fallback_provider=None,
             fallback_model=None, escalate_provider=None, escalate_model=None,
             tools=None):
    cfg = load(root)
    if provider not in cfg.get("providers", {}):
        raise SystemExit(f"ERROR: unknown provider '{provider}' — add it first")
    r = dict(cfg.get("roles", {}).get(role, {}))
    r.update({"provider": provider, "model": model})
    if fallback_provider:
        r["fallback_provider"] = fallback_provider
        r["fallback_model"] = fallback_model or model
    if escalate_model:
        r["escalate_provider"] = escalate_provider or provider
        r["escalate_model"] = escalate_model
    if tools is not None:
        r["tools"] = tools
    cfg.setdefault("roles", {})[role] = r
    save(root, cfg)
    return r


def summary(root):
    import credentials
    cfg = load(root)
    provs = {}
    for name, p in cfg.get("providers", {}).items():
        env = p.get("api_key_env", "")
        provs[name] = {"base_url": p.get("base_url", ""),
                       "mock": p.get("type") == "mock",
                       "key_env": env,
                       # every source the runtime honours — names only
                       "key_sources": [k for k, _ in credentials.sources_for(p)],
                       "key_present": credentials.key_present(p, root)}
    return {"providers": provs, "roles": cfg.get("roles", {}),
            "known_rails": KNOWN}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("--root", default=HOME)
    p = sub.add_parser("add")
    p.add_argument("name"); p.add_argument("--base-url", default=None)
    p.add_argument("--key-env", default=None)
    p.add_argument("--native-tools", default=None)
    p.add_argument("--header", action="append", default=[])
    p.add_argument("--root", default=HOME)
    p = sub.add_parser("models")
    p.add_argument("name"); p.add_argument("--filter", default="")
    p.add_argument("--free", action="store_true")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--root", default=HOME)
    p = sub.add_parser("set-role")
    p.add_argument("role"); p.add_argument("--provider", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--fallback-provider", default=None)
    p.add_argument("--fallback-model", default=None)
    p.add_argument("--escalate-provider", default=None)
    p.add_argument("--escalate-model", default=None)
    p.add_argument("--root", default=HOME)
    p = sub.add_parser("test")
    p.add_argument("--root", default=HOME)
    args = ap.parse_args()

    if args.cmd == "list":
        s = summary(args.root)
        for n, p in s["providers"].items():
            mark = "mock" if p["mock"] else ("key set" if p["key_present"]
                                             else f"needs {p['key_env']}")
            print(f"{n:<14} {p['base_url'] or '(mock)':<45} {mark}")
        print("\nroles:")
        for r, v in s["roles"].items():
            print(f"  {r:<14} {v.get('provider','')}/{v.get('model','')}"
                  + (f"  fallback {v['fallback_provider']}/{v.get('fallback_model')}"
                     if v.get("fallback_provider") else "")
                  + (f"  escalate {v.get('escalate_model')}"
                     if v.get("escalate_model") else ""))
        print("\nknown rails you can add by name: " + ", ".join(sorted(KNOWN)))
    elif args.cmd == "add":
        hdrs = dict(h.split("=", 1) for h in args.header) if args.header else None
        nt = None if args.native_tools is None else \
            args.native_tools.lower() not in ("false", "0", "no")
        p = add(args.root, args.name, args.base_url, args.key_env, nt, hdrs)
        print(f"added provider '{args.name}': {p['base_url']} "
              f"(key from {p['api_key_env']})")
    elif args.cmd == "models":
        for m in catalog(args.root, args.name, args.filter, args.free, args.limit):
            ctx = f"  ctx {m['context']}" if m.get("context") else ""
            print(f"{'FREE ' if m.get('free') else '     '}{m['id']}{ctx}")
    elif args.cmd == "set-role":
        r = set_role(args.root, args.role, args.provider, args.model,
                     args.fallback_provider, args.fallback_model,
                     args.escalate_provider, args.escalate_model)
        print(f"{args.role} -> {r['provider']}/{r['model']}")
    elif args.cmd == "test":
        import loop
        rows, ok = loop.Agent(args.root).check_providers()
        for role, prov, model, status in rows:
            print(f"{role:<14} {prov}/{model:<38} {status}")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
