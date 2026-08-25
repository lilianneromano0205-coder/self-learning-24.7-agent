#!/usr/bin/env python3
"""THE GRADERS THEMSELVES ARE GRADED.

A benchmark whose checks are wrong is worse than no benchmark: it produces a
number, the number moves, and nobody can tell whether the system improved or
the grader was broken. So before any score from evalsuite.py means anything,
every check in it has to be shown to do two things:

  1. PASS on a known-correct answer   (or the task is impossible and every
     score is depressed by a bug in the exam)
  2. FAIL on a known-wrong answer     (or the task is free and every score is
     inflated by a check that cannot say no)

Both directions, for all 24 tasks. A check that only ever passes is exactly
the dead check this project found in its own packaging test — three ways
worked, the fourth had never once evaluated true.

Also asserted: the split is real (no id appears in both halves), and the
statistics are honest — a 12-task split cannot resolve small differences, and
the module says so rather than printing a bare percentage.

Run from the agent/ directory:  python tests/test_evalsuite.py
"""

import os
import subprocess
import sys
import tempfile

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import evalsuite               # noqa: E402

PY = sys.executable

# A correct answer for every task, and a wrong one. Written by hand, because
# the point is to test the CHECK — generating the answer from the check would
# prove nothing at all.
ANSWERS = {
    "structured-json":     ('eval/out/cfg.json', '{"host": "db1", "port": 8080}',
                            '{"host": "db1", "port": 8080, "extra": 1}'),
    "negative-constraint": ('eval/out/notice.txt', 'This is APPROVED.',
                            'This is APPROVED but still a DRAFT.'),
    "citation-required":   ('eval/out/claim.md', 'Caches revalidate [src: rfc9111 section 4].',
                            'Caches revalidate, obviously.'),
    "csv-sum":             ('eval/out/total.txt', '28', '27'),
    "dedup-sorted":        ('eval/out/words.txt', 'apple\nfig\npear\n',
                            'pear\napple\nfig\n'),
    "exact-count":         ('eval/out/lines.txt', 'ok\n' * 7, 'ok\n' * 6),
    "json-nested":         ('eval/out/tree.json', '{"a": {"b": [1, 2, 3]}}',
                            '{"a": {"b": [1, 2]}}'),
    "preserve-input":      ('eval/out/keep.txt', 'line one\nline two\n\ttabbed\n',
                            'line one\nline two\n    tabbed\n'),
    "no-placeholder":      ('eval/out/readme.md',
                            ' '.join(['budget'] * 45),
                            'TODO write this later'),
    "runnable-python":     ('eval/out/add.py', 'def add(a, b):\n    return a + b\n',
                            'def add(a, b):\n    return a - b\n'),
    "ordering-matters":    ('eval/out/steps.md', 'build\ntest\ndeploy\n',
                            'test\nbuild\ndeploy\n'),
    "empty-is-valid":      ('eval/out/errors.txt', '', 'no errors found\n'),
    "h-json-keys":         ('eval/out/db.json', '{"driver": "pg", "pool": 12}',
                            '{"driver": "pg", "pool": 11}'),
    "h-forbidden-word":    ('eval/out/policy.txt', 'This is FINAL.',
                            'This is FINAL and PROVISIONAL.'),
    "h-citation":          ('eval/out/finding.md', 'Gap found [src: iso9001 clause 8].',
                            'Gap found.'),
    "h-csv-max":           ('eval/out/max.txt', '47', '33'),
    "h-dedup-reverse":     ('eval/out/ids.txt', 'a7\na3\na1\n', 'a1\na3\na7\n'),
    "h-exact-count":       ('eval/out/rows.txt', 'row\n' * 4, 'row\n' * 5),
    "h-json-nested":       ('eval/out/shape.json', '{"x": {"y": [4, 5]}}',
                            '{"x": {"y": [5, 4]}}'),
    "h-preserve":          ('eval/out/orig.txt', 'alpha\n  beta\n\tgamma\n',
                            'alpha\nbeta\ngamma\n'),
    "h-no-filler":         ('eval/out/brief.md', ' '.join(['breaker'] * 45),
                            'lorem ipsum dolor sit amet'),
    "h-runnable":          ('eval/out/mul.py', 'def mul(a, b):\n    return a * b\n',
                            'def mul(a, b):\n    return a + b\n'),
    "h-ordering":          ('eval/out/phases.md', 'plan\nbuild\nreview\n',
                            'build\nplan\nreview\n'),
    "h-empty-valid":       ('eval/out/denied.txt', '', 'none\n'),
}


