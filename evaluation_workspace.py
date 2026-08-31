"""Trusted, disposable evaluation snapshots; never copy credentials or prior outputs."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import time

BASE = ("settings.toml", "prompts", "scripts", "script.json", "mission.json", "mission.md", "capabilities")
PERSISTENT = ("courses", "research", "memory", "skills", "runbooks", "commons", "gotchas.json", "selfmodel.json")


def copy_snapshot(source, destination, persistent=True):
    source, destination = Path(source), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name in BASE + (PERSISTENT if persistent else ()):
        item = source / name
        if not item.exists():
            continue
        if item.is_symlink() or any(p.is_symlink() for p in item.rglob("*")):
            raise ValueError("evaluation snapshot refuses symlinks")
        if item.is_dir():
            shutil.copytree(item, destination / name)
        elif item.is_file():
            shutil.copy2(item, destination / name)
    return digest(destination)


def digest(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def _detach_log_handlers(under):
    """Close every logging handler whose file lives under `under`.

    loop.Agent._setup_logging attaches a RotatingFileHandler per root and
    nothing closes it; an in-process evaluation therefore leaves an open
    handle inside the arena, and on Windows that handle makes the teardown
    rmtree fail with WinError 32. Same defect and same fix as memory.retire
    (memory.py's retire walks loggerDict for exactly this reason)."""
    import logging
    prefix = os.path.realpath(under)
    for logger in list(logging.Logger.manager.loggerDict.values()):
        for handler in list(getattr(logger, "handlers", ())):
            base = getattr(handler, "baseFilename", None)
            if base and os.path.realpath(base).startswith(prefix):
                try:
                    handler.close()
                except Exception:
                    pass
                logger.removeHandler(handler)


@contextmanager
def arena(source, expert="student", persistent=True):
    temp = tempfile.mkdtemp(prefix="sealed-evaluation-")
    try:
        home = Path(temp)
        root = home / "experts" / expert
        snapshot_hash = copy_snapshot(source, root, persistent)
        yield str(home), str(root), snapshot_hash
    finally:
        _detach_log_handlers(temp)
        for _ in range(5):            # OneDrive/antivirus can hold a beat
            shutil.rmtree(temp, ignore_errors=True)
            if not os.path.exists(temp):
                break
            time.sleep(0.2)
        if os.path.exists(temp):      # a leftover sealed arena is a leak,
            shutil.rmtree(temp)       # so the last attempt may raise


def fixture(root, files):
    base = Path(root).resolve()
    for name, content in files.items():
        rel = Path(name)
        target = (base / rel).resolve()
        if rel.is_absolute() or ".." in rel.parts or not target.is_relative_to(base):
            raise ValueError("fixture path escapes evaluation workspace")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
