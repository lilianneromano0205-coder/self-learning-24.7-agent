#!/usr/bin/env python3
"""BACKUP AND RESTORE — the fleet's memory is the asset, so it is portable.

Everything this platform is worth lives in files: the cited notes, the proven
skills, the failure record, the commons, the archives. Code can be
re-downloaded; three months of an expert's study cannot. A platform without a
tested restore does not have backups, it has hopes.

    python backup.py create --home . --out ../fleet-backups
    python backup.py verify ../fleet-backups/fleet-2026-08-22-1430.zip
    python backup.py restore ../fleet-backups/fleet-2026-08-22-1430.zip --dest ./restored
    python backup.py list ../fleet-backups

What goes in: settings, prompts, identities, courses, skills, commons,
state, archives, transcripts, intentions, routines, approvals, gotchas.

What NEVER goes in: `agent.env`, `ui-token.txt`, federation identity keys.
A backup that carries credentials turns every copy of it into a breach, and
backups get emailed, synced and left on laptops. Restoring therefore asks you
to put the keys back — which is the correct amount of friction.

Also excluded by default: `logs/` (regenerable, and the bulk of the bytes).
Pass `--with-logs` when the audit trail matters more than the size.

Every archive carries `backup-manifest.json`: when it was taken, from where,
the platform version, the file count, and a SHA-256 for every file. `verify`
recomputes them, so "is this backup intact?" is a question with an answer.
"""

import argparse
import hashlib
import json
import os
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = "backup-manifest.json"
SECRET_NAMES = {"agent.env", "ui-token.txt", "identity.json", "cookies.txt",
                "bootstrap.json"}
SKIP_DIRS = {"__pycache__", ".git", "node_modules", "tmp", "demo-run"}
SKIP_EXT = {".pyc", ".tmp"}
LOG_DIRS = {"logs"}


def _version():
    try:
        import harness
        return getattr(harness, "HARNESS_VERSION", "unknown")
    except Exception:
        return "unknown"


def _sha(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _secret_roots(home):
    """Every root whose settings.toml can name an api_key_file: the fleet home
    and each expert. A hand-written filename list could never see these —
    the OPERATOR chooses those paths, which is exactly how a backup once
    archived keys/openai.key while reporting credentials excluded."""
    roots = [home]
    ex = os.path.join(home, "experts")
    if os.path.isdir(ex):
        roots += [os.path.join(ex, d) for d in os.listdir(ex)
                  if os.path.isdir(os.path.join(ex, d))]
    return roots


def _walk(home, with_logs=False):
    """Every file worth keeping, as (absolute, archive-relative, redactor).

    Exclusion is delegated to credentials.is_secret, which knows the
    conventional names AND the files settings.toml points at.
    """
    import credentials
    home = os.path.abspath(home)
    roots = _secret_roots(home)
    for dirpath, dirnames, filenames in os.walk(home):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in SKIP_DIRS
                             and (with_logs or d not in LOG_DIRS))
        for fn in sorted(filenames):
            if os.path.splitext(fn)[1] in SKIP_EXT:
                continue
            if fn.startswith("state.json.corrupt-"):
                continue
            full = os.path.join(dirpath, fn)
            if any(credentials.is_secret(full, r) for r in roots):
                continue
            rel = os.path.relpath(full, home).replace(os.sep, "/")
            yield full, rel


