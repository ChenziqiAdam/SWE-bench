import subprocess
from pathlib import Path

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
