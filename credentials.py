#!/usr/bin/env python3
"""ONE CREDENTIAL MODEL, for every subsystem that touches a secret.

The audit found four sources of provider keys and six subsystems that each
modelled them differently — no two agreeing. The consequences were concrete:
a backup archived `keys/openai.key` in plaintext while printing "2 credential
file(s) deliberately excluded"; the distributable shipped the federation HMAC
secret; the connectivity check reported a working provider as unfunded; and
the agent's own `read_file` could open the key file the runtime uses.

Every one of those is the same bug: a list of filenames written from memory by
whoever wrote that module. So the lists are gone, and this module answers the
three questions instead.

  sources_for(prov)     where does THIS provider's key come from? (names only)
  resolve(prov, root)   the key itself — the single implementation
  secret_paths(root)    every file in this tree that holds a credential,
                        INCLUDING the ones the operator named in settings.toml
  is_secret(path, root) may this path be read, backed up, or shipped?

The four sources, in the order the runtime tries them:

  1. api_key_env    an environment variable name              (recommended)
  2. agent.env      KEY=VALUE beside the expert, loaded into the environment
  3. api_key        the value inline in settings.toml         (discouraged)
  4. api_key_file   a path to a file holding the key

(3) is supported because the runtime has always supported it, and silently
dropping it would break a working install. It is reported by `inline_keys()`
so `doctor` and `preflight` can tell the owner to move it, and `redact()`
strips it from anything that leaves this machine.
"""

import os
import re

# Files that are credentials by convention, wherever they appear in a tree.
# One list, imported by everyone — loop's file tools, backup, package.
SECRET_BASENAMES = {
    "agent.env",            # provider keys, loaded into the environment
    "agent.env.example",    # same shape; an operator often edits it in place
    "ui-token.txt",         # the panel token IS the fleet
    "cookies.txt",          # yt-dlp session cookies for gated course video
    "bootstrap.json",       # setup record; may name keys
    "identity.json",        # federation identity — holds the HMAC secret
}
# A directory whose whole contents are secrets, under either spelling. The
# audit found `.keys/` protected and `keys/` — the likelier one — not.
SECRET_DIRS = {".keys", "keys", "secrets", ".secrets"}


def _cfg(root):
    try:
        import tomllib
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            return tomllib.loads(f.read().decode("utf-8-sig"))
    except (OSError, ValueError, ImportError):
        return {}


def sources_for(prov):
    """Which sources this provider declares. NAMES ONLY — never a value."""
    out = []
    if prov.get("api_key_env"):
        out.append(("env", prov["api_key_env"]))
    if prov.get("api_key"):
        out.append(("inline", "settings.toml [providers] api_key"))
    if prov.get("api_key_file"):
        out.append(("file", prov["api_key_file"]))
    return out


