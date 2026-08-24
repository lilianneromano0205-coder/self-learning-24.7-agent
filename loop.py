#!/usr/bin/env python3
"""Persistent autonomous agent loop (v4 master build document, Part 5).

The tick:
  load state -> take running task else next queued (honoring course locks)
  -> assemble context -> call model -> parse ONE tool call -> execute
  -> append step -> persist (atomically) -> repeat until finish_task.

State is persisted after every single step, so a `kill -9` at any moment
loses at most the in-flight step, which re-runs on restart (at-least-once
semantics: tool actions must be idempotent).

Usage:
  python loop.py run [--drain] [--root DIR]
  python loop.py add --role R --goal "..." [--course NAME] [--memory FILE ...] [--root DIR]
  python loop.py status [--root DIR]
"""

import argparse
import datetime
import hashlib
import json
import logging
import os
import platform
import re
import subprocess
import sys
import time
import tomllib
import traceback
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context
import prospective
import skills as skillgraph
from logging.handlers import RotatingFileHandler

# ---------------------------------------------------------------- constants

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file and return its content.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file, creating parent directories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command with a hard timeout. Returns exit code, stdout, stderr.",
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string"}},
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_task",
            "description": "Mark the current task as done, with a condensed 1-2k token summary "
                           "of what was accomplished. Everything worth keeping must already be on disk.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_human",
            "description": (
                "Ask the human a question. The question is appended to blocked.md, "
                "the task is marked blocked, and the agent moves on to the next "
                "queued task. Never wait idle for a human."
            ),
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
]

TOOL_NAMES = {t["function"]["name"] for t in TOOL_DEFS}


def stop_text(stop):
    """Render a task's stop condition for context and the panel."""
    if not stop:
        return "none declared (harness defaults apply)"
    parts = []
    if stop.get("criteria"):
        parts.append(f"done when: {stop['criteria']}")
    if stop.get("max_attempts"):
        parts.append(f"max attempts {stop['max_attempts']}")
    if stop.get("deadline"):
        parts.append(f"deadline {stop['deadline']}")
    if stop.get("max_steps"):
        parts.append(f"max steps {stop['max_steps']}")
    return " | ".join(parts) or "none declared"
MAX_TOOL_RESULT_CHARS = 40_000
# tool outputs longer than this are cleared out of the window at compaction
# time (the verbatim bytes stay in the archive) -- Anthropic's tool-result
# clearing: a summarizer must not spend its window re-reading raw payloads
CLEAR_TOOL_RESULT_CHARS = 1_500
# how long a capability-routing decision may be reused inside one process
ROUTE_TTL_SECONDS = 600
STEP_TRUNC = 300  # per-step record truncation in state.json


# ---------------------------------------------------------------- utilities

