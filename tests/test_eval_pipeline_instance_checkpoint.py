import json

from swebench.eval_pipeline.constants import COL_PR_NUMBER, COL_REPO
from swebench.eval_pipeline.instance_builder import build_all_instances


def test_checkpoint_superset_returns_only_requested_instances(tmp_path):
    selected = {"instance_id": "rdkit__rdkit-2083", "marker": "selected"}
    unrelated = {"instance_id": "openmm__openmm-1235", "marker": "unrelated"}
    checkpoint = tmp_path / "instances_checkpoint.jsonl"
    checkpoint.write_text(
        json.dumps(unrelated) + "\n" + json.dumps(selected) + "\n"
    )

    instances = build_all_instances(
        [{COL_REPO: "rdkit/rdkit", COL_PR_NUMBER: 2083}],
        checkpoint_path=str(checkpoint),
    )

    assert instances == [selected]