def create(home, out_dir=None, with_logs=False, label=""):
    """Write one archive. Returns the manifest dict (with `path`)."""
    home = os.path.abspath(home)
    out_dir = os.path.abspath(out_dir or os.path.join(home, "backups"))
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d-%H%M%S")
    name = f"fleet-{stamp}{('-' + label) if label else ''}.zip"
    path = os.path.join(out_dir, name)
    files, skipped_secrets, redacted_inline = [], 0, 0
    for full, rel in _walk(home, with_logs):
        files.append((full, rel))
    import credentials
    _roots = _secret_roots(home)
    for _dp, _dn, filenames in os.walk(home):
        skipped_secrets += sum(
            1 for f in filenames
            if any(credentials.is_secret(os.path.join(_dp, f), r) for r in _roots))
    experts = set()
    entries = []
    tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for full, rel in files:
            if rel.startswith("experts/"):
                parts = rel.split("/")
                if len(parts) > 1:
                    experts.add(parts[1])
            try:
                if os.path.basename(full).lower() == "settings.toml":
                    # the shape of the configuration travels; an inline
                    # api_key does not
                    with open(full, "r", encoding="utf-8-sig") as sf:
                        body = credentials.redact(sf.read())
                    data = body.encode("utf-8")
                    was_redacted = "<redacted by backup" in body
                    entries.append({"path": rel, "bytes": len(data),
                                    "sha256": hashlib.sha256(data).hexdigest(),
                                    "redacted": was_redacted})
                    if was_redacted:
                        redacted_inline += 1
                    z.writestr(rel, data)
                    continue
                entries.append({"path": rel, "bytes": os.path.getsize(full),
                                "sha256": _sha(full)})
                z.write(full, rel)
            except OSError:
                continue                      # a file that vanished mid-walk
        manifest = {
            "taken": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": home, "platform_version": _version(),
            "experts": sorted(experts), "files": len(entries),
            "bytes": sum(e["bytes"] for e in entries),
            "with_logs": bool(with_logs),
            "secrets_excluded": skipped_secrets,
            "inline_keys_redacted": redacted_inline,
            "entries": entries,
        }
        z.writestr(MANIFEST, json.dumps(manifest, indent=1))
    os.replace(tmp, path)
    manifest["path"] = path
    return manifest


def read_manifest(archive):
    with zipfile.ZipFile(archive) as z:
        try:
            return json.loads(z.read(MANIFEST).decode("utf-8"))
        except KeyError:
            return None


def verify(archive):
    """Recompute every checksum inside the archive. -> (ok, report).

    Never raises. An archive too damaged to open is the single most important
    case to report calmly: it must come back as "not ok" with the reason, so
    the caller can treat it as a blocker instead of an exception."""
    try:
        return _verify_inner(archive)
    except (zipfile.BadZipFile, OSError, EOFError, ValueError) as e:
        return False, {"error": f"unreadable archive: {type(e).__name__}: {e}",
                       "corrupt": [os.path.basename(str(archive))],
                       "missing": [], "secrets_leaked": [], "files": 0,
                       "experts": [], "taken": None}


def _verify_inner(archive):
    man = read_manifest(archive)
    if not man:
        return False, {"error": "no backup-manifest.json — not one of ours",
                       "corrupt": [], "missing": [], "secrets_leaked": [],
                       "files": 0, "experts": [], "taken": None}
    bad, missing = [], []
    with zipfile.ZipFile(archive) as z:
        names = set(z.namelist())
        for e in man["entries"]:
            if e["path"] not in names:
                missing.append(e["path"])
                continue
            h = hashlib.sha256()
            with z.open(e["path"]) as f:
                while True:
                    b = f.read(1 << 20)
                    if not b:
                        break
                    h.update(b)
            if h.hexdigest() != e["sha256"]:
                bad.append(e["path"])
        leaked = sorted(n for n in names
                        if os.path.basename(n) in SECRET_NAMES)
    ok = not bad and not missing and not leaked
    return ok, {"taken": man["taken"], "files": man["files"],
                "experts": man["experts"], "corrupt": bad, "missing": missing,
                "secrets_leaked": leaked,
                "platform_version": man.get("platform_version")}