def atomic_write_json(path, data):
    """Write via temp file + rename so a crash leaves old state or new state,
    never a torn file. On Windows the rename can transiently fail with
    PermissionError while a sync client (OneDrive), antivirus, or an editor
    holds the file open — retry briefly rather than losing the write."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.05 * (attempt + 1))


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def est_tokens(messages):
    """Rough token estimate: ~4 chars per token."""
    return sum(len(json.dumps(m, ensure_ascii=False)) for m in messages) // 4


def safe_course(name):
    """A course name is used as a PATH component by five harness writers
    (gotchas, candidates, conflicts, curriculum, the course lock), none of
    which passes through _safe_path. Sanitise once, where a course enters."""
    if not name:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:64]
    return slug or "course"


def truncate(text, limit=MAX_TOOL_RESULT_CHARS):
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated, {len(text) - limit} chars omitted]"


def parse_content_tool_call(content):
    """Fallback parser: a tool call embedded as JSON in the message text,
    per the grounding header: {"tool": "...", "args": {...}}."""
    if not content:
        return None
    s, e = content.find("{"), content.rfind("}")
    if s == -1 or e <= s:
        return None
    try:
        obj = json.loads(content[s:e + 1])
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and isinstance(obj.get("tool"), str):
        return {
            "id": "json_inline",
            "type": "function",
            "function": {
                "name": obj["tool"],
                "arguments": json.dumps(obj.get("args", {})),
            },
        }
    return None


def permanent_net_error(exc):
    """True when a network failure cannot possibly succeed on retry.

    Connection refused, an unknown host and a failed certificate check are
    verdicts, not weather. Timeouts, resets and temporary DNS failures are
    weather, and those still get the full backoff.
    """
    import socket
    import ssl
    seen, e = set(), exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, (ConnectionRefusedError, ssl.SSLCertVerificationError)):
            return True
        if isinstance(e, socket.gaierror):
            # EAI_AGAIN is a temporary resolver failure; everything else here
            # means the name does not resolve
            return getattr(e, "errno", None) != getattr(socket, "EAI_AGAIN", -3)
        if isinstance(e, ValueError):        # malformed URL, unknown scheme
            return True
        e = getattr(e, "reason", None) if not isinstance(
            getattr(e, "reason", None), str) else None
    return False


def n_steps(task):
    steps = task.get("steps", [])
    return len(steps) if isinstance(steps, list) else int(steps)


# ---------------------------------------------------------------- the agent

class Agent:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        # identifies THIS loop process for the whole of its life, so a task
        # can record who is working on it and a sibling loop can tell a live
        # owner from a dead one (see _may_resume)
        self.runner_id = f"{os.getpid()}:{uuid.uuid4().hex[:12]}"
        self._load_env_file()
        with open(os.path.join(self.root, "settings.toml"), "rb") as f:
            self.cfg = tomllib.loads(f.read().decode("utf-8-sig"))
        a = self.cfg.get("agent", {})
        self.max_steps = a.get("max_steps", 150)
        self.command_timeout = a.get("command_timeout_seconds", 300)
        self.model_timeout = a.get("model_timeout_seconds", 180)
        self.poll_interval = a.get("poll_interval_seconds", 10)
        self.ctx_threshold = a.get("context_token_threshold", 50_000)
        self.ctx_keep_recent = a.get("context_keep_recent_messages", 10)
        self.max_malformed = a.get("max_malformed_tool_calls", 3)
        self.lock_stale_minutes = a.get("lock_stale_minutes", 30)
        # Backstop only. A running task is normally protected by its owner
        # being ALIVE (see _may_resume); this timeout exists for the cases
        # liveness cannot answer — the owner ran on a different host sharing
        # this storage, or the machine rebooted and recycled the pid. It must
        # exceed the longest gap between two commits of one task, which is a
        # model call plus its whole retry ladder.
        self.runner_lease_seconds = a.get("runner_lease_seconds", 900)
        self.reflect_after = a.get("reflect_after", ["practitioner"])
        self.exam_threshold = a.get("exam_threshold", 90)
        self.reexam_days = a.get("reexam_days", [7, 30, 90])
        self.max_skills_loaded = a.get("max_skills_loaded", 3)
        self.max_task_retries = a.get("max_task_retries", 2)
        self.auto_scan_inbox = a.get("auto_scan_inbox", True)
        self.inbox_settle_seconds = a.get("inbox_settle_seconds", 10)
        self.daily_budget_usd = a.get("daily_budget_usd", 0)  # 0 = disabled
        self.max_task_usd = a.get("max_task_usd", 2.0)   # per-run ceiling, 0=off
        self.max_done_rejects = a.get("max_done_rejects", 6)
        self.escalate_after_errors = a.get("escalate_after_errors", 3)
        self.max_output_tokens = a.get("max_output_tokens", 0)  # 0 = provider default
        # 24/7 durability: the hot queue stays small forever. Finished tasks
        # beyond this many are moved to an append-only archive — nothing is
        # lost, but every step's persist stays fast no matter how long the
        # fleet has been running.
        self.retain_finished = a.get("retain_finished_tasks", 150)
        self.chain = a.get("chain", {})
        self.state_path = os.path.join(self.root, "state.json")
        self.contexts_dir = os.path.join(self.root, "contexts")
        self.logs_dir = os.path.join(self.root, "logs")
        os.makedirs(self.contexts_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)
        self.log = self._setup_logging()
        self._mock_scripts = {}

    def _load_env_file(self):
        """Load KEY=VALUE lines from <root>/agent.env into the environment
        (existing variables win). Works identically on Windows and Linux, so
        local testing needs no shell setup."""
        try:
            with open(os.path.join(self.root, "agent.env"), "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except OSError:
            pass

    def _setup_logging(self):
        log = logging.getLogger(f"agent:{self.root}")
        log.setLevel(logging.INFO)
        if not log.handlers:
            h = RotatingFileHandler(
                os.path.join(self.logs_dir, "agent.log"),
                maxBytes=5_000_000, backupCount=5, encoding="utf-8",
            )
            h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            log.addHandler(h)
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            log.addHandler(sh)
        return log

    # ------------------------------------------------------------- state

    def load_state(self):
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"tasks": []}
        except json.JSONDecodeError as e:
            # never silently discard a corrupt queue: quarantine it for forensics
            backup = self.state_path + ".corrupt-" + time.strftime("%Y%m%d-%H%M%S")
            os.replace(self.state_path, backup)
            self.log.error(json.dumps({"event": "state_corrupt", "backup": backup,
                                       "error": str(e)}))
            return {"tasks": []}

    def save_state(self, state):
        atomic_write_json(self.state_path, state)

    @contextmanager
    def _state_lock(self, timeout=20):
        """Cross-PROCESS mutex for state.json read-modify-write cycles. The
        daemon, the panel, and team runs all write the same queue; without
        this, one writer's load->save erases another's update (proven by the
        race probe: tasks lost outright). O_EXCL lockfile; a lock older than
        8s is broken as a corpse, and release verifies we still own it — a
        stalled holder must not delete the lockfile of whoever replaced it."""
        lock = self.state_path + ".mutex"
        mine = f"{os.getpid()}:{uuid.uuid4().hex}"
        start = time.time()
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, mine.encode())
                os.close(fd)
                break
            except (FileExistsError, PermissionError):
                # PermissionError: Windows delete-pending while another
                # process releases the lock — same meaning as "busy, retry"
                try:
                    # a critical section holds this lock for milliseconds;
                    # kill -9 can orphan it, so anything older than 8s is
                    # a corpse — break it well inside the acquire timeout.
                    # (No PID-liveness probe: os.kill(pid, 0) on Windows
                    # can TERMINATE the target, and PIDs get reused.)
                    if time.time() - os.path.getmtime(lock) > 8:
                        os.remove(lock)
                        continue
                except OSError:
                    pass
                if time.time() - start > timeout:
                    raise RuntimeError(f"state mutex timeout ({lock})")
                time.sleep(0.03)
        try:
            yield
        finally:
            try:
                with open(lock, "r", encoding="utf-8") as f:
                    held = f.read().strip()
                if held == mine:
                    os.remove(lock)
                # else: ours was broken as stale and another process owns the
                # mutex now — removing it would admit a third writer
            except OSError:
                pass

    def commit_task(self, task):
        """The only safe way to persist a task: under the mutex, merge THIS
        task into a fresh read of the state — concurrent writers each own
        their tasks and can no longer erase each other's."""
        # every commit is also a pulse: the lease a sibling loop reads to
        # decide this task is still owned is refreshed here, once per step,
        # so a long task never looks abandoned while it is working
        if task.get("status") == "running" and \
                isinstance(task.get("runner"), dict) and \
                task["runner"].get("id") == self.runner_id:
            task["runner"]["ts"] = time.time()
        with self._state_lock():
            state = self.load_state()
            for i, t in enumerate(state["tasks"]):
                if t["id"] == task["id"]:
                    state["tasks"][i] = task
                    break
            else:
                state["tasks"].append(task)
            self._trim_state(state)
            self.save_state(state)

    # ------------------------------------------------------- retention
    # Measured: at 1500 finished tasks, state.json reaches 3.2 MB and every
    # step costs ~185 ms just to persist — a fleet running for weeks would
    # grind to a halt. Finished work moves to an append-only archive so the
    # hot file stays small while the full history survives.

    def archive_path(self):
        return os.path.join(self.logs_dir, "tasks-archive.jsonl")

    def _trim_state(self, state):
        """Called under the mutex with the state already loaded."""
        if self.retain_finished <= 0:
            return 0
        finished = [t for t in state["tasks"]
                    if t.get("status") in ("done", "failed")]
        # a slack band avoids rewriting on every single commit
        if len(finished) <= self.retain_finished + 25:
            return 0
        drop = finished[:len(finished) - self.retain_finished]
        drop_ids = {t["id"] for t in drop}
        try:
            with open(self.archive_path(), "a", encoding="utf-8") as f:
                for t in drop:
                    f.write(json.dumps(t, ensure_ascii=False) + "\n")
        except OSError as e:
            self.log.error(json.dumps({"event": "archive_failed", "error": str(e)}))
            return 0        # never drop what could not be archived
        state["tasks"] = [t for t in state["tasks"] if t["id"] not in drop_ids]
        self._archive_contexts(drop_ids)
        self.log.info(json.dumps({"event": "state_trimmed",
                                  "archived": len(drop_ids),
                                  "remaining": len(state["tasks"])}))
        return len(drop_ids)

    def _archive_contexts(self, task_ids):
        """Move finished transcripts out of the hot directory. The verbatim
        compaction archives (*.archive.jsonl) STAY where recall.py reads
        them — context is never lost, only tidied."""
        dest = os.path.join(self.contexts_dir, "archive")
        os.makedirs(dest, exist_ok=True)
        for tid in task_ids:
            # the transcript AND its compile manifest travel together, so the
            # window a finished task was given stays inspectable forever
            for name in (f"{tid}.json", f"{tid}.compile.json"):
                src = os.path.join(self.contexts_dir, name)
                if os.path.exists(src):
                    try:
                        os.replace(src, os.path.join(dest, name))
                    except OSError:
                        pass

    def task_history(self, limit=200, task_id=None):
        """Read archived tasks back — the full record is always recoverable."""
        out = []
        try:
            with open(self.archive_path(), "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        t = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if task_id and t.get("id") != task_id:
                        continue
                    out.append(t)
        except OSError:
            return []
        return out[-limit:]

    def find_task(self, task_id):
        """A task by id, wherever it now lives — hot queue or archive."""
        for t in self.load_state()["tasks"]:
            if t["id"] == task_id:
                return t
        hits = self.task_history(limit=1, task_id=task_id)
        return hits[-1] if hits else None

    # ------------------------------------------------------ runner leases
    # A task marked "running" means one of two opposite things: a loop is
    # working on it RIGHT NOW, or a loop died holding it and it must be
    # resumed. next_task could not tell them apart, so a second loop resumed
    # a task its live sibling was still executing — walking straight past
    # claim_task, the mutex written to make claiming exactly-once, because
    # that mutex only guards the QUEUED path. Observed on a loaded Linux
    # runner: 6 tasks queued, 14 task_end events, and a phantom RETRY task
    # for work that had in fact succeeded. The distinguishing fact is
    # whether the owner is still alive, so the owner is now recorded.

    def _runner_stamp(self):
        return {"id": self.runner_id, "pid": os.getpid(),
                "host": platform.node(), "ts": time.time()}

    @staticmethod
    def _process_alive(pid):
        """Is this pid a live process on THIS machine?

        Never os.kill on Windows: CPython implements it with TerminateProcess,
        so the POSIX idiom `os.kill(pid, 0)` would not ask whether a sibling
        loop is alive — it would kill it. Anything unexpected answers True,
        because the cost of a wrong "alive" is waiting for the lease backstop
        and the cost of a wrong "dead" is two loops running one task.
        """
        if not isinstance(pid, int) or pid <= 0:
            return False
        if os.name == "nt":
            try:
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
                k = ctypes.windll.kernel32
                h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if not h:
                    # 87 ERROR_INVALID_PARAMETER: no such process. Anything
                    # else (5 ERROR_ACCESS_DENIED) means it exists.
                    return ctypes.GetLastError() != 87
                code = ctypes.c_ulong()
                ok = k.GetExitCodeProcess(h, ctypes.byref(code))
                k.CloseHandle(h)
                return (not ok) or code.value == STILL_ACTIVE
            except Exception:
                return True
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True          # alive, just not ours to signal
        except OSError:
            return True

    def _may_resume(self, task):
        """May THIS loop pick up a task already marked running?"""
        r = task.get("runner")
        if not isinstance(r, dict):
            return True          # never stamped: a crash from before this
        if r.get("id") == self.runner_id:
            return True          # our own task, resumed after a step
        if r.get("host") == platform.node():
            # On our own machine liveness is the whole answer, and the lease
            # must not get a vote: a loop parked in a twenty-minute provider
            # call has a stale timestamp and is perfectly healthy. Overtaking
            # it because a clock said so is the very double-execution this
            # exists to prevent. Dead owner, on the other hand, recovers now.
            return not self._process_alive(r.get("pid"))
        # Another host cannot be asked: its pid numbers mean nothing here, so
        # the lease is the only thing that can ever free the task.
        return (time.time() - float(r.get("ts") or 0)) > self.runner_lease_seconds

    def adopt_task(self, task_id):
        """The running-path twin of claim_task: take over an abandoned task
        atomically. Without the re-check under the mutex, two loops could
        both find the same corpse and both revive it."""
        with self._state_lock():
            state = self.load_state()
            t = next((x for x in state["tasks"] if x["id"] == task_id), None)
            if t is None or t["status"] != "running" or not self._may_resume(t):
                return None
            t["runner"] = self._runner_stamp()
            self.save_state(state)
            return t

    def claim_task(self, task_id):
        """Atomically flip one queued task to running. Returns the fresh task,
        or None if another loop claimed it first."""
        with self._state_lock():
            state = self.load_state()
            t = next((x for x in state["tasks"] if x["id"] == task_id), None)
            if t is None or t["status"] != "queued":
                return None
            t["status"] = "running"
            t["runner"] = self._runner_stamp()
            self.save_state(state)
            return t

    def add_task(self, role, goal, memory_files=None, course=None,
                 attempt=1, base_goal=None, done_check=None, lineage=None,
                 stop=None, mission=None, criterion=None):
        tid = uuid.uuid4().hex[:12]
        # every loop is defined by its STOP CONDITION (the 2026 loop
        # taxonomy): criteria the evaluator checks, a ceiling on attempts,
        # a deadline, a step ceiling — declared on the task, enforced by the
        # harness, visible in the panel. None = today's defaults.
        stop = {k: v for k, v in (stop or {}).items()
                if k in ("criteria", "max_attempts", "deadline", "max_steps")
                and v not in (None, "", 0)} or None
        task = {
            "id": tid,
            # shared by every retry of this work: the effects ledger keys on
            # it so a retried task never hits the world twice
            "lineage": lineage or tid,
            "role": role,
            "status": "queued",
            "goal": goal,
            "base_goal": base_goal or goal,
            "attempt": attempt,
            # a course name becomes a PATH in five harness writers that never
            # pass through _safe_path; unsanitised, "../../x" wrote outside
            # the expert root entirely. Sanitise where it enters the system.
            "course": safe_course(course),
            # the mission this task serves, and the success criterion it
            # advances. context.compile recompiles the contract from disk on
            # every call, so the objective cannot drift out of the window.
            "mission": mission,
            "criterion": criterion,
            "done_check": done_check,   # shell command that must exit 0 to finish
            "stop": stop,
            "memory_files": memory_files or [],
            "context_ref": None,
            "steps": [],
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "error": None,
            "summary": None,
        }
        self.commit_task(task)
        return task["id"]

    # ------------------------------------------------------------- locks
    # Single-writer lock per course (Part 5 B7): one task writes to a
    # course's memory at a time. Stale locks (crash leftovers) are broken.

    def lock_path(self, course):
        return os.path.join(self.root, "courses", course, ".lock")

    def can_lock(self, state, task):
        course = task.get("course")
        if not course:
            return True
        p = self.lock_path(course)
        if not os.path.exists(p):
            return True
        try:
            with open(p, "r", encoding="utf-8") as f:
                owner = f.read().strip()
        except OSError:
            return True
        if owner == task["id"]:
            return True
        owner_task = next((t for t in state["tasks"] if t["id"] == owner), None)
        stale_age = (time.time() - os.path.getmtime(p)) > self.lock_stale_minutes * 60
        if owner_task is None or owner_task["status"] != "running" or stale_age:
            self.log.info(json.dumps({
                "event": "lock_break", "course": course, "owner": owner,
                "reason": "stale" if stale_age else "owner not running",
            }))
            os.remove(p)
            return True
        return False

    def acquire_lock(self, task):
        course = task.get("course")
        if not course:
            return
        p = self.lock_path(course)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(task["id"])

    def release_lock(self, task):
        course = task.get("course")
        if not course:
            return
        p = self.lock_path(course)
        try:
            with open(p, "r", encoding="utf-8") as f:
                owner = f.read().strip()
            if owner == task["id"]:
                os.remove(p)  # must happen after the file is closed (Windows)
        except OSError:
            pass

    def next_task(self, state):
        # Resume an ABANDONED running task first (crash recovery); otherwise
        # the next queued task whose course lock is free. A running task whose
        # owner is still alive belongs to that owner and is skipped — this
        # loop moves on to work nobody is doing.
        for t in state["tasks"]:
            if t["status"] == "running" and self._may_resume(t):
                return t
        for t in state["tasks"]:
            if t["status"] == "queued" and self.can_lock(state, t):
                return t
        return None

    # ------------------------------------------------------------- prompts
    # Context assembly, fixed order (Part 5 B3): constitution -> grounding
    # header -> role prompt -> mission.md -> referenced files (index first,
    # then cited files) -> step history -> the task goal.

    def system_sources(self, role):
        """The files the system prompt is built from, in order, plus the
        charter variant on trial (if any). The panel shows exactly this list:
        whose words are in this agent's head must never be a mystery."""
        # constitution first (it overrides everything), then this expert's
        # identity, then the grounding contract, then the role
        role_prompt = os.path.join(self.root, "prompts", f"{role}.md")
        # charter-evolution trials select a variant prompt via env var only —
        # nothing on disk changes until variants.promote() passes its gate
        vid, variant = os.environ.get("AGENT_PROMPT_VARIANT"), None
        if vid and re.fullmatch(r"[\w-]+", vid):
            cand = os.path.join(self.root, "variants", vid, f"{role}.md")
            if os.path.isfile(cand):
                role_prompt, variant = cand, vid
        sources = [
            os.path.join(self.root, "prompts", "constitution.md"),
            os.path.join(self.root, "identity.md"),
            os.path.join(self.root, "prompts", "_grounding.md"),
            role_prompt,
        ]
        return [p for p in sources if os.path.isfile(p)], variant

    def system_prompt(self, role):
        paths, _ = self.system_sources(role)
        parts = []
        for p in paths:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    parts.append(f.read().strip())
            except OSError:
                pass
        if not parts:
            parts = [f"You are the {role} agent. Complete the task using the tools provided."]
        return "\n\n".join(parts)

    def _read_block(self, rel):
        """Data marking (spotlighting): file content is fenced so the model
        can distinguish untrusted material from real instructions — the
        grounding header forbids following directives found inside the fence."""
        p = os.path.join(self.root, rel)
        try:
            with open(p, "r", encoding="utf-8") as f:
                return (f"=== {rel} ===\n<<<FILE-CONTENT {rel}>>>\n"
                        f"{truncate(f.read())}\n<<<END-FILE-CONTENT {rel}>>>")
        except OSError:
            return None

    def matching_skills(self, goal):
        """Procedural-memory fetch rule (Part 6): a skills/ playbook loads when
        the task goal matches its name (all filename tokens present) or any of
        its declared KEYWORDS (first line: 'KEYWORDS: a, b, c')."""
        goal_words = set(re.findall(r"[a-z0-9]+", goal.lower()))
        out = []
        # both shapes count: the flat skills/x.md the Reflector writes and
        # the Agent Skills folder skills/x/SKILL.md the owner imports
        for s in skillgraph.discover(self.root):
            stem_tokens = set(re.findall(r"[a-z0-9]+", s["stem"].lower()))
            # KEYWORDS: what the skill is about; TRIGGER: the situation
            # that should summon it (ReasoningBank-style applicability)
            keywords = {k.strip().lower()
                        for k in (s["keywords"] + s["trigger"]) if k.strip()}
            # a keyword or TRIGGER may be a PHRASE ("load more"): it matches
            # when every word of the phrase appears in the goal
            hit = any(set(re.findall(r"[a-z0-9]+", k)) <= goal_words
                      for k in keywords if k.strip())
            if (stem_tokens and stem_tokens <= goal_words) or hit:
                out.append(s["rel"])
            if len(out) >= self.max_skills_loaded * 2:
                break
        # the skill GRAPH decides what actually loads: quarantined skills are
        # excluded, proven ones outrank candidates, and each selected skill
        # pulls its declared sub-skills (one hop) so procedures compose
        return skillgraph.select(self.root, out, self.max_skills_loaded)

    def initial_messages(self, task):
        """The first window is COMPILED, not piled up: context.py budgets each
        source (commons, course, gotchas, premise, skills, handed files),
        trims what overflows with a pointer to read the rest, and writes a
        manifest next to the transcript so the owner can see exactly what
        this agent was given — and what was left out, and why."""
        messages, _manifest = context.compile(self, task)
        return messages

    # ------------------------------------------------------------- model

    def allowed_tools(self, role):
        """Per-role tool allowlist (the 'Rule of Two': roles that read
        untrusted material should not also hold run_command). finish_task and
        ask_human are always allowed — a role must be able to end or escalate."""
        tools = self.role_cfg(role).get("tools")
        if not tools:
            return set(TOOL_NAMES)
        return set(tools) | {"finish_task", "ask_human"}

    def role_cfg(self, role):
        roles = self.cfg.get("roles", {})
        if role in roles:
            return roles[role]
        if "default" in roles:
            return roles["default"]
        raise RuntimeError(f"No [roles.{role}] and no [roles.default] in settings.toml")

    def provider_cfg(self, name):
        providers = self.cfg.get("providers", {})
        if name not in providers:
            raise RuntimeError(f"No [providers.{name}] in settings.toml")
        return providers[name]

    def _api_key(self, prov):
        if "api_key_env" in prov:
            key = os.environ.get(prov["api_key_env"], "")
            if key:
                return key
        if "api_key" in prov:
            return prov["api_key"]
        if "api_key_file" in prov:
            try:
                with open(prov["api_key_file"], "r", encoding="utf-8") as f:
                    return f.read().strip()
            except OSError:
                pass
        return ""

    def _collect_cards(self, task, text):
        """Collect UI cards an agent emitted. The catalogue is closed: an
        unknown type is dropped and logged, never rendered 'as best we can'."""
        if not text or "<<<UI-CARD" not in str(text):
            return
        try:
            import uicards
            have = len(task.get("cards") or [])
            cards, problems = uicards.parse(text, cap=uicards.MAX_CARDS - have)
        except Exception:
            return
        if cards:
            task.setdefault("cards", []).extend(cards)
            task["cards"] = task["cards"][:uicards.MAX_CARDS]
            self.log.info(json.dumps({"event": "ui_card", "task": task["id"],
                                      "n": len(cards),
                                      "types": [c["type"] for c in cards]}))
        for p in problems:
            self.log.info(json.dumps({"event": "ui_card_invalid",
                                      "task": task["id"], "why": p}))

    def _route_for(self, role):
        """The routing decision for a role, computed once per loop process
        and logged the first time — a decision nobody can see is not a
        decision, it is a rumour."""
        cache = getattr(self, "_route_cache", None)
        if cache is None:
            cache = self._route_cache = {}
        hit = cache.get(role)
        # a 24/7 process may run for weeks: a routing decision made on the
        # first task must not be frozen for the life of the process, or a
        # model that starts failing keeps its job forever
        if hit and time.time() - hit.get("_at", 0) < ROUTE_TTL_SECONDS:
            return hit
        d = {"routed": False, "rule": "static", "why": "routing unavailable"}
        try:
            import modelrouter
            prov, model, d = modelrouter.choose(self, role)
            d = {**d, "provider": prov, "model": model}
            if d.get("routed"):
                self.log.info(json.dumps({"event": "model_routed", "role": role,
                                          "chosen": d.get("chosen"),
                                          "why": d.get("why")}))
        except Exception as e:
            d = {"routed": False, "rule": "static", "why": f"router error: {e}"}
        d["_at"] = time.time()
        cache[role] = d
        return d

    def call_model(self, role, messages, use_tools=True, escalated=False,
                   purpose="step", task_id=None):
        """Call the model with exponential backoff (5 tries) on the primary
        provider, then the fallback provider. Returns (message, usage, provider).
        When escalated, the role's escalate_provider/escalate_model is tried
        first — cheap by default, expensive on the hard steps."""
        rc = self.role_cfg(role)
        attempts = []
        if escalated and rc.get("escalate_model"):
            attempts.append((rc.get("escalate_provider", rc["provider"]),
                             rc["escalate_model"]))
        # CAPABILITY ROUTING: when the role is on route = "auto", the model
        # is chosen from this expert's own measured outcomes (cheapest that
        # clears the gate bar). The configured pair always stays as the
        # fallback below, so routing can never strand a role.
        routed = self._route_for(role)
        if routed.get("routed"):
            attempts.append((routed["provider"], routed["model"]))
        attempts.append((rc["provider"], rc["model"]))
        if rc.get("fallback_provider"):
            attempts.append((rc["fallback_provider"], rc.get("fallback_model", rc["model"])))
        last_err = None
        for prov_name, model in attempts:
            prov = self.provider_cfg(prov_name)
            if prov.get("type") == "mock":
                t0 = time.time()
                msg = self._call_mock(prov, messages)
                # scripted calls are spend too: the suite proves the breaker
                # by charging mock tokens, and a ledger that skipped them
                # would make the daily brake untestable
                cost = self._cost(role, self._mock_usage)
                self._record_spend(cost)
                self._meter(purpose, role, prov_name, model,
                            self._mock_usage, cost, task_id, t0)
                return msg, self._mock_usage, prov_name
            for attempt in range(5):
                _t0 = time.time()
                try:
                    payload = {"model": model, "messages": messages}
                    if self.max_output_tokens > 0:
                        payload["max_tokens"] = self.max_output_tokens
                    # providers/models without function calling (set
                    # native_tools = false) rely on the grounding header's
                    # inline-JSON tool format instead
                    if use_tools and prov.get("native_tools", True):
                        allowed = self.allowed_tools(role)
                        payload["tools"] = [t for t in TOOL_DEFS
                                            if t["function"]["name"] in allowed]
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self._api_key(prov)}",
                    }
                    headers.update(prov.get("extra_headers", {}))
                    req = urllib.request.Request(
                        prov["base_url"].rstrip("/") + "/chat/completions",
                        data=json.dumps(payload).encode("utf-8"),
                        headers=headers,
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=self.model_timeout) as r:
                        raw = r.read().decode("utf-8", errors="replace")
                    # A 200 carrying a body that is not a chat completion is
                    # ordinary provider weather: a proxy's HTML error page, a
                    # truncated stream, a gateway that answers 200 with
                    # {"error": ...}. It used to raise JSONDecodeError or
                    # KeyError straight out of the retry ladder, so the task
                    # died and the FALLBACK PROVIDER WAS NEVER TRIED — the one
                    # situation the fallback exists for. Treat it as the
                    # transient failure it is, and name the provider, because
                    # an operator with four of them configured cannot act on
                    # "Expecting value: line 1 column 1".
                    try:
                        resp = json.loads(raw)
                        msg = resp["choices"][0]["message"]
                    except (ValueError, KeyError, IndexError, TypeError) as e:
                        last_err = (f"{prov_name} returned a body that is not "
                                    f"a chat completion ({type(e).__name__}): "
                                    f"{raw[:160]!r}")
                        self.log.info(json.dumps({
                            "event": "provider_malformed",
                            "provider": prov_name, "model": model,
                            "error": str(e)[:160], "body": raw[:200]}))
                        time.sleep(min(2 ** attempt * 2, 30))
                        continue
                    usage = resp.get("usage", {})
                    _cost = self._cost(role, usage)
                    self._meter(purpose, role, prov_name, model, usage,
                                _cost, task_id, _t0)
                    # EVERY model call is spend, wherever it was made from.
                    # This used to be recorded by run_task_step alone, so the
                    # compaction summarizer, replay.py and benchmark.py spent
                    # money the daily breaker never saw — and compaction fires
                    # on the longest tasks, so the ceiling under-counted worst
                    # exactly where it mattered most.
                    self._record_spend(_cost)
                    return msg, usage, prov_name
                except urllib.error.HTTPError as e:
                    last_err = f"{prov_name} HTTP {e.code}"
                    if e.code in (429, 500, 502, 503, 504):
                        time.sleep(min(2 ** attempt * 2, 30))
                        continue
                    break  # non-retryable on this provider
                except (urllib.error.URLError, TimeoutError, OSError) as e:
                    last_err = f"{prov_name}: {e}"
                    # Retrying an error that CANNOT succeed on retry is pure
                    # latency: nothing is listening, the host does not
                    # resolve, the certificate is wrong. Five backoffs cost a
                    # full minute per step before the fallback is even tried
                    # — on a 24/7 fleet with one misconfigured base_url, every
                    # task pays it. Fail over immediately instead.
                    if permanent_net_error(e):
                        self.log.info(json.dumps({
                            "event": "provider_unreachable",
                            "provider": prov_name, "error": str(e)[:200]}))
                        break
                    time.sleep(min(2 ** attempt * 2, 30))
        raise RuntimeError(f"All providers failed. Last error: {last_err}")

    def _call_mock(self, prov, messages):
        """Deterministic scripted provider for offline testing. The next
        response is chosen by counting assistant messages already in the
        context, so a killed-and-resumed task picks up exactly where it was.
        style = "native" (default) emits tool_calls; style = "json" emits the
        grounding-header inline-JSON form in content."""
        script_path = os.path.join(self.root, prov["script"])
        if script_path not in self._mock_scripts:
            with open(script_path, "r", encoding="utf-8-sig") as f:
                self._mock_scripts[script_path] = json.load(f)
        script = self._mock_scripts[script_path]
        idx = sum(1 for m in messages if m.get("role") == "assistant")
        delay = prov.get("delay_seconds", 0)
        if delay:
            time.sleep(delay)
        if idx >= len(script):
            step = {"tool": "finish_task", "args": {"summary": "script exhausted"}}
        else:
            step = script[idx]
        self._mock_usage = prov.get("fake_usage", {"prompt_tokens": 0,
                                                   "completion_tokens": 0})
        if prov.get("style") == "json":
            return {
                "role": "assistant",
                "content": json.dumps({"tool": step["tool"], "args": step.get("args", {})}),
                "tool_calls": None,
            }
        return {
            "role": "assistant",
            "content": step.get("content"),
            "tool_calls": [{
                "id": f"mock_{idx}",
                "type": "function",
                "function": {
                    "name": step["tool"],
                    "arguments": json.dumps(step.get("args", {})),
                },
            }] if "tool" in step else None,
        }

    def _cost(self, role, usage):
        prov = self.provider_cfg(self.role_cfg(role)["provider"])
        pin = prov.get("input_per_mtok", 0.0)
        pout = prov.get("output_per_mtok", 0.0)
        return (usage.get("prompt_tokens", 0) * pin
                + usage.get("completion_tokens", 0) * pout) / 1_000_000

    # ------------------------------------------------------------- tools

    # credentials never pass through the model's hands: the file tools
    # refuse them even though they sit inside the root (constitution rule 3)
    # Files the agent may never REWRITE, because they define what the agent
    # is allowed to do. Writing settings.toml let a model point a provider at
    # an attacker's base_url and post the API key to it; writing prompts/
    # bypassed variants.py's promotion gate; writing approvals/ forged the
    # owner's sign-off; writing prospective.json stored a shell command that
    # the gate later ran. Capability removal only works if the file listing
    # the capabilities is out of reach.
    def _protected_for_write(self, rel):
        """Why the File Authority would refuse this write, or None.

        This used to carry its OWN copy of the control tables — a tuple of
        five filenames and four directory names — and it was never called by
        anything: _safe_path delegates to fileauth, and has since the File
        Authority was introduced. So it was a second, unreachable definition
        of which files are protected, sitting in the module a reader checks
        first when asking "what can the agent write?".

        Being dead was not the danger; being STALE was. Its copy predated
        `org/` and predated skills/graph.json becoming a control path, so
        anyone who wired it up — it reads exactly like the live check — would
        have silently handed back the skill trust graph. Two tables that must
        agree and no third thing comparing them is the same defect this
        codebase has now hit four times.

        One table, in fileauth. This asks it.
        """
        import fileauth
        r = str(rel).replace("\\", "/").strip("/")
        zone = fileauth.zone_of(r)
        if zone == fileauth.ZONE_CONTROL:
            return f"{r} is a CONTROL file: it defines what this agent may do"
        if zone == fileauth.ZONE_RUNTIME:
            return f"{r} is runtime state the harness owns"
        return None

    def _safe_path(self, rel, write=False):
        """The agent's file tools go through the FILE AUTHORITY (fileauth.py,
        manual §19): one gateway that canonicalises, refuses traversal and
        symlink escapes, refuses credentials, and refuses writes to control
        or runtime state. It used to be a per-call-site check here, which is
        exactly why five harness writers reached the filesystem without it."""
        import fileauth
        try:
            return fileauth.resolve(self.root, rel,
                                    "write" if write else "read", "agent")
        except fileauth.Denied as e:
            # the tool contract is a ValueError carrying a message the model
            # can act on; keep that shape
            raise ValueError(str(e))

    def check_done(self, task):
        """Run the task's done_check. Returns (passed, evidence). A task with
        no done_check is trusted (returns True) — the gate only exists where
        you declared what 'done' means.

        The gate runs under the SAME containment as run_command. It used not
        to, and that was the platform's worst hole: gate commands are written
        by the model (the Watcher writes CHECK: into spec.md, the planner
        emits them for goals), and this path executed them with shell=True,
        no policy screening, and the full environment — so a done_check could
        read the provider keys that run_command is scrubbed of. Measured: the
        gate saw a planted key marker; run_command saw ABSENT.

        Verification is not a lesser path than work. It gets the same two
        layers: policy decides what may run, sandbox decides what it can see.
        """
        cmd = task.get("done_check")
        if not cmd:
            return True, ""
        # ONE gateway (execution.py, manual §19): policy screens it, the
        # untrusted-skill guard runs, the sandbox scrubs the environment, and
        # the whole thing is traced — the same stack run_command gets.
        import execution
        try:
            rc, out, err = execution.run(
                "gate", cmd, self.root, cfg=self.cfg,
                role=task.get("role", "default"), task=task.get("id"),
                timeout=self.command_timeout, reason="definition of done")
        except execution.Refused as e:
            self.log.info(json.dumps({"event": "gate_refused_by_policy",
                                      "task": task.get("id"),
                                      "reason": str(e)[:200]}))
            return False, f"done_check refused: {e}"
        body = ((out or "") + (err or "")).strip()
        return rc == 0, f"exit={rc}\n{truncate(body, 2000)}"

    def exec_tool(self, task, name, args):
        """Every tool returns TEXT, including its failures — an agent can
        recover from 'exit=1, file not found'; it cannot recover from an
        exception that kills its task."""
        try:
            return self._exec_tool(task, name, args)
        except Exception as e:
            self.log.info(json.dumps({"event": "tool_error", "task": task["id"],
                                      "tool": name, "error": str(e)}))
            return f"ERROR: {type(e).__name__}: {e}"

    def _exec_tool(self, task, name, args):
        if name == "read_file":
            try:
                p = self._safe_path(args["path"])
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    return truncate(f.read())
            except (OSError, ValueError) as e:
                return f"ERROR: {e}"
        if name == "write_file":
            try:
                p = self._safe_path(args["path"], write=True)
            except ValueError as e:
                return f"ERROR: {e}"
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(args["content"])
            return f"ok, wrote {len(args['content'])} chars to {args['path']}"
        if name == "run_command":
            cmd = args["cmd"]
            with open(os.path.join(self.logs_dir, "commands.log"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} task={task['id']} {cmd}\n")
            env = {"PYTHONUTF8": "1",
                   "AGENT_ROOT": self.root,
                   "AGENT_TASK_ID": task["id"],
                   "AGENT_TASK_LINEAGE": task.get("lineage") or task["id"],
                   "AGENT_ROLE": task.get("role", "default")}
            # ONE gateway (execution.py, manual §19): the policy layer decides
            # what the model MAY run, the provenance guard keeps a community
            # skill's bundled scripts disabled, the sandbox decides WHERE it
            # runs and what it can see, and every attempt is traced. An
            # unavailable backend fails closed.
            import execution
            try:
                rc, out, err = execution.run(
                    "model_command", cmd, self.root, cfg=self.cfg,
                    role=task.get("role", "default"), task=task["id"],
                    timeout=self.command_timeout, env=env)
            except execution.Refused as e:
                # carry WHY forward: "refused" without a reason is the kind of
                # log line that makes an incident unreadable a week later
                reason = str(e)
                self.log.info(json.dumps({
                    "event": "command_refused", "task": task["id"],
                    "reason": ("untrusted skill script"
                               if "COMMUNITY skill" in reason
                               else reason[:200]),
                    "cmd": cmd[:200]}))
                return reason
            return truncate(
                f"exit={rc}\n--- stdout ---\n{out}\n--- stderr ---\n{err}")
        if name == "ask_human":
            with open(os.path.join(self.root, "blocked.md"), "a", encoding="utf-8") as f:
                f.write(
                    f"\n## {time.strftime('%Y-%m-%d %H:%M')} — task {task['id']} ({task['role']}"
                    f"{', course ' + task['course'] if task.get('course') else ''})\n"
                    f"{args['question']}\n"
                )
            return "question recorded in blocked.md; task marked blocked"
        raise ValueError(f"unknown tool {name}")

    # ------------------------------------------------------------- context

    def context_path(self, task):
        return os.path.join(self.contexts_dir, f"{task['id']}.json")

    def load_context(self, task):
        msgs = load_json(self.context_path(task), None)
        if msgs is None:
            msgs = self.initial_messages(task)
        return msgs

    def save_context(self, task, messages):
        atomic_write_json(self.context_path(task), messages)

    def compact_context(self, task, messages):
        """Past the token threshold, summarize the oldest turns into a compact
        note and keep recent turns verbatim (Anthropic's compaction primitive)."""
        if est_tokens(messages) <= self.ctx_threshold:
            return messages
        head, tail = messages[:2], messages[2:]
        keep = min(self.ctx_keep_recent, len(tail))
        # never start the kept tail on a dangling tool result
        while keep < len(tail) and tail[-keep].get("role") == "tool":
            keep += 1
        middle, recent = tail[:-keep] if keep else tail, tail[-keep:] if keep else []
        if not middle:
            return messages
        # NEVER lose context (MemGPT recall tier): before the old turns are
        # summarized out of the working window, archive them verbatim. The
        # summary is for the model's window; the archive is for recall.py.
        archive = self.context_path(task).replace(".json", ".archive.jsonl")
        start_line = 0
        try:
            with open(archive, "r", encoding="utf-8") as f:
                start_line = sum(1 for _ in f)
        except OSError:
            pass
        with open(archive, "a", encoding="utf-8") as f:
            for m in middle:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        # TOOL-RESULT CLEARING: the payloads are now safe on disk, so the
        # summarizer is handed a POINTER instead of the bytes. Re-summarizing
        # a 30 KB grep dump costs tokens and teaches nothing; the line number
        # makes the original one read_file away, and recall.py can find it.
        cleaned, cleared = [], 0
        for i, m in enumerate(middle):
            body = m.get("content") or ""
            if m.get("role") == "tool" and len(body) > CLEAR_TOOL_RESULT_CHARS:
                m = dict(m, content=(
                    f"[archived tool output: {len(body)} chars; verbatim at "
                    f"contexts/{task['id']}.archive.jsonl line "
                    f"{start_line + i + 1}; recall.py finds it]"))
                cleared += 1
            cleaned.append(m)
        if cleared:
            self.log.info(json.dumps({"event": "tool_results_cleared",
                                      "task": task["id"], "n": cleared}))
        try:
            context.note_compaction(self.root, task["id"], {
                "at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "turns": len(middle), "cleared": cleared,
                "kept_recent": len(recent)})
        except Exception:
            pass
        blob = truncate(json.dumps(cleaned, ensure_ascii=False), 60_000)
        # COMPACTION AS A CONTRACT: the note must carry fixed sections, and
        # the harness appends what it KNOWS mechanically — goal, gate, files
        # written — so the essentials never depend on the summarizer's mood
        sections = ["GOAL & ACCEPTANCE", "VERIFIED STATE", "DECISIONS",
                    "OPEN DEFECTS", "ARTIFACTS", "NEXT ACTION", "UNCERTAIN"]
        try:
            msg, _, _ = self.call_model(
                task["role"],
                [
                    {"role": "system", "content": "You compress agent transcripts."},
                    {"role": "user", "content":
                        "Summarize the following agent conversation turns into a compact "
                        "note preserving every fact, file path, decision, and open item. "
                        "Use EXACTLY these headings, each on its own line: "
                        + "; ".join(sections)
                        + ". Under UNCERTAIN list anything you are not sure of — "
                        "never turn a guess into a fact.\n" + blob},
                ],
                use_tools=False, purpose="compaction",
                task_id=task.get("id"),
            )
            summary = msg.get("content") or blob[:4000]
        except Exception:
            summary = blob[:4000]
        written = []
        for m in middle:
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                if fn.get("name") == "write_file":
                    try:
                        p = json.loads(fn.get("arguments") or "{}").get("path")
                        if p and p not in written:
                            written.append(p)
                    except json.JSONDecodeError:
                        pass
        missing = [sct for sct in sections if sct.lower() not in summary.lower()]
        facts = ("\n[HARNESS FACTS — recorded mechanically, not summarized]\n"
                 f"Task goal: {(task.get('goal') or '')[:400]}\n"
                 f"Definition of done: {task.get('done_check') or 'none'}\n"
                 f"Stop condition: {stop_text(task.get('stop'))}\n"
                 f"Files written in the compacted turns: "
                 f"{', '.join(written[:40]) or 'none'}\n")
        if missing:
            facts += (f"[COMPACTION CONTRACT: the note above omitted "
                      f"{', '.join(missing)} — treat those as UNKNOWN and "
                      f"re-read the files before relying on them]\n")
            self.log.info(json.dumps({"event": "compaction_incomplete",
                                      "task": task["id"], "missing": missing}))
        return head + [
            {"role": "user", "content": f"[Compact summary of {len(middle)} earlier turns]\n{summary}{facts}"}
        ] + recent

    # ------------------------------------------------------------- run loop

    def run_task_step(self, state, task):
        """One full tick. Returns False when the task left the running state."""
        messages = self.load_context(task)
        messages = self.compact_context(task, messages)

        # the task's own STOP CONDITION outranks the harness defaults
        stop = task.get("stop") or {}
        if stop.get("deadline") and \
                time.strftime("%Y-%m-%dT%H:%M:%S") >= str(stop["deadline"]):
            task["status"] = "failed"
            task["error"] = f"stop condition: deadline {stop['deadline']} passed"
            self.log.info(json.dumps({"event": "stop_condition", "task": task["id"],
                                      "which": "deadline"}))
            self.save_context(task, messages)
            self.commit_task(task)
            return False
        if stop.get("max_steps") and n_steps(task) >= int(stop["max_steps"]):
            task["status"] = "failed"
            task["error"] = (f"stop condition: max_steps {stop['max_steps']} "
                             f"reached without finishing")
            self.log.info(json.dumps({"event": "stop_condition", "task": task["id"],
                                      "which": "max_steps"}))
            self.save_context(task, messages)
            self.commit_task(task)
            return False

        routed = self._route_for(task["role"])
        if routed.get("routed"):
            task["route"] = {k: routed[k] for k in
                             ("chosen", "why", "cost", "rule") if k in routed}
        try:
            msg, usage, prov_name = self.call_model(
                task["role"], messages, escalated=bool(task.get("escalated")),
                purpose="step", task_id=task["id"])
            task["provider"] = prov_name
            task["model"] = (routed.get("model") if routed.get("routed")
                             else self.role_cfg(task["role"]).get("model"))
        except RuntimeError as e:
            task["status"] = "failed"
            task["error"] = str(e)
            self.commit_task(task)
            self.log.error(json.dumps({"task": task["id"], "event": "provider_failure", "error": str(e)}))
            return False

        task["tokens_in"] += usage.get("prompt_tokens", 0)
        task["tokens_out"] += usage.get("completion_tokens", 0)
        step_cost = self._cost(task["role"], usage)
        task["cost_usd"] = round(task["cost_usd"] + step_cost, 6)
        # (the daily ledger was already credited inside call_model, which is
        # the only place that knows about EVERY call, not just this one)

        # generative UI, from a fixed catalogue: an agent may hand the panel a
        # table, checklist, diff or metric card. Never markup, never a script.
        self._collect_cards(task, msg.get("content"))

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            # grounding-header fallback: one tool call as inline JSON
            tc = parse_content_tool_call(msg.get("content"))
            if tc:
                tool_calls = [tc]

        messages.append({
            "role": "assistant",
            "content": msg.get("content"),
            "tool_calls": tool_calls or None,
        })

        if not tool_calls:
            task["malformed"] = task.get("malformed", 0) + 1
            if task["malformed"] >= self.max_malformed:
                task["status"] = "failed"
                task["error"] = "model produced no valid tool call after retries"
                self.save_context(task, messages)
                self.commit_task(task)
                return False
            messages.append({
                "role": "user",
                "content": "ERROR: you must respond with exactly one tool call "
                           f"({', '.join(sorted(TOOL_NAMES))}). Try again.",
            })
            self.save_context(task, messages)
            self.commit_task(task)
            return True

        tc = tool_calls[0]
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
            if name not in TOOL_NAMES:
                raise ValueError(f"unknown tool: {name}")
            if name not in self.allowed_tools(task["role"]):
                messages.append({
                    "role": "tool", "tool_call_id": tc.get("id", "?"),
                    "content": f"ERROR: tool '{name}' is not permitted for the "
                               f"{task['role']} role. Allowed: "
                               f"{', '.join(sorted(self.allowed_tools(task['role'])))}.",
                })
                self.save_context(task, messages)
                self.commit_task(task)
                return True
        except (json.JSONDecodeError, ValueError) as e:
            task["malformed"] = task.get("malformed", 0) + 1
            if task["malformed"] >= self.max_malformed:
                task["status"] = "failed"
                task["error"] = f"malformed tool call: {e}"
                self.save_context(task, messages)
                self.commit_task(task)
                return False
            messages.append({
                "role": "tool", "tool_call_id": tc.get("id", "?"),
                "content": f"PARSE ERROR: {e}. Fix the tool call and retry.",
            })
            self.save_context(task, messages)
            self.commit_task(task)
            return True
        task["malformed"] = 0

        if name == "finish_task":
            # Definition of done as a CONSTRAINT, not a suggestion: when the
            # task carries a done_check, finish_task is refused until that
            # command exits 0. The agent gets the failure output and keeps
            # working. "Please verify" in a prompt is advice; this is a gate.
            ok, evidence = self.check_done(task)
            if ok:
                task["status"] = "done"
                summary = args.get("summary", "")
                self._collect_cards(task, summary)   # cards in the sign-off
                try:
                    import uicards
                    summary = uicards.strip(summary) or summary
                except Exception:
                    pass
                task["summary"] = summary
                result = "task finished" + (
                    f" (done_check passed: {truncate(evidence, 300)})"
                    if task.get("done_check") else "")
            else:
                task["done_rejects"] = task.get("done_rejects", 0) + 1
                if task["done_rejects"] >= self.max_done_rejects:
                    task["status"] = "failed"
                    task["error"] = (f"done_check never passed after "
                                     f"{task['done_rejects']} attempts: {evidence}")
                    result = f"TASK FAILED: {task['error']}"
                else:
                    result = (
                        "finish_task REFUSED — your definition of done is not met.\n"
                        f"$ {task['done_check']}\n{evidence}\n"
                        "Fix the underlying problem and call finish_task again "
                        f"(attempt {task['done_rejects']} of {self.max_done_rejects}).")
                    self.log.info(json.dumps({"event": "done_refused",
                                              "task": task["id"],
                                              "attempt": task["done_rejects"]}))
        elif name == "ask_human":
            result = self.exec_tool(task, name, args)
            task["status"] = "blocked"
        else:
            result = self.exec_tool(task, name, args)

        # --- model routing: escalate to the stronger model on hard steps.
        # Trigger 1: consecutive tool errors. Trigger 2: the model asks, by
        # writing [[ESCALATE]] in its message (see the grounding header).
        # Trigger 3: task type — the role's configured model tier.
        if str(result).startswith(("ERROR", "PARSE ERROR", "exit=1", "TASK FAILED")) \
                or "ERROR:" in str(result)[:40]:
            task["tool_errors"] = task.get("tool_errors", 0) + 1
        else:
            task["tool_errors"] = 0
        wants = "[[ESCALATE]]" in (msg.get("content") or "")
        if not task.get("escalated") and self.role_cfg(task["role"]).get("escalate_model") \
                and (wants or (self.escalate_after_errors
                               and task["tool_errors"] >= self.escalate_after_errors)):
            task["escalated"] = True
            reason = "model requested" if wants else \
                f"{task['tool_errors']} consecutive tool errors"
            messages.append({"role": "user", "content":
                             f"[escalated to the stronger model: {reason}]"})
            self.log.info(json.dumps({"event": "escalated", "task": task["id"],
                                      "reason": reason}))

        # a guarded call that stopped for the owner is an EVENT, not a buried
        # line in a tool result: the live stream and the pulse show it at once
        if "APPROVAL REQUIRED (ap-" in str(result):
            m_ap = re.search(r"APPROVAL REQUIRED \((ap-[\w-]+)\): (\S+?)\.(\S+?) ",
                             str(result))
            self.log.info(json.dumps({
                "event": "approval_required", "task": task["id"],
                "approval": m_ap.group(1) if m_ap else None,
                "server": m_ap.group(2) if m_ap else None,
                "tool": m_ap.group(3) if m_ap else None}))
        messages.append({"role": "tool", "tool_call_id": tc.get("id", "?"), "content": result})
        task["steps"].append({
            "tool": name,
            "args": truncate(json.dumps(args, ensure_ascii=False), STEP_TRUNC),
            "result": truncate(str(result), STEP_TRUNC),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        task["context_ref"] = os.path.relpath(self.context_path(task), self.root)

        # repetition breaker: an agent re-issuing the identical call is stuck
        steps = task["steps"]
        same = 1
        while same < len(steps) and steps[-1 - same]["tool"] == steps[-1]["tool"] \
                and steps[-1 - same]["args"] == steps[-1]["args"]:
            same += 1
        if task["status"] == "running" and same >= 5:
            task["status"] = "failed"
            task["error"] = f"repetition loop: identical {name} call {same} times in a row"
        elif task["status"] == "running" and same == 3:
            messages.append({
                "role": "user",
                "content": f"WARNING: you have made the identical {name} call "
                           f"{same} times in a row. Repeating it again will fail "
                           f"the task — change your approach or call ask_human.",
            })

        if task["status"] == "running" and n_steps(task) >= self.max_steps:
            task["status"] = "failed"
            task["error"] = f"max steps ceiling ({self.max_steps}) reached"

        # third brake: a hard per-run cost ceiling that kills the run
        if task["status"] == "running" and self.max_task_usd > 0 \
                and task["cost_usd"] >= self.max_task_usd:
            task["status"] = "failed"
            task["error"] = (f"cost ceiling reached: ${task['cost_usd']} spent, "
                             f"limit ${self.max_task_usd} (max_task_usd)")
            self.log.error(json.dumps({"event": "task_cost_ceiling",
                                       "task": task["id"],
                                       "cost_usd": task["cost_usd"]}))

        self.save_context(task, messages)
        self.commit_task(task)
        self.log.info(json.dumps({
            "task": task["id"], "role": task["role"], "step": n_steps(task),
            "provider": prov_name, "tool": name,
            "args": truncate(json.dumps(args, ensure_ascii=False), STEP_TRUNC),
            "result": truncate(str(result), STEP_TRUNC),
            "tokens_in": task["tokens_in"], "tokens_out": task["tokens_out"],
            "cost_usd": task["cost_usd"], "status": task["status"],
        }, ensure_ascii=False))
        return task["status"] == "running"

    # --------------------------------------------------- budget breaker
    # The most-reported agent failure in the wild: no session budget, no
    # circuit breaker. Provider spend caps are the outer wall; this is the
    # inner one — a daily dollar ceiling enforced in the loop itself.

    def _spend_path(self):
        return os.path.join(self.logs_dir, f"spend-{time.strftime('%Y%m%d')}.json")

    def _meter(self, purpose, role, provider, model, usage, cost, task_id, t0):
        """Manual §19 Model Gateway: EVERY provider call is attributed to a
        purpose and a model, per call. Task-level attribution credited a whole
        task to whichever provider served its last step, which mis-credits any
        task that failed over. Never raises — metering must not break work."""
        try:
            import modelgateway
            modelgateway.record(
                self.root, purpose=purpose, role=role, provider=provider,
                model=model, usage=usage, cost=cost, task=task_id,
                ms=int((time.time() - t0) * 1000))
        except Exception:
            pass

    def _record_spend(self, usd):
        if usd <= 0:
            return
        with self._state_lock():   # two loops must not lose each other's dollars
            s = load_json(self._spend_path(), {"usd": 0.0, "notified": False})
            s["usd"] = round(s["usd"] + usd, 6)
            atomic_write_json(self._spend_path(), s)

    def _org_spend_ceiling(self):
        """The organization's `require_approval_over_usd`, or 0 for none.

        This flag has been in org.json since the first workspace was created
        and read by nothing — an owner who set a $5 ceiling got no ceiling.
        It is enforced HERE rather than in a new subsystem because the loop
        already owns the day's spend ledger and already knows how to pause an
        expert and say why; a second mechanism for the same question is how
        the two would come to disagree.

        It composes with settings.toml's daily_budget_usd rather than
        replacing it: the org ceiling binds the whole workspace, the expert's
        own ceiling binds one expert, and the LOWER of the two wins, which is
        the only combination that cannot be escaped by editing the file the
        agent's own owner does not control.
        """
        try:
            import org
            v = float(org.policy_flag(self.root, "require_approval_over_usd", 0)
                      or 0)
            return v if v > 0 else 0.0
        except Exception:
            return 0.0

    def _budget_exceeded(self):
        """Has this expert hit a spend ceiling today?

        Two ceilings, one rule: the LOWER binds. The expert's own
        daily_budget_usd lives in a settings.toml the expert's operator can
        edit; the organization's require_approval_over_usd lives in org.json
        and only the owner can change it. Taking the minimum is what stops the
        workspace ceiling being escaped by editing the file below it.

        Either being unset (0 or absent) simply removes that ceiling; both
        unset means no breaker, which is the historical behaviour.
        """
        org_cap = self._org_spend_ceiling()
        own_cap = self.daily_budget_usd if self.daily_budget_usd > 0 else 0.0
        caps = [c for c in (own_cap, org_cap) if c > 0]
        if not caps:
            return False
        cap = min(caps)
        s = load_json(self._spend_path(), {"usd": 0.0, "notified": False})
        if s["usd"] < cap:
            return False
        if not s.get("notified"):
            if org_cap and cap == org_cap:
                why = (f"ORG SPEND CEILING\nThis workspace requires owner "
                       f"approval over ${org_cap} and ${s['usd']} has been "
                       f"spent today, so this expert is paused.\nRaise it "
                       f"with `python org.py policy --set "
                       f"require_approval_over_usd=<amount> "
                       f"--as <owner-email>`.")
            else:
                why = (f"BUDGET BREAKER\nDaily budget of ${own_cap} reached "
                       f"(${s['usd']} spent today). The agent is paused until "
                       f"tomorrow. Raise daily_budget_usd in settings.toml to "
                       f"resume sooner.")
            with open(os.path.join(self.root, "blocked.md"), "a",
                      encoding="utf-8") as f:
                f.write(f"\n## {time.strftime('%Y-%m-%d %H:%M')} — {why}\n")
            s["notified"] = True
            atomic_write_json(self._spend_path(), s)
            self.log.error(json.dumps({"event": "budget_exceeded",
                                       "spent_usd": s["usd"],
                                       "budget_usd": cap,
                                       "ceiling": "org" if (org_cap and
                                                            cap == org_cap)
                                                  else "expert"}))
        return True

    # --------------------------------------------------- provider check

    def _probe(self, prov_name, model):
        """One cheap live request to a provider/model pair. No retries — this
        reports reality, it doesn't paper over it."""
        try:
            prov = self.provider_cfg(prov_name)
        except RuntimeError as e:
            return f"FAIL: {e}"
        if prov.get("type") == "mock":
            return "OK (mock, scripted)"
        key = self._api_key(prov)
        if not key:
            return f"FAIL: no API key ({prov.get('api_key_env', 'api_key')} not set)"
        payload = {"model": model, "max_tokens": 16,
                   "messages": [{"role": "user",
                                 "content": "Reply with the single word: ok"}]}
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {key}"}
        headers.update(prov.get("extra_headers", {}))
        req = urllib.request.Request(
            prov["base_url"].rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"), headers=headers,
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                resp = json.loads(r.read().decode("utf-8"))
            resp["choices"][0]["message"]
            return "OK"
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:160]
            return f"FAIL: HTTP {e.code} {body}"
        except (urllib.error.URLError, TimeoutError, OSError, KeyError,
                json.JSONDecodeError) as e:
            return f"FAIL: {e}"

    def check_providers(self):
        """Probe every role's provider (and fallback). Returns (rows, all_ok)."""
        cache, rows = {}, []
        for role in sorted(self.cfg.get("roles", {})):
            rc = self.role_cfg(role)
            pairs = [(rc["provider"], rc["model"])]
            if rc.get("fallback_provider"):
                pairs.append((rc["fallback_provider"],
                              rc.get("fallback_model", rc["model"])))
            for prov_name, model in pairs:
                k = (prov_name, model)
                if k not in cache:
                    cache[k] = self._probe(prov_name, model)
                rows.append((role, prov_name, model, cache[k]))
        return rows, all(s.startswith("OK") for *_, s in rows)

    # --------------------------------------------------- exit criterion
    # A course is COMPLETE when: every spec item PASS + exam score >= the
    # threshold + gaps.md empty (Part 8). Then spaced re-exams at the
    # configured intervals with NEW hidden questions.

    def course_status(self, course):
        base = os.path.join(self.root, "courses", course)

        def read(name):
            try:
                with open(os.path.join(base, name), "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                return ""

        spec_ids = re.findall(r"^\s*(R-[\w.]+)\s*[:\[]", read("spec.md"), re.M)
        spec_ids = list(dict.fromkeys(spec_ids))
        verdicts = {}
        for rid, verdict in re.findall(
                r"(R-[\w.]+)\b[^\n]*?\b(PASS|FAIL|NOT ATTEMPTED)\b",
                read("exam-results.md")):
            verdicts[rid] = verdict  # last occurrence wins
        passed = [r for r in spec_ids if verdicts.get(r) == "PASS"]
        gaps_open = len(re.findall(r"^\s*-?\s*G-[\w.]+", read("gaps.md"), re.M))
        scores = re.findall(r"^\s*SCORE:\s*(\d+)", read("exam-results.md"), re.M)
        score = int(scores[-1]) if scores else None
        complete = (bool(spec_ids) and len(passed) == len(spec_ids)
                    and gaps_open == 0
                    and score is not None and score >= self.exam_threshold)
        return {
            "course": course, "spec_total": len(spec_ids),
            "spec_pass": len(passed),
            "spec_missing": [r for r in spec_ids if r not in passed],
            "gaps_open": gaps_open, "score": score,
            "threshold": self.exam_threshold, "complete": complete,
        }

    def _reexam_tick(self):
        """When the queue is idle: create re-exam schedules for newly complete
        courses and enqueue any due re-exam. Returns True if a task was queued."""
        courses_dir = os.path.join(self.root, "courses")
        try:
            courses = sorted(
                c for c in os.listdir(courses_dir)
                if os.path.isdir(os.path.join(courses_dir, c)))
        except OSError:
            return False
        queued = False
        today = datetime.date.today()
        for c in courses:
            sched_path = os.path.join(courses_dir, c, "exam", "schedule.json")
            if not os.path.exists(sched_path):
                if not self.course_status(c)["complete"]:
                    continue
                sched = {
                    "completed": today.isoformat(),
                    "entries": [
                        {"due": (today + datetime.timedelta(days=d)).isoformat(),
                         "done": False, "task": None}
                        for d in self.reexam_days
                    ],
                }
                os.makedirs(os.path.dirname(sched_path), exist_ok=True)
                atomic_write_json(sched_path, sched)
                self.log.info(json.dumps({"event": "reexam_scheduled", "course": c,
                                          "dues": [e["due"] for e in sched["entries"]]}))
            sched = load_json(sched_path, None)
            if not sched:
                continue
            changed = False
            for entry in sched["entries"]:
                if not entry["done"] and entry["due"] <= today.isoformat():
                    tid = self.add_task(
                        "examiner",
                        f"Spaced re-exam for course {c}: generate NEW hidden exam "
                        f"questions from the notes (past exams are in exam/ — do not "
                        f"reuse questions), grade strictly, update the SCORE line in "
                        f"exam-results.md, and write every miss to gaps.md.",
                        course=c,
                    )
                    entry["done"] = True
                    entry["task"] = tid
                    changed = queued = True
                    self.log.info(json.dumps({"event": "reexam_queued",
                                              "course": c, "task": tid}))
            if changed:
                atomic_write_json(sched_path, sched)
        return queued

    def _inbox_tick(self):
        """The daemon scans its own inbox on idle: dropped files become
        courses and tasks with no separate timer or human command. Returns
        True only when something was actually ingested."""
        if not self.auto_scan_inbox:
            return False
        inbox = os.path.join(self.root, "inbox")
        try:
            items = [f for f in os.listdir(inbox) if not f.startswith(".")
                     and os.path.isfile(os.path.join(inbox, f))]
        except OSError:
            return False
        if not items:
            return False
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import ingest
        processed = ingest.scan_inbox(self.root)
        if processed:
            self.log.info(json.dumps({"event": "inbox_scanned", "items": processed}))
        return processed > 0

    def _gap_tick(self):
        """Part 9 mechanism 1: every open gap becomes a queued task — nothing
        evaporates. Gap lines may carry a role hint: '- G-012 (watcher) ...';
        untagged gaps default to the Librarian. One task per role per course
        per distinct gap set (tracked in exam/gaps-state.json), so an
        unresolved set is never re-queued in a loop."""
        courses_dir = os.path.join(self.root, "courses")
        try:
            courses = sorted(
                c for c in os.listdir(courses_dir)
                if os.path.isdir(os.path.join(courses_dir, c)))
        except OSError:
            return False
        queued = False
        for c in courses:
            gaps_path = os.path.join(courses_dir, c, "gaps.md")
            try:
                with open(gaps_path, "r", encoding="utf-8") as f:
                    gaps_text = f.read()
            except OSError:
                continue
            found = re.findall(r"^\s*-\s*(G-[\w.]+)\s*(?:\((\w+)\))?",
                               gaps_text, re.M)
            if not found:
                continue
            key = ",".join(sorted(g for g, _ in found))
            state_path = os.path.join(courses_dir, c, "exam", "gaps-state.json")
            gstate = load_json(state_path, {})
            if gstate.get("key") == key:
                continue  # this exact set was already dispatched
            by_role = {}
            for gid, role in found:
                by_role.setdefault(role or "librarian", []).append(gid)
            tids = []
            for role, gids in sorted(by_role.items()):
                tids.append(self.add_task(
                    role,
                    f"Resolve open gaps in courses/{c}/gaps.md assigned to your "
                    f"role: {', '.join(gids)}. Re-read the cited notes and "
                    f"sources, do the re-study/re-execution/rewrite your role "
                    f"prescribes, and remove each resolved '- G-nnn' line from "
                    f"gaps.md (record retractions in retractions.md where a "
                    f"claim is withdrawn).",
                    course=c))
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            atomic_write_json(state_path, {"key": key, "tasks": tids})
            self.log.info(json.dumps({"event": "gaps_queued", "course": c,
                                      "gaps": key, "tasks": tids}))
            queued = True
        return queued

    def _exam_tick(self):
        """Hidden exams as a mechanism (Part 8 layer 3): a question file in
        exam/pending/ that has no answer file gets a closed-book Student task.
        The Student's context carries only mission.md, index.md, and the
        questions, and its tool allowlist has no read access — the exam is
        closed-book by construction, not by convention. Grading is chained
        (student -> examiner). Dispatch is tracked by CONTENT HASH, so an exam
        is sat exactly once per question file, and a replaced file (same name,
        new questions) is a new exam, not a silently skipped one."""
        courses_dir = os.path.join(self.root, "courses")
        try:
            courses = sorted(
                c for c in os.listdir(courses_dir)
                if os.path.isdir(os.path.join(courses_dir, c)))
        except OSError:
            return False
        queued = False
        for c in courses:
            pending_dir = os.path.join(courses_dir, c, "exam", "pending")
            if not os.path.isdir(pending_dir):
                continue
            state_path = os.path.join(courses_dir, c, "exam", "exam-state.json")
            est = load_json(state_path, {"dispatched": {}})
            if isinstance(est.get("dispatched"), list):
                # state from before content hashing: filenames known, hashes not
                est["dispatched"] = {fn: "?" for fn in est["dispatched"]}
            changed = False
            for fn in sorted(f for f in os.listdir(pending_dir) if f.endswith(".md")):
                with open(os.path.join(pending_dir, fn), "rb") as f:
                    digest = hashlib.sha256(f.read()).hexdigest()[:16]
                seen = est["dispatched"].get(fn)
                if seen == digest:
                    continue  # this exact question file was already dispatched
                if seen is None and os.path.exists(
                        os.path.join(courses_dir, c, "exam", "answers", fn)):
                    # answers exist with no dispatch record (restored backup):
                    # adopt them as sat rather than overwriting silently
                    est["dispatched"][fn] = digest
                    changed = True
                    continue
                exam_rel = f"courses/{c}/exam/pending/{fn}"
                tid = self.add_task(
                    "student",
                    f"Closed-book exam: answer every question in {exam_rel} using "
                    f"ONLY the course mission, index, and the exam text already in "
                    f"your context — you have no access to the notes. Write your "
                    f"answers to courses/{c}/exam/answers/{fn}, citing for each "
                    f"answer the atom IDs (C-/P-nnnn) you believe support it. If "
                    f"you cannot answer, say so explicitly.",
                    memory_files=[exam_rel], course=c)
                est["dispatched"][fn] = digest
                changed = queued = True
                self.log.info(json.dumps({"event": "exam_dispatched", "course": c,
                                          "exam": fn, "task": tid}))
            if changed:
                atomic_write_json(state_path, est)
        return queued

    def _maybe_retry(self, task):
        """The endurance promise: a failed task is re-queued with fresh eyes —
        a new context carrying the previous error — up to max_task_retries
        times. Blocked tasks are the human's, not retried."""
        if task["status"] != "failed":
            return
        attempt = task.get("attempt", 1)
        limit = (task.get("stop") or {}).get("max_attempts")
        if limit and attempt >= int(limit):
            self.log.info(json.dumps({"event": "retries_exhausted",
                                      "task": task["id"], "attempts": attempt,
                                      "stop": "max_attempts"}))
            return
        if attempt > self.max_task_retries:
            self.log.info(json.dumps({"event": "retries_exhausted",
                                      "task": task["id"], "attempts": attempt}))
            return
        base = task.get("base_goal") or task["goal"]
        nid = self.add_task(
            task["role"],
            f"RETRY {attempt + 1} of {self.max_task_retries + 1}: the previous "
            f"attempt ({task['id']}) failed with: {truncate(task.get('error') or '?', 300)}. "
            f"Diagnose what went wrong and take a different approach.\n\n"
            f"Original goal: {base}",
            memory_files=task.get("memory_files"), course=task.get("course"),
            attempt=attempt + 1, base_goal=base,
            lineage=task.get("lineage") or task["id"],
            done_check=task.get("done_check"), stop=task.get("stop"))
        self.log.info(json.dumps({"event": "retry_queued", "failed_task": task["id"],
                                  "retry_task": nid, "attempt": attempt + 1}))

    def answer_task(self, task_id, text):
        """Resume a blocked task: the human's answer is appended to its
        context and the task returns to the queue."""
        state = self.load_state()
        task = next((t for t in state["tasks"] if t["id"] == task_id), None)
        if task is None:
            raise SystemExit(f"no task {task_id}")
        if task["status"] != "blocked":
            raise SystemExit(f"task {task_id} is {task['status']}, not blocked")
        messages = self.load_context(task)
        messages.append({"role": "user",
                         "content": f"Human answer to your blocked question: {text}"})
        self.save_context(task, messages)
        task["status"] = "queued"
        self.commit_task(task)
        self.log.info(json.dumps({"event": "task_unblocked", "task": task_id}))

    def _file_memory(self, task):
        """Every finished task files institutional memory: a structured,
        categorized failure record when it failed, and an earned competence
        outcome either way. Neither is self-reported — the category comes from
        the harness's own error, and 'verified' means a done_check passed.
        Skills loaded into the task file their outcome too: that evidence is
        what promotes a candidate skill to proven (>=3 distinct wins, one
        gate-verified) or quarantines a repeat loser."""
        if task["status"] not in ("done", "failed"):
            return
        # CONFIDENCE: how much doubt is left, measured from what the harness
        # already checked. Recorded on the task, never self-reported, and
        # used to decide whether more compute is warranted (candidates.py).
        try:
            import confidence
            rep = confidence.score(self, task)
            task["confidence"] = {k: rep[k] for k in
                                  ("confidence", "band", "action", "why")}
            # the task was committed when it finished, so this needs its own
            # write or the band exists only in memory and dies with the loop
            self.commit_task(task)
            if rep["band"] != "high":
                self.log.info(json.dumps({
                    "event": "low_confidence", "task": task["id"],
                    "confidence": rep["confidence"], "band": rep["band"],
                    "action": rep["action"], "why": rep["why"]}))
        except Exception as e:
            self.log.error(json.dumps({"event": "confidence_failed",
                                       "error": str(e)}))
        will_retry_s = (task["status"] == "failed"
                        and task.get("attempt", 1) <= self.max_task_retries)
        if not will_retry_s and task.get("skills_used"):
            try:
                changed = skillgraph.record_use(
                    self.root, task["skills_used"], task["id"],
                    success=(task["status"] == "done"),
                    verified=bool(task.get("done_check")))
                for stem, (old_st, new_st) in changed.items():
                    self.log.info(json.dumps({
                        "event": "skill_status", "skill": stem,
                        "from": old_st, "to": new_st}))
            except Exception as e:
                self.log.error(json.dumps({"event": "skill_record_failed",
                                           "error": str(e)}))
        # the routing ledger: this task's own result becomes the evidence for
        # which model the next task of this kind should use. Kept per expert
        # (not per fleet) — a model that suits this expert's work may be
        # wrong for another's.
        if not will_retry_s:
            try:
                import modelrouter
                modelrouter.record(self.root, task,
                                   task.get("provider") or "unknown",
                                   task.get("model") or "unknown",
                                   task.get("cost_usd", 0))
            except Exception as e:
                self.log.error(json.dumps({"event": "route_record_failed",
                                           "error": str(e)}))
        # experts/<slug> -> the fleet home two levels up
        parent = os.path.dirname(self.root)
        if os.path.basename(parent) != "experts":
            return
        home = os.path.dirname(parent)
        slug = os.path.basename(self.root)
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import memory
            domain = task.get("course") or task.get("role") or "general"
            # competence measures WORK, not attempts: a task that will be
            # retried has not finished yet, so only the terminal outcome
            # counts. Otherwise one hard task would deflate an agent's record
            # three times over.
            will_retry = (task["status"] == "failed"
                          and task.get("attempt", 1) <= self.max_task_retries)
            if not will_retry:
                memory.record_outcome(
                    home, slug, domain,
                    success=(task["status"] == "done"),
                    verified=bool(task.get("done_check")),
                    task_id=task["id"],
                    note=(task.get("summary") or task.get("error") or "")[:200])
                # work that PASSED ITS GATE closes any case it matches: the
                # same mechanical evidence that let it finish is the evidence
                # that the problem is solved
                if task["status"] == "done":
                    try:
                        import cases
                        closed = cases.record_fix(self.root, task)
                        if closed:
                            self.log.info(json.dumps({
                                "event": "case_fixed", "task": task["id"],
                                "cases": [c["case"] for c in closed]}))
                    except Exception as e:
                        self.log.error(json.dumps({"event": "case_failed",
                                                   "error": str(e)}))
            if task["status"] == "failed":
                rec = memory.record_failure(home, slug, task)
                # the same failure, written where it will bite again: a
                # gotcha line scoped to the course or the MCP server, so the
                # next matching task is warned before it repeats the mistake
                # a failure opens a CASE: the ledger that tracks whether the
                # eventual fix actually held (cases.py)
                try:
                    import cases
                    c = cases.open_case(self.root, task, rec)
                    if c and c.get("event") == "recurred":
                        self.log.info(json.dumps({
                            "event": "case_recurred", "task": task["id"],
                            "case": c.get("case")}))
                except Exception as e:
                    self.log.error(json.dumps({"event": "case_failed",
                                               "error": str(e)}))
                try:
                    import gotchas
                    files = gotchas.from_failure(self.root, task, rec)
                    if files:
                        self.log.info(json.dumps({
                            "event": "gotcha_filed", "task": task["id"],
                            "category": rec["category"], "files": files}))
                except Exception as e:
                    self.log.error(json.dumps({"event": "gotcha_failed",
                                               "error": str(e)}))
                if rec["recurrence"] > 1:
                    self.log.info(json.dumps({
                        "event": "failure_recurred", "task": task["id"],
                        "category": rec["category"],
                        "times": rec["recurrence"]}))
        except Exception as e:      # memory must never break the loop
            self.log.error(json.dumps({"event": "memory_file_failed",
                                       "error": str(e)}))

    def _prospective_tick(self):
        """Fire due future intentions (prospective memory). Deterministic and
        cheap — a tiny ledger read at most every 20s — and firing just queues
        a normal gated task, so a fired intention earns no shortcuts."""
        now = time.time()
        # a 24/7 loop checks every 20s; a --drain run must check on EVERY
        # idle tick, or a workflow's next stage would never fire before
        # the drain declares itself complete
        throttle = 0 if getattr(self, "_drain_mode", False) else 20
        if now - getattr(self, "_pm_last", 0) < throttle:
            return False
        self._pm_last = now
        try:
            return prospective.check(self.root, self) > 0
        except Exception as e:
            self.log.error(json.dumps({"event": "prospective_check_failed",
                                       "error": str(e)}))
            return False

    def _maybe_queue_chain(self, task):
        """Pipeline chaining: [agent.chain] maps a finished role to the next
        role, e.g. ripper -> watcher, so ingested material is studied without
        a human queuing the follow-up."""
        if task["status"] != "done":
            return
        next_role = self.chain.get(task["role"])
        if not next_role:
            return
        self.add_task(
            next_role,
            f"Pipeline continuation: the {task['role']} task {task['id']} "
            f"finished (summary: {truncate(task.get('summary') or '', 300)}). "
            f"Its goal was: {truncate(task['goal'], 300)}. "
            f"Do your role's work on its outputs.",
            course=task.get("course"),
        )
        self.log.info(json.dumps({"event": "chain_queued", "after_task": task["id"],
                                  "role": next_role}))

    def _maybe_queue_reflection(self, task):
        """Part 9 mechanism 2: the Reflector runs after each execution task."""
        if task["status"] != "done":
            return
        if task["role"] == "reflector" or task["role"] not in self.reflect_after:
            return
        self.add_task(
            "reflector",
            f"Reflect on completed task {task['id']} (role {task['role']}). "
            f"Its step log is in {task['context_ref']}. Read it, then update "
            f"lessons-learned.md, the matching skills/ playbook, and reputation.md.",
            course=task.get("course"),
        )
        self.log.info(json.dumps({"event": "reflection_queued", "after_task": task["id"]}))

    def heartbeat(self, task=None, note=""):
        """A liveness pulse. A loop wedged inside a slow provider call looks
        identical to a healthy idle one from outside — this is what tells the
        panel and the doctor the difference."""
        try:
            atomic_write_json(os.path.join(self.logs_dir, "heartbeat.json"), {
                "ts": time.time(),
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "pid": os.getpid(),
                "task": (task or {}).get("id"),
                "role": (task or {}).get("role"),
                "step": n_steps(task) if task else 0,
                "note": note,
            })
        except OSError:
            pass

    def _health_ritual(self):
        """Begin every session by checking the world before doing new work
        (the long-running-agent discipline): settings, prompts, ledgers,
        locks, disk — in milliseconds, with no model. The result is written
        where the panel and the doctor read it, and never stops the loop:
        a loop that refuses to start cannot repair anything."""
        try:
            import harness
            h = harness.integrity(self.root)
            atomic_write_json(os.path.join(self.logs_dir, "health.json"), h)
            try:
                atomic_write_json(os.path.join(self.logs_dir, "harness.json"),
                                  harness.manifest(self.root))
            except Exception as e:
                self.log.error(json.dumps({"event": "harness_manifest_failed",
                                           "error": str(e)[:200]}))
            self.log.info(json.dumps({"event": "health_ritual", "ok": h["ok"],
                                      "problems": len(h["problems"]),
                                      "ms": h["ms"]}))
            self.heartbeat(note="health:ok" if h["ok"]
                           else f"health:{len(h['problems'])} problems")
            return h
        except Exception as e:
            self.log.error(json.dumps({"event": "health_ritual_failed",
                                       "error": str(e)[:200]}))
            return None

    def run(self, drain=False):
        self.log.info(json.dumps({"event": "agent_start", "root": self.root, "drain": drain}))
        self._drain_mode = drain
        self._health_ritual()
        self.heartbeat(note="started")
        while True:
            if self._budget_exceeded():
                if drain:
                    self.log.info(json.dumps({"event": "drain_budget_stop"}))
                    self.heartbeat(note="drain_budget_stop")
                    return
                time.sleep(self.poll_interval)
                continue
            state = self.load_state()
            task = self.next_task(state)
            if task is None:
                self.heartbeat(note="idle")
                if (self._prospective_tick() or self._inbox_tick()
                        or self._gap_tick() or self._exam_tick()
                        or self._reexam_tick()):
                    continue
                if drain:
                    self.log.info(json.dumps({"event": "drain_complete"}))
                    self.heartbeat(note="drain_complete")
                    return
                time.sleep(self.poll_interval)
                continue
            if task["status"] == "queued":
                claimed = self.claim_task(task["id"])
                if claimed is None:
                    continue      # another loop claimed it between read and now
                task = claimed
                self.acquire_lock(task)
                self.log.info(json.dumps({
                    "event": "task_start", "task": task["id"],
                    "role": task["role"], "course": task.get("course"),
                }))
            else:
                # resumed running task: prove it is abandoned and take
                # ownership under the mutex before touching it, exactly as
                # the queued path does. Losing the race is not an error —
                # it means a sibling got there first, so look for other work.
                adopted = self.adopt_task(task["id"])
                if adopted is None:
                    continue
                task = adopted
                self.acquire_lock(task)
                self.log.info(json.dumps({
                    "event": "task_resumed", "task": task["id"],
                    "role": task["role"], "steps": n_steps(task),
                }))
            while task["status"] == "running":
                try:
                    self.heartbeat(task, note="working")
                    if not self.run_task_step(state, task):
                        break
                except Exception:
                    # an unexpected error fails the task, never the daemon
                    task["status"] = "failed"
                    task["error"] = "internal error:\n" + traceback.format_exc(limit=5)
                    self.commit_task(task)
                    self.log.error(json.dumps({"event": "step_crash",
                                               "task": task["id"],
                                               "error": task["error"]}))
                    break
            self.release_lock(task)
            self.log.info(json.dumps({
                "event": "task_end", "task": task["id"],
                "status": task["status"], "steps": n_steps(task),
                "cost_usd": task["cost_usd"],
            }))
            self._file_memory(task)
            self._maybe_queue_chain(task)
            self._maybe_queue_reflection(task)
            self._maybe_retry(task)


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run the agent loop")
    p_run.add_argument("--drain", action="store_true",
                       help="exit when no queued or running tasks remain")
    p_run.add_argument("--root", default=".")

    p_add = sub.add_parser("add", help="queue a task")
    p_add.add_argument("--role", required=True)
    p_add.add_argument("--goal", required=True)
    p_add.add_argument("--course", default=None,
                       help="course name; enables the single-writer lock and "
                            "auto-loads the course's mission.md and index.md")
    p_add.add_argument("--done-check", default=None, dest="done_check",
                       help="shell command that must exit 0 before finish_task "
                            "is accepted — the definition of done, enforced")
    p_add.add_argument("--memory", action="append", default=[],
                       help="memory file (relative to root) to load into context")
    p_add.add_argument("--root", default=".")
    p_add.add_argument("--stop-criteria", default=None, dest="stop_criteria",
                       help="what must be true for the loop to stop")
    p_add.add_argument("--max-attempts", type=int, default=None, dest="max_attempts")
    p_add.add_argument("--deadline", default=None,
                       help="ISO timestamp after which the task fails")
    p_add.add_argument("--max-steps", type=int, default=None, dest="max_steps")

    p_st = sub.add_parser("status", help="show the task queue")
    p_st.add_argument("--root", default=".")

    p_co = sub.add_parser("course", help="exit-criterion report for a course")
    p_co.add_argument("name")
    p_co.add_argument("--root", default=".")

    p_an = sub.add_parser("answer", help="answer a blocked task's question and requeue it")
    p_an.add_argument("task_id")
    p_an.add_argument("--text", required=True)
    p_an.add_argument("--root", default=".")

    p_ck = sub.add_parser("check", help="probe every role's provider with one live request")
    p_ck.add_argument("--root", default=".")

    args = ap.parse_args()
    agent = Agent(args.root)

    if args.cmd == "run":
        agent.run(drain=args.drain)
    elif args.cmd == "add":
        tid = agent.add_task(args.role, args.goal, args.memory, args.course,
                             done_check=args.done_check,
                             stop={"criteria": args.stop_criteria,
                                   "max_attempts": args.max_attempts,
                                   "deadline": args.deadline,
                                   "max_steps": args.max_steps})
        print(f"queued task {tid}")
    elif args.cmd == "status":
        for t in agent.load_state()["tasks"]:
            course = t.get("course") or "-"
            print(f"{t['id']}  {t['status']:<8} {t['role']:<12} {course:<12} "
                  f"steps={n_steps(t):<4} ${t['cost_usd']:<9} {t['goal'][:56]}")
    elif args.cmd == "answer":
        agent.answer_task(args.task_id, args.text)
        print(f"task {args.task_id} unblocked and requeued")
    elif args.cmd == "check":
        rows, ok = agent.check_providers()
        for role, prov, model, status in rows:
            print(f"{role:<14} {prov:<12} {model:<36} {status}")
        print("\nall providers OK" if ok else "\nSOME PROVIDERS FAILED — fix before running")
        sys.exit(0 if ok else 1)
    elif args.cmd == "course":
        s = agent.course_status(args.name)
        print(f"course:   {s['course']}")
        print(f"spec:     {s['spec_pass']}/{s['spec_total']} PASS"
              + (f"  (missing: {', '.join(s['spec_missing'][:10])})" if s['spec_missing'] else ""))
        print(f"gaps:     {s['gaps_open']} open")
        print(f"exam:     {s['score'] if s['score'] is not None else 'no score'}"
              f" (threshold {s['threshold']})")
        print(f"status:   {'COMPLETE' if s['complete'] else 'IN PROGRESS'}")


if __name__ == "__main__":
    main()
