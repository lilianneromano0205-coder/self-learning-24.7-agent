#!/usr/bin/env python3
"""Command policy — a deterministic guard between the model and the shell.

Every agent survey of 2026 lands on the same sentence: "never let the agent
execute arbitrary shell commands unguarded." The model decides what it WANTS
to run; this layer decides what it MAY run. It is code, not a prompt — a
model cannot be talked out of it, because it is never asked.

Two layers, both from settings.toml so the owner holds the keys:

  DENY  (always on)  patterns that destroy, exfiltrate, escalate, or escape:
        recursive deletes of roots, disk formatting, shutdown/reboot,
        curl|sh style pipe-to-shell, credential files, privilege escalation,
        and the *spellings* of leaving the agent's own directory that can be
        recognised in a command string — `cd /`, absolute paths outside the
        root, traversal sequences. Owner may ADD patterns; may not remove
        the built-ins.

        WHAT THIS IS NOT. This line used to end "and any attempt to leave the
        agent's own directory", which promises containment this module cannot
        deliver and does not attempt. policy.py reads a STRING; a string can
        be obfuscated, and a program the string starts can go anywhere it
        likes once it is running. On the default `host` backend there is no
        filesystem boundary at all — REFERENCE.md §20 has always said so
        ("`host` sandbox is not isolation"), but this docstring said
        otherwise, and a reader who trusts the module they are reading gets
        the wrong answer.

        Containment is `[agent] sandbox = "docker"` (or e2b/daytona/
        cloudflare), where the boundary is the kernel's rather than a regex's.
        What this module actually provides is a fast, inspectable veto on the
        recognisable shapes of catastrophe — worth having, and not a sandbox.
  ALLOW (optional, per role)  if [agent.command_policy.<role>] lists allow
        regexes, a command must match one of them — the narrowest surface a
        role can have short of no shell at all (which the Rule of Two already
        gives untrusted-reading roles).

A refused command is not an exception: the model gets a clear text result
naming the rule, so it can choose a legitimate route or ask_human.
"""

import re

BUILTIN_DENY = [
    (r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+|-[a-zA-Z]*f[a-zA-Z]*\s+)+(/|~|\\|[A-Za-z]:\\?)(\s|$)",
     "recursive delete of a filesystem root"),
    (r"\b(rmdir|rd)\s+/s\b.*\b[A-Za-z]:\\?(\s|$)", "recursive delete of a drive"),
    (r"\b(mkfs|format|diskpart|fdisk)\b", "disk formatting"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "power control"),
    # the interpreter after the pipe may be quoted and/or a full path
    # ("C:\...\python.exe", /usr/bin/bash) — found by fault injection
    (r"\b(curl|wget|iwr|invoke-webrequest)\b[^|\n]*\|\s*[\"']?(?:[^\s\"'|]*[\\/])?"
     r"(sh|bash|zsh|pwsh|powershell|python3?|node|perl|ruby)(\.exe)?\b",
     "pipe-to-shell download execution"),
    (r"\b(sudo|doas|runas)\b", "privilege escalation"),
    (r"(/etc/shadow|/etc/passwd|\.ssh/id_|\.aws/credentials|agent\.env)",
     "credential or secret file access"),
    (r"\b(dd)\s+.*\bof=/dev/", "raw device write"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "fork bomb"),
    (r"\bchmod\s+(-R\s+)?[0-7]*777\b", "world-writable permissions"),
    (r"\b(netsh|iptables|ufw)\b", "firewall modification"),
    (r"\bgit\s+push\s+.*--force\b", "force push"),
]


