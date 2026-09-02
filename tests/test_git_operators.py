#!/usr/bin/env python3
"""Phase 5 exit benchmark — Git semantic operators, held green.

docs/DESIGN-P5-git-operators.md preregistered exactly this: the fourth
deterministic state world must show, before it becomes permanent, that

  1. DETERMINISM       same bytes + same verbs = byte-identical commits
  2. CLOSED SURFACE    unknown/network verbs, unscreened names, .git paths,
                       unasserted mutations refuse before any side effect
  3. RESTORE           a failed declared effect leaves HEAD, refs, index
                       and worktree exactly as before
  4. CONFLICT          a conflicting merge is refused by name and restored
  5. TAMPER            a planted hook or edited .git/config fails closed
  6. AUTHORITY         git-write:<repo> is owner-granted, per leaf and per
                       static walk; the worker tool honours the allowlist
  7. END TO END        gated trajectories -> candidate -> owner-sealed fresh
                       suite -> PROVEN -> zero-model replay under the task's
                       own INDEPENDENT git gate
  8. REGISTRATION      the tool pair, the predicate and the audit entry exist

Mock providers stand in for the model; the machinery under test is the
platform's. The zero-model claim is enforced the hard way: the routed
task's worker gets an EMPTY provider script, so consulting a model could
only have failed its gate.

Run from the agent/ directory:  python tests/test_git_operators.py
"""
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile

from common import AGENT_DIR, PY, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import fleet                    # noqa: E402
import gitstate                 # noqa: E402
import loop                     # noqa: E402
import operators                # noqa: E402
import procedure                # noqa: E402
import runbook                  # noqa: E402

FAMILY = "gitpublish"


def _settings(root, providers, git_write=()):
    s = ['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
         'poll_interval_seconds = 1', 'max_task_usd = 0', 'reflect_after = []',
         'max_done_rejects = 2', 'max_task_retries = 0',
         'git_write = [' + ", ".join(f'"{p}"' for p in git_write) + ']', '']
    for name in providers:
        s += [f'[providers.{name}]', 'type = "mock"',
              f'script = "scripts/{name}.json"', '']
    s += ['[roles.default]', f'provider = "{providers[0]}"', 'model = "mock"', '']
    for name in providers:
        s += [f'[roles.r_{name}]', f'provider = "{name}"', 'model = "mock"', '']
    io.open(os.path.join(root, "settings.toml"), "w",
            encoding="utf-8").write("\n".join(s))
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)


def _script(root, name, steps):
    json.dump(steps, io.open(os.path.join(root, "scripts", f"{name}.json"),
                             "w", encoding="utf-8"))


def _events(root):
    out = []
    for line in io.open(os.path.join(root, "logs", "agent.log"),
                        encoding="utf-8", errors="replace"):
        if "{" in line and line.rstrip().endswith("}"):
            try:
                out.append(json.loads(line[line.index("{"):]))
            except ValueError:
                pass
    return out


def _tasks(root):
    p = os.path.join(root, "state.json")
    if not os.path.isfile(p):
        return []
    return json.load(io.open(p, encoding="utf-8"))["tasks"]


def refuses(fragment, fn, *args):
    try:
        fn(*args)
    except ValueError as exc:
        assert fragment in str(exc), (fragment, str(exc))
        return
    raise AssertionError(f"accepted what must be refused: {fragment}")


def _routed_done(root, goal, inputs, done_check, family):
    """Queue a task for the SILENT worker and drain: only the zero-model
    route can complete it, and its own gate still judges."""
    agent = loop.Agent(root)
    agent.add_task("r_silent", goal, done_check=done_check, family=family,
                   inputs=inputs)
    assert run_drain(root, timeout=180) == 0
    third = _tasks(root)[-1]
    assert third["status"] == "done" and third.get("procedure_routed"), third
    routed = [e for e in _events(root) if e.get("event") == "procedure_route"]
    assert routed and routed[-1]["model_calls"] == 0, routed
    return third


def _arena(name):
    base = os.environ.get("AGENT_TEST_TMP") or os.path.join(
        tempfile.gettempdir(), "agent-suite")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix=f"gitops-{name}-", dir=base)


