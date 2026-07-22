"""Isolated host environments for standalone repository evaluation."""
from __future__ import annotations

import os
import tempfile
import venv
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def isolated_python_environment(parent: str | Path) -> Iterator[dict[str, str]]:
    """Yield an environment backed by a disposable virtual environment."""
    Path(parent).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="python-env-", dir=parent) as temp_dir:
        environment_dir = Path(temp_dir) / "venv"
        venv.EnvBuilder(with_pip=True).create(environment_dir)
        bin_dir = environment_dir / ("Scripts" if os.name == "nt" else "bin")
        environment = dict(os.environ)
        environment["PATH"] = str(bin_dir) + os.pathsep + environment.get("PATH", "")
        environment["VIRTUAL_ENV"] = str(environment_dir)
        environment.pop("PYTHONHOME", None)
        yield environment
