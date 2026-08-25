import hashlib
import io
import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from swebench.issue_pipeline import claude_stream_gateway as gateway
from swebench.issue_pipeline import offline_claude_run as run


def test_actual_workbook_maps_88_rows_to_84_source_instances():
    root = Path(__file__).parents[1]
    instances, _, mapping = run.select_workbook_instances(
        root / "Issues_No_Tests_final.xlsx",
        root / "outputs/issues_no_tests_final_cc/instances.jsonl",
    )
    assert len(instances) == 84
    assert mapping == {"workbook_row_count": 88, "unique_closing_pr_count": 84}


@pytest.mark.parametrize(
    "value",
    [
        "https://openrouter.ai/api/v1/chat/completions",
        "https://openrouter.ai/api/v1",
        "https://openrouter.ai/api",
    ],
)
def test_openrouter_endpoint_normalization(value):
    assert gateway.normalize_openrouter_endpoint(value) == "https://openrouter.ai/api"


def test_env_loading_and_redaction_never_expose_key(tmp_path, capsys):
    secret = "sk-or-secret-value"
    path = tmp_path / ".env"
    path.write_text(
        f"MODEL_NAME=stealth/ox-alpha\nENDPOINT=https://openrouter.ai/api/v1\nAPI_KEY={secret}\n"
    )
    values = run.load_env_file(path)
    assert values["API_KEY"] == secret
    assert secret not in gateway.redact_secrets(f"failed: {secret}", [secret])
    assert secret not in capsys.readouterr().out


def test_limiter_is_concurrent_and_persistent(tmp_path):
    path = tmp_path / "limiter.json"
    limiter = gateway.RollingWindowLimiter(path, limit=2, window=0.08)
    admitted = []
    lock = threading.Lock()

    def acquire():
        value = limiter.acquire()
        with lock:
            admitted.append(value)

    threads = [threading.Thread(target=acquire) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    admitted.sort()
    assert admitted[2] - admitted[0] >= 0.07

    persisted = json.loads(path.read_text())["admissions"]
    assert persisted
    restarted = gateway.RollingWindowLimiter(path, limit=2, window=0.08)
    started = time.time()
    restarted.acquire()
    assert time.time() - started >= 0.06


class _StreamingResponse:
    status = 200
    headers = {"Content-Type": "text/event-stream"}

    def __init__(self):
        self.parts = iter([b"data: one\n\n", b"data: two\n\n", b""])

    def read(self, _size):
        return next(self.parts)


def test_gateway_streams_response_and_sanitizes_diagnostics(tmp_path):
    proxy = gateway.ClaudeStreamGateway(
        "https://openrouter.ai/api",
        "super-secret",
        tmp_path,
        opener=lambda *_args, **_kwargs: _StreamingResponse(),
    )
    output = io.BytesIO()
    proxy._stream_response(_StreamingResponse(), output)
    proxy._diagnostic(
        {"instance_id": "case", "status": 200, "body": "private request", "api_key": "super-secret"}
    )
    assert output.getvalue() == b"data: one\n\ndata: two\n\n"
    diagnostic = (tmp_path / "gateway_diagnostics.jsonl").read_text()
    assert "case" in diagnostic
    assert "private request" not in diagnostic
    assert "super-secret" not in diagnostic


@pytest.mark.parametrize(
    "status,payload,interrupted,expected",
    [
        (429, "", False, "transient"),
        (503, "", False, "transient"),
        (401, "", False, "fatal"),
        (404, "capability route missing", False, None),
        (404, "model not found", False, "fatal"),
        (400, "instance context rejected", False, "transient"),
        (400, "no endpoints found for model", False, "fatal"),
        (200, "", True, "transient"),
        (200, "", False, None),
    ],
)
def test_provider_failure_classification(status, payload, interrupted, expected):
    assert gateway.classify_provider_failure(
        status, payload=payload, interrupted=interrupted
    ) == expected


def test_auto_resume_detects_existing_manifest(tmp_path, monkeypatch):
    output = tmp_path / "out"
    output.mkdir()
    (output / "run_manifest.json").write_text("{}")
    parser = run.make_parser()
    args = parser.parse_args(
        ["--instances", "i.jsonl", "--output-dir", str(output), "--auto-resume"]
    )
    assert args.auto_resume is True


def test_retry_after_wins_and_backoff_is_capped():
    assert gateway.retry_delay(1, "17") == 17
    assert gateway.retry_delay(100, None, uniform=lambda _a, b: b) == 900


def test_preflight_requires_tool_use(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"content": [{"type": "tool_use", "name": "ping"}]}).encode()

    monkeypatch.setattr(run.urllib.request, "urlopen", lambda *_a, **_k: Response())
    assert run.preflight_claude_tools("https://openrouter.ai/api", "secret", "model")["tool_use"]