def op(**kw):
    return json.dumps(kw)


def asserts(*items):
    return json.dumps(list(items))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _write(repo, rel, data):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(data)


def _status(repo):
    return gitstate.query(repo, json.dumps({"kind": "status"}))


def _real_git(repo, *args):
    """The INDEPENDENT witness: the host's own git, none of the adapter."""
    return subprocess.run(["git", "-C", repo, *args], capture_output=True,
                          text=True, errors="replace")


def _sequence(repo, content=b"alpha\n"):
    gitstate.apply_op(repo, op(verb="init"),
                      asserts({"kind": "head_is", "name": "main"}))
    _write(repo, "notes.md", content)
    gitstate.apply_op(repo, op(verb="commit", paths=["notes.md"],
                               message="add notes"),
                      asserts({"kind": "clean_worktree"},
                              {"kind": "file_at_ref", "ref": "HEAD",
                               "path": "notes.md", "sha256": sha(content)},
                              {"kind": "rev_count", "ref": "HEAD", "equals": 1}))
    gitstate.apply_op(repo, op(verb="branch", name="release"),
                      asserts({"kind": "branch_exists", "name": "release"}))
    gitstate.apply_op(repo, op(verb="tag", name="v1"),
                      asserts({"kind": "tag_exists", "name": "v1"},
                              {"kind": "ancestor", "ancestor": "v1",
                               "descendant": "main"}))
    return _status(repo)["head"]


# ------------------------------------------------------- 8. registration

def check_registration():
    assert "git_op" in procedure.DETERMINISTIC_TOOLS
    names = [t["function"]["name"] for t in loop.TOOL_DEFS]
    assert "git_op" in names and "git_query" in names, names
    operators.validate_predicate({"predicate": "repo_satisfies", "path": "r",
                                  "assertions": "[]"})
    refuses("repo_satisfies needs assertions", operators.validate_predicate,
            {"predicate": "repo_satisfies", "path": "r"})
    import execution
    assert "gitstate.py" in execution.ALLOWED_RAW, \
        "the adapter's subprocess use must be declared, never exempted silently"
    print("[registration] git_op/git_query declared, repo_satisfies in the "
          "algebra, gitstate.py declared to the execution audit")


# ------------------------------------------------------ 2. closed surface

def check_closed_surface():
    refuses("unknown verb", gitstate.canonical_op, op(verb="push"))
    refuses("unknown verb", gitstate.canonical_op, op(verb="fetch", name="origin"))
    refuses("unknown verb", gitstate.canonical_op, op(verb="rebase", name="main"))
    refuses("unknown verb", gitstate.canonical_op, op(verb="reset", name="main"))
    refuses("takes exactly", gitstate.canonical_op, op(verb="init", name="x"))
    refuses("must be relative", gitstate.canonical_op,
            op(verb="commit", paths=["-rf"], message="m"))
    refuses("reaches into .git", gitstate.canonical_op,
            op(verb="commit", paths=[".git/hooks/pre-commit"], message="m"))
    refuses("'..' components", gitstate.canonical_op,
            op(verb="commit", paths=["../escape"], message="m"))
    refuses("not an acceptable ref name", gitstate.canonical_op,
            op(verb="branch", name="-rf"))
    refuses("not an acceptable ref name", gitstate.canonical_op,
            op(verb="branch", name="a..b"))
    refuses("not an acceptable ref name", gitstate.canonical_op,
            op(verb="tag", name="HEAD"))
    refuses("commit message", gitstate.canonical_op,
            op(verb="commit", paths=["a"], message="   "))
    refuses("no declared observable effect", gitstate.canonical_assertions, "[]")
    refuses("kind in", gitstate.canonical_assertions,
            asserts({"kind": "remote_synced"}))
    refuses("exactly one of", gitstate.canonical_assertions,
            asserts({"kind": "file_at_ref", "ref": "HEAD", "path": "a",
                     "sha256": "0" * 64, "text": "x"}))
    refuses("takes exactly", gitstate.canonical_assertions,
            asserts({"kind": "head_is", "name": "main", "extra": 1}))
    refuses("non-negative integer", gitstate.canonical_assertions,
            asserts({"kind": "rev_count", "ref": "HEAD", "equals": True}))
    refuses("unknown query", gitstate.canonical_query,
            json.dumps({"kind": "reflog"}))
    # refused BEFORE any side effect
    repo = os.path.join(_arena("closed"), "r")
    refuses("unknown verb", gitstate.apply_op, repo, op(verb="push"),
            asserts({"kind": "head_is", "name": "main"}))
    refuses("no declared observable effect", gitstate.apply_op, repo,
            op(verb="init"), "[]")
    assert not os.path.exists(repo), "a refused verb must touch nothing"
    # a repository the adapter did not initialize is not one it operates
    foreign = os.path.join(os.path.dirname(repo), "foreign")
    os.makedirs(foreign)
    assert _real_git(foreign, "init", "-q").returncode == 0
    refuses("tampered", gitstate.apply_op, foreign, op(verb="tag", name="v1"),
            asserts({"kind": "tag_exists", "name": "v1"}))
    print("[closed-surface] push/fetch/rebase/reset do not exist; unscreened names, "
          ".git paths, unasserted mutations and foreign repositories refuse "
          "before any side effect")


