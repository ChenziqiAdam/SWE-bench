#!/usr/bin/env python3
"""Deterministic test-only scorer for the DeepChem sanitizer task (SANITIZER.md 9).

    python evaluate_submission.py --repo <instrumented checkout> --patch sub.diff \
        --python <interpreter> [--out result.json] [--timeout 600]

Pipeline: fresh checkout of the frozen commit -> validate the patch (approved
test locations only, no use of the checker module / log) -> apply -> run only
the submitted test files with sanitizer logging -> keep triggers from tests that
passed -> deduplicate to IDs and root-cause families -> result record.
The two banks are never summed; this runner scores the scientific bank only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEST_FILE = re.compile(r"^deepchem/(?:[\w.]+/)*(?:tests?|test)/(?:[\w.]+/)*test_[\w.]+\.py$")
TEST_DATA = re.compile(r"^deepchem/(?:[\w.]+/)*(?:tests?|test)/(?:assets|data)/[\w./-]+$")
# a test may not touch the instrumentation or forge its output (SANITIZER.md 9.1)
FORBIDDEN = re.compile(
    r"_scientific_checkers|SCIBENCH_|SCIENTIFIC_CHECKERS|trigger_if|"
    r"checker_id|trigger_log|sanitizers\.json", re.I)


def run(cmd, **kw):
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def patch_files(patch: str) -> list[str]:
    files = []
    for m in re.finditer(r"^diff --git a/(\S+) b/(\S+)$", patch, re.M):
        files.append(m.group(2))
    return files


def added_lines(patch: str) -> list[str]:
    return [l[1:] for l in patch.splitlines()
            if l.startswith("+") and not l.startswith("+++")]


def validate(patch: str) -> tuple[list[str], list[str]]:
    """Return (test_files, violations)."""
    violations, tests = [], []
    files = patch_files(patch)
    if not files:
        violations.append("patch touches no files")
    for f in files:
        if TEST_FILE.match(f):
            tests.append(f)
        elif TEST_DATA.match(f):
            continue
        else:
            violations.append(f"path outside approved test locations: {f}")
    for line in added_lines(patch):
        if FORBIDDEN.search(line):
            violations.append(f"forbidden reference in added line: {line.strip()[:100]}")
    if re.search(r"^(deleted file mode|rename from)", patch, re.M):
        violations.append("deleting or renaming files is not allowed")
    return tests, violations


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--patch", type=Path, required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--manifest", type=Path, default=HERE / "sanitizers.json")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--timeout", type=int, default=900, help="total seconds")
    ap.add_argument("--test-timeout", type=int, default=120, help="seconds per test")
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text())
    family = {s["id"]: s["family"] for s in manifest["sanitizers"]}
    patch = args.patch.read_text()
    tests, violations = validate(patch)
    record = {"patch": str(args.patch), "violations": violations, "tests": [],
              "triggered_ids": [], "triggered_families": []}
    if violations:
        record["status"] = "rejected"
        return finish(record, args.out)

    work = Path(tempfile.mkdtemp(prefix="dc_eval_"))
    try:
        # fresh checkout of the frozen commit (no working-tree state is reused)
        head = run(["git", "-C", str(args.repo), "rev-parse", "HEAD"]).stdout.strip()
        record["commit"] = head
        shutil.rmtree(work)
        clone = run(["git", "clone", "-q", "--no-hardlinks", str(args.repo), str(work)])
        if clone.returncode:
            record.update(status="error", error=clone.stderr[-500:])
            return finish(record, args.out)
        run(["git", "-C", str(work), "checkout", "-q", head])
        apply = run(["git", "-C", str(work), "apply", "--whitespace=nowarn", "-"],
                    input=patch)
        if apply.returncode:
            record.update(status="rejected", violations=["patch does not apply: " +
                                                         apply.stderr[-300:]])
            return finish(record, args.out)

        log = work / "sanitizer_trigger_log.jsonl"
        result_json = work / "per_test.json"
        log.write_text("")
        env = dict(os.environ, SCIBENCH_TRIGGER_LOG=str(log),
                   SCIBENCH_RESULT_JSON=str(result_json),
                   PYTHONPATH=os.pathsep.join([str(work), str(HERE)]))
        env.pop("SCIBENCH_CHECKER_DEBUG", None)
        cmd = [args.python, "-W", "ignore", "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "-p", "scibench_pytest_plugin", f"--timeout={args.test_timeout}",
               "--rootdir", str(work), *tests]
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, cwd=work, env=env, text=True,
                                  capture_output=True, timeout=args.timeout)
            record["pytest_returncode"] = proc.returncode
            record["pytest_tail"] = proc.stdout[-600:]
        except subprocess.TimeoutExpired:
            record["pytest_returncode"] = "timeout"
        record["wall_seconds"] = round(time.time() - t0, 1)

        per_test = json.loads(result_json.read_text()) if result_json.exists() else []
        record["tests"] = [{"nodeid": r["nodeid"], "passed": r["passed"],
                            "triggers": sorted(set(r["triggers"]))} for r in per_test]
        valid = [r for r in per_test if r["passed"]]
        ids = sorted({i for r in valid for i in r["triggers"] if i in family})
        record["triggered_ids"] = ids
        record["triggered_families"] = sorted({family[i] for i in ids})
        record["n_tests"] = len(per_test)
        record["n_passed"] = len(valid)
        record["ignored_triggers_from_failed_tests"] = sorted(
            {i for r in per_test if not r["passed"] for i in r["triggers"]} - set(ids))
        record["status"] = "scored"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return finish(record, args.out)


def finish(record: dict, out: Path | None) -> int:
    text = json.dumps(record, indent=2)
    if out:
        out.write_text(text + "\n")
    print(text)
    return 0 if record.get("status") == "scored" else 1


if __name__ == "__main__":
    raise SystemExit(main())
