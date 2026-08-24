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

A backup that only exists on the machine being backed up is not a backup, so
archives can be pushed to any S3-compatible store -- Cloudflare R2, MinIO,
B2, AWS -- with AWS Signature V4 written in stdlib rather than a dependency:

    python backup.py push  <archive> --endpoint https://<id>.r2.cloudflarestorage.com                            --bucket fleet
    python backup.py pull  fleet-2026-08-24-0130.zip --dest ../restored                            --endpoint ... --bucket fleet
    python backup.py remote-list --endpoint ... --bucket fleet

A pull VERIFIES before it returns: the bytes are written, then every checksum
in the manifest is recomputed. A corrupt backup discovered at restore time is
the worst possible moment to discover it.

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
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
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


def _walk(home, with_logs=False, exclude_dir=None):
    """Every file worth keeping, as (absolute, archive-relative, redactor).

    Exclusion is delegated to credentials.is_secret, which knows the
    conventional names AND the files settings.toml points at.

    `exclude_dir` is where the archive is being WRITTEN, and skipping it is
    not tidiness — it is the difference between backups that work and backups
    that destroy the machine. The default output directory is `<home>/backups`,
    which is inside the tree being archived and is not in SKIP_DIRS, so every
    snapshot swallowed all of its predecessors. Measured on a fresh fleet:
    28,451 -> 43,088 -> 72,321 bytes, with one then two nested archives
    inside. That is exponential, and the disk it fills is the disk the fleet
    needs in order to save itself at all — so the failure mode of the backup
    system was to make backups impossible. `preflight.py` recommends exactly
    that output path, so the recommended configuration was the broken one.
    """
    import credentials
    home = os.path.abspath(home)
    roots = _secret_roots(home)
    skip_real = os.path.realpath(exclude_dir) if exclude_dir else None
    for dirpath, dirnames, filenames in os.walk(home):
        if skip_real:
            dirnames[:] = [d for d in dirnames
                           if os.path.realpath(os.path.join(dirpath, d)) != skip_real]
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
    for full, rel in _walk(home, with_logs, exclude_dir=out_dir):
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



# ------------------------------------------------------------------ remote
# A backup that only exists on the machine being backed up is not a backup.
# This is the smallest thing that makes an archive survive the machine: PUT
# it to any S3-compatible endpoint, GET it back.
#
# Written against AWS Signature V4 with hmac and urllib rather than boto3,
# because "no dependencies" is a promise this platform keeps and SigV4 is
# ninety lines. It works with Cloudflare R2 (region "auto", and egress is
# free, which is what you want from something you restore from), Backblaze
# B2, MinIO, and AWS itself.
#
# The endpoint is OPERATOR-configured, exactly like a provider base_url, so
# it is not subject to the SSRF policy that governs model-supplied URLs in
# ingest.py. A URL the owner typed is not untrusted input.

S3_KEY_ID = "R2_ACCESS_KEY_ID"
S3_KEY_SECRET = "R2_SECRET_ACCESS_KEY"
_UNSIGNED = "UNSIGNED-PAYLOAD"


def _s3_credentials(root=None):
    """-> (access_key_id, secret) through the Credential Authority.

    Never os.environ directly: credentials.resolve models four sources (env,
    agent.env beside the expert AND beside the code, inline, key file), and a
    subsystem that models fewer would report a working configuration broken.
    Falls back to the AWS_* names so an existing profile works unchanged.
    """
    import credentials
    kid = (credentials.resolve({"api_key_env": S3_KEY_ID}, root)
           or credentials.resolve({"api_key_env": "AWS_ACCESS_KEY_ID"}, root))
    sec = (credentials.resolve({"api_key_env": S3_KEY_SECRET}, root)
           or credentials.resolve({"api_key_env": "AWS_SECRET_ACCESS_KEY"}, root))
    return kid, sec


