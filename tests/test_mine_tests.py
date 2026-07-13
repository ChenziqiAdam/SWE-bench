from swebench.eval_pipeline.mine_tests import apply_mined_to_instances


def test_apply_mined_keeps_curated_f2p_when_mining_finds_none():
    instances = [
        {
            "instance_id": "demo__repo-1",
            "FAIL_TO_PASS": ["curated-target"],
            "PASS_TO_PASS": [],
        }
    ]
    mining = {
        "demo__repo-1": {
            "ok": True,
            "FAIL_TO_PASS": [],
            "PASS_TO_PASS": ["passing-target"],
        }
    }

    result = apply_mined_to_instances(instances, mining)

    assert result[0]["FAIL_TO_PASS"] == ["curated-target"]
    assert result[0]["PASS_TO_PASS"] == ["passing-target"]


def test_apply_mined_uses_dynamic_f2p_when_present():
    instances = [
        {
            "instance_id": "demo__repo-1",
            "FAIL_TO_PASS": ["curated-target"],
            "PASS_TO_PASS": [],
        }
    ]
    mining = {
        "demo__repo-1": {
            "ok": True,
            "FAIL_TO_PASS": ["mined-target"],
            "PASS_TO_PASS": [],
        }
    }

    result = apply_mined_to_instances(instances, mining)

    assert result[0]["FAIL_TO_PASS"] == ["mined-target"]


def test_apply_mined_uses_spec_fallback_for_empty_cached_instance():
    instances = [
        {
            "instance_id": "openmm__openmm-2187",
            "repo": "openmm/openmm",
            "version": "2187",
            "FAIL_TO_PASS": [],
            "PASS_TO_PASS": [],
        }
    ]
    mining = {
        "openmm__openmm-2187": {
            "ok": True,
            "FAIL_TO_PASS": [],
            "PASS_TO_PASS": ["TestReferenceCustomNonbondedForce"],
        }
    }

    result = apply_mined_to_instances(instances, mining)

    assert result[0]["FAIL_TO_PASS"] == ["TestReferenceCustomNonbondedForce"]
