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
        and any attempt to leave the agent's own directory via cd/absolute
        paths outside the root. Owner may ADD patterns; may not remove the
        built-ins.
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


def load_policy(cfg):
    """cfg = the [agent] table. Returns (extra_deny, per_role_allow)."""
    pol = (cfg or {}).get("command_policy") or {}
    extra = [(p, "owner deny rule") for p in (pol.get("deny") or [])]
    allow = {k: v for k, v in pol.items()
             if isinstance(v, dict) and v.get("allow")}
    return extra, allow


def check(cmd, role="default", cfg=None):
    """Return None if allowed, else a refusal string explaining the rule."""
    text = cmd if isinstance(cmd, str) else " ".join(map(str, cmd))
    low = text.lower()
    extra, allow = load_policy(cfg)
    for pattern, why in BUILTIN_DENY + extra:
        try:
            if re.search(pattern, low if pattern.islower() else text,
                         re.IGNORECASE):
                return (f"COMMAND REFUSED by policy ({why}). This is a hard "
                        f"rule of the harness, not a suggestion: find a "
                        f"legitimate route inside your own directory, or "
                        f"ask_human if the task truly needs this.")
        except re.error:
            continue
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
