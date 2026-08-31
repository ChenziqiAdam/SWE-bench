"""Recover terminal-success Gemini patches rejected by a superseded tool policy."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from swebench.eval_pipeline.inference import _clean_patch, _extract_diff, _repair_patch
from swebench.issue_pipeline.offline_codex_run import _canonical_hash
from swebench.issue_pipeline.offline_gemini_pilot import SAFE_CORE_TOOLS, audit_trajectory


RECOVERY_VERSION = 2
RECOVERABLE_ERRORS = {"attempted_network", "antigravity_result_error"}


def _jsonl_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _jsonl_text(rows: list[dict]) -> str:
    return "".join(json.dumps(row) + "\n" for row in rows)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _patch_paths(patch: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"^diff --git a/(.*?) b/", patch, re.MULTILINE)))


def _repair_terminal_patch(patch: str) -> str:
    """Repair malformed new-file diffs observed in terminal result payloads."""
    lines = patch.splitlines()
    repaired: list[str] = []
    new_file = False
    in_hunk = False
    for line in lines:
        if line.startswith("diff --git "):
            new_file = False
            in_hunk = False
        elif line == "new file mode 100644":
            new_file = True
        elif line.startswith("@@"):
            in_hunk = True
        if new_file and repaired and repaired[-1] == "--- /dev/null" and line.startswith("+--- b/"):
            line = "+++ b/" + line[len("+--- b/"):]
        elif new_file and in_hunk and line == "":
            line = "+"
        repaired.append(line)
    return _repair_patch("\n".join(repaired) + "\n")


def _validate_patch_syntax(patch: str) -> None:
    result = subprocess.run(
        ["git", "apply", "--numstat", "--recount", "-"],
        input=patch,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or "git could not parse patch"
        raise ValueError(f"terminal diff is malformed: {detail}")


def _terminal_result(trajectory: str) -> dict:
    results = []
    for line in trajectory.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == "result":
            result = event.get("result")
            if isinstance(result, dict):
                results.append(result)
    if not results:
        raise ValueError("trajectory has no terminal result")
    return results[-1]


def recover_prediction(row: dict, trajectory: str) -> tuple[dict, dict]:
    """Return a recovered copy only when all no-inference recovery gates pass."""
    if (row.get("model_patch") or "").strip():
        raise ValueError("prediction already has a patch")
    original_error = row.get("error")
    if original_error not in RECOVERABLE_ERRORS:
        raise ValueError("original error is not recoverable from a terminal diff")

    audit = row.get("offline_audit") or {}
    original_findings = audit.get("network_findings") or []
    reclassified_tools: set[str] = set()
    if original_error == "attempted_network":
        if not original_findings:
            raise ValueError("original audit has no findings")
        reclassified_tools = {
            str(finding.get("evidence", "")).split(":", 1)[0].lower()
            for finding in original_findings
            if finding.get("kind") == "forbidden_tool"
        }
        if (
            len(reclassified_tools) == 0
            or any(finding.get("kind") != "forbidden_tool" for finding in original_findings)
            or not reclassified_tools.issubset(set(SAFE_CORE_TOOLS))
        ):
            raise ValueError("original findings are not reclassifiable local tools")
    elif original_findings:
        raise ValueError("terminal-error recovery has unresolved audit findings")
    if audit_trajectory(trajectory):
        raise ValueError("trajectory still violates the current safety policy")
    if audit.get("disallowed_paths"):
        raise ValueError("original audit has disallowed patch paths")

    result = _terminal_result(trajectory)
    terminal_status = str(result.get("status", "")).upper()
    if terminal_status not in {"SUCCESS", "ERROR"}:
        raise ValueError("trajectory has no recoverable terminal state")
    patch = _repair_terminal_patch(
        _clean_patch(_extract_diff(str(result.get("response") or "")))
    )
    if not patch.strip():
        raise ValueError("terminal response has no recoverable patch")

    patch_paths = _patch_paths(patch)
    changed_paths = list(audit.get("changed_paths") or [])
    if not changed_paths:
        raise ValueError("original runner captured no final changed paths")
    if sorted(patch_paths) != sorted(changed_paths):
        raise ValueError(
            f"terminal diff paths do not match captured paths: "
            f"diff={patch_paths}, captured={changed_paths}"
        )
    _validate_patch_syntax(patch)

    recovered = json.loads(json.dumps(row))
    provenance = {
        "version": RECOVERY_VERSION,
        "method": "terminal_final_diff",
        "no_inference": True,
        "trajectory_sha256": row["trajectory_sha256"],
        "original_error": original_error,
        "terminal_status": terminal_status,
        "terminal_error": result.get("error"),
        "original_audit_sha256": _canonical_hash(audit),
        "original_network_findings": original_findings,
        "reclassified_local_tools": sorted(reclassified_tools),
        "policy_reclassification": (
            "legacy local tool now allowed by frozen agy policy"
            if reclassified_tools
            else "terminal infrastructure error occurred after final patch capture"
        ),
        "patch_paths": patch_paths,
    }
    recovered["model_patch"] = patch
    recovered["automatic_error"] = recovered.pop("error")
    recovered["offline_audit"].update(
        status="passed",
        network_findings=[],
        recovery=provenance,
    )
    recovered["recovered_old_inference"] = True
    return recovered, provenance


def recover_run(run_dir: Path) -> dict:
    source_path = run_dir / "agent_predictions.jsonl"
    rows = _jsonl_rows(source_path)
    recovered_rows = []
    recovered_cases = []
    skipped = {}
    for row in rows:
        candidate = json.loads(json.dumps(row))
        if not candidate.get("model_patch") and candidate.get("error") in RECOVERABLE_ERRORS:
            trajectory_path = run_dir / candidate["offline_audit"]["trajectory_path"]
            trajectory = trajectory_path.read_text()
            digest = _sha256(trajectory.encode())
            if digest != candidate.get("trajectory_sha256"):
                raise ValueError(f"trajectory hash mismatch for {candidate['instance_id']}")
            try:
                candidate, provenance = recover_prediction(candidate, trajectory)
            except ValueError as exc:
                skipped[candidate["instance_id"]] = str(exc)
            else:
                recovered_cases.append(
                    {"instance_id": candidate["instance_id"], **provenance}
                )
        recovered_rows.append(candidate)

    output_path = run_dir / "agent_predictions.recovered.jsonl"
    selected_path = run_dir / "agent_predictions.recovered.selected.jsonl"
    output_text = _jsonl_text(recovered_rows)
    output_path.write_text(output_text)
    selected_path.write_text(output_text)
    report = {
        "recovery_version": RECOVERY_VERSION,
        "source_path": source_path.name,
        "source_sha256": _sha256(source_path.read_bytes()),
        "output_path": output_path.name,
        "output_sha256": _sha256(output_text.encode()),
        "no_inference": True,
        "total_predictions": len(rows),
        "original_nonempty": sum(bool(row.get("model_patch", "").strip()) for row in rows),
        "recovered_count": len(recovered_cases),
        "final_nonempty": sum(
            bool(row.get("model_patch", "").strip()) for row in recovered_rows
        ),
        "recovered_cases": recovered_cases,
        "skipped_recovery_cases": skipped,
    }
    (run_dir / "gemini_recovery_report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    report = recover_run(args.run_dir)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