def _sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sigv4(method, url, payload_sha, kid, secret, region="auto", service="s3",
           now=None):
    """-> headers for one signed request. Pure function, so it is testable
    against the published AWS example vectors without a network."""
    u = urllib.parse.urlsplit(url)
    host = u.netloc
    path = urllib.parse.quote(u.path or "/", safe="/~")
    # The canonical query string is NOT the raw one. Parameters are sorted by
    # name, every value is URI-encoded, and a valueless parameter becomes
    # "name=" with the equals sign present. Passing u.query through unchanged
    # produced a signature AWS rejects — caught by checking against AWS's own
    # published example rather than by a live 403, which is the whole reason
    # that vector is in the test suite.
    parts = []
    for item in (u.query or "").split("&"):
        if not item:
            continue
        k, _eq, v = item.partition("=")
        parts.append((urllib.parse.quote(urllib.parse.unquote(k), safe="~"),
                      urllib.parse.quote(urllib.parse.unquote(v), safe="~")))
    query = "&".join(f"{k}={v}" for k, v in sorted(parts))
    t = time.gmtime(now if now is not None else time.time())
    stamp = time.strftime("%Y%m%dT%H%M%SZ", t)
    date = time.strftime("%Y%m%d", t)

    canon_headers = (f"host:{host}\n"
                     f"x-amz-content-sha256:{payload_sha}\n"
                     f"x-amz-date:{stamp}\n")
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canon = (f"{method}\n{path}\n{query}\n{canon_headers}\n"
             f"{signed_headers}\n{payload_sha}")
    scope = f"{date}/{region}/{service}/aws4_request"
    to_sign = ("AWS4-HMAC-SHA256\n"
               f"{stamp}\n{scope}\n"
               + hashlib.sha256(canon.encode("utf-8")).hexdigest())
    k = _sign(("AWS4" + secret).encode("utf-8"), date)
    k = _sign(k, region)
    k = _sign(k, service)
    k = _sign(k, "aws4_request")
    sig = hmac.new(k, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "Host": host,
        "x-amz-content-sha256": payload_sha,
        "x-amz-date": stamp,
        "Authorization": (f"AWS4-HMAC-SHA256 Credential={kid}/{scope}, "
                          f"SignedHeaders={signed_headers}, Signature={sig}"),
    }


def _s3(method, url, kid, secret, body=None, region="auto", timeout=300):
    """One signed request. Returns (status, bytes). Errors carry the endpoint
    and the status, never the key."""
    payload_sha = (hashlib.sha256(body).hexdigest() if body is not None
                   else hashlib.sha256(b"").hexdigest())
    headers = _sigv4(method, url, payload_sha, kid, secret, region=region)
    req = urllib.request.Request(url, data=body, method=method)
    for h, v in headers.items():
        if h != "Host":                    # urllib sets Host itself
            req.add_header(h, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:400].decode("utf-8", "replace")
        raise RuntimeError(
            f"{method} {urllib.parse.urlsplit(url).path} -> HTTP {e.code}. "
            f"{detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"cannot reach {urllib.parse.urlsplit(url).netloc}: "
                           f"{e.reason}") from None