# --------------------------------------------------------- 1. determinism

def check_determinism():
    a = os.path.join(_arena("det-a"), "r")
    b = os.path.join(_arena("det-b"), "r")
    ha, hb = _sequence(a), _sequence(b)
    assert ha and ha == hb, (ha, hb)
    assert gitstate.state_digest(a) == gitstate.state_digest(b)
    assert not os.path.exists(os.path.join(a, ".git", "hooks"))
    with open(os.path.join(a, ".git", "config"), "rb") as f:
        assert f.read() == gitstate.CANONICAL_CONFIG.encode("utf-8")
    c = os.path.join(_arena("det-c"), "r")
    assert _sequence(c, content=b"alpha\r\n") != ha, \
        "different bytes must be a different commit — no normalization"
    # an approximate or partial observation cannot pass
    ok, why = gitstate.check_assertions(a, asserts(
        {"kind": "file_at_ref", "ref": "HEAD", "path": "notes.md",
         "sha256": sha(b"alpha")}))
    assert not ok and "observed" in why, why
    assert gitstate.check_assertions(a, asserts(
        {"kind": "file_at_ref", "ref": "HEAD", "path": "notes.md",
         "text": "alpha\n"}))[0]
    assert not gitstate.check_assertions(a, asserts(
        {"kind": "file_at_ref", "ref": "HEAD", "path": "notes.md",
         "text": "alpha"}))[0]
    assert not gitstate.check_assertions(a, asserts(
        {"kind": "rev_count", "ref": "HEAD", "equals": 2}))[0]
    assert not gitstate.check_assertions(a, asserts(
        {"kind": "branch_exists", "name": "ghost"}))[0]
    assert gitstate.check_assertions(a, asserts(
        {"kind": "branch_absent", "name": "ghost"}))[0]
    assert gitstate.query(a, json.dumps({"kind": "log"})) == [[ha, "add notes"]]
    assert gitstate.query(a, json.dumps({"kind": "branches"})) == \
        {"branches": ["main", "release"], "current": "main"}
    assert gitstate.query(a, json.dumps({"kind": "show", "ref": "v1",
                                         "path": "notes.md"})) == "alpha\n"
    print(f"[determinism] two arenas, same bytes and verbs: identical "
          f"commit {ha[:12]}; a byte changed changes it; partial and "
          f"approximate observations refuse")


# ------------------------------------------------------------ 3. restore

