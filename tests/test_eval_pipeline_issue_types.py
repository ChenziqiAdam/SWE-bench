from swebench.eval_pipeline.ingest import normalize_issue_type
from swebench.eval_pipeline.run_pipeline import _parse_issue_types


def test_parse_issue_types_keeps_combined_type_intact():
    assert _parse_issue_types(["1,2"]) == {"1,2"}


def test_parse_issue_types_supports_repeated_values():
    assert _parse_issue_types(["1", "1,2"]) == {"1", "1,2"}


def test_normalize_issue_type_handles_excel_numeric_values():
    assert normalize_issue_type(1) == "1"
    assert normalize_issue_type(1.0) == "1"
    assert normalize_issue_type(" 1,2 ") == "1,2"
