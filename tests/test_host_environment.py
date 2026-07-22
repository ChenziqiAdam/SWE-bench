import subprocess
from pathlib import Path

from swebench.eval_pipeline import host_environment
from swebench.eval_pipeline.host_environment import isolated_python_environment


def test_isolated_python_environment_does_not_reuse_active_prefix(tmp_path):
    with isolated_python_environment(tmp_path) as environment:
        completed = subprocess.run(
            [
                "python",
                "-c",
                "import sys; print(int(sys.prefix != sys.base_prefix))",
            ],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        virtual_environment = environment["VIRTUAL_ENV"]

    assert completed.stdout.strip() == "1"
    assert not Path(virtual_environment).exists()


def test_isolated_python_environment_suppresses_cleanup_race(tmp_path, monkeypatch):
    real_rmtree = host_environment.shutil.rmtree
    calls = []

    def flaky_rmtree(path, *args, **kwargs):
        calls.append(kwargs.get("ignore_errors", False))
        if len(calls) == 1:
            raise OSError(39, "Directory not empty")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(host_environment.shutil, "rmtree", flaky_rmtree)
    with isolated_python_environment(tmp_path) as environment:
        virtual_environment = environment["VIRTUAL_ENV"]

    assert calls == [False, True]
    assert not Path(virtual_environment).exists()
