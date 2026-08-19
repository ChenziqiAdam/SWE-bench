#!/usr/bin/env python3
"""Curator-only adapter for task 0020: invokes pinned spsur::spsurtime() verbatim
via Rscript against an official covid19-environmental-correlates checkout. Follows
the same CLI contract as official_adapter.py (--task/--checkout/--input/--output/
--raw-output) so it slots into promote_official.py unchanged; the underlying
computation runs in R because the official implementation is an R analysis
(README.Rmd), not a Python module.

spsur 1.0.1.3 (2020-04) requires an era-matched spatialreg (>= 1.1-5, whose
anova.sarlm S3 export spsur imports directly) and spdep (1.1-8); both need small
FCONE/DOUBLE_EPS patches (curation_tools/patches/0020-*.patch) to compile against
modern R's stricter Fortran-character-length ABI. Neither patch changes numerical
behavior -- they only restore the calling convention the old C code assumed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

TASK_SUFFIX = "0020"

DRIVER_PATH = Path(__file__).resolve().parent / "covid19env_driver.R"

README_SHA256 = "833de267c429ac99d37e84bd946924eeb75ab749e7d4c9012ecc09091b72b68b"
SPSUR_TARBALL_SHA256 = "0b2ee549d46f8e00ec9f031310abbb6305d973f55f1afc95df0a8d521dda723f"
COVID19ENV_TARBALL_SHA256 = "9974602f0ed6de1aaa7ee9c03e8449746d8b1b4aedba11880a4b50fc61b75e69"

LAST_RAW: dict[str, Any] | None = None


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _r_env(rscript: str) -> dict[str, str]:
    # source packages (spatialreg/spdep) need the conda env's own C/Fortran
    # compilers, which only resolve via Makeconf if that env's bin/ leads PATH.
    env_bin = str(Path(rscript).resolve().parent)
    path = os.environ.get("PATH", "")
    return dict(os.environ, RENV_CONFIG_AUTOLOADER_ENABLED="FALSE", PATH=f"{env_bin}:{path}")


def resolve_rscript() -> str:
    override = os.environ.get("COVID19ENV_RSCRIPT")
    if override:
        if not Path(override).is_file():
            raise RuntimeError(f"COVID19ENV_RSCRIPT does not point to a file: {override}")
        return override
    sibling = Path(sys.executable).resolve().parent / "Rscript"
    if sibling.is_file():
        return str(sibling)
    conda_base = os.environ.get("CONDA_BASE") or subprocess.check_output(
        ["conda", "info", "--base"], text=True
    ).strip()
    candidate = Path(conda_base) / "envs/scibench-replication-0020/bin/Rscript"
    if not candidate.is_file():
        raise RuntimeError(
            "no R interpreter found; set COVID19ENV_RSCRIPT to the pinned "
            "curation_tools/environments/0020-r-environment.yml Rscript path"
        )
    return str(candidate)


def validate_case(case: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(case, dict):
        raise ValueError("case must be a JSON object")
    required = {"lag_spec", "restricted"}
    if set(case) != required:
        raise ValueError(f"case must have exactly the fields {sorted(required)}")
    if case["lag_spec"] not in {"lag8", "lag11", "lag11w"}:
        raise ValueError("lag_spec must be lag8, lag11, or lag11w")
    if not isinstance(case["restricted"], bool):
        raise ValueError("restricted must be a boolean")
    return case


def verify_pinned_source(checkout: Path) -> None:
    readme_path = checkout / "README.Rmd"
    spsur_tarball = checkout / "spsur_1.0.1.3.tar.gz"
    covid19env_tarball = checkout / "covid19env_0.1.0.tar.gz"
    for path in (readme_path, spsur_tarball, covid19env_tarball):
        if not path.is_file():
            raise RuntimeError(f"pinned official source is missing from checkout: {path.name}")
    if digest(readme_path) != README_SHA256:
        raise RuntimeError("pinned official README.Rmd changed since pinning")
    if digest(spsur_tarball) != SPSUR_TARBALL_SHA256:
        raise RuntimeError("pinned spsur_1.0.1.3.tar.gz changed since pinning")
    if digest(covid19env_tarball) != COVID19ENV_TARBALL_SHA256:
        raise RuntimeError("pinned covid19env_0.1.0.tar.gz changed since pinning")


def _run_r(rscript: str, expr: str, cwd: Path) -> None:
    env = _r_env(rscript)
    subprocess.run(
        [rscript, "--vanilla", "-e", expr],
        check=True, cwd=str(cwd), env=env, capture_output=True, text=True,
    )


def install_packages(checkout: Path, rscript: str) -> None:
    tools_dir = Path(__file__).resolve().parent
    spatialreg_patch = tools_dir / "patches/0020-spatialreg-1.1-5-fclen.patch"
    spdep_fclen_patch = tools_dir / "patches/0020-spdep-1.1-8-fclen.patch"
    spdep_eps_patch = tools_dir / "patches/0020-spdep-1.1-8-double-eps.patch"
    for path in (spatialreg_patch, spdep_fclen_patch, spdep_eps_patch):
        if not path.is_file():
            raise RuntimeError(f"missing curator patch: {path}")

    already_installed = subprocess.run(
        [rscript, "--vanilla", "-e",
         'q(status = if (requireNamespace("spsur", quietly=TRUE) && '
         'requireNamespace("covid19env", quietly=TRUE)) 0 else 1)'],
        cwd=str(checkout), capture_output=True, text=True,
    )
    if already_installed.returncode == 0:
        return

    env = _r_env(rscript)
    result = subprocess.run(
        [rscript, "--vanilla", "-e",
         'install.packages("expm", repos="https://cloud.r-project.org"); '
         'if (!requireNamespace("expm", quietly=TRUE)) stop("install verification failed for expm")'],
        cwd=str(checkout), env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"failed to install expm: {result.stdout}\n{result.stderr}")

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _fetch_and_patch_spdep(tmp_path, rscript, checkout, spdep_fclen_patch, spdep_eps_patch)
        _fetch_and_patch_spatialreg(tmp_path, rscript, checkout, spatialreg_patch)

    _install_checked(rscript, checkout, env, checkout / "spsur_1.0.1.3.tar.gz")
    _install_checked(rscript, checkout, env, checkout / "covid19env_0.1.0.tar.gz")


def _package_name(source: Path) -> str:
    if source.is_dir():
        return source.name
    return source.name.split("_", 1)[0]


def _install_checked(rscript: str, checkout: Path, env: dict[str, str], source: Path) -> None:
    package = _package_name(source)
    expr = (
        f'install.packages("{source}", repos=NULL, type="source"); '
        f'if (!requireNamespace("{package}", quietly=TRUE)) stop("install verification failed for {package}")'
    )
    result = subprocess.run(
        [rscript, "--vanilla", "-e", expr],
        cwd=str(checkout), env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"failed to install {package}: {result.stdout}\n{result.stderr}")


def _apply_patch(source_dir: Path, patch_path: Path) -> None:
    completed = subprocess.run(
        ["patch", "-p1"], cwd=str(source_dir),
        input=patch_path.read_text(encoding="utf-8"), text=True, capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"failed to apply patch {patch_path.name}: {completed.stdout}\n{completed.stderr}"
        )


def _fetch_and_patch_spatialreg(tmp_path: Path, rscript: str, checkout: Path, patch: Path) -> None:
    url = "https://cran.r-project.org/src/contrib/Archive/spatialreg/spatialreg_1.1-5.tar.gz"
    env = _r_env(rscript)
    subprocess.run(["curl", "-sfL", url, "-o", str(tmp_path / "spatialreg.tar.gz")], check=True)
    subprocess.run(["tar", "xzf", str(tmp_path / "spatialreg.tar.gz"), "-C", str(tmp_path)], check=True)
    _apply_patch(tmp_path / "spatialreg", patch)
    _install_checked(rscript, checkout, env, tmp_path / "spatialreg")


def _fetch_and_patch_spdep(tmp_path: Path, rscript: str, checkout: Path, fclen_patch: Path, eps_patch: Path) -> None:
    url = "https://cran.r-project.org/src/contrib/Archive/spdep/spdep_1.1-8.tar.gz"
    env = _r_env(rscript)
    subprocess.run(["curl", "-sfL", url, "-o", str(tmp_path / "spdep.tar.gz")], check=True)
    subprocess.run(["tar", "xzf", str(tmp_path / "spdep.tar.gz"), "-C", str(tmp_path)], check=True)
    _apply_patch(tmp_path / "spdep", fclen_patch)
    _apply_patch(tmp_path / "spdep", eps_patch)
    _install_checked(rscript, checkout, env, tmp_path / "spdep")


def solve(case: dict[str, Any], checkout: Path) -> dict[str, Any]:
    global LAST_RAW
    clean = validate_case(case)
    verify_pinned_source(checkout)
    rscript = resolve_rscript()
    install_packages(checkout, rscript)

    input_path = checkout / "_covid19env_adapter_case.json"
    input_path.write_text(json.dumps(clean), encoding="utf-8")
    env = _r_env(rscript)
    try:
        completed = subprocess.run(
            [rscript, "--vanilla", str(DRIVER_PATH), str(input_path)],
            check=True, cwd=str(checkout), env=env, capture_output=True, text=True,
        )
    finally:
        input_path.unlink(missing_ok=True)

    raw = json.loads(completed.stdout)
    LAST_RAW = raw

    names = list(raw["coefficient_names"])
    coefficients = {name: float(value) for name, value in zip(names, raw["coefficients"])}
    std_errors = {name: float(value) for name, value in zip(names, raw["std_errors"])}
    result = {
        "coefficients": coefficients,
        "std_errors": std_errors,
        "rho": [float(value) for value in raw["rho"]],
        "r2_by_equation": [float(value) for value in raw["r2_by_equation"]],
        "pooled_r2": float(raw["pooled_r2"]),
    }
    for key in ("rho", "r2_by_equation"):
        if not all(math.isfinite(value) for value in result[key]):
            raise ValueError(f"non-finite value in {key}")
    for mapping_key in ("coefficients", "std_errors"):
        if not all(math.isfinite(value) for value in result[mapping_key].values()):
            raise ValueError(f"non-finite value in {mapping_key}")
    if not math.isfinite(result["pooled_r2"]):
        raise ValueError("non-finite pooled_r2")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path)
    args = parser.parse_args()
    if args.task != TASK_SUFFIX:
        parser.error("unsupported task")
    case = json.loads(args.input.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    result = solve(case, args.checkout.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    if args.raw_output is not None:
        if LAST_RAW is None:
            raise RuntimeError("adapter did not expose raw official output")
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        args.raw_output.write_text(json.dumps(LAST_RAW, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