def push(archive, endpoint, bucket, prefix="", root=None, region="auto"):
    """Upload one archive. -> {"url", "bytes", "sha256"}.

    The local archive is not deleted and not modified: a push is a copy, so a
    failed upload can never cost you the backup you already had.
    """
    kid, secret = _s3_credentials(root)
    if not kid or not secret:
        raise SystemExit(
            f"ERROR: no S3 credentials. Put {S3_KEY_ID} and {S3_KEY_SECRET} "
            f"in agent.env (or the AWS_* equivalents). For Cloudflare R2: "
            f"dash.cloudflare.com -> R2 -> Manage API tokens. The values are "
            f"never printed by this tool.")
    with open(archive, "rb") as f:
        body = f.read()
    key = (prefix.strip("/") + "/" if prefix.strip("/") else "") + \
        os.path.basename(archive)
    url = f"{endpoint.rstrip('/')}/{bucket}/{urllib.parse.quote(key)}"
    _s3("PUT", url, kid, secret, body=body, region=region)
    return {"url": url, "key": key, "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest()}


def pull(key, dest_dir, endpoint, bucket, root=None, region="auto"):
    """Download one archive by key. -> the local path.

    Verified before it is trusted: the bytes are written, then `verify()`
    recomputes every checksum in the manifest. A truncated download is a
    corrupt backup, and a corrupt backup discovered at restore time is the
    worst possible moment to discover it.
    """
    kid, secret = _s3_credentials(root)
    if not kid or not secret:
        raise SystemExit(f"ERROR: no S3 credentials ({S3_KEY_ID}).")
    url = f"{endpoint.rstrip('/')}/{bucket}/{urllib.parse.quote(key)}"
    _st, body = _s3("GET", url, kid, secret, region=region)
    os.makedirs(dest_dir, exist_ok=True)
    out = os.path.join(dest_dir, os.path.basename(key))
    with open(out, "wb") as f:
        f.write(body)
    # Two bugs lived in the two lines this replaces, and together they meant
    # the verification a pull advertises never ran:
    #
    #   rep = verify(out)          # verify() returns (ok, report), a TUPLE
    #   if rep.get("problems"):    # -> AttributeError on EVERY pull, even a
    #                              #    perfectly good archive
    #
    # and "problems" is not a key the report has ever contained — the real
    # ones are corrupt/missing/secrets_leaked — so unpacking the tuple
    # correctly would have produced None and passed a DAMAGED archive in
    # silence. A wrong check that crashes is luckier than a wrong check that
    # agrees with you; this one managed to be both.
    #
    # There was no test. `push` was covered by pinned AWS signature vectors
    # and `remote-list` by the same, while `pull` — the half a container
    # depends on to get its expert's memory back at boot — had none.
    ok, rep = verify(out)
    if not ok:
        bad = list(rep.get("corrupt") or []) + list(rep.get("missing") or [])
        raise RuntimeError(
            f"downloaded archive is DAMAGED and was NOT trusted: "
            f"{bad[:3] or rep}. The file is on disk at {out} for inspection; "
            f"restoring from it would put a corrupted memory back into the "
            f"fleet, which is worse than starting empty.")
    return out


def remote_list(endpoint, bucket, prefix="", root=None, region="auto"):
    """-> [{"key", "bytes"}] newest-name-last, without parsing XML properly:
    the listing response is small and the two fields wanted are unambiguous."""
    kid, secret = _s3_credentials(root)
    if not kid or not secret:
        raise SystemExit(f"ERROR: no S3 credentials ({S3_KEY_ID}).")
    q = "list-type=2" + (f"&prefix={urllib.parse.quote(prefix)}" if prefix else "")
    url = f"{endpoint.rstrip('/')}/{bucket}?{q}"
    _st, body = _s3("GET", url, kid, secret, region=region)
    text = body.decode("utf-8", "replace")
    keys = re.findall(r"<Key>([^<]+)</Key>", text)
    sizes = re.findall(r"<Size>(\d+)</Size>", text)
    return [{"key": k, "bytes": int(s)} for k, s in zip(keys, sizes)]


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

    for name, helptext in (("push", "upload an archive to S3/R2"),
                           ("pull", "download an archive from S3/R2"),
                           ("remote-list", "what archives exist remotely")):
        p = sub.add_parser(name, help=helptext)
        if name == "push":
            p.add_argument("archive")
        if name == "pull":
            p.add_argument("key")
            p.add_argument("--dest", required=True)
        p.add_argument("--endpoint", required=True,
                       help="e.g. https://<accountid>.r2.cloudflarestorage.com")
        p.add_argument("--bucket", required=True)
        p.add_argument("--prefix", default="")
        p.add_argument("--region", default="auto")
        p.add_argument("--root", default=None,
                       help="where to look for agent.env (default: beside the code)")
        p.add_argument("--json", action="store_true")

    a = ap.parse_args()
    if a.cmd in ("push", "pull", "remote-list"):
        if a.cmd == "push":
            out = push(a.archive, a.endpoint, a.bucket, a.prefix, a.root, a.region)
            print(json.dumps(out, indent=2) if a.json else
                  f"pushed {out['bytes']:,} bytes -> {out['key']}  "
                  f"sha256 {out['sha256'][:16]}")
        elif a.cmd == "pull":
            local = pull(a.key, a.dest, a.endpoint, a.bucket, a.root, a.region)
            print(json.dumps({"path": local}, indent=2) if a.json else
                  f"pulled {a.key} -> {local}  (checksums verified)")
        else:
            rows = remote_list(a.endpoint, a.bucket, a.prefix, a.root, a.region)
            if a.json:
                print(json.dumps(rows, indent=2))
            elif not rows:
                print("no archives at that prefix")
            else:
                for r in rows:
                    print(f"{r['bytes']:>12,}  {r['key']}")
        return

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