def restore(archive, dest, force=False):
    """Extract into `dest`. Refuses a non-empty destination unless forced —
    a restore that silently merges into a live fleet is how you get a
    half-and-half state nobody can reason about."""
    dest = os.path.abspath(dest)
    if os.path.isdir(dest) and os.listdir(dest) and not force:
        raise FileExistsError(
            f"{dest} is not empty — restore into a fresh directory, or pass "
            f"--force if you really mean to overwrite it")
    ok, report = verify(archive)
    if not ok:
        raise ValueError(f"refusing to restore a damaged archive: {report}")
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if name == MANIFEST:
                continue
            # zip-slip: never let an entry escape the destination
            target = os.path.abspath(os.path.join(dest, name))
            if not target.startswith(dest + os.sep) and target != dest:
                raise ValueError(f"archive entry escapes the destination: {name}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(name) as src, open(target, "wb") as out:
                out.write(src.read())
    report["restored_to"] = dest
    report["next"] = ("put your keys back: create agent.env (or run "
                      "bootstrap.py --key NAME=VALUE) — backups never carry "
                      "credentials")
    return report


def backups(out_dir):
    """Every archive in a directory, newest first."""
    out = []
    try:
        names = os.listdir(out_dir)
    except OSError:
        return out
    for n in sorted(names, reverse=True):
        if not n.endswith(".zip"):
            continue
        p = os.path.join(out_dir, n)
        man = None
        try:
            man = read_manifest(p)
        except (OSError, zipfile.BadZipFile):
            pass
        out.append({"path": p, "name": n, "bytes": os.path.getsize(p),
                    "taken": (man or {}).get("taken"),
                    "experts": (man or {}).get("experts", []),
                    "files": (man or {}).get("files")})
    return out


def latest(out_dir):
    rows = [b for b in backups(out_dir) if b.get("taken")]
    return rows[0] if rows else None


def age_days(out_dir):
    """How stale is the newest backup? None when there is none at all."""
    b = latest(out_dir)
    if not b:
        return None
    try:
        t = time.mktime(time.strptime(b["taken"], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return None
    return round((time.time() - t) / 86400, 2)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create", help="write a new backup archive")
    p.add_argument("--home", default=HERE)
    p.add_argument("--out", default=None, help="directory for the archive")
    p.add_argument("--with-logs", action="store_true")
    p.add_argument("--label", default="")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("verify", help="recompute every checksum")
    p.add_argument("archive")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("restore", help="extract into a fresh directory")
    p.add_argument("archive")
    p.add_argument("--dest", required=True)
    p.add_argument("--force", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("list", help="what backups exist, newest first")
    p.add_argument("dir")
    p.add_argument("--json", action="store_true")

    a = ap.parse_args()
    if a.cmd == "create":
        man = create(a.home, a.out, a.with_logs, a.label)
        if a.json:
            man.pop("entries", None)
            print(json.dumps(man, indent=1))
        else:
            print(f"{man['path']}\n  {man['files']} file(s), "
                  f"{man['bytes'] / 1e6:.1f} MB, "
                  f"{len(man['experts'])} expert(s): "
                  f"{', '.join(man['experts']) or 'none'}\n"
                  f"  {man['secrets_excluded']} credential file(s) excluded"
                  + (f", {man.get('inline_keys_redacted', 0)} inline key(s) "
                     f"redacted" if man.get("inline_keys_redacted") else "")
                  + "\n  (excluded: the conventional key files, anything "
                    "settings.toml points at, and any file that is one bare "
                    "token. A secret in prose this cannot see — check the "
                    "manifest before sharing an archive.)")
        return
    if a.cmd == "verify":
        ok, rep = verify(a.archive)
        print(json.dumps(rep, indent=1) if a.json else
              ("INTACT" if ok else "DAMAGED") +
              f": {rep.get('files')} file(s), taken {rep.get('taken')}, "
              f"experts: {', '.join(rep.get('experts') or []) or 'none'}" +
              (f"\n  corrupt: {rep['corrupt']}" if rep.get("corrupt") else "") +
              (f"\n  missing: {rep['missing']}" if rep.get("missing") else "") +
              (f"\n  SECRETS LEAKED: {rep['secrets_leaked']}"
               if rep.get("secrets_leaked") else ""))
        raise SystemExit(0 if ok else 1)
    if a.cmd == "restore":
        rep = restore(a.archive, a.dest, a.force)
        print(json.dumps(rep, indent=1) if a.json else
              f"restored {rep['files']} file(s) to {rep['restored_to']}\n"
              f"  {rep['next']}")
        return
    rows = backups(a.dir)
    if a.json:
        print(json.dumps(rows, indent=1))
        return
    if not rows:
        print(f"no backups in {a.dir}")
    for b in rows:
        print(f"{b['name']:<38} {b['bytes'] / 1e6:>7.1f} MB  "
              f"{b['taken'] or 'unreadable':<20} "
              f"{len(b['experts'])} expert(s)")


if __name__ == "__main__":
    main()
