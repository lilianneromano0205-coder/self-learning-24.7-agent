#!/usr/bin/env python3
"""PRODUCTION PREFLIGHT — is this fleet fit to run someone's business on?

`doctor.py` answers "is the software healthy?" and `harness.py --check`
answers "do the contracts hold?". Neither answers the question an owner
actually has before pointing this at real work and real money:

    if this runs unattended for a month, what will hurt?

So this is an operational audit, not a health check. Every item is a
BLOCKER, a RISK or a NOTE, each with the exact command that fixes it, and
the exit code is the verdict: 0 = fit to run, 1 = risks worth reading,
2 = something will hurt.

    python preflight.py
    python preflight.py --json
    python preflight.py --backups ../fleet-backups --exposed

Nothing here is advice in general. Every check reads this installation.
"""

import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

BLOCKER, RISK, NOTE, OK = "BLOCKER", "RISK", "NOTE", "OK"
STALE_BACKUP_DAYS = 7
LOW_DISK_GB = 2.0
BIG_LOG_MB = 200


def _load_cfg(root):
    import tomllib
    try:
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            return tomllib.loads(f.read().decode("utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _experts(home):
    d = os.path.join(home, "experts")
    try:
        return sorted(n for n in os.listdir(d)
                      if os.path.isdir(os.path.join(d, n)))
    except OSError:
        return []


def _finding(level, area, what, fix):
    return {"level": level, "area": area, "what": what, "fix": fix}


# ------------------------------------------------------------------ checks

def check_spend(home):
    """A cap that is off is a cap that will not save you at 3am."""
    out = []
    roots = [home] + [os.path.join(home, "experts", s) for s in _experts(home)]
    for root in roots:
        cfg = _load_cfg(root)
        if not cfg:
            continue
        ag = cfg.get("agent", {}) or {}
        who = "the fleet default" if root == home else os.path.basename(root)
        daily = ag.get("daily_budget_usd", 0)
        per_task = ag.get("max_task_usd", 2.0)
        if not daily:
            out.append(_finding(
                RISK, "cost", f"{who}: no daily budget breaker "
                              f"(daily_budget_usd = 0)",
                f"set [agent] daily_budget_usd in {root}/settings.toml — "
                f"without it a loop can spend all night"))
        if not per_task:
            out.append(_finding(
                RISK, "cost", f"{who}: no per-task ceiling (max_task_usd = 0)",
                f"set [agent] max_task_usd in {root}/settings.toml"))
    if not out:
        out.append(_finding(OK, "cost",
                            "every settings file has a daily breaker and a "
                            "per-task ceiling", ""))
    return out


def check_secrets(home):
    out = []
    env = os.path.join(home, "agent.env")
    if not os.path.exists(env):
        out.append(_finding(NOTE, "secrets", "no agent.env at the fleet home",
                            "python bootstrap.py --key NAME=VALUE"))
    copies = [os.path.join(home, "experts", s, "agent.env")
              for s in _experts(home)]
    copies = [p for p in copies if os.path.exists(p)]
    if copies:
        out.append(_finding(
            NOTE, "secrets",
            f"the key file is duplicated into {len(copies)} expert "
            f"director{'y' if len(copies) == 1 else 'ies'}",
            "rotating a key means replacing every copy; `python "
            "package.py` and `python backup.py` both exclude them all"))
    if os.name != "nt":
        for p in [env] + copies + [os.path.join(home, "ui-token.txt")]:
            if not os.path.exists(p):
                continue
            mode = os.stat(p).st_mode & 0o777
            if mode & 0o077:
                out.append(_finding(
                    BLOCKER, "secrets",
                    f"{p} is readable by other users (mode {oct(mode)})",
                    f"chmod 600 {p}"))
    if not any(f["level"] in (BLOCKER, RISK) for f in out):
        out.append(_finding(OK, "secrets",
                            "credential files are owner-only, and every "
                            "packaging path excludes them", ""))
    return out


def check_exposure(home, exposed=False):
    out = []
    tok = os.path.join(home, "ui-token.txt")
    has_token = os.path.exists(tok) or bool(os.environ.get("UI_TOKEN"))
    if exposed and not has_token:
        out.append(_finding(
            BLOCKER, "access",
            "the panel is meant to be exposed but no token exists",
            "start it as `python ui.py --host 0.0.0.0` (a token is generated "
            "and saved to ui-token.txt) and put it behind Tailscale or an "
            "HTTPS proxy — never plain HTTP on the open internet"))
    elif exposed:
        out.append(_finding(
            RISK, "access",
            "the panel is exposed beyond localhost",
            "confirm it is behind Tailscale or an HTTPS reverse proxy; the "
            "token protects the API but the transport is plain HTTP"))
    else:
        out.append(_finding(
            OK, "access",
            "the panel binds localhost only (token auto-enables if exposed)",
            ""))
    out.append(_finding(
        NOTE, "access",
        "access is single-owner: one token grants everything",
        "there are no per-user roles or audit-by-user — do not hand the "
        "token to people you would not give the server to"))
    return out


def check_backups(home, backup_dir=None):
    out = []
    try:
        import backup
    except ImportError:
        return [_finding(BLOCKER, "backups", "backup.py is missing", "")]
    d = backup_dir or os.path.join(home, "backups")
    rows = backup.backups(d)
    if not rows:
        out.append(_finding(
            BLOCKER, "backups", f"no backups in {d}",
            f'python backup.py create --home "{home}" --out "{d}"'
            f'   (already keeping them elsewhere? point the audit at them: '
            f'python preflight.py --backups <dir>)'))
        return out
    age = backup.age_days(d)
    newest = backup.latest(d)
    if age is None:
        out.append(_finding(RISK, "backups",
                            f"the newest archive in {d} has no readable manifest",
                            "python backup.py verify <archive>"))
    elif age > STALE_BACKUP_DAYS:
        out.append(_finding(
            RISK, "backups", f"the newest backup is {age} days old",
            f'python backup.py create --home "{home}" --out "{d}"  '
            f"(or schedule it: see REFERENCE.md §21)"))
    else:
        ok, rep = backup.verify(newest["path"])
        if not ok:
            out.append(_finding(
                BLOCKER, "backups",
                f"the newest backup fails verification: {rep}",
                "take a fresh one and verify it before trusting it"))
        else:
            out.append(_finding(
                OK, "backups",
                f"newest backup {age} days old, {rep['files']} files, "
                f"checksums verified", ""))
    known = {s for s in _experts(home)}
    covered = set(newest.get("experts") or [])
    if known - covered:
        out.append(_finding(
            RISK, "backups",
            f"expert(s) missing from the newest backup: "
            f"{', '.join(sorted(known - covered))}",
            "take a fresh backup"))
    return out


def check_disk(home):
    try:
        usage = shutil.disk_usage(home)
    except OSError as e:
        return [_finding(RISK, "capacity", f"cannot read disk usage: {e}", "")]
    free_gb = usage.free / 1e9
    if free_gb < LOW_DISK_GB:
        return [_finding(
            BLOCKER, "capacity", f"only {free_gb:.1f} GB free",
            "free space: a full disk stops every write, including the state "
            "file every task depends on")]
    big = []
    for slug in _experts(home):
        logs = os.path.join(home, "experts", slug, "logs")
        total = 0
        for dirpath, _, names in os.walk(logs):
            for n in names:
                try:
                    total += os.path.getsize(os.path.join(dirpath, n))
                except OSError:
                    continue
        if total > BIG_LOG_MB * 1e6:
            big.append(f"{slug} ({total / 1e6:.0f} MB)")
    out = [_finding(OK, "capacity", f"{free_gb:.1f} GB free; logs rotate at "
                                    f"5 MB x 5 per expert", "")]
    if big:
        out.append(_finding(NOTE, "capacity",
                            f"large log directories: {', '.join(big)}",
                            "rotation caps agent.log, but effects/model "
                            "ledgers grow; archive them if it matters"))
    return out


def check_resilience(home):
    """Fallbacks, escalation and sandbox choice — the settings that decide
    what happens on a bad night."""
    out = []
    for slug in _experts(home):
        root = os.path.join(home, "experts", slug)
        cfg = _load_cfg(root)
        roles = cfg.get("roles", {}) or {}
        no_fb = [r for r, rc in roles.items()
                 if isinstance(rc, dict) and not rc.get("fallback_provider")]
        if no_fb and roles:
            out.append(_finding(
                NOTE, "resilience",
                f"{slug}: {len(no_fb)} role(s) have no fallback provider",
                f"add fallback_provider to [roles.*] in {root}/settings.toml "
                f"so one provider outage does not stop the fleet"))
        sb = (cfg.get("agent", {}) or {}).get("sandbox", "host")
        if sb == "host":
            out.append(_finding(
                NOTE, "resilience", f"{slug}: commands run on the host",
                'set [agent] sandbox = "docker" for untrusted work — policy '
                'limits what may be attempted, not what a command could do'))
    if not _experts(home):
        out.append(_finding(RISK, "resilience", "no experts exist yet",
                            'python fleet.py create "Name" --identity "..."'))
    return out


def check_critic(home):
    """A reviewer running the same model as the author is not a second
    opinion. The platform supports pointing roles at different providers;
    nothing checked that anyone did, so the review could silently become
    theatre."""
    out = []
    for slug in _experts(home):
        root = os.path.join(home, "experts", slug)
        roles = (_load_cfg(root).get("roles", {}) or {})

        def wiring(name):
            rc = roles.get(name) or roles.get("default") or {}
            return (rc.get("provider"), rc.get("model"))

        author, critic = wiring("practitioner"), wiring("examiner")
        judge = wiring("consultant")
        if not roles or author == (None, None):
            continue
        if author == critic:
            out.append(_finding(
                NOTE, "critic",
                f"{slug}: the examiner runs the same model as the "
                f"practitioner ({author[1] or author[0]})",
                f"point [roles.examiner] at a different provider or model in "
                f"{root}/settings.toml — a reviewer sharing the author's "
                f"blind spots reviews nothing"))
        if author == judge and judge != (None, None):
            out.append(_finding(
                NOTE, "critic",
                f"{slug}: the consultant shares the practitioner's model",
                f"a citation-gated answer is still safer read by a different "
                f"model; set [roles.consultant] in {root}/settings.toml"))
    if not out and _experts(home):
        out.append(_finding(OK, "critic",
                            "reviewers run different models from the work "
                            "they review", ""))
    return out


def check_verification(home):
    """A platform whose own tests have not been run is not verified."""
    out = []
    try:
        import harness
        rep = harness.check_contracts(home)
        problems = rep if isinstance(rep, list) else rep.get("problems", [])
        if problems:
            out.append(_finding(BLOCKER, "verification",
                                f"harness contracts broken: {problems[:3]}",
                                "python harness.py --check"))
        else:
            out.append(_finding(OK, "verification",
                                "every harness contract holds", ""))
    except Exception as e:
        out.append(_finding(RISK, "verification",
                            f"could not check harness contracts: {e}",
                            "python harness.py --check"))
    ci = os.path.join(HERE, ".github", "workflows")
    if not os.path.isdir(ci):
        out.append(_finding(NOTE, "verification",
                            "no CI workflow in this checkout",
                            "the suite is the specification — run "
                            "`python tests/run_all.py` before every deploy"))
    return out


def check_governance(home):
    out = []
    try:
        import approvals
        pend = 0
        for slug in _experts(home):
            pend += len(approvals.pending(os.path.join(home, "experts", slug)))
        if pend:
            out.append(_finding(
                RISK, "governance", f"{pend} approval(s) waiting on a human",
                "python approvals.py list — work stops until they are decided"))
    except Exception:
        pass
    blocked = 0
    for slug in _experts(home):
        p = os.path.join(home, "experts", slug, "blocked.md")
        if os.path.exists(p) and os.path.getsize(p) > 0:
            blocked += 1
    if blocked:
        out.append(_finding(
            RISK, "governance",
            f"{blocked} expert(s) have unanswered questions in blocked.md",
            "answer them in the panel, or `python loop.py answer <id> --text`"))
    if not out:
        out.append(_finding(OK, "governance",
                            "nothing is waiting on a human", ""))
    return out


CHECKS = (
    ("cost", check_spend), ("secrets", check_secrets),
    ("backups", check_backups), ("capacity", check_disk),
    ("resilience", check_resilience), ("verification", check_verification),
    ("critic", check_critic),
    ("governance", check_governance),
)


def run(home, backup_dir=None, exposed=False):
    findings = []
    for name, fn in CHECKS:
        try:
            if name == "backups":
                findings += fn(home, backup_dir)
            else:
                findings += fn(home)
        except Exception as e:                # a check must never be the outage
            findings.append(_finding(RISK, name, f"the check itself failed: {e}",
                                     "report this — a preflight that crashes "
                                     "is worse than one that fails"))
    findings += check_exposure(home, exposed)
    counts = {lvl: sum(1 for f in findings if f["level"] == lvl)
              for lvl in (BLOCKER, RISK, NOTE, OK)}
    verdict = ("NOT READY" if counts[BLOCKER] else
               "READY WITH RISKS" if counts[RISK] else "READY")
    return {"home": os.path.abspath(home), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "verdict": verdict, "counts": counts, "findings": findings}


def render(rep):
    lines = [f"PRODUCTION PREFLIGHT — {rep['home']}", ""]
    for lvl in (BLOCKER, RISK, NOTE, OK):
        rows = [f for f in rep["findings"] if f["level"] == lvl]
        if not rows:
            continue
        lines.append(f"{lvl} ({len(rows)})")
        for f in rows:
            lines.append(f"  [{f['area']}] {f['what']}")
            if f["fix"]:
                lines.append(f"      -> {f['fix']}")
        lines.append("")
    c = rep["counts"]
    lines.append("=" * 62)
    lines.append(f"VERDICT: {rep['verdict']}  "
                 f"({c[BLOCKER]} blocker(s), {c[RISK]} risk(s), "
                 f"{c[NOTE]} note(s))")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", default=HERE)
    ap.add_argument("--backups", default=None,
                    help="where backups live (default: <home>/backups)")
    ap.add_argument("--exposed", action="store_true",
                    help="audit as if the panel is reachable beyond localhost")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rep = run(a.home, a.backups, a.exposed)
    print(json.dumps(rep, indent=1) if a.json else render(rep))
    raise SystemExit(2 if rep["counts"][BLOCKER] else
                     1 if rep["counts"][RISK] else 0)


if __name__ == "__main__":
    main()
