#!/usr/bin/env python3
"""MUTATION TESTING — break the feature, confirm the test notices.

A passing test proves nothing on its own: a test that would pass with the
feature removed is a test that measures nothing. This deliberately breaks
each load-bearing behaviour and requires the test that claims to cover it to
FAIL. Every mutation is reverted afterwards.

Run from the agent/ directory.
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time

AGENT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# (label, file, find, replace, test, what the test must notice)
MUTATIONS = [
    ("docker: egress allowed by default", "sandbox.py",
     '''    if not _cfg(cfg).get("sandbox_network"):
        argv += ["--network", "none"]           # default-deny egress''',
     '''    if False:
        argv += ["--network", "none"]''',
     "test_docker_live.py",
     "a container that can reach the internet by default"),

    ("docker: timeout leaves the container", "sandbox.py",
     '''    except subprocess.TimeoutExpired:
        _kill_container(name)
        raise''',
     '''    except subprocess.TimeoutExpired:
        raise''',
     "test_docker_live.py",
     "an orphaned container after a timeout"),

    # Was labelled "docker: credentials passed through" and paired with the
    # credential assertions, which scrub_env has already satisfied before
    # _docker runs at all -- so this breaks the SECOND filter, not the one
    # that stops credentials. It reported CAUGHT on Windows for a reason that
    # had nothing to do with the test noticing: forwarding a Windows PATH
    # into a Linux container means `sh` is not found and the container never
    # boots, so the credential check never executed. Linux, where the host
    # PATH is valid, told the truth and reported MISSED. Now it says what it
    # breaks, is POSIX-only for the same boot reason, and the docker test
    # asserts the property it actually removes.
    ("docker: every host variable forwarded into the container", "sandbox.py",
     '''    for k, v in sorted(_agent_env(env).items()):''',
     '''    for k, v in sorted(env.items()):''',
     "test_docker_live.py",
     "the host's entire environment inside the container",
     "forwarding a Windows PATH into a Linux container stops `sh` from being "
     "found, so the container never boots and no assertion is ever reached — "
     "a CAUGHT here would be the crash being counted, not the test noticing"),

    ("backup: the S3 query string signed uncanonicalised", "backup.py",
     '''    query = "&".join(f"{k}={v}" for k, v in sorted(parts))''',
     '''    query = u.query or ""''',
     "test_backup.py",
     "every signed request with a query string rejected by the store"),

    ("backup: a push proceeds without credentials", "backup.py",
     '''    if not kid or not secret:
        raise SystemExit(
            f"ERROR: no S3 credentials. Put {S3_KEY_ID} and {S3_KEY_SECRET} "''',
     '''    if False:
        raise SystemExit(
            f"ERROR: no S3 credentials. Put {S3_KEY_ID} and {S3_KEY_SECRET} "''',
     "test_backup.py",
     "an unauthenticated upload attempt instead of a refusal"),

    ("acquire: install becomes bookkeeping again", "acquire.py",
     '''    rc, out, err = execution.run("converter", argv, root, timeout=600,
                                 reason=f"acquire {spec}")
    ok = (rc == 0)''',
     '''    rc, out, err = 0, "(install %s)" % spec, ""
    ok = True''',
     "test_acquire.py",
     "an acquisition reaching 'trusted' with nothing installed"),

    ("acquire: the capability test accepts a supplied verdict", "acquire.py",
     '''    if passed is None:''',
     '''    if False:''',
     "test_acquire.py",
     "the MANDATORY step recording a claim instead of an observation"),

    ("acquire: a need matches a capability by substring", "acquire.py",
     '''    hay = set(re.findall(r"[a-z0-9_]+", str(haystack or "").lower()))
    return bool(need_words & hay)''',
     '''    return any(w in str(haystack or "").lower() for w in need_words)''',
     "test_acquire.py",
     "unrelated requests refused because 'thing' is inside 'everything'"),

    ("backup: a snapshot archives its own backups", "backup.py",
     '''    for full, rel in _walk(home, with_logs, exclude_dir=out_dir):''',
     '''    for full, rel in _walk(home, with_logs):''',
     "test_backup.py",
     "archives compounding until the disk the fleet saves itself onto is full"),

    ("execution: the declared approval control is skipped", "execution.py",
     '''    if spec.get("approval"):''',
     '''    if False:''',
     "test_invariants.py",
     "an agent publishing or deleting without the owner ever being asked"),

    ("policy: a consequential command is treated as ordinary", "policy.py",
     '''    for pattern, why in REVIEW + extra:''',
     '''    for pattern, why in extra:''',
     "test_invariants.py",
     "git push, npm publish and rm -r all running unreviewed"),

    ("activate: a provider is chosen whose key is absent", "bootstrap.py",
     '''        probe = {"api_key_env": key_env}
        if not credentials.resolve(probe, root=home):
            continue''',
     '''        probe = {"api_key_env": key_env}
        if False:
            continue''',
     "test_first_day.py",
     "every role pointed at a provider that cannot authenticate"),

    ("activate: incomplete credentials are used anyway", "bootstrap.py",
     '''        if any(not v for v in extra.values()):
            continue                      # a key without its account id is not usable''',
     '''        if False:
            continue''',
     "test_first_day.py",
     "a base_url still containing {CLOUDFLARE_ACCOUNT_ID}"),

    ("toolbox: a capability is judged by PATH alone", "toolbox.py",
     '''        import ingest
        return ingest.tool_argv(binary, module)''',
     '''        return [shutil.which(binary)] if shutil.which(binary) else None''',
     "test_invariants.py",
     "a capability reported MISSING that the machine actually has"),

    ("inbox: a zero settle window can still hold a file back", "ingest.py",
     '''        if settle > 0 and age < settle:''',
     '''        if age < settle:''',
     "test_url.py",
     "a dropped file never ingested because a clock ran a few ms ahead"),

    ("credentials: the environment scrub removed from every backend",
     "sandbox.py",
     '''    env, dropped = scrub_env({**os.environ, **(env or {})}, cfg, cmd)''',
     '''    env, dropped = {**os.environ, **(env or {})}, []''',
     "test_secrets.py",
     "API keys handed to a command the harness did not write"),

    ("provider: no Authorization header", "loop.py",
     '''                        "Authorization": f"Bearer {self._api_key(prov)}",''',
     '''                        "X-Not-Auth": "removed",''',
     "test_live_provider.py",
     "requests sent with no credential"),

    ("provider: malformed body kills the task", "loop.py",
     '''                    except (ValueError, KeyError, IndexError, TypeError) as e:''',
     '''                    except (KeyError, IndexError) as e:''',
     "test_live_provider.py",
     "a garbled body escaping the retry ladder"),

    ("provider: 4xx retried like weather", "loop.py",
     '''                    if e.code in (429, 500, 502, 503, 504):''',
     '''                    if e.code in (400, 401, 429, 500, 502, 503, 504):''',
     "test_live_provider.py",
     "five paid retries of a request that cannot succeed"),

    ("package: ship the credential file", "package.py",
     None,   # handled specially: plant agent.env and neuter the skip rule
     None,
     "test_package.py",
     "a shipped API key"),

    ("endurance: never archive finished work", "loop.py",
     '''        if len(finished) <= self.retain_finished + 25:''',
     '''        if True:''',
     "test_endurance.py",
     "a hot queue that grows without bound"),

    ("rbac: every write allowed", "ui.py",
     '''            org.check(self.home, getattr(self, "actor", OWNER_ACTOR),
                      permission, obj)
            return True''',
     '''            return True''',
     "test_rbac.py",
     "a viewer able to delete an agent"),

    ("fleet: creation stops seeding the home", "fleet.py",
     '''    seed_home(home)
    os.makedirs(os.path.join(home, "experts"), exist_ok=True)''',
     '''    os.makedirs(os.path.join(home, "experts"), exist_ok=True)''',
     "test_invariants.py",
     "a crash on a never-bootstrapped home"),

    # --- found by CI, the first time this suite ran on Linux ---

    ("loop: a running task is stolen from a live sibling", "loop.py",
     '''    def _may_resume(self, task):
        """May THIS loop pick up a task already marked running?"""
        r = task.get("runner")''',
     '''    def _may_resume(self, task):
        """May THIS loop pick up a task already marked running?"""
        return True
        r = task.get("runner")''',
     "test_audit.py",
     "two loops executing one task at the same time"),

    ("credentials: a secret written under the umask", "credentials.py",
     '''    path = os.fspath(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)''',
     '''    path = os.fspath(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path''',
     "test_preflight.py",
     "a fleet token every account on the machine can read", True),

    ("docker: the container runs as root in the mount", "sandbox.py",
     '''    if os.name != "nt":
        # Files created in a bind mount belong to the user INSIDE the''',
     '''    if False:
        # Files created in a bind mount belong to the user INSIDE the''',
     "test_docker_live.py",
     "a workspace the agent can no longer write to", True),

    # All three are paired with test_frontier.py, which needs no Docker and
    # never prints the token these results are scored on — so they are CAUGHT
    # or MISSED on every machine, never silently skipped.
    ("frontier: a probe need not fail before acquiring", "frontier.py",
     '''    if row["stage"] != "red":''',
     '''    if False:''',
     "test_frontier.py",
     "installing on the strength of a probe that never distinguished having "
     "the capability from not having it"),

    ("frontier: the last seal wins", "frontier.py",
     '''        if first is None:
            first = h
        elif h != first:
            conflict = True''',
     '''        first = h''',
     "test_frontier.py",
     "an attacker who never needs to edit a seal, because appending one wins"),

    ("universal: physical actuation is not an authority gap", "universal.py",
     '''     "acting on physical equipment, which cannot be undone by a retry"),''',
     '''     "acting on physical equipment (unreachable)") if False else
     (r"(?!x)x", "unreachable"),''',
     "test_universal.py",
     "a fleet that cuts power to a heater or changes a CNC feed rate without "
     "ever stopping to ask — the one failure here that burns something"),

    ("universal: a media noun has no direction", "universal.py",
     '''        makes = producing or verb''',
     '''        makes = False''',
     "test_universal.py",
     "synthesis answered with recognition — a run sent at the tool that does "
     "the reverse of the task"),

    ("universal: the losing side of a direction is not suppressed",
     "universal.py",
     '''        seen.add(make_cap)
        seen.add(read_cap)''',
     '''        seen.add(cap)''',
     "test_universal.py",
     "a goal asking for BOTH synthesis and recognition of the same noun, so "
     "the run picks whichever it likes"),

    ("frontier: readiness is decided inside the expert root", "frontier.py",
     '''            if (ad and ad.get("probe_hash") == row.get("probe_hash")
                    and ad.get("how_hash") == _how_hash(row.get("how_argv") or [])):''',
     '''            if True:''',
     "test_frontier.py",
     "a capability made READY by writing one word into a file the worker can "
     "reach"),
]


def run_test(name, timeout=900):
    """-> "CAUGHT" | "MISSED" | "SKIP".

    A test that SKIPS itself (docker unavailable, for instance) exits 0
    without having run anything, and calling that MISSED would report a
    false alarm on every machine without a daemon. Read the marker the test
    prints rather than the exit code alone.
    """
    r = subprocess.run([PY, os.path.join(AGENT, "tests", name)],
                       cwd=os.path.join(AGENT, "tests"),
                       capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, "PYTHONUTF8": "1"})
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0 and "SKIP " in out:
        return "SKIP"
    return "CAUGHT" if r.returncode != 0 else "MISSED"


def _plant_decoy(path, text):
    """Create a decoy file, or return None if a REAL one is already there.

    THE RETURN VALUE IS THE WHOLE POINT: `planted` must mean "a file WE
    created and may therefore delete". It used to be assigned BEFORE the
    existence check —

        planted = os.path.join(AGENT, "agent.env")
        if os.path.exists(planted):
            results.append((label, "SKIP", "agent.env already exists"))
            continue                 # a `continue` inside try RUNS finally
        ...
        finally:
            if planted and os.path.exists(planted):
                os.remove(planted)   # ...and deleted the owner's real keys

    — so the guard correctly detected a real agent.env, announced that it was
    SKIPPING to avoid touching it, and then deleted it on the way out.
    Running `python mutate_check.py` destroyed the operator's API keys
    silently, while reporting a skip. Found when a real agent.env vanished
    from this working tree mid-session and the deletion was traced here.

    A name that means "ours" cannot be assigned before we know it is ours.
    """
    if os.path.exists(path):
        return None
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    results = []
    for entry in MUTATIONS:
        label, fname, find, repl, test, expect = entry[:6]
        # Some properties exist only on POSIX — file modes are one, because
        # Windows uses ACLs and the platform says so at every chmod. Calling
        # such a mutation MISSED on Windows would be a false alarm; calling
        # it CAUGHT would be a lie. It is declared, and skipped out loud.
        # True, or a string saying WHY this one is POSIX-only. A single
        # blanket reason was wrong the moment a second kind of mutation
        # became POSIX-only for a different cause, and a skip line nobody
        # can trust is worse than no skip line.
        posix_only = entry[6] if len(entry) > 6 else False
        if only and only not in label:
            continue
        if posix_only and os.name == "nt":
            why = posix_only if isinstance(posix_only, str) else \
                "Windows uses ACLs, not modes, so nothing here can catch it"
            results.append((label, "SKIP", f"POSIX-only: {why} — run on Linux"))
            continue
        path = os.path.join(AGENT, fname)
        backup = path + ".mutbak"
        planted = None
        shutil.copy(path, backup)
        try:
            if find is None:                    # the packaging mutation
                planted = _plant_decoy(
                    os.path.join(AGENT, "agent.env"),
                    "OPENAI_API_KEY=sk-mutation-should-be-caught\n")
                if planted is None:
                    results.append((label, "SKIP", "agent.env already exists"))
                    continue
                src = io.open(path, encoding="utf-8").read()
                mutated = src.replace("def should_skip(", "def _orig_skip(")
                mutated += ("\n\ndef should_skip(*a, **k):\n"
                            "    return False\n")
                io.open(path, "w", encoding="utf-8", newline="\n").write(mutated)
            else:
                src = io.open(path, encoding="utf-8").read()
                if src.count(find) != 1:
                    results.append((label, "SKIP",
                                    f"anchor appears {src.count(find)}x"))
                    continue
                io.open(path, "w", encoding="utf-8", newline="\n").write(
                    src.replace(find, repl, 1))
            t0 = time.time()
            verdict = run_test(test)
            took = time.time() - t0
            said = {"CAUGHT": "failed", "MISSED": "PASSED ANYWAY",
                    "SKIP": "skipped itself (a prerequisite is missing)"}
            results.append((label, verdict,
                            f"{test} {said[verdict]} in {took:.0f}s — {expect}"))
        finally:
            shutil.copy(backup, path)
            os.remove(backup)
            if planted and os.path.exists(planted):
                os.remove(planted)
    print()
    print("=" * 78)
    print("MUTATION RESULTS — a MISSED row is a test that measures nothing")
    print("=" * 78)
    for label, verdict, detail in results:
        print(f"  {verdict:<7} {label}")
        print(f"          {detail}")
    missed = [r for r in results if r[1] == "MISSED"]
    print()
    print(f"{len(results)} mutations: "
          f"{sum(1 for r in results if r[1] == 'CAUGHT')} caught, "
          f"{len(missed)} missed, "
          f"{sum(1 for r in results if r[1] == 'SKIP')} skipped")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
