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


def key_shaped(tok):
    """Is this TOKEN credential-shaped? The single-token judgement, factored
    out so the whole-file test and the content scan cannot disagree."""
    tok = (tok or "").strip().strip('"').strip("'").strip()
    if not tok:
        return False
    if any(tok.startswith(p) for p in _KEY_PREFIXES):
        return True
    return bool(_KEYISH_RE.fullmatch(tok)) and any(c.isdigit() for c in tok)


# A name that means "this value is a credential", and the value it is set to.
_ASSIGN_RE = re.compile(
    r"""(?ix)
    \b ( [A-Z0-9_.\-]* (?: KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|APIKEY )
         [A-Z0-9_.\-]* )
    \s* [:=] \s*
    ["']? ( [^\s"',;]{16,200} ) ["']?
    """)
# Values that are obviously not a live credential. Kept deliberately short:
# every entry here is a hole, so it holds only spellings that CANNOT be a
# working key rather than anything that merely looks harmless.
_PLACEHOLDER_MARKS = ("example", "your", "changeme", "change-me", "redacted",
                      "placeholder", "xxxx", "...", "<", ">", "${", "{{",
                      "dummy", "notreal", "not-real", "fake", "sample")


_IDENTIFIER_RE = re.compile(r"^[A-Z][A-Z0-9_]{3,}$")


def _is_identifier(value):
    """`R2_SECRET_ACCESS_KEY` is the NAME of a place a key lives, not a key.

    Configuration maps one name to another all over this platform --
    S3_KEY_SECRET = "R2_SECRET_ACCESS_KEY" in backup.py, api_key_env in every
    settings.toml -- and every one of those is a screaming-snake-case
    identifier. Real credentials are not: they carry a vendor prefix or mixed
    case, because they are random. Without this rule the content scan reports
    the platform's own configuration as a leak, and a scanner that cries wolf
    on documentation gets switched off.
    """
    return bool(_IDENTIFIER_RE.fullmatch(value.strip().strip('"').strip("'")))


def _is_path(value):
    """`snapshots/fleet-2026-08-24-013000-cf-one.zip` is a filename."""
    v = value.strip().strip('"').strip("'")
    return ("/" in v or "\\" in v) and bool(re.search(r"\.[A-Za-z0-9]{1,5}$", v))


def keys_in_text(text, max_hits=50):
    """Assigned credential VALUES inside a document. -> [(line_no, excerpt)].

    This exists because the packaging test's "by CONTENT" scan was calling
    looks_like_key() -- which takes a PATH and starts with os.path.getsize()
    -- on a LINE OF TEXT. Every call raised OSError inside the function and
    returned False, so the loop could not report anything, while the test
    printed "228 archive members checked four ways ... and by reading every
    text file". Three of the four ways worked. The fourth was the one that
    would catch a key pasted somewhere nobody thought to name, and it had
    never once evaluated true.

    A file-shaped test cannot answer a content-shaped question, and the type
    error was invisible because both a dead check and a passing check return
    False.
    """
    hits = []
    for i, line in enumerate(str(text or "").splitlines(), 1):
        if len(line) > 4000:
            continue
        low = line.lower()
        for name, value in _ASSIGN_RE.findall(line):
            # Judge the VALUE, not the whole line. Matching the line meant a
            # single "<" anywhere on it switched the scan off — and "<" is
            # ordinary punctuation in markdown, HTML and comments, so
            #     api_key = "sk-live-realkey..."   <!-- ours -->
            # was silently not a finding. A placeholder is a property of the
            # value; a stray angle bracket forty characters away is not.
            if any(m in value.lower() for m in _PLACEHOLDER_MARKS):
                continue
            if _is_identifier(value) or _is_path(value):
                continue
            if key_shaped(value):
                hits.append((i, f"{name}={value[:12]}..."))
                break
        else:
            for tok in line.split():
                t = tok.strip('"\'',).strip(",;")
                # A bare token must clear the prefix AND the shape: prefix
                # alone matches the setting NAMES `api_key_env` and
                # `api_key_file`, because "api_" is in _KEY_PREFIXES. Those
                # appear in the manual, the reference, backup.py and the
                # build manifest, so a prefix-only rule reported six members
                # of the platform's own documentation as leaked credentials.
                # A key that is 11 characters long is not a key.
                if (any(t.startswith(p) for p in _KEY_PREFIXES)
                        and _KEYISH_RE.fullmatch(t)
                        and any(c.isdigit() for c in t)):
                    if not any(m in t.lower() for m in _PLACEHOLDER_MARKS):
                        hits.append((i, f"bare token {t[:12]}..."))
                    break
        if len(hits) >= max_hits:
            break
    return hits


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
    except OSError:
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="strict") as f:
            body = f.read(max_bytes)
    except OSError:
        return False
    except UnicodeDecodeError:
        # A file this cannot DECODE used to be declared not-a-secret, which
        # is the wrong way round: "I could not read it" is not "I read it and
        # it was fine". A UTF-16 or otherwise non-UTF-8 credential file — the
        # default when a key is pasted into Notepad on Windows, or written by
        # PowerShell's Out-File — therefore sailed past is_secret() and into
        # every backup and package. The detector's whole job is to keep
        # credentials out of archives that get emailed and synced.
        #
        # So decode it lossily and judge THAT. A real credential is ASCII, so
        # a lossy decode of a key file still yields the key; prose in another
        # encoding still yields prose with spaces and newlines, which the
        # single-token test rejects. Failing closed here costs a false
        # positive at worst; failing open costs a leak.
        try:
            with open(path, "rb") as f:
                body = f.read(max_bytes).decode("utf-8", errors="replace")
        except OSError:
            return False
        body = body.replace("�", "").replace("\x00", "")
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if len(lines) != 1:
        return False
    return key_shaped(lines[0])


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


def write_secret(path, text):
    """THE way to create a credential file. Returns the path.

    This module could always RECOGNISE a secret (is_secret, looks_like_key)
    but had no way to CREATE one, so every writer rolled its own `open` and
    its own chmod: three in the platform, and a fourth in a test that forgot.
    On Linux the forgotten one landed at mode 0644 — a fleet access token
    readable by every account on the box — and the platform's own preflight
    caught it, on the only operating system where the check means anything.
    The lesson this codebase keeps relearning is that a control repeated at
    each call site is a control missing from the next one.

    Two properties the hand-rolled versions did not have:

    The mode is set as the file is CREATED, not corrected afterwards, so the
    secret is never world-readable on disk — not even for the microsecond
    between the write and the chmod.

    And the replacement is atomic, so a crash or a full disk mid-write leaves
    the previous credential intact rather than a truncated one. The temp file
    is itself created 0600: writing atomically through a temp file the umask
    made 0644 and chmodding the destination afterwards protects nothing,
    because os.replace carries the TEMP file's mode onto the destination.
    """
    path = os.fspath(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f".{os.path.basename(path)}.{os.getpid()}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, 0o600)     # belt and braces; Windows ACLs differ
        except OSError:              # pragma: no cover
            pass
        os.replace(tmp, path)
    finally:
        try:
            os.remove(tmp)           # only survives if replace never ran
        except OSError:
            pass
    return path


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
