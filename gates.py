#!/usr/bin/env python3
"""THE GATE CATALOGUE — a definition of done you can name, not author.

`done_check` was a free-form shell string executed with `shell=True`. That is
maximum expressiveness for nothing: every gate this platform actually uses is
one of five shapes, all parameterisable. Meanwhile the free-form string was
accepted from the panel's HTTP body, and a cross-origin POST turned it into
arbitrary code execution on the owner's machine (measured, not theorised).

So the network names a gate and supplies parameters; the harness builds the
command. The catalogue is closed, the parameters are validated as contained
relative paths or course names, and nothing a caller sends becomes shell
syntax:

    {"gate": "exists", "path": "out/index.html"}
    {"gate": "designcheck", "path": "out/index.html"}
    {"gate": "citecheck", "path": "consults/c-1/answer.md"}
    {"gate": "verify", "course": "design"}
    {"gate": "memcheck", "course": "design"}

`build()` returns the command string the loop will run, or raises ValueError
with a message the caller can act on. `describe()` renders the catalogue for
the panel so the owner picks from a list instead of typing a command.

The CLI keeps free-form gates: an operator with a terminal already has a shell,
so refusing them there would protect nothing. This module exists to stop a
REMOTE caller from reaching one.
"""

import os
import re
import sys

HOME = os.path.dirname(os.path.abspath(__file__))

# a parameter may name a file inside the expert, and nothing else: no quotes,
# no shell metacharacters, no absolute paths, no traversal, no leading dot
_PATH_RE = re.compile(r"[A-Za-z0-9_.\-/]{1,200}")
_COURSE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def _rel_path(value, what="path"):
    """A contained relative path, or ValueError. Mirrors loop._safe_path's
    rule, but on the string alone — this runs before any file exists."""
    v = str(value or "").strip().replace("\\", "/")
    if not v:
        raise ValueError(f"the '{what}' parameter is required")
    if not _PATH_RE.fullmatch(v):
        raise ValueError(
            f"'{what}' may contain only letters, digits, dot, dash, "
            f"underscore and '/' — got {value!r}")
    if v.startswith("/") or re.match(r"^[A-Za-z]:", v):
        raise ValueError(f"'{what}' must be relative to the expert, not absolute")
    parts = [p for p in v.split("/") if p]
    if any(p == ".." for p in parts) or any(p.startswith(".") for p in parts):
        raise ValueError(f"'{what}' must stay inside the expert ({value!r})")
    return "/".join(parts)


def _course(value):
    v = str(value or "").strip().lower()
    if not _COURSE_RE.fullmatch(v):
        raise ValueError(f"'course' must be a simple course name, got {value!r}")
    return v


def _py():
    return f'"{sys.executable}"'


def _tool(name):
    return f'"{os.path.join(HOME, name)}"'


def _exists(rel):
    """An existence gate built from a Python literal, never string-spliced:
    repr() escapes whatever the path contains, and the path is validated
    above anyway. Belt and braces, because this is the gate everything else
    falls back to."""
    return (f'{_py()} -c "import os,sys;sys.exit(0 if os.path.exists('
            f'{rel!r}) else 1)"')


CATALOGUE = {
    "exists": {
        "needs": ("path",),
        "what": "the deliverable file exists",
        "build": lambda p: _exists(_rel_path(p.get("path"))),
    },
    "designcheck": {
        "needs": ("path",),
        "what": "the interface passes the design gate (contrast, scale, "
                "semantics, the filler tells)",
        "build": lambda p: (f'{_py()} {_tool("designcheck.py")} '
                            f'"{_rel_path(p.get("path"))}"'
                            + (f' --root . --course {_course(p["course"])}'
                               if p.get("course") else "")),
    },
    "citecheck": {
        "needs": ("path",),
        "what": "every atom the answer cites is defined in the notes",
        "build": lambda p: (f'{_py()} {_tool("citecheck.py")} '
                            f'"{_rel_path(p.get("path"))}" --root .'),
    },
    "verify": {
        "needs": ("course",),
        "what": "the course's CHECK commands in spec.md all pass",
        "build": lambda p: (f'{_py()} {_tool("verify.py")} '
                            f'{_course(p.get("course"))} --root .'),
    },
    "memcheck": {
        "needs": ("course",),
        "what": "the course's memory is internally sound (ids, citations, "
                "spec grounding, index coverage)",
        "build": lambda p: (f'{_py()} {_tool("memcheck.py")} '
                            f'{_course(p.get("course"))} --root .'),
    },
}


def build(spec):
    """spec -> a done_check command string.

    Accepts {"gate": name, ...params}. Returns None for an empty spec (a task
    with no gate is legal — the gate only exists where you declared what done
    means). Raises ValueError for anything outside the catalogue.
    """
    if spec in (None, "", {}):
        return None
    if not isinstance(spec, dict):
        raise ValueError(
            "a done_check from the network must be an object naming a gate, "
            f"e.g. {{\"gate\": \"exists\", \"path\": \"out/index.html\"}} — "
            f"got {type(spec).__name__}. Free-form shell gates are accepted "
            f"from the CLI only.")
    name = str(spec.get("gate") or "").strip().lower()
    if name not in CATALOGUE:
        raise ValueError(
            f"unknown gate {name!r}; the catalogue is: "
            f"{', '.join(sorted(CATALOGUE))}")
    entry = CATALOGUE[name]
    for need in entry["needs"]:
        if not spec.get(need):
            raise ValueError(f"gate '{name}' needs a '{need}' parameter")
    return entry["build"](spec)


def describe():
    """The catalogue, for the panel's gate picker."""
    return [{"gate": k, "needs": list(v["needs"]), "what": v["what"]}
            for k, v in sorted(CATALOGUE.items())]


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser(description="the done-check gate catalogue")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--build", help='a gate spec as JSON, e.g. '
                                    '\'{"gate":"exists","path":"out/x.html"}\'')
    a = ap.parse_args()
    if a.build:
        print(build(json.loads(a.build)))
        return
    if a.json:
        print(json.dumps(describe(), indent=1))
        return
    for row in describe():
        print(f"{row['gate']:<14} needs {', '.join(row['needs']):<8} "
              f"— {row['what']}")


if __name__ == "__main__":
    main()
