#!/usr/bin/env python3
"""ONE COMMAND TO RUN THE PLATFORM TODAY.

    python bootstrap.py

That is the whole install story. This script does, in order, the things a
new owner would otherwise have to discover:

  1. create agent.env from the example if it is missing (never overwriting)
  2. take any --key NAME=VALUE pairs into it, WITHOUT ever echoing the value
  3. run doctor.readiness(): if something blocks a real run, print it as a
     numbered TODO with the exact command to fix it, and exit 2
  4. probe the live providers (skipped with --offline) so a wrong key fails
     here, in ten seconds, rather than inside an agent's third step
  5. create the first expert if the fleet is empty
  6. optionally teach it something at once (--teach <url-or-folder>)
  7. start the control panel and open it in the browser
  8. write bootstrap.json — the machine-readable record of all of the above

Idempotent: running it twice changes nothing and still exits 0. Keys are
read and written but NEVER printed: this script prints ENV NAMES only.

Exit codes:  0 = ready to run   2 = blocked, with the numbered list above
"""

import argparse
import json
import os
import subprocess
import sys
import time
import webbrowser

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

ENV_FILE = "agent.env"
ENV_EXAMPLE = "agent.env.example"
REPORT = "bootstrap.json"


def _env_path(home):
    return os.path.join(home, ENV_FILE)


def ensure_env(home, keys=()):
    """Create agent.env from the example, then merge --key pairs into it.
    Returns (path, created, names_set) — names, never values."""
    p = _env_path(home)
    created = False
    if not os.path.exists(p):
        src = os.path.join(HOME, ENV_EXAMPLE)
        body = ""
        if os.path.isfile(src):
            with open(src, "r", encoding="utf-8") as f:
                body = f.read()
        with open(p, "w", encoding="utf-8") as f:
            f.write(body or "# provider keys, one NAME=VALUE per line\n")
        created = True
    if not keys:
        return p, created, []
    with open(p, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    names = []
    for pair in keys:
        if "=" not in pair:
            raise SystemExit(f"--key expects NAME=VALUE (got {pair.split('=')[0]})")
        name, _, value = pair.partition("=")
        name = name.strip()
        names.append(name)
        replaced = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{name}="):
                lines[i] = f"{name}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{name}={value}")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    try:                       # keys are secrets: no group/other access
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p, created, names


def load_env(home):
    """Put agent.env into this process, so readiness sees the same world the
    loop will."""
    p = _env_path(home)
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass


def seed_home(home):
    """A fresh --home directory is not a fleet yet. Give it the charters and
    the default settings this install ships with, so an expert can be born
    there — without ever overwriting something the owner already put there."""
    import shutil
    copied = []
    for name in ("prompts", "settings.toml", "mcp.json"):
        src, dst = os.path.join(HOME, name), os.path.join(home, name)
        if os.path.exists(dst) or not os.path.exists(src):
            continue
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copyfile(src, dst)
        copied.append(name)
    return copied


def first_expert(home, name, identity):
    import fleet
    have = fleet.list_experts(home)
    if have:
        return have[0]["name"], False
    root = fleet.create(home, name, identity)
    return os.path.basename(root), True


def probe(home, slug):
    """Ask every role's provider whether it answers. Returns (rows, ok)."""
    import loop
    root = os.path.join(home, "experts", slug)
    agent = loop.Agent(root)
    rows, ok = agent.check_providers()
    return [{"role": r, "provider": p, "model": m, "status": s}
            for r, p, m, s in rows], ok


def teach(home, slug, what):
    """Hand the first expert its first material — a URL or a folder."""
    import ingest
    root = os.path.join(home, "experts", slug)
    if os.path.isdir(what):
        return {"kind": "folder", "queued": ingest.ingest_folder(root, what)}
    return {"kind": "url", "task": ingest.add_url(root, what)}


def start_panel(home, port, host, token, open_browser=True):
    cmd = [sys.executable, os.path.join(HOME, "ui.py"), "--home", home,
           "--port", str(port), "--host", host]
    if token:
        cmd += ["--token", token]
    proc = subprocess.Popen(cmd, env={**os.environ, "PYTHONUTF8": "1"})
    url = f"http://127.0.0.1:{port}"
    for _ in range(40):
        time.sleep(0.25)
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=2):
                break
        except Exception:
            if proc.poll() is not None:
                return proc, url, False
    if open_browser:
        try:
            webbrowser.open(url + (f"#t={token}" if token else ""))
        except Exception:
            pass
    return proc, url, True