def resolve(prov, root=None):
    """The provider's key, or "". The ONLY implementation — loop, providers
    and any probe call this, so a working configuration cannot be reported as
    broken by a subsystem that models fewer sources than the runtime."""
    env_name = prov.get("api_key_env", "")
    if env_name:
        v = os.environ.get(env_name, "")
        if v:
            return v
    # agent.env, beside the expert and beside the code
    if env_name:
        for base in filter(None, (root, os.path.dirname(os.path.abspath(__file__)))):
            try:
                with open(os.path.join(base, "agent.env"),
                          encoding="utf-8-sig") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or "=" not in line:
                            continue
                        k, _, v = line.partition("=")
                        if k.strip() == env_name and v.strip():
                            return v.strip().strip('"').strip("'")
            except OSError:
                continue
    if prov.get("api_key"):
        return str(prov["api_key"])
    if prov.get("api_key_file"):
        try:
            p = prov["api_key_file"]
            if not os.path.isabs(p) and root:
                p = os.path.join(root, p)
            with open(p, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            pass
    return ""


def key_present(prov, root=None):
    """Is this provider funded? True/False — never the value. Used by the
    health check and the chief's briefing, which used to look at api_key_env
    alone and call a working api_key_file provider 'unfunded'."""
    if prov.get("type") == "mock":
        return True
    return bool(resolve(prov, root))


def configured_key_files(root):
    """Absolute paths of every file an api_key_file points at in this tree."""
    out = set()
    for prov in (_cfg(root).get("providers") or {}).values():
        p = prov.get("api_key_file")
        if not p:
            continue
        full = p if os.path.isabs(p) else os.path.join(root, p)
        out.add(os.path.realpath(full))
    return out


def inline_keys(root):
    """Providers carrying a key inline in settings.toml. Names only. The
    owner should move these; doctor and preflight say so."""
    return sorted(name for name, prov in (_cfg(root).get("providers") or {}).items()
                  if prov.get("api_key"))


_KEYISH_RE = re.compile(r"^[A-Za-z0-9_\-./+=]{20,200}$")
_KEY_PREFIXES = ("sk-", "sk_", "pk-", "pk_", "api-", "api_", "xoxb-", "xoxp-",
                 "ghp_", "gho_", "github_pat_", "AKIA", "ASIA", "AIza",
                 "hf_", "gsk_", "nvapi-", "Bearer ")


def looks_like_key(path, max_bytes=4096):
    """A file whose ENTIRE content is one credential-shaped token.

    Deliberately narrow. A hand-written filename list cannot see a file the
    operator called `my-secret.txt`, but a whole-file-is-one-opaque-token
    test can — and it will not fire on course material, because a lesson is
    prose with spaces and newlines, not a single 40-character token.
    """
    try:
        if os.path.getsize(path) > max_bytes:
            return False
        with open(path, "r", encoding="utf-8", errors="strict") as f:
            body = f.read(max_bytes)
    except (OSError, UnicodeDecodeError):
        return False
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if len(lines) != 1:
        return False
    tok = lines[0]
    if any(tok.startswith(p) for p in _KEY_PREFIXES):
        return True
    return bool(_KEYISH_RE.fullmatch(tok)) and any(c.isdigit() for c in tok)


def is_secret(path, root=None):
    """Should this file be withheld from a model, a backup, or a package?

    Covers the conventional names, any file inside a keys directory, and the
    files the OPERATOR named in settings.toml — which is the half every
    hand-written list was missing.
    """
    p = os.path.realpath(str(path))
    if os.path.basename(p).lower() in SECRET_BASENAMES:
        return True
    # Directory names are judged INSIDE the tree only. Judging the absolute
    # path would let an unrelated ancestor decide — a sandbox living under a
    # folder called `secrets/` made every file in it unreadable.
    inside = p
    if root:
        try:
            inside = os.path.relpath(p, os.path.realpath(root))
        except ValueError:              # different drive on Windows
            inside = p
        if inside.startswith(".."):     # not under root at all
            inside = os.path.basename(p)
    parts = {seg.lower() for seg in inside.replace("\\", "/").split("/")[:-1]}
    if parts & SECRET_DIRS:
        return True
    if os.path.splitext(p)[1].lower() in (".pem", ".key", ".p12", ".pfx"):
        return True
    if root and p in configured_key_files(root):
        return True
    if looks_like_key(p):
        return True
    return False


_INLINE_RE = re.compile(r'^(\s*api_key\s*=\s*)(["\']).*?\2\s*$', re.M)


def redact(text):
    """settings.toml with any inline api_key value removed. A backup or a
    package carries the SHAPE of the configuration, never the secret."""
    return _INLINE_RE.sub(
        r'\1"<redacted by backup — restore this key from agent.env>"', text)


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser(description="the one credential model")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    cfg = _cfg(root)
    rows = []
    for name, prov in sorted((cfg.get("providers") or {}).items()):
        rows.append({"provider": name,
                     "sources": [f"{k}:{v}" for k, v in sources_for(prov)],
                     "funded": key_present(prov, root),
                     "mock": prov.get("type") == "mock"})
    report = {"providers": rows,
              "inline_keys": inline_keys(root),
              "key_files": sorted(os.path.basename(p)
                                  for p in configured_key_files(root))}
    if a.json:
        print(json.dumps(report, indent=1))
        return
    for r in rows:
        print(f"{r['provider']:<16} {'funded' if r['funded'] else 'NOT FUNDED':<11} "
              f"{', '.join(r['sources']) or 'no key source declared'}")
    if report["inline_keys"]:
        print(f"\nWARNING: {', '.join(report['inline_keys'])} carry a key INLINE "
              f"in settings.toml.\n  settings.toml is readable by the agent and "
              f"travels with backups. Move these to agent.env.")


if __name__ == "__main__":
    main()
