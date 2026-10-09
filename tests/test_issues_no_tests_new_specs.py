"""Coverage lock for the Issues_No_Tests_new.xlsx eval test specs.

Every one of the 75 new instances must resolve a per-PR spec key, and
`make_test_spec` must succeed for it. Specs are grouped as either "real"
(a genuine build + test command) or an explicit non-evaluable placeholder
(``echo '... not evaluable' && false`` + ``_curation_todo``). This test
pins both sets so a later spec edit cannot silently drop or downgrade one.
"""
import json
from pathlib import Path

import pytest

from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS
from swebench.harness.test_spec.test_spec import make_test_spec

_INSTANCES = Path("outputs/issues_no_tests_new_ds/instances.jsonl")

# PRs deliberately shipped as non-evaluable placeholders (base repo predates
# any supported Python, or needs heavy C/C++ toolchain curation). qiskit-845,
# obspy-956, yt-2128/2485 were curated 2026-10-04 and are no longer here.
EXPECTED_NON_EVALUABLE = {
    ("sunpy/sunpy", "1505"),
    ("psi4/psi4", "1244"),
    ("psi4/psi4", "3005"),
    ("qgis/QGIS", "52213"),
    ("qgis/QGIS", "52303"),
    ("qgis/QGIS", "52476"),
    ("qgis/QGIS", "57840"),
    ("fenics/dolfinx", "1264"),
}


def _load_instances():
    if not _INSTANCES.exists():
        pytest.skip(f"{_INSTANCES} not present")
    return [json.loads(line) for line in _INSTANCES.read_text().splitlines() if line.strip()]


def _spec_for(repo: str, pr: str):
    return MAP_REPO_VERSION_TO_SPECS[repo][pr]


def _is_non_evaluable(spec) -> bool:
    tc = spec.get("test_cmd")
    text = "\n".join(tc) if isinstance(tc, (list, tuple)) else str(tc or "")
    return "not evaluable" in text or "no curated spec" in text


def test_every_new_instance_resolves_a_spec_key():
    missing = []
    for inst in _load_instances():
        repo, pr = inst["repo"], str(inst["pull_number"])
        try:
            _spec_for(repo, pr)
        except KeyError:
            missing.append((repo, pr))
    assert not missing, f"instances with no spec key: {missing}"


def test_make_test_spec_succeeds_for_every_new_instance():
    failures = []
    for inst in _load_instances():
        pr = str(inst["pull_number"])
        stub = {**inst, "version": pr, "FAIL_TO_PASS": [], "PASS_TO_PASS": []}
        try:
            make_test_spec(stub)
        except Exception as exc:  # noqa: BLE001
            failures.append((inst["repo"], pr, str(exc)[:120]))
    assert not failures, f"make_test_spec failures: {failures}"


def test_non_evaluable_placeholder_set_is_exactly_as_expected():
    actual = set()
    for inst in _load_instances():
        repo, pr = inst["repo"], str(inst["pull_number"])
        spec = _spec_for(repo, pr)
        if _is_non_evaluable(spec):
            actual.add((repo, pr))
            assert spec.get("_curation_todo"), f"{repo}#{pr} placeholder lacks _curation_todo"
    assert actual == EXPECTED_NON_EVALUABLE, (
        f"non-evaluable set drifted.\n  unexpected: {actual - EXPECTED_NON_EVALUABLE}"
        f"\n  missing: {EXPECTED_NON_EVALUABLE - actual}"
    )


def test_real_specs_have_a_runnable_test_command():
    for inst in _load_instances():
        repo, pr = inst["repo"], str(inst["pull_number"])
        spec = _spec_for(repo, pr)
        if _is_non_evaluable(spec):
            continue
        tc = spec.get("test_cmd")
        text = " ".join(tc) if isinstance(tc, (list, tuple)) else str(tc or "")
        assert text.strip(), f"{repo}#{pr} real spec has empty test_cmd"
        assert ("pytest" in text) or ("ctest" in text) or ("make test" in text), (
            f"{repo}#{pr} real spec test_cmd is not a recognised runner: {text!r}"
        )


