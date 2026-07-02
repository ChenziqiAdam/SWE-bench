"""Stage 4 (agentic, SWE-agent backend): Invokes SWE-agent CLI as a subprocess per instance.

Mirrors the interface of agent_inference.py so run_pipeline.py can swap backends.
Output format is identical to inference.py so Stage 5 (Docker eval) is unchanged.

SWE-agent output layout (v1.1):
  <output_dir>/<problem_statement_id>/<problem_statement_id>.pred  — JSON with model_patch key
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import yaml
from tqdm.auto import tqdm

from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit
from swebench.eval_pipeline.inference import _clean_patch, _repair_patch
from swebench.eval_pipeline.media_assets import format_issue_media_for_prompt
from swebench.eval_pipeline.prediction_utils import prediction_matches_backend

logger = logging.getLogger(__name__)
AGENT_BACKEND = "sweagent"

_SWEAGENT_TIMEOUT = 600  # seconds per instance
# SWE-agent runs each instance in a container (deployment: docker) so its local-repo
# handler can upload the repo to a writable /<repo_name>. Any image with git + a shell
# works; SWE-agent installs its own tools at runtime.
_DEFAULT_DOCKER_IMAGE = "python:3.11"
_DEFAULT_MAX_INPUT_TOKENS = 32768


def _sweagent_problem_text(instance: dict) -> str:
    """Build a compact task text for SWE-agent.

    SWE-agent's default template already instructs tool use, but some
    OpenAI-compatible models do not reliably honor the function-calling wrapper.
    Put the most important operational constraints directly in the task text so
    they remain visible after history truncation.
    """
    problem = (instance.get("problem_statement") or "").strip()
    if not problem:
        pr_title = (instance.get("pr_title") or "").strip()
        pr_body = (instance.get("pr_body") or "").strip()
        problem = f"{pr_title}\n\n{pr_body}".strip()

    file_contents = instance.get("file_contents") or {}
    target_files = sorted(file_contents)
    f2p = instance.get("FAIL_TO_PASS") or []

    guidance = [
        "Operational constraints for this SWE-agent run:",
        "- Use exactly one tool call per assistant turn. Never emit multiple tool calls in one response.",
        "- Make the smallest source change that addresses the issue and the listed failing tests.",
        "- Avoid broad repository scans and avoid copying or rewriting large generated files.",
        "- For large C++ changes, inspect only the directly relevant files first, then patch incrementally.",
        "- Submit as soon as the minimal patch is ready; do not keep exploring after producing a plausible fix.",
    ]
    if target_files:
        guidance.append("Relevant base-commit files from instance construction:")
        guidance.extend(f"- {path}" for path in target_files[:12])
    if f2p:
        guidance.append("Mined FAIL_TO_PASS tests for scoring:")
        guidance.extend(f"- {test}" for test in f2p[:12])

    media_ctx = format_issue_media_for_prompt(instance)
    return "\n".join(guidance) + "\n\n" + media_ctx + "Issue:\n" + problem


def _sweagent_bin() -> str:
    """Return path to sweagent CLI.

    Checks in order:
    1. PATH (covers activated venv or system install)
    2. bin/ directory next to the running Python interpreter (works when called from venv Python)
    3. <repo_root>/.venv/bin/sweagent or <repo_root>/venv/bin/sweagent — handles the case
       where conda/system Python invokes code installed in a project venv
    """
    import sys

    found = shutil.which("sweagent")
    if found:
        return found

    venv_bin = Path(sys.executable).parent / "sweagent"
    if venv_bin.exists():
        return str(venv_bin)

    # Repo-relative venv: __file__ is swebench/eval_pipeline/swe_agent_inference.py
    repo_root = Path(os.path.abspath(__file__)).parent.parent.parent
    for candidate in [
        repo_root / ".venv" / "bin" / "sweagent",
        repo_root / "venv" / "bin" / "sweagent",
    ]:
        if candidate.exists():
            return str(candidate)

    return "sweagent"  # last resort — raises FileNotFoundError at subprocess.run


def _default_config_path() -> Optional[Path]:
    """Locate SWE-agent's bundled config/default.yaml.

    The default config ships the system/instance/next_step templates (which carry
    the {{problem_statement}} placeholder) and the tool bundle + parser. Without it,
    SWE-agent runs with empty templates ("system_template/instance_template is not
    set") and the agent never learns the task → wanders → empty patch.
    """
    try:
        import sweagent
        cfg = Path(sweagent.CONFIG_DIR) / "default.yaml"
        if cfg.exists():
            return cfg
    except Exception:
        pass
    return None


def _build_sweagent_config(
    instance: dict,
    repo_dir: Path,
    model_name: str,
    output_dir: Path,
    base_config: Optional[dict] = None,
    docker_image: str = _DEFAULT_DOCKER_IMAGE,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    max_input_tokens: int = _DEFAULT_MAX_INPUT_TOKENS,
) -> dict:
    """Build a SWE-agent RunSingleConfig dict for one instance.

    Uses a Docker deployment: SWE-agent's local repo handler uploads the repo to
    ``/<repo_name>`` inside the container (where ``/`` is writable), avoiding the
    PermissionError that ``deployment: local`` hits when copying to the host root.

    When ``api_base`` is given, the model is reached through an OpenAI-compatible
    endpoint: litellm needs the ``openai/`` provider prefix on the model name plus
    ``api_base``/``api_key``. Without this, litellm can't resolve a custom model
    name like ``deepseek-v4-flash`` and the run hangs until timeout.
    """
    problem = _sweagent_problem_text(instance)

    # litellm model name: prefix with openai/ for a custom OpenAI-compatible endpoint.
    # litellm's openai provider POSTs to <api_base>/chat/completions, so api_base must
    # point at the OpenAI-compatible root (e.g. https://api.deepseek.com/v1, NOT the
    # bare host — bare host 404s and the agent hangs until timeout).
    litellm_name = model_name
    model_cfg: dict = {"name": litellm_name}
    if api_base:
        base = api_base.rstrip("/")
        # api.deepseek.com exposes its OpenAI-compatible API under /v1
        if base.endswith("api.deepseek.com"):
            base = base + "/v1"
        if not litellm_name.startswith("openai/"):
            model_cfg["name"] = f"openai/{litellm_name}"
        model_cfg["api_base"] = base
        if api_key:
            model_cfg["api_key"] = api_key

    # litellm has no price table for custom/self-hosted models, so SWE-agent's cost
    # safety check raises ModelConfigurationError ("This model isn't mapped yet") and
    # aborts after step 1. Disabling the cost limits turns the check off.
    model_cfg.setdefault("per_instance_cost_limit", 0.0)
    model_cfg.setdefault("total_cost_limit", 0.0)
    # litellm also can't infer the context window for unknown models; set a sane cap so
    # SWE-agent's history truncation works instead of warning every step.
    model_cfg.setdefault("max_input_tokens", max_input_tokens)

    if base_config:
        cfg = json.loads(json.dumps(base_config))  # deep copy
        cfg.setdefault("agent", {})["model"] = model_cfg
    else:
        cfg = {
            "agent": {"model": model_cfg},
        }

    # Override env to use local repo uploaded into a Docker container.
    cfg["env"] = {
        "repo": {
            "type": "local",
            "path": str(repo_dir),
            "base_commit": instance["base_commit"],
        },
        "deployment": {"type": "docker", "image": docker_image},
    }
    cfg["problem_statement"] = {"type": "text", "text": problem}
    cfg["output_dir"] = str(output_dir)
    return cfg


def _read_patch_from_output(output_dir: Path, instance_id: str) -> str:
    """Read the patch SWE-agent wrote. Returns empty string if not found."""
    # Primary: <output_dir>/<instance_id>/<instance_id>.pred (JSON)
    pred_file = output_dir / instance_id / f"{instance_id}.pred"
    if pred_file.exists():
        try:
            data = json.loads(pred_file.read_text())
            return data.get("model_patch") or ""
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: any .patch file under the output dir
    for p in output_dir.glob("**/*.patch"):
        return p.read_text()

    return ""


def run_sweagent_inference(
    instances: list[dict],
    output_file: str,
    model_name: str,
    github_token: Optional[str] = None,
    max_workers: int = 2,
    sweagent_config: Optional[str] = None,
    docker_image: str = _DEFAULT_DOCKER_IMAGE,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    retry_empty_predictions: bool = False,
    max_input_tokens: int = _DEFAULT_MAX_INPUT_TOKENS,
) -> None:
    """Run SWE-agent inference for all instances. Writes same JSONL format as inference.py."""
    # Base config: an explicit --sweagent_config wins; otherwise fall back to
    # SWE-agent's bundled config/default.yaml so the agent gets real templates +
    # tools (an empty/minimal config leaves the agent with no task description).
    config_path = sweagent_config
    if not config_path:
        default_cfg = _default_config_path()
        if default_cfg:
            config_path = str(default_cfg)
            logger.info(f"Using SWE-agent default config: {config_path}")
        else:
            logger.warning(
                "Could not locate SWE-agent's bundled default.yaml; running with a "
                "minimal config (no templates → agent may not understand the task)."
            )
    base_config: Optional[dict] = None
    if config_path:
        with open(config_path) as f:
            base_config = yaml.safe_load(f)

    # Resume: skip already-done instances.  Empty patches are often transient
    # SWE-agent/model failures, so callers can opt into retrying them.
    existing_ids: set[str] = set()
    out_path = Path(output_file)
    retained_records: list[dict] = []
    if out_path.exists():
        with open(out_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if prediction_matches_backend(obj, AGENT_BACKEND, model_name):
                        has_patch = bool((obj.get("model_patch") or "").strip())
                        if has_patch or not retry_empty_predictions:
                            existing_ids.add(obj["instance_id"])
                            retained_records.append(obj)
                        else:
                            logger.info(
                                f"[{obj.get('instance_id')}] retrying prior empty SWE-agent prediction"
                            )
                    else:
                        retained_records.append(obj)
                except (json.JSONDecodeError, KeyError):
                    pass
    if existing_ids:
        logger.info(f"Resuming: {len(existing_ids)} predictions already written")

    todo = [i for i in instances if i["instance_id"] not in existing_ids]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if retry_empty_predictions and out_path.exists():
        with open(out_path, "w") as f:
            for obj in retained_records:
                print(json.dumps(obj), file=f)
    # Per-instance sweagent stdout/stderr lands here so the trajectory is inspectable.
    logs_dir = out_path.parent / "sweagent_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    write_lock = threading.Lock()

    def _process_one(inst: dict) -> None:
        instance_id = inst["instance_id"]
        repo_dir = None
        tmp_cfg = None
        tmp_out = None
        sweagent_tmp = None
        try:
            repo_dir = _clone_repo_at_commit(inst["repo"], inst["base_commit"], github_token)
            tmp_out = Path(tempfile.mkdtemp(prefix="sweagent_out_"))

            cfg = _build_sweagent_config(
                inst, repo_dir, model_name, tmp_out, base_config,
                docker_image, api_base, api_key, max_input_tokens,
            )
            tmp_cfg = Path(tempfile.mktemp(suffix=".yaml"))
            tmp_cfg.write_text(yaml.dump(cfg))

            # SWE-agent's LocalDeployment stages a working copy of the repo under a
            # temp dir. If TMPDIR is unset it can resolve to a non-writable path at
            # the filesystem root (/sweagent_xxxx → PermissionError). Pin it to a
            # writable per-instance temp dir.
            sweagent_tmp = Path(tempfile.mkdtemp(prefix="sweagent_tmp_"))
            env = dict(os.environ)
            env["TMPDIR"] = str(sweagent_tmp)
            env["TMP"] = str(sweagent_tmp)
            env["TEMP"] = str(sweagent_tmp)

            instance_log = logs_dir / f"{instance_id}.log"
            result = subprocess.run(
                [_sweagent_bin(), "run", "--config", str(tmp_cfg)],
                capture_output=True,
                text=True,
                timeout=_SWEAGENT_TIMEOUT,
                env=env,
            )
            # Persist the full trajectory (stdout + stderr) for inspection.
            with open(instance_log, "w") as lf:
                lf.write(f"=== config (agent.model) ===\n{cfg.get('agent', {}).get('model')}\n")
                lf.write(f"=== exit code: {result.returncode} ===\n")
                lf.write("=== STDOUT ===\n")
                lf.write(result.stdout or "")
                lf.write("\n=== STDERR ===\n")
                lf.write(result.stderr or "")
            if result.returncode != 0:
                logger.warning(
                    f"[{instance_id}] sweagent exited with code {result.returncode}. "
                    f"stderr: {result.stderr[-500:]}"
                )

            patch = _read_patch_from_output(tmp_out, instance_id)
            patch = _clean_patch(patch)
            patch = _repair_patch(patch)
            logger.info(
                f"[{instance_id}] sweagent exit={result.returncode}, "
                f"patch_len={len(patch)}, log={instance_log}"
            )
            record = {
                "instance_id": instance_id,
                "model_patch": patch,
                "model_name_or_path": model_name,
                "agent_backend": AGENT_BACKEND,
            }
        except subprocess.TimeoutExpired as te:
            def _dec(s):
                if not s:
                    return ""
                return s if isinstance(s, str) else s.decode(errors="replace")
            so, se = _dec(te.stdout), _dec(te.stderr)
            try:
                with open(logs_dir / f"{instance_id}.log", "w") as lf:
                    lf.write(f"=== TIMEOUT after {_SWEAGENT_TIMEOUT}s ===\n")
                    lf.write("=== STDOUT ===\n" + so + "\n=== STDERR ===\n" + se)
            except Exception:
                pass
            tail = f" stderr tail: {se[-500:]}" if se else ""
            logger.error(f"[{instance_id}] sweagent timed out after {_SWEAGENT_TIMEOUT}s.{tail}")
            record = {
                "instance_id": instance_id,
                "model_patch": "",
                "model_name_or_path": model_name,
                "agent_backend": AGENT_BACKEND,
                "error": "timeout",
            }
        except Exception as e:
            logger.error(f"Error on {instance_id}: {e}")
            traceback.print_exc()
            record = {
                "instance_id": instance_id,
                "model_patch": "",
                "model_name_or_path": model_name,
                "agent_backend": AGENT_BACKEND,
                "error": str(e),
            }
        finally:
            if repo_dir:
                shutil.rmtree(repo_dir, ignore_errors=True)
            if tmp_out:
                shutil.rmtree(tmp_out, ignore_errors=True)
            if tmp_cfg and tmp_cfg.exists():
                tmp_cfg.unlink(missing_ok=True)
            if sweagent_tmp:
                shutil.rmtree(sweagent_tmp, ignore_errors=True)

        with write_lock:
            with open(out_path, "a") as f:
                print(json.dumps(record), file=f, flush=True)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_process_one, inst): inst for inst in todo}
        with tqdm(total=len(todo), desc=f"SWE-agent inference ({model_name})") as pbar:
            for fut in as_completed(futs):
                fut.result()
                pbar.update(1)
