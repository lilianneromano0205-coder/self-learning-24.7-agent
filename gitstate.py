"""Git repository state — the fourth world of the Semantic Operator Runtime.

docs/DESIGN-P5-git-operators.md names the rules this module enforces:

  - one CLOSED VERB per mutation (init, commit, branch, switch, merge, tag)
    — no network, no history rewriting, no raw passthrough. argv is built
    structurally from screened data: no shell, no model-authored flag;
  - every mutation declares observable ASSERTIONS that are re-observed
    afterwards; a false one RESTORES the pre-verb state and refuses. A
    merge conflict is a deterministic refusal with the merge aborted;
  - DETERMINISM: author, committer and time are pinned, signing is off,
    line endings and symlinks are literal, configuration is isolated — so
    the same bytes and the same verbs yield byte-identical commit hashes;
  - the repository is NOT TRUSTED: .git/ sits in the workspace where a
    worker's write_file can reach. Before every operation .git/config must
    equal the canonical configuration this adapter wrote and .git/hooks
    must be absent or empty, else the operation refuses — fail closed.
    Every invocation also overrides the execution vectors git itself
    offers (hooksPath, fsmonitor, protocol.allow) and pins GIT_DIR and
    GIT_WORK_TREE so no command can discover a parent repository.

Tool-name mapping (the design's dotted names, as worker tools):
  git.op + git.assert  ->  git_op     (one verb + assertions; restore on failure)
  git.observe          ->  git_query  (status / log / show / branches)

Authority: mutating a repository requires the owner-granted token
"git-write:<relative-path>" (settings.toml [agent] git_write, default
empty — fail closed). Reading is workspace read.
"""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile

MAX_ASSERTIONS = 32
MAX_PATHS = 64
MAX_MESSAGE = 2000
MAX_TEXT = 200_000
MAX_LOG = 100
TIMEOUT_SECONDS = 120

VERBS = ("init", "commit", "branch", "switch", "merge", "tag")
QUERIES = ("status", "log", "show", "branches")
ASSERTIONS = ("branch_exists", "branch_absent", "tag_exists", "head_is",
              "ancestor", "file_at_ref", "clean_worktree", "rev_count")

_VERB_KEYS = {"init": set(), "commit": {"paths", "message"},
              "branch": {"name"}, "switch": {"name"}, "merge": {"name"},
              "tag": {"name"}}
_QUERY_KEYS = {"status": set(), "log": {"max"}, "show": {"ref", "path"},
               "branches": set()}