# Regression locks for build/import failures seen in the 2026-10-01 server run
# (build_diagnostics tails). Each pins the pin that fixes the logged error.
def test_astropy_12525_numpy_predates_asscalar_removal():
    spec = _spec_for("astropy/astropy", "12525")
    assert spec["python"] == "3.10"  # numpy<1.23 has no cp311 wheels
    assert "numpy==1.22.4" in spec["pip_packages"]
    assert "numpy==1.22.4" in spec["install"]


def test_obspy_setuptools_keeps_feature_class():
    for pr in ("2560", "2570"):
        pre = " ".join(_spec_for("obspy/obspy", pr)["pre_install"])
        assert "setuptools==45.3.0" in pre  # setuptools.Feature removed in 46


def test_pyscf_cmake_below_4_and_17x_prebuild():
    for pr in ("551", "794", "1143", "1164", "1219"):
        assert "'cmake<4'" in " ".join(_spec_for("pyscf/pyscf", pr)["pre_install"])
    for pr in ("551", "794"):
        install = _spec_for("pyscf/pyscf", pr)["install"]
        assert "cmake ..;" in install and "-lblas" in install
        assert install.index("--target libcint") < install.index("--target libxc libxcfun")
        assert install.index("--target libxc libxcfun") < install.index("pip install -e")


def test_nilearn_installs_requests_for_no_deps_build():
    for pr in ("2431", "2706"):
        assert "requests" in _spec_for("nilearn/nilearn", pr)["pip_packages"]


def test_yt_40_spec_has_nose_for_plotwindow_tests():
    for pr in ("3532", "3556"):
        pkgs = _spec_for("yt-project/yt", pr)["pip_packages"]
        assert "nose==1.3.7" in pkgs and "pytest==7.4.4" in pkgs


def test_qgis_60631_qwt_build_runs_in_subshell():
    # the cwd-relative `cmake -S .` that follows must still run from /testbed
    pre = _spec_for("qgis/QGIS", "60631")["pre_install"]
    qwt = [c for c in pre if "qwt-6.3.0" in c and "qmake6" in c]
    assert len(qwt) == 1 and qwt[0].startswith("(cd /tmp/qwt-6.3.0") and qwt[0].endswith(")")


def test_nilearn_2431_pins_matplotlib_before_cmap_reregister_error():
    assert "matplotlib==3.3.4" in _spec_for("nilearn/nilearn", "2431")["pip_packages"]
    assert "matplotlib==3.5.3" in _spec_for("nilearn/nilearn", "2706")["pip_packages"]


def test_mne_legacy_pins_pyparsing_below_deprecation_warnings():
    assert "pyparsing==3.0.9" in _spec_for("mne-tools/mne-python", "9459")["pip_packages"]


def test_curated_former_placeholders_are_evaluable():
    for repo, pr in (
        ("yt-project/yt", "2128"),
        ("yt-project/yt", "2485"),
        ("obspy/obspy", "956"),
        ("qiskit/qiskit", "845"),
    ):
        spec = _spec_for(repo, pr)
        assert "not evaluable" not in str(spec) and spec["test_cmd"] != "false"


def test_yt_36_spec_is_py37_with_nose_and_old_numpy():
    spec = _spec_for("yt-project/yt", "2128")
    assert spec["python"] == "3.7"
    assert "nose==1.3.7" in spec["pip_packages"] and "numpy==1.17.5" in spec["pip_packages"]


def test_qiskit_845_skips_cmake_build_with_pth():
    spec = _spec_for("qiskit/qiskit", "845")
    assert "testbed.pth" in spec["install"] and "cmake" not in spec["install"]


def test_obspy_956_reuses_numpy_distutils_build_on_py37():
    spec = _spec_for("obspy/obspy", "956")
    assert spec["python"] == "3.7" and "future==0.18.3" in spec["pip_packages"]
    assert "setuptools==45.3.0" in " ".join(spec["pre_install"])