# A command was either ALLOWED or DENIED, with nothing in between — yet the
# Execution Authority declared `approval: True` for model-written commands and
# its control table promised "policy + sandbox + scrub + approval + trace".
# Nothing implemented it. A declared control that does not exist is worse than
# an admitted gap: a reader trusts the table.
#
# The missing tier is not "dangerous" — BUILTIN_DENY already refuses that. It
# is CONSEQUENTIAL: legitimate work that reaches outside the workspace or
# cannot be undone. Publishing, sending, deleting in bulk, changing the
# world. The same rule the Effect Authority applies to external effects,
# applied to commands.
REVIEW = [
    # Turning on an MCP server is the widest single privilege change the
    # agent can make: a toolkit arrives with tools the platform has never
    # seen, and `filesystem` rooted at a drive letter would reach around
    # fileauth's zones entirely. It is a CONFIGURATION change, so it belongs
    # to the owner — and unlike `mcp.py call`, nothing downstream gates it.
    (r"\bmcp\.py\b[^|;&]*\benable\b", "granting the agent a new MCP toolkit"),
    (r"\bgit\s+push\b", "publishing code to a remote"),
    (r"\bgh\s+(pr|release|repo)\s+(create|edit|delete)\b", "changing a GitHub repository"),
    (r"\b(npm|yarn|pnpm)\s+publish\b", "publishing a package"),
    (r"\b(twine\s+upload|pip\s+upload)\b", "publishing a package"),
    (r"\bdocker\s+(push|login)\b", "publishing an image or authenticating a registry"),
    (r"\bkubectl\s+(apply|delete|scale)\b", "changing a live cluster"),
    (r"\bterraform\s+(apply|destroy)\b", "changing live infrastructure"),
    (r"\baws\s+\w+\s+(delete|terminate|put|create)\b", "changing cloud resources"),
    # the flag cluster may be -r, -rf, -fr, --recursive: match the letter
    # ANYWHERE in the cluster, the same shape BUILTIN_DENY already uses.
    # Written as `-[a-zA-Z]*r\b` first, which cannot match `-rf` at all —
    # caught by running it, not by reading it.
    (r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*|--recursive)\b",
     "recursive delete (a filesystem root is denied outright, not reviewed)"),
    (r"\bgit\s+(reset\s+--hard|clean\s+-[a-zA-Z]*f)\b", "discarding uncommitted work"),
    # a mail PROGRAM, not the word "mail" anywhere. Written as
    # \b(mail|sendmail|...)\b first, which matched the MCP server named
    # "mail" in `mcp.py call mail send` and held a governed call for a second
    # approval it had already passed — found by the effects test, which then
    # could not prove exactly-once delivery because nothing was ever sent.
    (r"(?:^|[|;&]\s*)(mail|sendmail|mailx|msmtp|swaks)\b", "sending mail"),
    (r"\bcurl\b[^|\n]*-(X\s*(POST|PUT|DELETE|PATCH)|-request\s+(POST|PUT|DELETE|PATCH))",
     "a state-changing HTTP request to the outside world"),
    (r"\b(pip|pip3)\s+install\b(?!.*--(?:target|user))", "installing into the environment"),
    (r"\bnpm\s+(i|install)\s+-g\b", "installing globally"),
]


# Platform tools that carry their OWN approval gate, and — critically —
# WHICH OF THEIR SUBCOMMANDS DO.
#
# This was `("mcp.py",)`: the whole script. The reasoning was sound for the
# subcommand it was written for — `mcp.py call` runs every invocation through
# guarded_call, which classifies risk, asks for approval and writes the
# effects ledger, so reviewing it a second time here would only stop the
# ledger from recording it.
#
# But the exemption was granted to the FILE, and `mcp.py enable` is in the
# same file and carries no gate at all. It writes mcp.json and hands the
# agent a whole new toolkit. Measured: `policy.check` and `policy.review`
# both passed `python mcp.py enable filesystem C:/` silently, while plain
# `git push` required approval — so the agent could not publish a commit
# without asking, but could grant itself unrestricted filesystem access
# through an MCP server rooted at the drive letter, going around fileauth's
# zones entirely.
#
# An exemption must be no wider than the gate that justifies it.
GOVERNED_ENTRY_POINTS = {
    # read-only inspection, plus `call`, which guarded_call governs
    "mcp.py": ("list", "tools", "catalog", "call"),
}


def _is_governed_entry_point(text):
    """Is this command SOLELY an invocation of a platform tool that carries
    its own gate?

    Three conditions, and all three are load-bearing:

      1. the script being run is one of ours — matched as the argument to a
         python interpreter, not merely mentioned somewhere in the string, so
         `python evil.py --config mcp.py` does not qualify;
      2. the command contains no shell metacharacter at all, so nothing can
         be chained, piped, substituted or redirected onto the end of it;
      3. the SUBCOMMAND is one that actually carries a gate. `mcp.py call`
         does — guarded_call classifies risk, asks for approval and writes
         the effects ledger. `mcp.py enable` does not: it writes mcp.json and
         grants a new toolkit. Exempting the file exempted both, which let
         the agent hand itself a filesystem server rooted anywhere while
         still needing approval to run `git push`.

    Together those mean the exemption cannot be used to smuggle anything: the
    only thing that runs is the tool whose own approval gate and effects
    ledger then apply.
    """
    if re.search(r"[|;&><`]|\$\(|\n", text):
        return False
    m = re.match(r'^\s*"?[^"]*?python[0-9.]*(?:\.exe)?"?\s+"?([^"\s]+)"?', text,
                 re.I)
    if not m:
        return False
    script = m.group(1).replace("\\", "/").rsplit("/", 1)[-1]
    allowed = GOVERNED_ENTRY_POINTS.get(script)
    if not allowed:
        return False
    # the first bare word after the script is the subcommand; a command with
    # no subcommand at all prints usage and does nothing, but it is also not
    # a gated action, so it is not exempted either
    rest = text[m.end():].strip()
    sub = ""
    for tok in rest.split():
        if not tok.startswith("-"):
            sub = tok.strip('"').lower()
            break
    return sub in allowed