def test_resume_manifest_is_exact(tmp_path, monkeypatch):
    output = tmp_path / "out"
    output.mkdir()
    (output / "run_manifest.json").write_text(json.dumps({"model": "old"}))
    monkeypatch.setattr(run, "_jsonl_rows", lambda _path: [])
    with pytest.raises(ValueError, match="manifest"):
        run.run_full(
            [], output, manifest={"model": "new"}, resume=True, model="new",
            timeout=1, workers=1, wave_size=1, github_token=None, expected_repos={}
        )


def test_transient_peer_is_retried_after_successful_peer_checkpoint(tmp_path, monkeypatch):
    instances = [
        {"instance_id": "a", "repo": "science/repo"},
        {"instance_id": "b", "repo": "science/repo"},
    ]
    calls = {"a": 0, "b": 0}

    class FakeGateway:
        api_key = "secret"
        local_base = "http://127.0.0.1:1"

        def start(self):
            return self.local_base

        def close(self):
            return None

        def failure_for(self, instance_id):
            return "transient" if instance_id == "a" and calls[instance_id] == 1 else None

        def retry_after_for(self, _instance_id):
            return "0"

        def clear_failure(self, _instance_id):
            return None

    def fake_wave(wave, _checkout, output, **_kwargs):
        for instance in wave:
            instance_id = instance["instance_id"]
            calls[instance_id] += 1
            text = json.dumps({"type": "result", "case": instance_id}) + "\n"
            trajectory = output / "trajectories" / f"{instance_id}.jsonl"
            trajectory.write_text(text)
            digest = hashlib.sha256(text.encode()).hexdigest()
            audit = {
                "instance_id": instance_id,
                "status": "passed",
                "network_findings": [],
                "changed_paths": ["tests/test_case.py"],
                "disallowed_paths": [],
                "trajectory_path": f"trajectories/{instance_id}.jsonl",
                "trajectory_sha256": digest,
            }
            yield {
                "instance_id": instance_id,
                "model_patch": "diff --git a/tests/test_case.py b/tests/test_case.py\n",
                "offline_audit": dict(audit),
                "trajectory_sha256": digest,
            }, audit

    monkeypatch.setattr(run, "_run_wave", fake_wave)
    monkeypatch.setattr(run, "build_pilot_prompt", lambda item: item["instance_id"])
    monkeypatch.setattr(run, "inference_worktree_root", lambda _name: tmp_path)
    monkeypatch.setattr(run.time, "sleep", lambda _delay: None)
    predictions = run.run_full(
        instances,
        tmp_path / "out",
        manifest={"fixed": True},
        resume=False,
        model="model",
        timeout=1,
        workers=2,
        wave_size=2,
        github_token=None,
        expected_repos={"science/repo": 2},
        gateway=FakeGateway(),
    )
    assert [item["instance_id"] for item in predictions] == ["a", "b"]
    assert calls == {"a": 2, "b": 1}
    assert (tmp_path / "out/checkpoints/b.json").is_file()


def test_checkout_failure_requeues_wave_without_checkpoint(tmp_path, monkeypatch):
    instances = [{"instance_id": "a", "repo": "science/repo"}]
    calls = 0

    def fake_wave(_wave, _checkout, output, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise run.CheckoutFetchError("temporary fetch timeout")
        text = json.dumps({"type": "result"}) + "\n"
        trajectory = output / "trajectories" / "a.jsonl"
        trajectory.write_text(text)
        digest = hashlib.sha256(text.encode()).hexdigest()
        audit = {
            "instance_id": "a",
            "status": "passed",
            "network_findings": [],
            "changed_paths": ["tests/test_case.py"],
            "disallowed_paths": [],
            "trajectory_path": "trajectories/a.jsonl",
            "trajectory_sha256": digest,
        }
        yield {
            "instance_id": "a",
            "model_patch": "diff --git a/tests/test_case.py b/tests/test_case.py\n",
            "offline_audit": dict(audit),
            "trajectory_sha256": digest,
        }, audit

    monkeypatch.setattr(run, "_run_wave", fake_wave)
    monkeypatch.setattr(run, "build_pilot_prompt", lambda item: item["instance_id"])
    monkeypatch.setattr(run, "inference_worktree_root", lambda _name: tmp_path)
    monkeypatch.setattr(run.time, "sleep", lambda _delay: None)
    predictions = run.run_full(
        instances,
        tmp_path / "out",
        manifest={"fixed": True},
        resume=False,
        model="model",
        timeout=1,
        workers=1,
        wave_size=1,
        github_token=None,
        expected_repos={"science/repo": 1},
    )
    assert calls == 2
    assert [item["instance_id"] for item in predictions] == ["a"]
