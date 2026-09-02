# DESIGN — Phase 5: Git semantic operators

**Branch:** `phase5/git-operators` · **Status:** BUILT — the preregistered
benchmark below is `tests/test_git_operators.py` in the acceptance suite;
all eight properties hold (first run: identical commit `381e342a…` in two
arenas; `procedure_compiled` from two gated trajectories; PROVEN on a
sealed fresh suite with an empty-note edge case; `procedure_route` with
`model_calls: 0` under an independent `git` gate). Implementation:
`gitstate.py`, `repo_satisfies` in `operators.py`, the `git_op` leaf
through `procedure.py`, the `git_op`/`git_query` tool pair in `loop.py`,
`[agent] git_write` in `settings.toml`. · **Contract:**
[VISION_CONTRACT.md](../VISION_CONTRACT.md) binds every decision. ·
**Audit order:** the 2026-09-02 checkpoint audit names the operator-universe
expansion order after Phase 4 — *"1. Git semantic operators — because
software has excellent mechanical tests"* — and requires every phase to
answer *what measurable capability does this add* and *what benchmark must
improve before this becomes permanent*. Both answers are below.

## The problem, stated from evidence

The runtime has three deterministic state worlds — files (`write_file`,
`copy_file`), typed tables (`transform_table`) and gated SQLite
(`db_transaction`). Repository work has none: today a worker can only
touch a git repository through `run_command`, which is model-authored shell
— a model step, never a deterministic leaf, so no repeated repository
workflow can ever compile into a procedure, and no gate can observe
repository state except by running more shell. The capability graph counts
"repo maintenance" among the LEARN-001 families the thesis must eventually
cover, and the audit's own list of what induction still cannot learn
includes *Git workflows*.

## What Phase 5 builds — measurable capability

**`gitstate.py`** — the fourth state world: a trusted deterministic Git
adapter whose every mutation is one closed verb with declared, observable
post-state assertions, restored on failure; plus `repo_satisfies`, the
predicate that lets any gate, suite or procedure effect observe a
repository the way `db_satisfies_all` observes a database.

The capability it adds, in one sentence: **a repeated repository workflow
can now become a proven procedure and replay with zero model calls, judged
by the task's own gate** — which the benchmark below must demonstrate end
to end before merge.

### The closed verb set (one verb per `git_op` call)

```
init                       create an empty repository (default branch main)
commit  {paths, message}   stage exactly these paths, commit them
branch  {name}             create a branch at HEAD
switch  {name}             check out an existing branch
merge   {name}             merge a branch into the current one
tag     {name}             lightweight tag at HEAD
```

There is deliberately no `push`, `pull`, `fetch`, `clone`, `remote`,
`submodule`, `rebase`, `reset`, `filter-branch` or raw passthrough. Network
verbs would make every result depend on a world the adapter cannot
re-observe; history rewriting would make "what happened" unrecoverable.
The verb set is data — the adapter builds `argv` structurally and never
passes a shell or a model-authored flag. Names are screened
(`[A-Za-z0-9][A-Za-z0-9._-]{0,80}`, never `HEAD`, never a leading `-`),
paths are relative, contained, and may not contain a `.git` component.

### Determinism, made exact

Commit identity depends on author, committer and time. The adapter pins all
of them (`agent <agent@local>`, `2000-01-01T00:00:00+0000`), disables
signing, pins `core.autocrlf=false`, `core.symlinks=false`,
`core.filemode=false`, and isolates configuration (global and system
config redirected to an empty file the adapter owns, `HOME` and
`XDG_CONFIG_HOME` likewise, every ambient `GIT_*` variable dropped). So the
same file bytes and the same verb sequence yield **byte-identical commit
hashes** in two different arenas — property 1 below. Merge commits carry a
fixed message for the same reason.

### Assertions (the closed observation language)

```
branch_exists / branch_absent {name}
tag_exists {name}
head_is {name}                       HEAD is the symbolic ref of this branch
ancestor {ancestor, descendant}      merge-base --is-ancestor
file_at_ref {ref, path, sha256}      exact bytes of the blob
file_at_ref {ref, path, text}        utf-8 text, line endings normalized to \n
clean_worktree                       no tracked change staged or unstaged
rev_count {ref, equals}              rev-list --count
```

Every one is a read-only plumbing observation. A mutation with no declared
assertion refuses — the same rule as `db_transaction`. After the verb, the
assertions are re-observed; any false one **restores the pre-verb state**
(commit: branch and index reset to the previous head, files untouched;
merge: the pre-merge head restored, which is safe because merge requires a
clean tracked worktree; branch/tag: the created ref deleted; switch: back to
the previous branch; init: the created `.git` removed) and raises. A merge
conflict is a deterministic refusal with the merge aborted.

### The repository is not trusted either

