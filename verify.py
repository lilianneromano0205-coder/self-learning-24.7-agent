#!/usr/bin/env python3
"""Mechanical spec verification — layer 1 of the hierarchy (Part 8).

Spec items in courses/<name>/spec.md may carry an embedded check command:

    R-014 [from C-0701]: retry uses exponential backoff CHECK: python -m pytest tests/test_retry.py -q
    R-016: health endpoint returns 200 CHECK: curl -sf localhost:8080/health

Everything after ' CHECK: ' runs as a shell command from the agent root;
exit 0 = PASS, anything else = FAIL. No model opinion involved. Items without
a CHECK are listed as NOT MECHANICAL — those are the Examiner's to grade.

Results are written into the '## Mechanical checks' section of
courses/<name>/exam-results.md (replacing the previous run's section) and
printed. Exit code: 0 if no mechanical check failed, 1 otherwise.

Usage:  python verify.py <course> [--root DIR] [--timeout SECONDS]
"""

import argparse
import os
import re
import subprocess
import sys
import time

SECTION = "## Mechanical checks"
ITEM_RE = re.compile(r"^\s*(R-[\w.]+)\s*(?:\[[^\]]*\])?\s*:\s*(.+)$")


def parse_spec(path):
    """Yield (rid, description, check_command_or_None)."""
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return items
    for line in lines:
        m = ITEM_RE.match(line)
        if not m:
            continue
        rid, rest = m.group(1), m.group(2)
        if " CHECK: " in rest:
            desc, cmd = rest.split(" CHECK: ", 1)
            items.append((rid, desc.strip(), cmd.strip()))
        else:
            items.append((rid, rest.strip(), None))
    return items


def run_checks(items, root, timeout):
    """CHECK commands come from spec.md, which the WATCHER writes — they are
    model-authored, so they run under the same containment as any other
    model-authored command: policy screens them, and the sandbox scrubs the
    environment so a spec item cannot read the harness's provider keys.
    Falls back to a plain run only if those modules are unavailable (verify.py
    is also used standalone, outside an expert)."""
    results = []
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    cfg = {}
    try:
        import tomllib
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            cfg = tomllib.loads(f.read().decode("utf-8-sig"))
    except (OSError, ValueError, ImportError):
        pass
    for rid, desc, cmd in items:
        if cmd is None:
            results.append((rid, "NOT MECHANICAL", ""))
            continue
        try:
            import execution
            rc, out, err = execution.run("gate", cmd, root, cfg=cfg,
                                         role="examiner", timeout=timeout,
                                         reason=f"spec item {rid}")
            verdict = "PASS" if rc == 0 else "FAIL"
            body = ((out or "") + (err or "")).strip()
            evidence = (f"exit={rc}; " + body.splitlines()[0][:160]
                        if body else f"exit={rc}")
        except Exception as e:
            verdict, evidence = "FAIL", str(e)[:160]
        results.append((rid, verdict, evidence))
    return results


def write_results(course_dir, results):
    path = os.path.join(course_dir, "exam-results.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        content = ""
    # drop the previous mechanical section (up to the next ## or EOF)
    content = re.sub(rf"{re.escape(SECTION)}.*?(?=\n## |\Z)", "", content,
                     flags=re.S).rstrip()
    lines = [SECTION, f"Run: {time.strftime('%Y-%m-%d %H:%M:%S')} (verify.py)", ""]
    for rid, verdict, evidence in results:
        lines.append(f"- {rid}: {verdict}" + (f" — {evidence}" if evidence else ""))
    new = (content + "\n\n" if content else "") + "\n".join(lines) + "\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("course")
    ap.add_argument("--root", default=".")
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    course_dir = os.path.join(root, "courses", args.course)
    items = parse_spec(os.path.join(course_dir, "spec.md"))
    if not items:
        print(f"no spec items found in courses/{args.course}/spec.md")
        sys.exit(1)

    results = run_checks(items, root, args.timeout)
    write_results(course_dir, results)

    counts = {"PASS": 0, "FAIL": 0, "NOT MECHANICAL": 0}
    for rid, verdict, evidence in results:
        counts[verdict] += 1
        print(f"{rid}: {verdict}" + (f" — {evidence}" if evidence else ""))
    print(f"\n{counts['PASS']} PASS, {counts['FAIL']} FAIL, "
          f"{counts['NOT MECHANICAL']} left for the Examiner")
    sys.exit(1 if counts["FAIL"] else 0)


if __name__ == "__main__":
    main()