_ASSERTION_KEYS = {"branch_exists": {"name"}, "branch_absent": {"name"},
                   "tag_exists": {"name"}, "head_is": {"name"},
                   "ancestor": {"ancestor", "descendant"},
                   "file_at_ref": {"ref", "path"},   # + exactly one of sha256 | text
                   "clean_worktree": set(), "rev_count": {"ref", "equals"}}

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_REF_RE = re.compile(r"^(?:HEAD|[0-9a-f]{7,40}|[A-Za-z0-9][A-Za-z0-9._-]{0,80})$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# pinned identity and time: commit hashes become a pure function of content
# and history, which is what lets a replayed procedure be checked byte for
# byte against its earlier self
IDENTITY = {"GIT_AUTHOR_NAME": "agent", "GIT_AUTHOR_EMAIL": "agent@local",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000",
            "GIT_COMMITTER_NAME": "agent", "GIT_COMMITTER_EMAIL": "agent@local",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000"}

# what .git/config must be, byte for byte, in every repository this adapter
# operates — anything else is a control file the adapter did not write
CANONICAL_CONFIG = ("[core]\n"
                    "\trepositoryformatversion = 0\n"
                    "\tfilemode = false\n"
                    "\tbare = false\n"
                    "\tlogallrefupdates = true\n"
                    "\tautocrlf = false\n"
                    "\tsymlinks = false\n")


def _fail(why):
    raise ValueError(f"git state: {why}")


# ------------------------------------------------------------- screening

def _name(value, what):
    if not isinstance(value, str) or not _NAME_RE.match(value) or \
            value == "HEAD" or ".." in value or value.endswith(".") or \
            value.endswith(".lock"):
        _fail(f"{what} {value!r} is not an acceptable ref name "
              f"([A-Za-z0-9][A-Za-z0-9._-]*, no '..', never HEAD)")
    return value


def _ref(value, what):
    if not isinstance(value, str) or not _REF_RE.match(value) or \
            ".." in value or value.endswith(".lock"):
        _fail(f"{what} {value!r} is not an acceptable ref (a screened name, "
              f"HEAD, or an abbreviated commit hash)")
    return value


def _path(value):
    if not isinstance(value, str) or not value or len(value) > 240:
        _fail("commit paths must be non-empty relative strings")
    normalized = value.replace("\\", "/")
    if normalized.startswith(("/", "-")) or (len(normalized) > 1 and normalized[1] == ":"):
        _fail(f"commit path {value!r} must be relative to the repository")
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        _fail(f"commit path {value!r} may not contain empty, '.' or '..' components")
    if any(part.lower() == ".git" for part in parts):
        _fail(f"commit path {value!r} reaches into .git — control files are "
              f"never worker content")
    return normalized


def _message(value):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_MESSAGE:
        _fail(f"commit message must be non-empty text of at most {MAX_MESSAGE} chars")
    return value


def _dict(text, what):
    try:
        value = json.loads(text) if isinstance(text, str) else None
    except ValueError as exc:
        _fail(f"{what} is not valid JSON ({exc})")
    if not isinstance(value, dict):
        _fail(f"{what} must be a JSON object")
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def canonical_op(text):
    """{verb, ...} -> one canonical JSON string, fully screened."""
    op = _dict(text, "op")
    verb = op.get("verb")
    if verb not in VERBS:
        _fail(f"unknown verb {verb!r}: the closed set is {', '.join(VERBS)} — "
              f"no network, no history rewriting, no passthrough")
    if set(op) != {"verb"} | _VERB_KEYS[verb]:
        _fail(f"verb {verb} takes exactly {sorted(_VERB_KEYS[verb])}")
    out = {"verb": verb}
    if verb == "commit":
        paths = op["paths"]
        if not isinstance(paths, list) or not paths or len(paths) > MAX_PATHS:
            _fail(f"commit paths must be a list of 1..{MAX_PATHS} entries")
        out["paths"] = sorted({_path(p) for p in paths})
        out["message"] = _message(op["message"])
    elif verb in ("branch", "switch", "merge", "tag"):
        out["name"] = _name(op["name"], f"{verb} name")
    return _canonical(out)


def canonical_assertions(text):
    """[{kind, ...}] -> canonical JSON. Every assertion is a read-only
    observation of repository state; a mutation with none is not gated."""
    try:
        assertions = json.loads(text) if isinstance(text, str) else None
    except ValueError as exc:
        _fail(f"assertions are not valid JSON ({exc})")
    if not isinstance(assertions, list) or not assertions or \
            len(assertions) > MAX_ASSERTIONS:
        _fail(f"assertions must be a list of 1..{MAX_ASSERTIONS} entries — "
              f"a mutation with no declared observable effect is not gated")
    out = []
    for entry in assertions:
        if not isinstance(entry, dict) or entry.get("kind") not in ASSERTIONS:
            _fail(f"each assertion is {{kind, ...}} with kind in "
                  f"{', '.join(ASSERTIONS)}")
        kind = entry["kind"]
        keys = set(entry) - {"kind"}
        item = {"kind": kind}
        if kind == "file_at_ref":
            if keys - {"ref", "path", "sha256", "text"} or \
                    not {"ref", "path"} <= keys or \
                    len(keys & {"sha256", "text"}) != 1:
                _fail("file_at_ref takes ref, path and exactly one of "
                      "sha256 (exact bytes) or text (newline-normalized)")
            item["ref"] = _ref(entry["ref"], "file_at_ref ref")
            item["path"] = _path(entry["path"])
            if "sha256" in entry:
                if not isinstance(entry["sha256"], str) or \
                        not _SHA256_RE.match(entry["sha256"]):
                    _fail("file_at_ref sha256 must be 64 lowercase hex chars")
                item["sha256"] = entry["sha256"]
            else:
                if not isinstance(entry["text"], str) or len(entry["text"]) > MAX_TEXT:
                    _fail(f"file_at_ref text must be a string of at most {MAX_TEXT} chars")
                item["text"] = entry["text"].replace("\r\n", "\n")
        elif keys != _ASSERTION_KEYS[kind]:
            _fail(f"{kind} takes exactly {sorted(_ASSERTION_KEYS[kind])}")
        elif kind in ("branch_exists", "branch_absent", "tag_exists", "head_is"):
            item["name"] = _name(entry["name"], f"{kind} name")
        elif kind == "ancestor":
            item["ancestor"] = _ref(entry["ancestor"], "ancestor")
            item["descendant"] = _ref(entry["descendant"], "descendant")
        elif kind == "rev_count":
            item["ref"] = _ref(entry["ref"], "rev_count ref")
            if type(entry["equals"]) is not int or entry["equals"] < 0:
                _fail("rev_count equals must be a non-negative integer")
            item["equals"] = entry["equals"]
        out.append(item)
    return _canonical(out)


def canonical_query(text):
    q = _dict(text, "query")
    kind = q.get("kind")
    if kind not in QUERIES:
        _fail(f"unknown query {kind!r}: the closed set is {', '.join(QUERIES)}")
    if set(q) - {"kind"} - _QUERY_KEYS[kind]:
        _fail(f"query {kind} takes at most {sorted(_QUERY_KEYS[kind])}")
    out = {"kind": kind}
    if kind == "log":
        limit = q.get("max", 20)
        if type(limit) is not int or not 1 <= limit <= MAX_LOG:
            _fail(f"log max must be 1..{MAX_LOG}")
        out["max"] = limit
    elif kind == "show":
        if not {"ref", "path"} <= set(q):
            _fail("show takes ref and path")
        out["ref"] = _ref(q["ref"], "show ref")
        out["path"] = _path(q["path"])
    return _canonical(out)


# ------------------------------------------------------------ invocation

_ISOLATION = None


def _isolation():
    """A directory the worker cannot reach: the empty hooks path every
    invocation is pointed at, the empty template init copies from, an empty
    config file standing in for global/system config, and a HOME."""
    global _ISOLATION
    if _ISOLATION is None or not os.path.isdir(_ISOLATION):
        base = tempfile.mkdtemp(prefix="gitstate-isolation-")
        for sub in ("hooks", "template", "home"):
            os.makedirs(os.path.join(base, sub), exist_ok=True)
        with open(os.path.join(base, "no-config"), "wb") as f:
            f.write(b"")
        _ISOLATION = base
    return _ISOLATION


def _env(repo):
    iso = _isolation()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(IDENTITY)
    env.update({"GIT_CONFIG_GLOBAL": os.path.join(iso, "no-config"),
                "GIT_CONFIG_SYSTEM": os.path.join(iso, "no-config"),
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                "GIT_PAGER": "cat", "GIT_EDITOR": ":", "GIT_OPTIONAL_LOCKS": "0",
                "HOME": os.path.join(iso, "home"),
                "XDG_CONFIG_HOME": os.path.join(iso, "home"),
                "LC_ALL": "C", "LANG": "C", "TZ": "UTC"})
    if repo is not None:
        env["GIT_DIR"] = os.path.join(repo, ".git")
        env["GIT_WORK_TREE"] = repo
    return env


def _git(args, repo=None, cwd=None, binary=False, check=True):
    exe = shutil.which("git")
    if not exe:
        _fail("git is not available on this host; the adapter fails closed")
    iso = _isolation()
    argv = [exe,
            "-c", "core.hooksPath=" + os.path.join(iso, "hooks"),
            "-c", "core.fsmonitor=false", "-c", "gc.auto=0",
            "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
            "-c", "protocol.allow=never", "-c", "core.autocrlf=false",
            "-c", "core.symlinks=false", "-c", "core.filemode=false",
            "-c", "init.defaultBranch=main", "-c", "core.pager=cat",
            "-c", "advice.detachedHead=false", *args]
    try:
        result = subprocess.run(
            argv, cwd=cwd or repo, env=_env(repo), capture_output=True,
            timeout=TIMEOUT_SECONDS, **({} if binary else
                                        {"text": True, "encoding": "utf-8",
                                         "errors": "replace"}))
    except subprocess.TimeoutExpired:
        _fail(f"git {args[0]} exceeded {TIMEOUT_SECONDS}s")
    except OSError as exc:
        _fail(f"git could not be invoked: {exc}")
    if check and result.returncode != 0:
        noise = result.stderr if isinstance(result.stderr, str) else \
            result.stderr.decode("utf-8", "replace")
        noise = " ".join((noise or (result.stdout if isinstance(result.stdout, str)
                                    else "")).split())[:300]
        _fail(f"git {args[0]} failed: {noise or 'no diagnostic'}")
    return result


# ----------------------------------------------------------- integrity

def is_repository(repo):
    return os.path.isdir(os.path.join(repo, ".git")) and \
        os.path.isfile(os.path.join(repo, ".git", "config"))


def _verify(repo):
    """The repository's control files, checked against what this adapter
    wrote. .git/ is inside the workspace, so a worker can write there — a
    hook, a fsmonitor command or a filter driver would be code the adapter
    never authored, run under the harness's own authority. Refuse."""
    if not os.path.isdir(repo) or os.path.islink(repo):
        _fail(f"{os.path.basename(repo) or repo!r} is not a repository directory")
    gitdir = os.path.join(repo, ".git")
    if os.path.islink(gitdir) or not os.path.isdir(gitdir):
        _fail("not a repository this adapter initialized (no .git directory)")
    config = os.path.join(gitdir, "config")
    current = None
    if os.path.isfile(config) and not os.path.islink(config):
        with open(config, "rb") as f:
            current = f.read()
    if current != CANONICAL_CONFIG.encode("utf-8"):
        _fail("repository control files were tampered: .git/config differs "
              "from the adapter's canonical configuration — fail closed")
    hooks = os.path.join(gitdir, "hooks")
    if os.path.lexists(hooks) and (os.path.islink(hooks) or
                                   not os.path.isdir(hooks) or os.listdir(hooks)):
        _fail("repository control files were tampered: .git/hooks is not "
              "empty — a hook is code the adapter never wrote, fail closed")


def _head_branch(repo):
    result = _git(["symbolic-ref", "-q", "--short", "HEAD"], repo=repo, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _rev(repo, ref):
    result = _git(["rev-parse", "-q", "--verify", ref + "^{commit}"],
                  repo=repo, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _ref_exists(repo, full):
    return _git(["show-ref", "--verify", "--quiet", full], repo=repo,
                check=False).returncode == 0


def _tracked_dirty(repo):
    return _git(["status", "--porcelain", "--untracked-files=no"],
                repo=repo).stdout.strip()


def state_digest(repo):
    """One digest over every ref and the symbolic HEAD — the before/after
    evidence a trajectory records for a repository, the way it records a
    file's hash. None for a non-repository; 'tampered' when the control
    files fail verification, so the record says so instead of guessing."""
    if not is_repository(repo):
        return None
    try:
        _verify(repo)
    except ValueError:
        return "tampered"
    refs = _git(["for-each-ref", "--format=%(refname)%00%(objectname)"],
                repo=repo).stdout
    head = _git(["symbolic-ref", "-q", "HEAD"], repo=repo, check=False)
    marker = head.stdout.strip() if head.returncode == 0 else \
        "detached:" + (_rev(repo, "HEAD") or "")
    return hashlib.sha256((refs + "\n" + marker).encode("utf-8")).hexdigest()


# ---------------------------------------------------------- observation

def _observe(repo, assertion):
    kind = assertion["kind"]
    if kind == "branch_exists":
        present = _ref_exists(repo, "refs/heads/" + assertion["name"])
        return present, "present" if present else "absent"
    if kind == "branch_absent":
        present = _ref_exists(repo, "refs/heads/" + assertion["name"])
        return not present, "present" if present else "absent"
    if kind == "tag_exists":
        present = _ref_exists(repo, "refs/tags/" + assertion["name"])
        return present, "present" if present else "absent"
    if kind == "head_is":
        head = _head_branch(repo)
        return head == assertion["name"], head or "detached"
    if kind == "ancestor":
        result = _git(["merge-base", "--is-ancestor", assertion["ancestor"],
                       assertion["descendant"]], repo=repo, check=False)
        return result.returncode == 0, {0: "yes", 1: "no"}.get(
            result.returncode, "unresolvable")
    if kind == "file_at_ref":
        result = _git(["cat-file", "blob", f"{assertion['ref']}:{assertion['path']}"],
                      repo=repo, binary=True, check=False)
        if result.returncode != 0:
            return False, "missing"
        if "sha256" in assertion:
            got = hashlib.sha256(result.stdout).hexdigest()
            return got == assertion["sha256"], got
        got = result.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        return got == assertion["text"], got[:80]
    if kind == "clean_worktree":
        dirty = _tracked_dirty(repo)
        return not dirty, dirty.splitlines()[0] if dirty else "clean"
    if kind == "rev_count":
        result = _git(["rev-list", "--count", assertion["ref"]], repo=repo,
                      check=False)
        if result.returncode != 0:
            return False, "unresolvable"
        got = int(result.stdout.strip() or 0)
        return got == assertion["equals"], str(got)
    _fail(f"unknown assertion {kind!r}")


def check_assertions(repo, assertions_text):
    """Re-observe every assertion read-only. -> (ok, first_mismatch_or_'')."""
    assertions = json.loads(canonical_assertions(assertions_text))
    _verify(repo)
    for assertion in assertions:
        ok, got = _observe(repo, assertion)
        if not ok:
            return False, (f"assertion {_canonical(assertion)[:120]} "
                           f"observed {got!r}")
    return True, ""


def query(repo, query_text):
    """Read-only observation. -> JSON-serializable value."""
    q = json.loads(canonical_query(query_text))
    _verify(repo)
    if q["kind"] == "status":
        lines = _git(["status", "--porcelain"], repo=repo).stdout.splitlines()
        return {"branch": _head_branch(repo), "head": _rev(repo, "HEAD"),
                "clean_tracked": not _tracked_dirty(repo),
                "entries": lines[:500]}
    if q["kind"] == "log":
        result = _git(["log", "--format=%H%x1f%s", "-n", str(q["max"])],
                      repo=repo, check=False)
        if result.returncode != 0:
            return []
        return [line.split("\x1f", 1) for line in result.stdout.splitlines() if line]
    if q["kind"] == "show":
        result = _git(["cat-file", "blob", f"{q['ref']}:{q['path']}"],
                      repo=repo, binary=True, check=False)
        if result.returncode != 0:
            _fail(f"{q['path']} does not exist at {q['ref']}")
        return result.stdout.decode("utf-8", "replace")[:100_000]
    heads = _git(["for-each-ref", "--format=%(refname:short)", "refs/heads"],
                 repo=repo).stdout.split()
    return {"branches": sorted(heads), "current": _head_branch(repo)}


# ------------------------------------------------------------- mutation

def _rmtree(path):
    for base, dirs, files in os.walk(path):
        for name in dirs + files:
            try:
                os.chmod(os.path.join(base, name), stat.S_IWRITE | stat.S_IREAD |
                         stat.S_IEXEC)
            except OSError:
                pass
    shutil.rmtree(path)


def _init(repo):
    gitdir = os.path.join(repo, ".git")
    if os.path.lexists(gitdir):
        _fail("init refuses: a .git entry already exists here")
    if os.path.lexists(repo) and not os.path.isdir(repo):
        _fail("init refuses: the target exists and is not a directory")
    created = not os.path.isdir(repo)
    os.makedirs(repo, exist_ok=True)
    _git(["init", "-q", "--template=" + os.path.join(_isolation(), "template"),
          repo], repo=None, cwd=repo)
    with open(os.path.join(gitdir, "config"), "wb") as f:
        f.write(CANONICAL_CONFIG.encode("utf-8"))
    hooks = os.path.join(gitdir, "hooks")
    if os.path.isdir(hooks) and not os.listdir(hooks):
        os.rmdir(hooks)
    _verify(repo)

    def undo():
        _rmtree(gitdir)
        if created and not os.listdir(repo):
            os.rmdir(repo)
    return undo


def _commit(repo, op):
    for rel in op["paths"]:
        full = os.path.join(repo, *rel.split("/"))
        if not os.path.isfile(full) or os.path.islink(full):
            _fail(f"commit path {rel!r} is not a regular file in the repository")
    branch = _head_branch(repo)
    if branch is None:
        _fail("HEAD is detached; the adapter only commits on a branch")
    before = _rev(repo, "HEAD")

    def undo():
        if before:
            _git(["reset", "-q", "--mixed", before], repo=repo)
        else:
            if _rev(repo, "HEAD"):
                _git(["update-ref", "-d", "refs/heads/" + branch], repo=repo)
            _git(["reset", "-q"], repo=repo, check=False)
    _git(["add", "--", *op["paths"]], repo=repo)
    result = _git(["commit", "-q", "-m", op["message"]], repo=repo, check=False)
    if result.returncode != 0:
        undo()
        noise = " ".join(((result.stdout or "") + " " + (result.stderr or "")).split())
        _fail(f"commit refused — repository restored: {noise[:300]}")
    return undo


def _branch(repo, op):
    if _ref_exists(repo, "refs/heads/" + op["name"]):
        _fail(f"branch {op['name']!r} already exists")
    if _rev(repo, "HEAD") is None:
        _fail("branch refuses: no commit yet on this repository")
    _git(["branch", op["name"]], repo=repo)
    return lambda: _git(["branch", "-D", op["name"]], repo=repo)


def _switch(repo, op):
    if not _ref_exists(repo, "refs/heads/" + op["name"]):
        _fail(f"branch {op['name']!r} does not exist; switch creates nothing")
    previous = _head_branch(repo)
    if previous is None:
        _fail("HEAD is detached; the adapter only switches between branches")
    _git(["switch", "-q", op["name"]], repo=repo)
    return lambda: _git(["switch", "-q", previous], repo=repo)


def _merge(repo, op):
    before = _rev(repo, "HEAD")
    if before is None or _head_branch(repo) is None:
        _fail("merge refuses: HEAD must be a branch with at least one commit")
    if not _ref_exists(repo, "refs/heads/" + op["name"]):
        _fail(f"branch {op['name']!r} does not exist")
    if _tracked_dirty(repo):
        _fail("merge refuses: the tracked worktree must be clean so a failed "
              "merge can be restored exactly")
    result = _git(["merge", "-q", "--no-edit", "-m", "merge " + op["name"],
                   op["name"]], repo=repo, check=False)
    if result.returncode != 0:
        if os.path.exists(os.path.join(repo, ".git", "MERGE_HEAD")):
            _git(["merge", "--abort"], repo=repo, check=False)
        _git(["reset", "-q", "--hard", before], repo=repo)
        noise = " ".join(((result.stdout or "") + " " + (result.stderr or "")).split())
        _fail(f"merge conflict — aborted, repository restored: {noise[:300]}")
    return lambda: _git(["reset", "-q", "--hard", before], repo=repo)


def _tag(repo, op):
    if _ref_exists(repo, "refs/tags/" + op["name"]):
        _fail(f"tag {op['name']!r} already exists")
    if _rev(repo, "HEAD") is None:
        _fail("tag refuses: no commit yet on this repository")
    _git(["tag", op["name"]], repo=repo)
    return lambda: _git(["tag", "-d", op["name"]], repo=repo)


_MUTATORS = {"commit": _commit, "branch": _branch, "switch": _switch,
             "merge": _merge, "tag": _tag}


def apply_op(repo, op_text, assertions_text):
    """Execute ONE verb; every declared assertion must observe true
    afterwards, else the pre-verb state is restored and this raises. The
    repository is either in the asserted state or as it was — never between.
    -> receipt {verb, head, branch, state}."""
    op = json.loads(canonical_op(op_text))
    assertions = json.loads(canonical_assertions(assertions_text))
    if op["verb"] == "init":
        undo = _init(repo)
    else:
        _verify(repo)
        undo = _MUTATORS[op["verb"]](repo, op)
    for assertion in assertions:
        ok, got = _observe(repo, assertion)
        if not ok:
            try:
                undo()
            except ValueError as exc:
                _fail(f"effect did not hold AND restore failed: "
                      f"{_canonical(assertion)[:120]} observed {got!r}; {exc}")
            _fail(f"effect did not hold — repository restored: "
                  f"{_canonical(assertion)[:120]} observed {got!r}")
    return {"verb": op["verb"], "head": _rev(repo, "HEAD"),
            "branch": _head_branch(repo), "state": state_digest(repo)}