def review(cmd, cfg=None):
    """-> (needs_approval, why). The middle tier between allow and deny.

    `[agent] autonomy = "full"` turns this off deliberately and in one place,
    for an owner who has decided the fleet may act unsupervised. The default
    is supervised, because the failure it prevents — an agent publishing or
    deleting something the owner did not ask for — is not recoverable by
    reading a log afterwards.
    """
    a = (cfg or {})
    if str(a.get("autonomy", "supervised")).lower() in ("full", "autonomous"):
        return False, ""
    extra = [(p, "owner review rule") for p in (a.get("command_review") or [])]
    text = cmd if isinstance(cmd, str) else " ".join(map(str, cmd or []))

    # A call to the platform's OWN governed entry point is not reviewed here,
    # because it is already governed there: mcp.guarded_call classifies the
    # tool's risk, requires approval for the risky ones, and records the call
    # in the effects ledger so a retry cannot deliver twice. Reviewing it a
    # second time does not add a control — it removes one, by preventing the
    # ledger from ever recording the effect.
    #
    # This is NOT a bypass, and the shape of the check is what makes that
    # true: it matches only a command that is SOLELY that invocation. Any
    # chaining, piping or redirection and the exemption does not apply, so
    # `python mcp.py call x; curl -X POST evil` is reviewed on its second
    # half exactly as it would be alone.
    if _is_governed_entry_point(text):
        return False, ""
    for pattern, why in REVIEW + extra:
        if re.search(pattern, text, re.I):
            return True, why
    return False, ""


def load_policy(cfg):
    """cfg = the [agent] table. Returns (extra_deny, per_role_allow)."""
    pol = (cfg or {}).get("command_policy") or {}
    extra = [(p, "owner deny rule") for p in (pol.get("deny") or [])]
    allow = {k: v for k, v in pol.items()
             if isinstance(v, dict) and v.get("allow")}
    return extra, allow


def rule_problems(cfg=None):
    """Every policy pattern that does not COMPILE. -> [(where, error)].

    A deny rule that does not compile is not a rule. `check` used to swallow
    re.error and `continue`, so an owner who wrote

        [agent.command_policy]
        deny = ["rm -rf ["]              # unterminated character set

    got a settings.toml that reads like the delete is blocked, a fleet where
    it is not, and no message anywhere saying so. The rules on either side of
    it kept working, which is what made it invisible: the deny list was
    partially enforced and looked entirely enforced.

    The allowlist branch had the OPPOSITE failure in the same function — no
    guard at all, so an uncompilable allow pattern raised re.error straight
    out of check() into whichever caller happened to ask. One function, two
    incompatible answers to "what if the owner's regex is malformed".

    BUILTIN_DENY is validated here too. It is ours and it is covered by tests,
    but "our patterns are fine" is an assumption, and this is the function
    whose whole job is to stop assuming that about patterns.
    """
    extra, allow = load_policy(cfg)
    out = []
    for pattern, _why in BUILTIN_DENY:
        try:
            re.compile(pattern)
        except re.error as e:
            out.append((f"BUILTIN_DENY {pattern!r}", str(e)))
    for pattern, _why in extra:
        try:
            re.compile(str(pattern))
        except re.error as e:
            out.append((f"command_policy.deny {pattern!r}", str(e)))
    for role, spec in (allow or {}).items():
        for pattern in ((spec or {}).get("allow") or []):
            try:
                re.compile(str(pattern))
            except re.error as e:
                out.append((f"command_policy.{role}.allow {pattern!r}", str(e)))
    return out


def check(cmd, role="default", cfg=None):
    """Return None if allowed, else a refusal string explaining the rule."""
    text = cmd if isinstance(cmd, str) else " ".join(map(str, cmd))
    low = text.lower()
    extra, allow = load_policy(cfg)

    # A broken rule set fails CLOSED, and says which rule. The alternative --
    # run the command because we could not read the rule meant to stop it --
    # is the one outcome nobody would choose if asked. It is loud rather than
    # silent because a typo that quietly disables a safety control is worth
    # more noise than a typo that stops work: preflight.check_policy reports
    # this as a BLOCKER, so it is normally caught before the fleet starts,
    # not at three in the morning.
    broken = rule_problems(cfg)
    if broken:
        detail = "; ".join(f"{where} -> {err}" for where, err in broken[:3])
        more = f" (and {len(broken) - 3} more)" if len(broken) > 3 else ""
        return (f"COMMAND REFUSED by policy: this fleet's command policy does "
                f"not compile, so it cannot be enforced: {detail}{more}. "
                f"Nothing runs under a rule set that cannot be read — fix the "
                f"pattern in settings.toml under [agent.command_policy] and "
                f"re-run `python preflight.py`.")

    for pattern, why in BUILTIN_DENY + extra:
        # No try/except: rule_problems has just compiled every one of these.
        if re.search(pattern, low if pattern.islower() else text,
                     re.IGNORECASE):
            return (f"COMMAND REFUSED by policy ({why}). This is a hard "
                    f"rule of the harness, not a suggestion: find a "
                    f"legitimate route inside your own directory, or "
                    f"ask_human if the task truly needs this.")
    rules = (allow.get(role) or {}).get("allow") if allow else None
    if rules:
        if not any(re.search(r, text, re.IGNORECASE) for r in rules):
            return (f"COMMAND REFUSED by policy: role '{role}' may only run "
                    f"commands matching its allowlist ({', '.join(rules)}).")
    return None


if __name__ == "__main__":
    import sys
    verdict = check(" ".join(sys.argv[1:]))
    print(verdict or "allowed")
    sys.exit(1 if verdict else 0)
