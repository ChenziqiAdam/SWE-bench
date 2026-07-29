#!/usr/bin/env python3
"""Select a task evaluator from the trusted gold task ID."""

from __future__ import annotations

import sys

from .framework import run_cli
from .plugins import PLUGINS


def run_for_task(task_id: str) -> int:
    try:
        plugin = PLUGINS[task_id]
    except KeyError:
        print(f"evaluation input error: unsupported task {task_id}", file=sys.stderr)
        return 2
    return run_cli(plugin)
