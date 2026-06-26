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

logger = logging.getLogger(__name__)

_SWEAGENT_TIMEOUT = 600  # seconds per instance


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


def _build_sweagent_config(
    instance: dict,
    repo_dir: Path,
    model_name: str,
    output_dir: Path,
    base_config: Optional[dict] = None,
) -> dict:
    """Build a SWE-agent RunSingleConfig dict for one instance."""
    problem = (instance.get("problem_statement") or "").strip()
    if not problem:
        pr_title = (instance.get("pr_title") or "").strip()
        pr_body = (instance.get("pr_body") or "").strip()
        problem = f"{pr_title}\n\n{pr_body}".strip()

    if base_config:
        cfg = json.loads(json.dumps(base_config))  # deep copy
    else:
        cfg = {
            "agent": {"model": {"name": model_name}},
        }

    # Override env to use local repo + local deployment (no Docker)
    cfg["env"] = {
        "repo": {
            "type": "local",
            "path": str(repo_dir),
            "base_commit": instance["base_commit"],
        },
        "deployment": {"type": "local"},
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
) -> None:
    """Run SWE-agent inference for all instances. Writes same JSONL format as inference.py."""
    base_config: Optional[dict] = None
    if sweagent_config:
        with open(sweagent_config) as f:
            base_config = yaml.safe_load(f)

    # Resume: skip already-done instances
    existing_ids: set[str] = set()
    out_path = Path(output_file)
    if out_path.exists():
        with open(out_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("model_name_or_path") == model_name:
                        existing_ids.add(obj["instance_id"])
                except (json.JSONDecodeError, KeyError):
                    pass
    if existing_ids:
        logger.info(f"Resuming: {len(existing_ids)} predictions already written")

    todo = [i for i in instances if i["instance_id"] not in existing_ids]
    out_path.parent.mkdir(parents=True, exist_ok=True)
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

            cfg = _build_sweagent_config(inst, repo_dir, model_name, tmp_out, base_config)
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

            result = subprocess.run(
                [_sweagent_bin(), "run", "--config", str(tmp_cfg)],
                capture_output=True,
                text=True,
                timeout=_SWEAGENT_TIMEOUT,
                env=env,
            )
            if result.returncode != 0:
                logger.warning(
                    f"[{instance_id}] sweagent exited with code {result.returncode}. "
                    f"stderr: {result.stderr[-500:]}"
                )

            patch = _read_patch_from_output(tmp_out, instance_id)
            patch = _clean_patch(patch)
            patch = _repair_patch(patch)
            record = {
                "instance_id": instance_id,
                "model_patch": patch,
                "model_name_or_path": model_name,
            }
        except subprocess.TimeoutExpired:
            logger.error(f"[{instance_id}] sweagent timed out after {_SWEAGENT_TIMEOUT}s")
            record = {
                "instance_id": instance_id,
                "model_patch": "",
                "model_name_or_path": model_name,
                "error": "timeout",
            }
        except Exception as e:
            logger.error(f"Error on {instance_id}: {e}")
            traceback.print_exc()
            record = {
                "instance_id": instance_id,
                "model_patch": "",
                "model_name_or_path": model_name,
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
