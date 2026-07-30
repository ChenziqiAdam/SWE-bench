"""Filesystem boundaries and cache identity for benchmark inference."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable


def inference_input_hash(instance: dict) -> str:
    """Return a stable identity for every field supplied to an inference run."""
    payload = json.dumps(
        instance,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def inference_worktree_root(backend: str) -> Path:
    """Use a private checkout root that is not nested below result caches."""
    configured = os.environ.get("SWE_AGENT_TMPDIR")
    if configured:
        root = Path(configured).expanduser().resolve() / backend
    else:
        var_tmp = Path("/var/tmp")
        base = var_tmp if var_tmp.is_dir() and os.access(var_tmp, os.W_OK) else Path(
            tempfile.gettempdir()
        )
        root = base / f"swebench-inference-{os.getuid()}" / backend
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def inference_hidden_paths(
    output_file: str | Path,
    extra_paths: Iterable[str | Path] = (),
) -> list[str]:
    """Collect existing benchmark artifacts that must be invisible to agents."""
    project_root = Path(__file__).resolve().parents[2]
    candidates = [
        Path(output_file).resolve().parent,
        project_root / "outputs",
        project_root / "logs",
        project_root / "PROCESS.md",
        *project_root.glob("*.xlsx"),
        *(Path(path).expanduser().resolve() for path in extra_paths if path),
    ]
    existing = sorted(
        {path.resolve() for path in candidates if path.exists()},
        key=lambda path: (len(path.parts), str(path)),
    )
    minimal: list[Path] = []
    for path in existing:
        if any(path == parent or parent in path.parents for parent in minimal):
            continue
        minimal.append(path)
    return [str(path) for path in minimal]


def guarded_hidden_paths(
    policy: str,
    output_file: str | Path,
    extra_paths: Iterable[str | Path] = (),
) -> list[str]:
    """Return filesystem hides for formal guarded runs.

    ``unrestricted`` is the documented debugging escape hatch and cannot
    promise a host filesystem boundary.
    """
    if policy != "model-only":
        return []
    return inference_hidden_paths(output_file, extra_paths)
