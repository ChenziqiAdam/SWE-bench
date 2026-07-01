"""Utilities for backend-tagged agent prediction JSONL files."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


LEGACY_BACKENDS = {"builtin", "sweagent"}


def prediction_matches_backend(row: dict, backend: str, model_name: str) -> bool:
    """Return whether a prediction row belongs to a backend/model pair.

    Older pipeline records did not include ``agent_backend``. Treat those as
    compatible with the historical built-in/SWE-agent runners, but never with
    newer CLI backends, because otherwise a new eval could silently reuse old
    rows.
    """
    if row.get("model_name_or_path") != model_name:
        return False
    row_backend = row.get("agent_backend")
    if row_backend:
        return row_backend == backend
    return backend in LEGACY_BACKENDS


def read_prediction_rows(path: str | Path) -> list[dict]:
    pred_path = Path(path)
    if not pred_path.exists():
        return []
    rows = []
    with open(pred_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_prediction_rows(path: str | Path, rows: Iterable[dict]) -> None:
    pred_path = Path(path)
    pred_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pred_path, "w") as f:
        for row in rows:
            print(json.dumps(row), file=f)


def selected_prediction_rows(
    rows: Iterable[dict],
    backend: str,
    model_name: str,
    instance_ids: set[str] | None = None,
) -> list[dict]:
    """Return one latest matching prediction row per instance."""
    by_id: dict[str, dict] = {}
    for row in rows:
        instance_id = row.get("instance_id")
        if not instance_id:
            continue
        if instance_ids is not None and instance_id not in instance_ids:
            continue
        if prediction_matches_backend(row, backend, model_name):
            by_id[instance_id] = row
    return list(by_id.values())


def write_selected_predictions(
    source_path: str | Path,
    dest_path: str | Path,
    backend: str,
    model_name: str,
    instance_ids: set[str] | None = None,
) -> int:
    rows = selected_prediction_rows(
        read_prediction_rows(source_path),
        backend=backend,
        model_name=model_name,
        instance_ids=instance_ids,
    )
    write_prediction_rows(dest_path, rows)
    return len(rows)
