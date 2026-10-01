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
# any supported Python, or needs heavy C/C++ toolchain curation).
EXPECTED_NON_EVALUABLE = {
    ("qiskit/qiskit", "845"),
    ("obspy/obspy", "956"),
    ("sunpy/sunpy", "1505"),
    ("yt-project/yt", "2128"),
    ("yt-project/yt", "2485"),
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