def _write(root, rel, body):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(body)


def _run_check(root, task):
    r = subprocess.run([PY, "-c", task["check"]], cwd=root,
                       capture_output=True, text=True, timeout=60)
    return r.returncode


def main():
    ids = [t["id"] for t in evalsuite.SUITE]
    assert len(ids) == len(set(ids)), "duplicate task ids"
    train = {t["id"] for t in evalsuite.tasks("train")}
    hold = {t["id"] for t in evalsuite.tasks("holdout")}
    assert train and hold, "both splits must be populated"
    assert not (train & hold), (
        f"a task is in BOTH splits: {train & hold} — then the holdout is not "
        f"held out and every number from it is a number about training data")
    missing = [i for i in ids if i not in ANSWERS]
    assert not missing, f"no answer fixture written for: {missing}"

    passed_ok, failed_ok = 0, 0
    for task in evalsuite.SUITE:
        rel, right, wrong = ANSWERS[task["id"]]
        # 1. a correct answer must PASS
        root = tempfile.mkdtemp(prefix=f"ev-{task['id']}-ok-")
        for frel, body in evalsuite.fixtures_for(task).items():
            _write(root, frel, body)
        _write(root, rel, right)
        rc = _run_check(root, task)
        assert rc == 0, (
            f"{task['id']}: a hand-written CORRECT answer failed its own "
            f"check (exit {rc}). The task is impossible as written, and every "
            f"score this suite reports is depressed by a bug in the exam.")
        passed_ok += 1

        # 2. a wrong answer must FAIL
        root2 = tempfile.mkdtemp(prefix=f"ev-{task['id']}-bad-")
        for frel, body in evalsuite.fixtures_for(task).items():
            _write(root2, frel, body)
        _write(root2, rel, wrong)
        rc2 = _run_check(root2, task)
        assert rc2 != 0, (
            f"{task['id']}: a deliberately WRONG answer passed the check. "
            f"That task is free marks, and every score this suite reports is "
            f"inflated by a check that cannot say no.")
        failed_ok += 1

    print(f"[graders] all {passed_ok} checks pass a hand-written correct "
          f"answer and all {failed_ok} reject a deliberately wrong one — "
          f"both directions, because a check that only ever passes is the "
          f"dead check this project already found once in its own packaging "
          f"test")

    # the statistics must be reported honestly
    lo, hi = evalsuite.wilson(9, 12)
    assert lo < 0.60 and hi > 0.85, (
        f"a 9/12 result should carry a wide interval, got {lo:.2f}-{hi:.2f}")
    assert evalsuite.wilson(0, 0) == (0.0, 0.0), "empty must not divide by zero"
    full_lo, _ = evalsuite.wilson(12, 12)
    assert full_lo < 1.0, (
        "even a perfect 12/12 must not report a lower bound of 100% — twelve "
        "tasks cannot establish that a system never fails, and a suite that "
        "says otherwise invites exactly the 'iterate to 100%' mistake this "
        "module exists to prevent")
    print(f"[honest-stats] 9/12 reports {lo*100:.0f}%-{hi*100:.0f}%, and even "
          f"a perfect 12/12 reports a lower bound of {full_lo*100:.0f}% — "
          f"a small suite is never allowed to claim certainty")

    # and a holdout peek is COUNTED
    home = tempfile.mkdtemp(prefix="ev-ledger-")
    evalsuite.record(home, "holdout", {"code_hash": "aaa", "arm": "harness",
                                       "passed": 9, "total": 12})
    evalsuite.record(home, "holdout", {"code_hash": "bbb", "arm": "harness",
                                       "passed": 10, "total": 12})
    n, versions = evalsuite.peeks(home)
    assert n == 2 and versions == 2, (n, versions)
    assert len(evalsuite.history(home, "train")) == 0, "splits must not mix"
    print(f"[sealed] every holdout run is recorded against the code hash that "
          f"produced it — {n} looks across {versions} versions here — because "
          f"a held-out set spent without anyone counting is just training "
          f"data nobody labelled")
    print("PASS test_evalsuite")


if __name__ == "__main__":
    main()
