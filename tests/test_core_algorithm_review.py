import json
from pathlib import Path

import pytest

from paper_replication_tasks.review_core_algorithms import (
    APIResult,
    CheckpointMismatchError,
    ContextLengthError,
    DEFAULT_MODEL,
    PageText,
    PaperSource,
    PersistentRateLimiter,
    ResponseValidationError,
    ReviewAPI,
    ReviewError,
    SCHEMA_VERSION,
    audit_prompt,
    build_comparison,
    build_correction_prompt,
    build_full_prompt,
    checkpoint_status,
    metadata_for,
    is_retryable_run_failure,
    page_chunks,
    parse_args,
    parse_json_response,
    read_env_file,
    retry_delay_from_response,
    validate_final_record,
)
from paper_replication_tasks.validate_core_algorithm_review_local import (
    CALL_MODE as LOCAL_CALL_MODE,
    EXPECTED_HASHES as LOCAL_EXPECTED_HASHES,
    MODEL as LOCAL_MODEL,
    load_sources as load_local_sources,
    metadata as local_metadata,
    validate_records as validate_local_records,
)


class NoWait:
    def wait(self):
        return None


class Responses:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(payload)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def envelope(content, usage=None):
    body = {
        "id": "mock-id",
        "choices": [{"message": {"content": content}}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5},
    }
    return 200, {}, json.dumps(body)


def evidence(excerpt="The proposed method is the central scientific contribution."):
    return {"page": 1, "section": "1 Introduction", "excerpt": excerpt}


def source():
    text = (
        "1 Introduction\n"
        "The proposed method is the central scientific contribution. "
        "All main experiments depend on the proposed method. "
        "It maps a scientific input to a reproducible scientific output."
    )
    return PaperSource(
        paper_id="0011",
        path=Path("/tmp/paper.pdf"),
        sha256="a" * 64,
        pages=(PageText(1, text, ("1 Introduction",)),),
        char_count=len(text),
        nonempty_page_ratio=1.0,
        redaction_markers=(),
    )


