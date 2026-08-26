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
    # This note used to say "there are no per-user roles or audit-by-user".
    # There are now, so the audit must report which of the two situations this
    # installation is actually in — a stale reassurance is worse than none.
    try:
        import org
        rec = org.load(home)
    except Exception:
        rec = None
    if rec:
        with_tokens = sum(1 for u in rec["users"] if u.get("token_sha256"))
        n = len(rec["users"])
        if with_tokens >= n:
            out.append(_finding(
                OK, "access",
                f"{n} member(s), each with their own panel token and role",
                "every write is checked against the role that token belongs "
                "to, and the audit trail names the credential"))
        else:
            out.append(_finding(
                RISK, "access",
                f"{n - with_tokens} of {n} member(s) have no panel token",
                "without one they fall back to the panel's master token, "
                "which resolves to the owner: python org.py token <email> "
                "--as you@example.com"))
        out.append(_finding(
            NOTE, "access",
            "the panel's master token still grants everything",
            "that is by design — it already implies control of the process — "
            "so give people their own and keep the master one to yourself"))
    else:
        out.append(_finding(
            NOTE, "access",
            "access is single-owner: one token grants everything",
            "no organization has been created, so there are no per-user roles "
            "here yet (python org.py create ...). Do not hand the token to "
            "people you would not give the server to"))
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


def check_pricing(home):
    """A provider with no declared price disables every spend control.

    `_cost` multiplies tokens by the provider's input/output rate. A provider
    that declares neither returns 0.0, `_record_spend` returns early on
    `usd <= 0`, and daily_budget_usd, max_task_usd and the organisation's
    require_approval_over_usd ceiling all stop accumulating — the brakes are
    off, and a $0 ledger looks exactly like a frugal agent.

    settings.toml ships prices for deepseek and groq only, while its own
    RECOMMENDED lane points at openrouter. So the shipped configuration is
    the unmeasurable one. A genuinely free tier is fine and says `free =
    true`; silence is not the same claim.
    """
    out = []
    for root, label in ([(home, "fleet")] +
                        [(os.path.join(home, "experts", s), s)
                         for s in _experts(home)]):
        try:
            import tomllib
            with open(os.path.join(root, "settings.toml"), "rb") as f:
                cfg = tomllib.loads(f.read().decode("utf-8-sig"))
        except (OSError, ValueError, ImportError):
            continue
        provs = cfg.get("providers") or {}
        used = {r.get("provider") for r in (cfg.get("roles") or {}).values()}
        used |= {r.get("fallback_provider") for r in (cfg.get("roles") or {}).values()}
        unpriced = sorted(
            n for n, p in provs.items()
            if n in used and p.get("type") != "mock" and not p.get("free")
            and p.get("input_per_mtok") is None
            and p.get("output_per_mtok") is None)
        if unpriced:
            out.append(_finding(
                RISK, "cost",
                f"{label}: {', '.join(unpriced)} "
                f"{'declares' if len(unpriced) == 1 else 'declare'} no price, "
                f"so spend on "
                f"{'it' if len(unpriced) == 1 else 'them'} is recorded as $0 "
                f"and the daily breaker cannot fire",
                f"add input_per_mtok/output_per_mtok under [providers.<name>] "
                f"in {os.path.join(root, 'settings.toml')}, or `free = true` "
                f"if the tier genuinely costs nothing — an unmeasured fleet "
                f"cannot be a cheap one"))
    if not out:
        out.append(_finding(OK, "cost",
                            "every provider in use declares a price or is "
                            "marked free, so spend is measurable", ""))
    return out


def check_policy(home):
    """The command policy must COMPILE, or it is not enforcing anything.

    This is a preflight rather than only a runtime refusal because the failure
    it catches is silent: an owner deny rule with a bad regex used to be
    skipped, leaving a settings.toml that reads like the rule is active and a
    fleet where it is not. Caught here, it costs a message before the run;
    caught at runtime it costs the run.
    """
    import policy
    out = []
    for root, label in ([(home, "fleet")] +
                        [(os.path.join(home, "experts", s), s)
                         for s in _experts(home)]):
        try:
            import tomllib
            with open(os.path.join(root, "settings.toml"), "rb") as f:
                agent_cfg = (tomllib.loads(f.read().decode("utf-8-sig"))
                             .get("agent") or {})
        except (OSError, ValueError, ImportError):
            continue
        for where, err in policy.rule_problems(agent_cfg):
            out.append(_finding(
                BLOCKER, "policy",
                f"{label}: command policy does not compile — {where}: {err}",
                f"fix the pattern in {os.path.join(root, 'settings.toml')} "
                f"under [agent.command_policy]; until then EVERY command is "
                f"refused, because a rule set that cannot be read cannot be "
                f"enforced"))
    if not out:
        out.append(_finding(OK, "policy",
                            "every command-policy pattern compiles", ""))
    return out


def check_thinking(home):
    """CAN THIS FLEET THINK? Answered by asking doctor, not by re-deriving.

    The audit's exact words for the defect this closes: "Preflight reports
    'ready with risks', Doctor says the system cannot think, and the panel
    shows blockers. Operators cannot know whether work may safely start. In
    a proof-oriented product, contradictory truth is a release defect."

    It happened because the two surfaces computed DIFFERENT questions and
    published both answers under the one word "ready": doctor.readiness asks
    whether a usable model provider exists; preflight asked about spend,
    secrets, backups and exposure — and a fleet with no key at all could
    pass every one of those. Both were right; the product was wrong.

    So preflight now ASKS doctor rather than growing a second copy of the
    provider logic — one computation, two renderers, which is this
    codebase's standing rule for one truth. A fleet that cannot think is
    NOT READY here, whatever else is in order, because every capability an
    operator is about to rely on sits downstream of a model call.
    """
    import doctor
    out = []
    try:
        r = doctor.readiness(home)
    except Exception as e:                    # pragma: no cover
        return [_finding(RISK, "thinking",
                         f"doctor.readiness itself failed: {e}",
                         "python doctor.py — a readiness probe that crashes "
                         "cannot clear anything")]
    for item in r.get("items", []):
        if item.get("blocking"):
            out.append(_finding(BLOCKER, "thinking", item["what"],
                                item["how"]))
    if not out:
        out.append(_finding(OK, "thinking",
                            "doctor and preflight agree: nothing blocks "
                            "this fleet from thinking", ""))
    return out


CHECKS = (
    ("thinking", check_thinking),
    ("cost", check_spend), ("pricing", check_pricing),
    ("secrets", check_secrets), ("policy", check_policy),
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