`.git/` sits inside the workspace, where a worker's `write_file` can reach.
A planted hook, a `core.fsmonitor` command, a filter driver in
`.git/config` would run arbitrary code the moment the adapter invoked git.
So before every operation the adapter verifies the repository's control
files against what it wrote: `.git/config` must equal the adapter's
canonical configuration byte for byte and `.git/hooks` must be absent or
empty — anything else is a **tamper refusal, fail closed** (property 5).
Belt and braces: every invocation also overrides `core.hooksPath` to an
empty directory the worker cannot reach, `core.fsmonitor=false`,
`protocol.allow=never`, `gc.auto=0`, and pins `GIT_DIR`/`GIT_WORK_TREE` so
no command can discover a parent repository.

### Authority

Mutating a repository needs the owner-granted token `git-write:<path>`
(`settings.toml [agent] git_write`, default empty — fail closed), demanded
per leaf at bind time in V2 procedures and derived from bound steps in V1,
exactly as `db-write:` is. Reading (`git_query`: status, log, show,
branches) is workspace read. A sealed suite carries the scoped tokens its
arenas need, as it already does for databases.

### Wiring (each a one-line extension of an existing seam)

- `operators.py` — `repo_satisfies {path, assertions}` in
  `validate_predicate` and `observe` (handled before the file check: a
  repository is a directory).
- `procedure.py` — `git_op` joins `DETERMINISTIC_TOOLS`; `_normalize`
  canonicalizes op/assertions; `_snapshot` records repository existence
  and a digest of every ref (before/after evidence); `finish_action`
  re-observes the assertions independently of the tool's own gate;
  `_perform` executes; `_compile_aligned` emits a `repo_satisfies` effect
  (no file-existence guard on a directory target — repository verbs carry
  their own state discipline, and git targets do not offer IF guards);
  `_run_leaf` and the V1 walk demand `git-write:`.
- `loop.py` — two tool definitions and handlers with capture hooks; the
  deterministic route grants `git-write:` for every repository in
  `[agent] git_write`.
- `signatures.py` — unchanged: `git_op` is one more operator leaf, so
  structural identity already separates repository procedures.

## Benchmark (exit criterion, preregistered before build)

`tests/test_git_operators.py` — the benchmark that must pass before this
phase becomes permanent:

1. **Determinism:** the same verb sequence over the same bytes in two
   separate arenas yields byte-identical commit hashes; an assertion
   cannot pass with an approximate or partial observation.
2. **Closed surface:** an unknown verb (`push`), a network-shaped verb, an
   unscreened name (`-rf`, `a..b`, `HEAD`), a path with a `.git`
   component, an empty assertion list and an unknown assertion kind all
   refuse with the reason, before any side effect.
3. **Restore on failed effect:** a commit whose declared assertion does not
   hold leaves HEAD, refs and the worktree exactly as before; the refusal
   names the assertion.
4. **Deterministic conflict refusal:** a merge that conflicts is aborted,
   refused by name, and the repository is restored (same HEAD, clean
   tracked worktree, no merge in progress).
5. **Tamper fails closed:** a planted `.git/hooks/pre-commit` that would
   create a sentinel, and an edited `.git/config`, each make the next
   operation refuse; the sentinel never appears.
6. **Authority is owner-granted:** a procedure with a `git_op` leaf refuses
   without `git-write:<repo>` (V2 leaf and V1 walk) and runs with it; the
   worker tool refuses any repository outside `[agent] git_write`.
7. **End to end through the learning loop:** two independently gated
   trajectories (init → write → commit → branch → tag) compile into a
   CANDIDATE, an owner-sealed suite of fresh instances (including an edge
   case) takes it to PROVEN, and a later task with a **silent** worker
   (empty provider script) completes with **zero model calls** — judged by
   its own gate, which is an independent `git` check, not the adapter.
8. No existing test weakened; `test_vision_preservation.py` untouched;
   the harness manifest, prose counts and execution audit updated to
   include the new module and tool pair.

## What this phase does NOT claim

No real-model result. Mock workers stand in for the model exactly as in
Phases 1–4; the benchmark proves the harness mechanics of a fourth state
world, not model lift. LIFT-001A and LEARN-001 remain the only door to
economic claims and still wait on a provider key. No `push`: repository
work that must reach a remote still goes through the model and the owner.

## Claim envelope (added by Phase 6.1)

The 2026-09-02 consolidated audit found that `commit` staged the declared
paths and then ran a plain `git commit`, which commits *everything*
staged; Phase 6.1 closed that with a **clean-index precondition** (a
semantic commit refuses to start from a dirty index) and a host-git
witness that the commit holds exactly the declared paths, and renamed
`state_digest` to **`ref_state_digest`** because it covers refs and HEAD
only. What the benchmark proves, and no more:

| Property | Preconditions | Excluded states | Oracle |
|---|---|---|---|
| deterministic commit | same bytes, same verbs, adapter-initialized repo | hostile concurrent mutation | commit hash in two arenas |
| exact commit | clean index (enforced) | dirty index (refused) | host `git show --name-only` |
| restore on failed effect | clean index, adapter-initialized repo | process kill mid-verb | HEAD/refs/index/worktree via host git |
| conflict refusal | clean tracked worktree (enforced) | — | host git: no `MERGE_HEAD`, same HEAD |
| tamper fail-closed | control files as the adapter wrote them | a tamper mimicking the canonical bytes exactly | refusal before any git invocation |