def valid_record(*, accepted=True):
    ev = evidence()
    role = "core" if accepted else "supporting"
    gates = {
        f"G{i}": {
            "status": "PASS" if accepted else "REJECT",
            "reason": "Paper evidence supports this result.",
            "evidence": ["E1"],
        }
        for i in range(1, 6)
    }
    gates.update(
        {
            f"G{i}": {
                "status": "NOT_EVALUATED",
                "reason": "deferred to later benchmark-design stage",
                "evidence": [],
            }
            for i in range(6, 9)
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "paper_id": "0011",
        "evidence_catalog": [{"id": "E1", **ev}],
        "research_goal": {"summary": "Study the scientific problem.", "evidence": ["E1"]},
        "main_contributions": [{"id": "C1", "summary": "A proposed method.", "evidence": ["E1"]}],
        "contribution_graph": [
            {"from": "goal", "to": "C1", "relation": "motivates", "evidence": ["E1"]}
        ],
        "candidate_algorithms": [
            {
                "name": "Proposed method",
                "role": role,
                "description": "The paper's method.",
                "evidence": ["E1"],
                "deletion_test": {
                    "outcome": "FAILS_WITHOUT_ALGORITHM" if accepted else "SURVIVES_WITHOUT_ALGORITHM",
                    "reason": "The contribution depends on it.",
                    "evidence": ["E1"],
                },
            }
        ],
        "selected_core_algorithm": "Proposed method" if accepted else None,
        "uniqueness_reason": "There is exactly one central method." if accepted else "No candidate is central.",
        "scientific_contract": (
            {
                "algorithm": "Proposed method",
                "scientific_purpose": "Solve the scientific problem.",
                "inputs": ["scientific input"],
                "outputs": ["scientific output"],
                "core_operations": ["paper-specific transform"],
                "assumptions": ["stated assumption"],
                "parameters": ["model parameter"],
                "scientific_invariants": ["invariant"],
                "dependent_contributions": ["C1"],
                "dependent_experiments_results": ["main experiments"],
                "specificity_reason": "Not an off-the-shelf procedure.",
                "evidence": ["E1"],
            }
            if accepted
            else None
        ),
        "gates": gates,
        "evidence_gaps": [],
        "decision": "ACCEPT_FOR_DESIGN" if accepted else "REJECT_PAPER",
    }


def make_api(transport, *, retries=3, sleeps=None, errors=None):
    sleeps = [] if sleeps is None else sleeps
    errors = [] if errors is None else errors
    return ReviewAPI(
        "mock/model",
        transport,
        NoWait(),
        max_retries=retries,
        sleeper=sleeps.append,
        error_sink=errors.append,
        secret="secret-key",
    )


def test_env_reads_only_allowlisted_fields(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MODEL_NAME=test/model\nENDPOINT=https://example.test/v1\n"
        "API_KEY=secret-key\nUNRELATED=must-not-load\n"
    )
    values = read_env_file(env_file)
    assert values == {
        "ENDPOINT": "https://example.test/v1",
        "API_KEY": "secret-key",
    }


def test_default_model_and_output_are_glm52_and_isolated():
    args = parse_args([])
    assert args.model == DEFAULT_MODEL == "z-ai/glm-5.2:free"
    assert args.output_root == Path("paper_replication_tasks/core_algorithm_review_v2_glm52")
    assert args.resume_round_delay == 0.0


def test_prompt_contains_only_composed_sources_and_rejects_contamination():
    prompt = build_full_prompt("0011", "rubric text", source().pages)
    assert "rubric text" in prompt
    assert "COMPLETE PAPER 0011" in prompt
    assert '"output_object":' not in prompt
    assert "task.md" not in prompt
    with pytest.raises(ReviewError, match="contamination"):
        audit_prompt(prompt + "\ncuration_reports/old.json")


def test_json_and_evidence_validation_accepts_fenced_json():
    record = parse_json_response(f"```json\n{json.dumps(valid_record())}\n```")
    assert validate_final_record(record, source())["decision"] == "ACCEPT_FOR_DESIGN"


def test_evidence_must_match_cited_page():
    record = valid_record()
    record["evidence_catalog"][0]["excerpt"] = "This quotation does not occur in the PDF."
    with pytest.raises(ResponseValidationError, match="does not match"):
        validate_final_record(record, source())


def test_evidence_normalization_tolerates_pdf_layout_whitespace():
    record = valid_record()
    record["evidence_catalog"][0]["excerpt"] = "The proposed method is the centralscientific contribution."
    assert validate_final_record(record, source())["paper_id"] == "0011"


def test_gate_and_decision_consistency_is_enforced():
    record = valid_record()
    record["decision"] = "REJECT_PAPER"
    with pytest.raises(ResponseValidationError, match="decision inconsistent"):
        validate_final_record(record, source())


def test_mock_endpoint_normal_response_and_request_parameters():
    transport = Responses(envelope(json.dumps(valid_record())))
    api = make_api(transport)
    result, raw, meta = api.complete(
        "prompt", lambda value: validate_final_record(value, source()), stage="test"
    )
    assert result["decision"] == "ACCEPT_FOR_DESIGN"
    assert json.loads(raw)["paper_id"] == "0011"
    assert isinstance(meta, APIResult)
    assert transport.payloads[0]["temperature"] == 0
    assert transport.payloads[0]["max_tokens"] == 8000
    assert transport.payloads[0]["reasoning"] == {"effort": "minimal", "exclude": True}
    assert transport.payloads[0]["model"] == "mock/model"


def test_mock_endpoint_invalid_json_is_retried():
    errors = []
    transport = Responses(envelope("not-json"), envelope(json.dumps(valid_record())))
    api = make_api(transport, sleeps=[], errors=errors)
    result, _, _ = api.complete(
        "prompt", lambda value: validate_final_record(value, source()), stage="test"
    )
    assert result["decision"] == "ACCEPT_FOR_DESIGN"
    assert api.call_count == 2
    assert errors[0]["type"] == "ResponseValidationError"
    retry_prompt = transport.payloads[1]["messages"][0]["content"]
    assert "ORIGINAL RESPONSE:\nnot-json" in retry_prompt
    assert errors[0]["message"] in retry_prompt
    assert "do not change unrelated scientific judgments" in retry_prompt


def test_correction_retry_does_not_bypass_gate_or_evidence_validation():
    bad_gate = valid_record()
    bad_gate["decision"] = "REJECT_PAPER"
    bad_evidence = valid_record()
    bad_evidence["evidence_catalog"][0]["excerpt"] = "This fabricated quotation is absent from the paper page."
    transport = Responses(envelope(json.dumps(bad_gate)), envelope(json.dumps(bad_evidence)))
    api = make_api(transport, retries=1, sleeps=[])
    with pytest.raises(ReviewError, match="failed after 2 attempts"):
        api.complete("prompt", lambda value: validate_final_record(value, source()), stage="test")


def test_correction_prompt_preserves_exact_response_and_validator_error():
    prompt = build_correction_prompt("base", '{"bad":true}', "$.gates.G2.status invalid")
    assert '{"bad":true}' in prompt
    assert "$.gates.G2.status invalid" in prompt


def test_mock_endpoint_null_content_is_retried():
    errors = []
    null_body = json.dumps(
        {"id": "null", "choices": [{"finish_reason": "length", "message": {"content": None}}], "usage": {}}
    )
    transport = Responses((200, {}, null_body), envelope(json.dumps(valid_record())))
    api = make_api(transport, sleeps=[], errors=errors)
    result, _, _ = api.complete(
        "prompt", lambda value: validate_final_record(value, source()), stage="test"
    )
    assert result["decision"] == "ACCEPT_FOR_DESIGN"
    assert errors[0]["type"] == "ResponseValidationError"
    assert "finish_reason='length'" in errors[0]["message"]


def test_mock_endpoint_429_honors_retry_after():
    sleeps = []
    transport = Responses(
        (429, {"Retry-After": "7"}, '{"error":"rate limited"}'),
        envelope(json.dumps(valid_record())),
    )
    api = make_api(transport, sleeps=sleeps)
    api.complete("prompt", lambda value: validate_final_record(value, source()), stage="test")
    assert sleeps == [7.0]


def test_retry_after_is_read_from_provider_error_metadata():
    body = json.dumps(
        {"error": {"metadata": {"retry_after_seconds": 5, "headers": {"Retry-After": "4"}}}}
    )
    assert retry_delay_from_response({}, body, 1.0) == 5.0


def test_temporary_no_endpoint_error_retries_but_bad_model_fails_closed():
    transient = Responses(
        (404, {}, '{"error":"No endpoints found for this free model"}'),
        envelope(json.dumps(valid_record())),
    )
    api = make_api(transient, sleeps=[])
    api.complete("prompt", lambda value: validate_final_record(value, source()), stage="test")
    assert api.call_count == 2

    permanent = Responses((404, {}, '{"error":"model not found: bad/model"}'))
    api = make_api(permanent, sleeps=[])
    with pytest.raises(ReviewError, match="endpoint HTTP 404"):
        api.complete("prompt", lambda value: value, stage="test")
    assert api.call_count == 1


def test_http_error_body_is_preserved_as_raw_response():
    raw = []
    transport = Responses((429, {}, '{"error":"rate limited"}'))
    api = ReviewAPI(
        "mock/model",
        transport,
        NoWait(),
        max_retries=0,
        response_sink=raw.append,
        sleeper=lambda _: None,
        secret="secret-key",
    )
    with pytest.raises(ReviewError):
        api.complete("prompt", lambda value: value, stage="test")
    assert raw[0]["http_status"] == 429
    assert raw[0]["response_kind"] == "http_error"
    assert raw[0]["text"] == '{"error":"rate limited"}'


def test_mock_endpoint_timeout_is_retried():
    sleeps = []
    transport = Responses(TimeoutError("timed out"), envelope(json.dumps(valid_record())))
    api = make_api(transport, sleeps=sleeps)
    api.complete("prompt", lambda value: validate_final_record(value, source()), stage="test")
    assert api.call_count == 2
    assert sleeps == [1.0]


def test_only_explicit_context_error_triggers_context_exception():
    transport = Responses((400, {}, '{"error":"maximum context length exceeded"}'))
    api = make_api(transport)
    with pytest.raises(ContextLengthError):
        api.complete("prompt", lambda value: value, stage="full-review")
    assert api.call_count == 1


def test_page_chunks_cover_every_page_without_splitting_pages():
    pages = tuple(PageText(i, "x" * 100, ()) for i in range(1, 6))
    chunks = page_chunks(pages, token_budget=50)
    assert [page.number for chunk in chunks for page in chunk] == [1, 2, 3, 4, 5]
    assert all(tuple(range(chunk[0].number, chunk[-1].number + 1)) == tuple(p.number for p in chunk) for chunk in chunks)


def test_persistent_rate_limiter_uses_saved_timestamp(tmp_path):
    now = [100.0]
    sleeps = []
    limiter = PersistentRateLimiter(
        tmp_path / "rate.json", 20, clock=lambda: now[0], sleeper=sleeps.append
    )
    limiter.wait()
    now[0] = 101.0
    limiter.wait()
    assert sleeps == [2.0]


def test_shared_rate_limiter_reserves_capacity_across_instances(tmp_path):
    now = [100.0]
    sleeps = []
    state = tmp_path / "shared.json"
    first = PersistentRateLimiter(
        state, 20, reserve_rpm=8, clock=lambda: now[0], sleeper=sleeps.append
    )
    second = PersistentRateLimiter(
        state, 20, reserve_rpm=8, clock=lambda: now[0], sleeper=sleeps.append
    )
    first.wait()
    now[0] = 101.0
    second.wait()
    saved = json.loads(state.read_text())
    assert sleeps == [4.0]
    assert saved["effective_rpm"] == 12
    assert saved["call_epochs"] == [100.0, 105.0]


def test_only_transient_run_failures_are_scheduled_for_another_round():
    assert is_retryable_run_failure("full-review failed: HTTP 429 upstream")
    assert is_retryable_run_failure("provider unavailable")
    assert not is_retryable_run_failure("endpoint HTTP 401 unauthorized")
    assert not is_retryable_run_failure("decision inconsistent with hard gates")


def test_resume_accepts_identical_hashes_and_rejects_mismatch(tmp_path):
    expected = metadata_for(source(), "b" * 64, "c" * 64, "mock/model")
    paper_dir = tmp_path / "0011"
    paper_dir.mkdir()
    (paper_dir / "metadata.json").write_text(json.dumps(expected))
    (paper_dir / "record.json").write_text(json.dumps(valid_record()))
    assert checkpoint_status(paper_dir, expected) == "complete"
    changed = {**expected, "source_sha256": "d" * 64}
    with pytest.raises(CheckpointMismatchError, match="mismatch"):
        checkpoint_status(paper_dir, changed)


def test_errors_never_include_api_key():
    errors = []
    transport = Responses((429, {}, '{"error":"secret-key rate limited"}'))
    api = make_api(transport, retries=0, errors=errors)
    with pytest.raises(ReviewError) as caught:
        api.complete("prompt", lambda value: value, stage="test")
    assert "secret-key" not in str(caught.value)
    assert "secret-key" not in json.dumps(errors)


def test_comparison_ignores_failed_v2_and_reports_real_disagreement(tmp_path):
    baseline_root = tmp_path / "v2"
    current_root = tmp_path / "glm"
    baseline_root.mkdir()
    current_root.mkdir()
    baseline = {
        "model": "old/model",
        "complete_count": 1,
        "failed_count": 1,
        "papers": [
            {
                "paper_id": "0011",
                "status": "COMPLETE",
                "selected_core_algorithm": "Old core",
                "gates": {f"G{i}": "PASS" for i in range(1, 9)},
                "decision": "ACCEPT_FOR_DESIGN",
            },
            {"paper_id": "0014", "status": "FAILED"},
        ],
    }
    current = {
        "model": DEFAULT_MODEL,
        "complete_count": 2,
        "failed_count": 0,
        "papers": [
            {
                "paper_id": "0011",
                "status": "COMPLETE",
                "selected_core_algorithm": "New core",
                "gates": {f"G{i}": "PASS" for i in range(1, 9)},
                "decision": "ACCEPT_FOR_DESIGN",
            },
            {
                "paper_id": "0014",
                "status": "COMPLETE",
                "selected_core_algorithm": "Only current core",
                "gates": {f"G{i}": "PASS" for i in range(1, 9)},
                "decision": "ACCEPT_FOR_DESIGN",
            },
        ],
    }
    (baseline_root / "summary.json").write_text(json.dumps(baseline))
    (current_root / "summary.json").write_text(json.dumps(current))
    comparison = build_comparison(current_root, baseline_root)
    by_id = {item["paper_id"]: item for item in comparison["papers"]}
    assert by_id["0011"]["disagreement"] is True
    assert by_id["0014"]["disagreement"] is None
    assert comparison["disagreement_count"] == 1
    assert comparison["aggregation"].startswith("none")


def test_local_review_records_validate_against_all_complete_pdfs():
    repo_root = Path(__file__).resolve().parents[1]
    sources = load_local_sources(repo_root)
    records = validate_local_records(sources)
    assert {paper_id: item.sha256 for paper_id, item in sources.items()} == LOCAL_EXPECTED_HASHES
    assert sum(record["decision"] == "ACCEPT_FOR_DESIGN" for record in records.values()) == 7
    assert sum(record["decision"] == "REJECT_PAPER" for record in records.values()) == 2


def test_local_review_metadata_has_zero_remote_calls_or_tokens():
    value = local_metadata(source(), "b" * 64)
    assert value["model"] == LOCAL_MODEL == "codex-local-review"
    assert value["call_mode"] == LOCAL_CALL_MODE == "local_manual_review"
    assert value["call_count"] == 0
    assert value["token_usage"] == []
    assert "request_config" not in value


def test_local_validation_entrypoint_has_no_env_or_network_client():
    entrypoint = (
        Path(__file__).resolve().parents[1]
        / "paper_replication_tasks/validate_core_algorithm_review_local.py"
    ).read_text(encoding="utf-8")
    assert "read_env_file" not in entrypoint
    assert "urlopen(" not in entrypoint
    assert "requests." not in entrypoint
