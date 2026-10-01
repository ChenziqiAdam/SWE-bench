import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "audit_issue_run_records",
    Path(__file__).resolve().parent.parent / "scripts" / "audit_issue_run_records.py",
)
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)

_LIMIT = [{"type": "result", "is_error": True, "result": "You've hit your session limit"}]


def test_provider_cutoff_without_patch_is_a_rerun_candidate():
    pred = {"model_patch": "", "error": "disallowed_patch_scope"}
    assert audit._classify(pred, _LIMIT)[0] == "infra_failure"


def test_provider_cutoff_with_patch_is_flagged_but_not_rerun():
    assert audit._classify({"model_patch": "diff"}, _LIMIT)[0] == "interrupted_patch_kept"


def test_empty_patch_with_permission_denials_is_reviewed_not_blamed_on_model():
    pred = {"model_patch": "", "metrics": {"permission_denial_count": 3}}
    assert audit._classify(pred, [])[0] == "empty_patch_with_denials"
    assert audit._classify({"model_patch": "", "metrics": {}}, [])[0] == "empty_patch_no_signal"
