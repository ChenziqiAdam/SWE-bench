#!/usr/bin/env python3
"""Fail-closed promotion of 0023_core.

0023 is core-only from the start (no legacy ``scibench_replication_0023`` bundle).
G8 is a recorded WAIVER (Python-port oracle); the four-way implementation
provenance still must be present and distinct, but ``blind_submission_sha256`` may
be absent if G7 is also waived -- in which case ``validation_waivers`` must record
``G7_blind_implementation`` and the 3-way (adapter / independent / curator)
provenance must be distinct.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0023_core"
REPO = "https://github.com/djmorris7/RandomTimeShifts.jl"
PORT_COMMIT = "baf6da64fce7489503d709a9d1bc99080c5a5aa7"


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def atomic(path: Path, text: str) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path: Path, value) -> None:
    atomic(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--accept-g6-deviation",
        action="store_true",
        help="acknowledge that G6 was run via a documented protocol deviation "
        "(e.g. the codex-CLI variant, when the .env endpoint is unavailable)",
    )
    global args
    args = parser.parse_args()

    validation = json.loads((ROOT / "curation_reports/0023_core_validation.json").read_text())
    g6 = json.loads((ROOT / "core_algorithm_audits/0023_core_blind.json").read_text())
    oracle = json.loads((ROOT / "curation_reports/0023_core_oracle.json").read_text())
    g7_path = ROOT / "curation_reports/0023_core_g7.json"
    g7 = json.loads(g7_path.read_text()) if g7_path.is_file() else {}

    task = ROOT / TASK_ID
    provenance_path = task / "hidden/provenance.json"
    provenance = json.loads(provenance_path.read_text())

    if validation.get("status") != "ACCEPT" or not all(validation.get("gates", {}).values()):
        raise RuntimeError(f"validation not ACCEPT: {validation.get('hard_gate_failures')}")
    if g6.get("G6") != "PASS" or g6.get("pass_count", 0) < 2:
        raise RuntimeError("G6 blind identification not passing (>= 2/3)")
    g6_deviation = g6.get("model_selection") not in (None, "MODEL_NAME")
    if g6_deviation and not args.accept_g6_deviation:
        raise RuntimeError(
            f"G6 used a protocol deviation ({g6.get('model_selection')}); "
            "pass --accept-g6-deviation to promote anyway"
        )
    if oracle.get("G8") != "WAIVER":
        raise RuntimeError("expected a recorded G8 waiver for this task")

    waivers = ["G8_oracle_validity"]
    g7_ok = g7.get("G7") == "PASS" and g7.get("full_success") is True
    if not g7_ok:
        waivers.append("G7_blind_implementation")

    prov = oracle["provenance"]
    impls = [
        prov["official_adapter_sha256"],
        prov["independent_implementation_sha256"],
        prov["curator_reference_sha256"],
    ]
    blind_sha = None
    if g7_ok:
        blind_sha = sha(ROOT / "core_algorithm_audits/0023_core_g7_submission/solution.py")
        impls.append(blind_sha)
    if any(not v for v in impls) or len(set(impls)) != len(impls):
        raise RuntimeError("implementation provenance absent or not distinct")

    provenance["lifecycle"] = "validated"
    provenance["gold_source"] = "python_port_oracle"
    provenance["validation_waivers"] = waivers
    if blind_sha:
        provenance["blind_submission_sha256"] = blind_sha
    provenance["g6_audit"] = {
        "path": "core_algorithm_audits/0023_core_blind.json",
        "model_selection": g6.get("model_selection"),
        "configured_model": g6.get("configured_model"),
        "pass_count": g6["pass_count"],
        "independent_contexts": g6["independent_contexts_required"],
        "protocol_deviation": g6.get("protocol_deviation") if g6_deviation else None,
    }
    provenance["g7_audit"] = (
        {
            "path": "curation_reports/0023_core_g7.json",
            "model": g7.get("model"),
            "score": g7.get("score"),
            "full_success": g7.get("full_success"),
            "submission_sha256": g7.get("solution_sha256"),
        }
        if g7
        else {"status": "waiver", "reason": "no G7 run recorded; see validation_waivers"}
    )
    if g7 and not g7_ok:
        provenance["g7_audit"]["status"] = "fail"
        provenance["g7_audit"]["public_hidden_score"] = [
            g7.get("public_score", 0.0),
            g7.get("hidden_score", 0.0),
        ]
        provenance["g7_audit"]["waived"] = True
    atomic_json(provenance_path, provenance)

    manifest_path = ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if any(row["task_id"] == TASK_ID for row in manifest["tasks"]):
        raise RuntimeError("task already present in manifest")
    manifest["tasks"].append(
        {
            "task_id": TASK_ID,
            "lifecycle": "validated",
            "public_files": files(task / "public"),
            "hidden_files": files(task / "hidden"),
        }
    )

    registry_path = ROOT / "task_registry.py"
    registry = registry_path.read_text()
    marker = "}\n\nCANDIDATE_REGISTRY = {}"
    if marker not in registry or TASK_ID in registry:
        raise RuntimeError("unexpected registry state")
    row = (
        f'    "{TASK_ID}": {{"status": "validated", "repository": "{REPO}", '
        f'"commit": "{PORT_COMMIT}", "environment_file": None, '
        f'"curator_environment_file": "curation_tools/environments/0023-core-environment.yml", '
        f'"adapter_path": "curation_tools/rts_core_adapter.py", "adapter_output_is_directory": True, '
        f'"official_adapter": "Python port of RandomTimeShifts.jl (pinned commit) used as oracle under a recorded G8 waiver", '
        f'"functional_target": "random time-shift distribution of a supercritical multi-type branching process: '
        f'moment engine + bounded-error Taylor LST + recursive embedded-GF contraction + concentrated-matrix-exponential '
        f'inversion + multinomial moment aggregation", '
        f'"validation_waivers": {json.dumps(waivers)}}},\n'
    )
    registry = registry.replace(marker, row + marker)

    papers_path = ROOT / "papers.json"
    papers = json.loads(papers_path.read_text())
    matches = [
        row
        for row in papers["papers"]
        if row.get("github_url")
        in ("https://github.com/djmorris7/Computation_of_random_time-shifts", REPO)
    ]
    if len(matches) != 1 or matches[0].get("task_id") is not None:
        raise RuntimeError("unexpected papers.json entry for the random-time-shift paper")
    matches[0]["task_id"] = TASK_ID
    matches[0]["build_status"] = "validated"
    matches[0]["github_url"] = REPO
    matches[0].pop("note", None)
    papers["updated_at"] = str(date.today())

    atomic(registry_path, registry)
    atomic_json(papers_path, papers)
    atomic_json(manifest_path, manifest)
    print(f"promoted {TASK_ID} with waivers {waivers}")


if __name__ == "__main__":
    main()
