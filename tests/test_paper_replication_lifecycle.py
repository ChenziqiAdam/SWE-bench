import hashlib
import json
from pathlib import Path

from paper_replication_tasks.task_registry import active_task_ids, validated_task_ids


ROOT = Path(__file__).resolve().parents[1] / "paper_replication_tasks"
EXCLUDED = {
    "scibench_replication_0014",
    "scibench_replication_0019",
    "scibench_replication_0020",
}


def _bundle_file_map_hash(task_id: str) -> str:
    task_root = ROOT / task_id
    files = {
        path.relative_to(task_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(task_root.rglob("*"))
        if path.is_file()
    }
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def test_non_core_papers_are_excluded_but_archived():
    manifest_ids = {row["task_id"] for row in json.loads((ROOT / "manifest.json").read_text())["tasks"]}
    papers = {
        row["task_id"]: row
        for row in json.loads((ROOT / "papers.json").read_text())["papers"]
        if row.get("task_id") in EXCLUDED
    }

    assert EXCLUDED.isdisjoint(manifest_ids)
    assert EXCLUDED.isdisjoint(active_task_ids())
    assert EXCLUDED.isdisjoint(validated_task_ids())
    assert set(papers) == EXCLUDED

    for task_id in EXCLUDED:
        report = json.loads((ROOT / f"curation_reports/{task_id[-4:]}_excluded.json").read_text())
        assert papers[task_id]["build_status"] == "excluded_no_core_algorithm"
        assert report["status"] == "excluded_no_core_algorithm"
        assert report["historical_artifacts"] == "preserved"
        assert report["bundle_file_map_sha256"] == _bundle_file_map_hash(task_id)


def test_0018_core_supersedes_legacy_with_explicit_g7_waiver():
    manifest_ids = {
        row["task_id"]
        for row in json.loads((ROOT / "manifest.json").read_text())["tasks"]
    }
    provenance = json.loads(
        (ROOT / "scibench_replication_0018_core/hidden/provenance.json").read_text()
    )
    archive = json.loads((ROOT / "curation_reports/0018_superseded.json").read_text())

    assert "scibench_replication_0018_core" in manifest_ids
    assert "scibench_replication_0018" not in manifest_ids
    assert "scibench_replication_0018_core" in active_task_ids()
    assert provenance["validation_waivers"] == ["G7_blind_implementation"]
    assert provenance["g7_audit"]["status"] == "fail"
    assert archive["bundle_file_map_sha256"] == _bundle_file_map_hash(
        "scibench_replication_0018"
    )