def main():
    ap = argparse.ArgumentParser(
        description="set this platform up and start it, in one command")
    ap.add_argument("--home", default=HOME)
    ap.add_argument("--offline", action="store_true",
                    help="skip live provider probes (no network)")
    ap.add_argument("--no-panel", action="store_true")
    ap.add_argument("--start-loop", action="store_true",
                    help="also start the first expert's 24/7 loop")
    ap.add_argument("--expert", default="First Expert")
    ap.add_argument("--identity", default="A careful generalist. Cites its "
                                          "sources; proves its work.")
    ap.add_argument("--key", action="append", default=[], metavar="NAME=VALUE",
                    help="write a provider key into agent.env (never printed)")
    ap.add_argument("--teach", help="a URL or folder to teach the first expert")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--token", default=os.environ.get("UI_TOKEN") or None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    home = os.path.abspath(a.home)
    os.makedirs(home, exist_ok=True)
    report = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "home": home,
              "steps": [], "ready": False}

    def step(name, **kw):
        report["steps"].append({"step": name, **kw})
        if not a.json:
            detail = " ".join(f"{k}={v}" for k, v in kw.items() if k != "ok")
            print(f"[{name}] {detail}".rstrip())

    # 1 + 2 — the environment file
    p, created, names = ensure_env(home, a.key)
    step("env", file=os.path.basename(p),
         created=created, keys_written=",".join(names) or "none")
    load_env(home)
    seeded = seed_home(home)
    if seeded:
        step("seed", copied=",".join(seeded))

    # 3 — readiness
    import doctor
    rd = doctor.readiness(home)
    blocking = [i for i in rd["items"] if i["blocking"]]
    report["readiness"] = rd
    if blocking and not a.offline:
        step("readiness", ready=False, blocking=len(blocking))
        if not a.json:
            print("\nBefore this platform can run, do these:")
            for n, i in enumerate(blocking, 1):
                print(f"  {n}. {i['what']}\n     -> {i['how']}")
            print(f"\nThen run this command again. "
                  f"(Keys go in {os.path.basename(p)}; nothing is printed.)")
        report["blocked_on"] = blocking
        with open(os.path.join(home, REPORT), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
        if a.json:
            print(json.dumps(report, indent=1))
        return 2
    step("readiness", ready=True, notes=len(rd["items"]) - len(blocking))

    # 5 — the first expert
    slug, made = first_expert(home, a.expert, a.identity)
    step("expert", slug=slug, created=made)
    report["expert"] = slug

    # 4 — live providers (after the expert exists: it owns the settings)
    if a.offline:
        step("providers", skipped="--offline")
    else:
        rows, ok = probe(home, slug)
        report["providers"] = rows
        step("providers", ok=ok,
             checked=len(rows),
             failing=",".join(sorted({r["provider"] for r in rows
                                      if not r["status"].startswith("OK")})) or "none")
        if not ok and not a.json:
            print("  (a provider answered with an error — the panel's Models "
                  "tab shows the exact response)")

    # 6 — optional first material
    if a.teach:
        try:
            report["teach"] = teach(home, slug, a.teach)
            step("teach", what=a.teach, result=json.dumps(report["teach"]))
        except Exception as e:
            step("teach", what=a.teach, error=str(e)[:200])

    # 7 — the loop and the panel
    if a.start_loop:
        root = os.path.join(home, "experts", slug)
        subprocess.Popen([sys.executable, os.path.join(HOME, "loop.py"), "run",
                          "--root", root],
                         env={**os.environ, "PYTHONUTF8": "1"})
        step("loop", started=slug)
    url = None
    if not a.no_panel:
        proc, url, up = start_panel(home, a.port, a.host, a.token)
        step("panel", url=url, up=up, pid=proc.pid)
        report["panel"] = {"url": url, "pid": proc.pid, "up": up}

    report["ready"] = True
    with open(os.path.join(home, REPORT), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    if a.json:
        print(json.dumps(report, indent=1))
    else:
        print("\nREADY. " + (f"Panel: {url}" if url else "Panel not started.")
              + f"\nFirst expert: {slug}. Teach it: "
                f"python ingest.py url <link> --root experts/{slug}")
        if not a.no_panel:
            print("The panel keeps running in this terminal window; close it "
                  "with Ctrl+C or POST /api/shutdown.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