def check_failed_effect_restores():
    repo = os.path.join(_arena("restore"), "r")
    h1 = _sequence(repo)
    _write(repo, "notes.md", b"beta\n")
    refuses("repository restored", gitstate.apply_op, repo,
            op(verb="commit", paths=["notes.md"], message="beta"),
            asserts({"kind": "file_at_ref", "ref": "HEAD", "path": "notes.md",
                     "sha256": sha(b"gamma\n")}))
    st = _status(repo)
    assert st["head"] == h1 and st["branch"] == "main" and \
        not st["clean_tracked"], st
    with open(os.path.join(repo, "notes.md"), "rb") as f:
        assert f.read() == b"beta\n", "the worktree edit must survive"
    assert gitstate.check_assertions(repo, asserts(
        {"kind": "rev_count", "ref": "HEAD", "equals": 1}))[0]
    assert _real_git(repo, "diff", "--cached", "--quiet").returncode == 0, \
        "the index must be back at HEAD"
    landed = gitstate.apply_op(
        repo, op(verb="commit", paths=["notes.md"], message="beta"),
        asserts({"kind": "file_at_ref", "ref": "HEAD", "path": "notes.md",
                 "sha256": sha(b"beta\n")},
                {"kind": "rev_count", "ref": "HEAD", "equals": 2}))
    assert landed["head"] != h1
    # a failed FIRST commit leaves the repository unborn and usable
    repo2 = os.path.join(_arena("restore2"), "r")
    gitstate.apply_op(repo2, op(verb="init"),
                      asserts({"kind": "head_is", "name": "main"}))
    _write(repo2, "a.txt", b"a\n")
    refuses("repository restored", gitstate.apply_op, repo2,
            op(verb="commit", paths=["a.txt"], message="a"),
            asserts({"kind": "rev_count", "ref": "HEAD", "equals": 2}))
    assert _status(repo2)["head"] is None
    assert _real_git(repo2, "ls-files").stdout.strip() == "", \
        "nothing may stay staged after a restored first commit"
    assert gitstate.apply_op(repo2, op(verb="commit", paths=["a.txt"],
                                       message="a"),
                             asserts({"kind": "rev_count", "ref": "HEAD",
                                      "equals": 1}))["head"]
    print("[restore] a commit whose declared effect did not hold left HEAD, "
          "refs, index and worktree exactly as before — asserted or "
          "untouched, never between")


# ----------------------------------------------------------- 4. conflict

def check_merge_conflict_is_refused_and_restored():
    repo = os.path.join(_arena("merge"), "r")
    gitstate.apply_op(repo, op(verb="init"),
                      asserts({"kind": "head_is", "name": "main"}))

    def commit(message, count):
        gitstate.apply_op(repo, op(verb="commit", paths=["f.txt"],
                                   message=message),
                          asserts({"kind": "rev_count", "ref": "HEAD",
                                   "equals": count}))

    def switch(name):
        gitstate.apply_op(repo, op(verb="switch", name=name),
                          asserts({"kind": "head_is", "name": name}))

    _write(repo, "f.txt", b"one\n")
    commit("one", 1)
    gitstate.apply_op(repo, op(verb="branch", name="topic"),
                      asserts({"kind": "branch_exists", "name": "topic"}))
    switch("topic")
    _write(repo, "f.txt", b"two\n")
    commit("two", 2)
    switch("main")
    _write(repo, "f.txt", b"three\n")
    commit("three", 2)
    before = _status(repo)["head"]
    refuses("merge conflict", gitstate.apply_op, repo,
            op(verb="merge", name="topic"),
            asserts({"kind": "ancestor", "ancestor": "topic",
                     "descendant": "main"}))
    st = _status(repo)
    assert st["head"] == before and st["clean_tracked"] and \
        st["branch"] == "main", st
    assert not os.path.exists(os.path.join(repo, ".git", "MERGE_HEAD"))
    with open(os.path.join(repo, "f.txt"), "rb") as f:
        assert f.read() == b"three\n"
    # a clean merge lands, observable as ancestry and content
    gitstate.apply_op(repo, op(verb="branch", name="side"),
                      asserts({"kind": "branch_exists", "name": "side"}))
    switch("side")
    _write(repo, "g.txt", b"g\n")
    gitstate.apply_op(repo, op(verb="commit", paths=["g.txt"], message="g"),
                      asserts({"kind": "file_at_ref", "ref": "HEAD",
                               "path": "g.txt", "text": "g\n"}))
    switch("main")
    merged = gitstate.apply_op(
        repo, op(verb="merge", name="side"),
        asserts({"kind": "ancestor", "ancestor": "side", "descendant": "main"},
                {"kind": "file_at_ref", "ref": "HEAD", "path": "g.txt",
                 "text": "g\n"},
                {"kind": "clean_worktree"}))
    assert merged["head"] != before and merged["branch"] == "main"
    print("[conflict] a conflicting merge was refused by name with the "
          "repository restored (same HEAD, clean worktree, no merge in "
          "progress); a clean merge landed and verified as ancestry")


