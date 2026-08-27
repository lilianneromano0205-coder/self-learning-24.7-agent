# Contributing to Expert Fleet

Thank you for looking under the hood. This project has a small number of
non-negotiable disciplines; everything else is open.

## The disciplines

1. **Stdlib only.** No `requirements.txt`, no `pyproject.toml`, no third-party
   imports in platform code. CI fails the build if a dependency file appears.
   (The three pinned npm packages under `deploy/worker/` are the single,
   deliberate exception — they never run on the platform host.)

2. **Additive over invasive.** Extend; don't rewrite. Existing laws, ledgers
   and file formats keep working. If a behavior must change, its test changes
   in the same commit and the commit message says why.

3. **Every claim names its test.** A feature lands with an acceptance test in
   `tests/` that *prints what it proved* (the `[section]` sentences feed
   EVIDENCE.md). Register the test in `tests/run_all.py` **and** in
   `evidence.py` SYSTEMS — an unclassified test fails the evidence build
   loudly, by design.

4. **Break it on purpose.** A passing test proves nothing unless it would
   fail with the feature removed. Load-bearing protections get a mutation
   check: break the behavior, run the test, require red, restore
   byte-for-byte. See `mutate_check.py` for the pattern.

5. **Security boundaries are code, never prompts.** New powers route through
   the five authorities (Execution, File, Credential, Model Gateway,
   Effect). `python execution.py --audit` must stay at zero violations.
   Never print or log a credential value; `credentials.py` is the single
   reader.

6. **Honesty in artifacts.** EVIDENCE.md is generated (`python evidence.py`),
   never hand-edited. Skips are a third outcome, not a pass. Blind spots are
   stated, not omitted.

## The loop

```bash
python doctor.py            # everything imports, anatomy sound
python tests/run_all.py     # the whole suite (a few minutes)
python evidence.py          # regenerate EVIDENCE.md from a real run
python execution.py --audit # no authority bypasses
```

CI runs the suite on Ubuntu and Windows across Python 3.11/3.12/3.13, plus
the mutation check on Linux. Green on all six is the bar.

## Reporting security issues

See [SECURITY.md](SECURITY.md). Please do not open public issues for
vulnerabilities.
