#!/usr/bin/env python3
"""One cross-process lock primitive for every mutating ledger.

We deliberately support several loop processes on one expert (resilience,
teams, manual runs beside a daemon). That makes every read-modify-write file
a race: measured live, two processes evaluating the same due intention fired
it TWICE — the owner's action queued double. This is the exact failure class
the state-governance research calls duplicated external effects.

Same design as the loop's state mutex, shared so every ledger gets it:
O_EXCL creation is the atomic claim; a lock older than `stale` seconds is
broken (its owner is dead or wedged — liveness probes lie on Windows, age
does not); waiting longer than `timeout` raises rather than deadlocks.
Critical sections here are milliseconds, so contention is rare and short.
"""

import os
import time
import uuid
from contextlib import contextmanager


def _token():
    """Unique per acquisition, not merely per process: a PID is reused, and
    one process can acquire the same lock twice in a lifetime."""
    return f"{os.getpid()}:{uuid.uuid4().hex}"


@contextmanager
def holding(path, timeout=10.0, stale=8.0):
    """Hold <path>.lock for the duration of the with-block.

    Release VERIFIES OWNERSHIP. It did not, and that split the mutex: if a
    holder stalled past `stale` (OneDrive sync, an antivirus scan, a suspended
    process — ordinary on this platform) a second process broke the lock and
    took it, and then the first process's `finally` deleted the SECOND
    process's lockfile, letting a third in. Two writers inside a section whose
    whole purpose is preventing duplicated external effects.

    The token was always written into the file; it was simply never read back.
    """
    lock = path + ".lock"
    mine = _token()
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, mine.encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > stale:
                    os.remove(lock)     # the holder is gone; break it
                    continue
            except OSError:
                continue                # vanished between check and remove
            if time.time() > deadline:
                raise TimeoutError(f"lock busy: {lock}")
            time.sleep(0.05)
        except PermissionError:
            # Windows only in practice: creating the lockfile while a
            # releasing holder's os.remove is still pending reports EACCES —
            # the file exists AND is going away, which is CONTENTION, not a
            # rights problem. Left unhandled, it killed a whole writer:
            # CI's 10-thread ledger hammer lost one thread and its 25 rows
            # to a single such window (and a local 12-thread hammer
            # reproduced it 2 runs in 3). A genuine rights problem persists
            # across retries, so it still surfaces — as the timeout below,
            # with EACCES named instead of a silent thread death.
            if time.time() > deadline:
                raise TimeoutError(
                    f"lock busy: {lock} (EACCES on every attempt — "
                    f"delete-pending contention or a real permission "
                    f"problem on the directory)")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            with open(lock, "r", encoding="utf-8") as f:
                held = f.read().strip()
            if held == mine:
                os.remove(lock)
            # else: our lock was broken as stale and someone else holds it
            # now — deleting it would hand the section to a third process
        except OSError:
            pass


def held_by_me(path, mine):
    """True while `mine` still owns <path>.lock. A long critical section can
    call this to notice it was broken, instead of finishing work whose
    exclusivity has already been lost."""
    try:
        with open(path + ".lock", "r", encoding="utf-8") as f:
            return f.read().strip() == mine
    except OSError:
        return False