# ------------------------------------------------------------- 5. tamper

def check_tamper_fails_closed():
    root = _arena("tamper")
    rel = "work/t"
    repo = os.path.join(root, "work", "t")
    head = _sequence(repo)
    hooks = os.path.join(repo, ".git", "hooks")
    os.makedirs(hooks)
    hook = os.path.join(hooks, "pre-commit")
    with open(hook, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/sh\n: > SENTINEL\n")
    os.chmod(hook, 0o755)
    _write(repo, "notes.md", b"evil\n")
    clean = asserts({"kind": "clean_worktree"})
    refuses("tampered", gitstate.apply_op, repo,
            op(verb="commit", paths=["notes.md"], message="x"), clean)
    refuses("tampered", gitstate.query, repo, json.dumps({"kind": "status"}))
    assert not os.path.exists(os.path.join(repo, "SENTINEL")), \
        "the planted hook must never run"
    assert _real_git(repo, "rev-parse", "HEAD").stdout.strip() == head
    assert gitstate.state_digest(repo) == "tampered"
    assert operators.observe(root, {"predicate": "repo_satisfies", "path": rel,
                                    "assertions": asserts(
                                        {"kind": "head_is", "name": "main"})}) \
        is False, "a gate must read a tampered repository as not-true"
    os.remove(hook)
    os.rmdir(hooks)
    assert gitstate.check_assertions(repo, asserts(
        {"kind": "head_is", "name": "main"}))[0]
    config = os.path.join(repo, ".git", "config")
    with open(config, "ab") as f:
        f.write(b"\tfsmonitor = evil\n")
    refuses("tampered", gitstate.apply_op, repo,
            op(verb="commit", paths=["notes.md"], message="x"), clean)
    assert _real_git(repo, "rev-parse", "HEAD").stdout.strip() == head
    with open(config, "wb") as f:
        f.write(gitstate.CANONICAL_CONFIG.encode("utf-8"))
    landed = gitstate.apply_op(
        repo, op(verb="commit", paths=["notes.md"], message="x"), clean)
    assert landed["head"] != head
    assert not os.path.exists(os.path.join(repo, "SENTINEL"))
    print("[tamper] a planted pre-commit hook and an edited .git/config each "
          "made every operation refuse — fail closed — and the hook never "
          "ran; the canonical control files restored, work resumed")


# ---------------------------------------------------------- 6. authority

def check_authority_is_owner_granted(home):
    root = os.path.join(home, "gitauth")
    os.makedirs(os.path.join(root, "work"), exist_ok=True)
    init_assert = asserts({"kind": "head_is", "name": "main"})
    for version in (1, 2):
        rel = f"work/x{version}"
        leaf = {"kind": "deterministic", "id": "step-1", "depends_on": [],
                "action": {"tool": "git_op",
                           "args": {"repo": rel, "op": op(verb="init"),
                                    "assertions": init_assert}},
                "preconditions": [],
                "effects": [{"predicate": "repo_satisfies", "path": rel,
                             "assertions": init_assert}]}
        rb = {"name": f"proc-gitauth{version}", "triggers": ["gitauth"],
              "procedure_version": version, "steps": [leaf],
              "operator": {"inputs": {}, "preconditions": [], "effects": [],
                           "invariants": [], "cost_usd": 0.0,
                           "latency_seconds": 0.0,
                           "reversibility": "conditional",
                           "authority": ["workspace-write"]},
              "provenance": {"compiled": False, "family": "gitauth",
                             "acceptance_basis": "authored",
                             "input_hashes": [], "trajectory_ids": []}}
        assert procedure.validate(rb) == [], procedure.validate(rb)
        result = procedure.execute(root, rb, {})
        assert not result["ok"] and f"git-write:{rel}" in result["why"], result
        assert not os.path.exists(os.path.join(root, rel, ".git")), \
            "a refused authority must precede every side effect"
        granted = procedure.execute(root, rb, {},
                                    authority={"workspace-write",
                                               f"git-write:{rel}"})
        assert granted["ok"], granted
        assert gitstate.is_repository(os.path.join(root, rel))
    # the worker tool honours the owner's allowlist, fail closed
    desk = fleet.create(home, "Auth Desk", "checks git authority")
    _settings(desk, ["m"], git_write=["work/allowed"])
    _script(desk, "m", [])
    agent = loop.Agent(desk)
    probe = {"id": "auth-probe", "role": "r_m", "goal": "probe"}
    out = agent._exec_tool(probe, "git_op",
                           {"repo": "work/forbidden", "op": op(verb="init"),
                            "assertions": init_assert})
    assert "git_write allowlist" in out, out
    assert not os.path.exists(os.path.join(desk, "work", "forbidden"))
    out = agent._exec_tool(probe, "git_op",
                           {"repo": "work/allowed", "op": op(verb="init"),
                            "assertions": init_assert})
    assert out.startswith("ok, git init applied"), out
    out = agent._exec_tool(probe, "git_query",
                           {"repo": "work/allowed",
                            "query": json.dumps({"kind": "branches"})})
    assert json.loads(out) == {"branches": [], "current": "main"}, out
    print("[authority] a git step demands the owner's token for exactly its "
          "repository — per leaf (v2) and per static walk (v1) — never "
          "declared away; the worker tool refuses outside git_write")


# --------------------------------------------- 7. end to end (learning)

GATE = r'''import io, subprocess, sys
repo, expect = sys.argv[1], sys.argv[2]
def g(*a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True)
want = io.open(expect, encoding="utf-8").read().replace("\r\n", "\n")
blob = g("cat-file", "blob", "HEAD:notes.md").stdout.decode("utf-8", "replace")
ok = (blob.replace("\r\n", "\n") == want
      and g("symbolic-ref", "--short", "HEAD").stdout.decode().strip() == "main"
      and g("show-ref", "--verify", "--quiet", "refs/heads/release").returncode == 0
      and g("show-ref", "--verify", "--quiet", "refs/tags/v1").returncode == 0)
sys.exit(0 if ok else 1)
'''


def _publish_inputs(k, content):
    return {"repo": f"work/r-{k}", "path": f"work/r-{k}/notes.md",
            "content": content,
            "assertions": gitstate.canonical_assertions(asserts(
                {"kind": "clean_worktree"},
                {"kind": "file_at_ref", "ref": "HEAD", "path": "notes.md",
                 "text": content},
                {"kind": "rev_count", "ref": "HEAD", "equals": 1}))}


def _publish_steps(inp):
    repo = inp["repo"]
    return [
        {"tool": "git_op", "args": {"repo": repo, "op": op(verb="init"),
                                    "assertions": asserts(
                                        {"kind": "head_is", "name": "main"})}},
        {"tool": "write_file", "args": {"path": inp["path"],
                                        "content": inp["content"]}},
        {"tool": "git_op", "args": {"repo": repo,
                                    "op": op(verb="commit", paths=["notes.md"],
                                             message="publish notes"),
                                    "assertions": inp["assertions"]}},
        {"tool": "git_op", "args": {"repo": repo,
                                    "op": op(verb="branch", name="release"),
                                    "assertions": asserts(
                                        {"kind": "branch_exists",
                                         "name": "release"})}},
        {"tool": "git_op", "args": {"repo": repo, "op": op(verb="tag", name="v1"),
                                    "assertions": asserts(
                                        {"kind": "tag_exists", "name": "v1"},
                                        {"kind": "ancestor", "ancestor": "v1",
                                         "descendant": "main"})}},
        {"tool": "finish_task", "args": {"summary": "published"}}]


def _expect(root, k, content):
    io.open(os.path.join(root, f"expect-{k}.txt"), "w",
            encoding="utf-8").write(content)
    return f"expect-{k}.txt"


def check_end_to_end_learning(home):
    root = fleet.create(home, "Repo Desk", "publishes notes into repositories")
    _settings(root, ["wa", "wb", "silent"],
              git_write=["work/r-1", "work/r-2", "work/r-9"])
    io.open(os.path.join(root, "check.py"), "w", encoding="utf-8").write(GATE)
    agent = loop.Agent(root)
    contents = {1: "alpha release\n- first\n",
                2: "beta release\n- second\n- third\n"}
    for prov, k in (("wa", 1), ("wb", 2)):
        inp = _publish_inputs(k, contents[k])
        _script(root, prov, _publish_steps(inp))
        agent.add_task(f"r_{prov}", f"perform the {FAMILY} for repo r-{k}",
                       done_check=f'"{PY}" check.py work/r-{k} '
                                  f'{_expect(root, k, contents[k])}',
                       family=FAMILY, inputs=inp)
    assert run_drain(root, timeout=240) == 0
    done = _tasks(root)[-2:]
    assert all(t["status"] == "done" for t in done), done
    assert any(e.get("event") == "procedure_compiled" for e in _events(root)), \
        [e for e in _events(root) if "procedure" in str(e.get("event"))]
    assert runbook.status(root, f"proc-{FAMILY}") == "candidate"
    rb = runbook.load(root, f"proc-{FAMILY}")
    assert rb["operator"]["inputs"] == {"repo": "path", "path": "path",
                                        "content": "string",
                                        "assertions": "string"}, rb["operator"]
    tools = [s["action"]["tool"] for s in rb["steps"]]
    assert tools == ["git_op", "write_file", "git_op", "git_op", "git_op"], tools
    assert rb["steps"][0]["action"]["args"]["repo"] == {"input": "repo"}
    assert rb["steps"][0]["effects"][0]["predicate"] == "repo_satisfies"
    assert rb["steps"][2]["action"]["args"]["assertions"] == {"input": "assertions"}
    assert rb["steps"][4]["action"]["args"]["op"] == \
        gitstate.canonical_op(op(verb="tag", name="v1")), "constants stay literal"
    fresh = {"c4": "gamma\n", "c5": "delta notes\nwith two lines\n", "c6": ""}
    procedure.seal_suite(root, f"{FAMILY}-fresh", {
        "family": FAMILY,
        "authority": [f"git-write:work/r-{cid}" for cid in sorted(fresh)],
        "cases": [{"id": cid, "edge": cid == "c6",
                   "inputs": _publish_inputs(cid, fresh[cid])}
                  for cid in sorted(fresh)],
        "checks": [{"predicate": "repo_satisfies", "path": {"input": "repo"},
                    "assertions": {"input": "assertions"}},
                   {"predicate": "repo_satisfies", "path": {"input": "repo"},
                    "assertions": gitstate.canonical_assertions(asserts(
                        {"kind": "tag_exists", "name": "v1"},
                        {"kind": "branch_exists", "name": "release"},
                        {"kind": "head_is", "name": "main"}))}]})
    verdict = procedure.evaluate(root, f"proc-{FAMILY}", f"{FAMILY}-fresh")
    assert verdict["accepted"] and verdict["status"] == "proven", verdict
    _script(root, "silent", [])
    inp9 = _publish_inputs(9, "release nine\n- shipped\n")
    _routed_done(root, f"perform the {FAMILY} for repo r-9", inp9,
                 f'"{PY}" check.py work/r-9 '
                 f'{_expect(root, 9, inp9["content"])}', FAMILY)
    repo9 = os.path.join(root, "work", "r-9")
    assert _real_git(repo9, "tag", "-l", "v1").stdout.strip() == "v1"
    assert _real_git(repo9, "cat-file", "blob", "HEAD:notes.md").stdout \
        .replace("\r\n", "\n") == inp9["content"]
    assert _real_git(repo9, "log", "--format=%an <%ae>", "-1").stdout.strip() \
        == "agent <agent@local>", "pinned identity is what the witness sees"
    print("[end-to-end] init -> write -> commit -> branch -> tag went "
          "candidate from two gated trajectories, PROVEN on a sealed fresh "
          "suite (edge: an empty note), and replayed repository nine with "
          "zero model calls under its own independent git gate")


def main():
    home = make_sandbox("git-operators",
                        providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    check_registration()
    check_closed_surface()
    check_determinism()
    check_failed_effect_restores()
    check_merge_conflict_is_refused_and_restored()
    check_tamper_fails_closed()
    check_authority_is_owner_granted(home)
    check_end_to_end_learning(home)
    print("PASS test_git_operators")


if __name__ == "__main__":
    main()
