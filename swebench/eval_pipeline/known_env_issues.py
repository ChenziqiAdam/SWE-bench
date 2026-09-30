"""Instances whose outcome is decided by the environment, not by the model.

``IGNORED_INSTANCES``: verified unfixable with the current harness. A
non-resolved result for one of these gets status ``ignored`` and is left out of
every denominator (a genuine ``resolved`` is still reported as resolved).

``ENV_NOTES``: suspected or partially fixed environment problems. The status is
untouched; the note is written to the ``env_note`` CSV column so the result can
be read with the caveat attached.

Extra entries can be supplied without editing code through a JSON file named
by ``SWEBENCH_KNOWN_ENV_ISSUES`` with keys ``ignored`` and ``notes`` (both
``{instance_id: reason}``).
"""

from __future__ import annotations

import json
import os

IGNORED_INSTANCES: dict[str, str] = {
    "lammps__lammps-597": (
        "2017 commit has no cmake/ or unittest/ tree, so no generated test can "
        "be built (CMake Error: source directory /testbed/cmake does not exist)"
    ),
}

ENV_NOTES: dict[str, str] = {
    "astropy__astropy-9079": (
        "numpy ABI mismatch in the built image; spec now uses --no-build-isolation "
        "(unverified, re-run to confirm)"
    ),
    "mne-tools__mne-python-9459": (
        "matplotlib >=3.5 raises MatplotlibDeprecationWarning (rectprops) in mne's "
        "widgets; spec pinned to matplotlib 3.4.3 (unverified, re-run to confirm)"
    ),
    "qutip__qutip-1195": (
        "library code calls np.zeros() with a float shape for half-integer spin "
        "(TypeError on modern numpy) independent of the fix; tests using such j fail on gold"
    ),
    "openmm__openmm-2429": (
        "Context creation for a Drude+PME system raised 'Platform does not support "
        "all required kernels' for one model but not another; cause not identified"
    ),
    "qgis__QGIS-64781": (
        "saved logs are cut inside the build (256 KiB cap), verdict cannot be audited "
        "from the log; check *.tail.log after re-running"
    ),
}


def _extra() -> tuple[dict[str, str], dict[str, str]]:
    path = os.environ.get("SWEBENCH_KNOWN_ENV_ISSUES")
    if not path:
        return {}, {}
    with open(path) as handle:
        data = json.load(handle)
    return dict(data.get("ignored") or {}), dict(data.get("notes") or {})


def ignored_reason(instance_id: str) -> str:
    extra_ignored, _ = _extra()
    return extra_ignored.get(instance_id) or IGNORED_INSTANCES.get(instance_id, "")


def env_note(instance_id: str) -> str:
    _, extra_notes = _extra()
    return extra_notes.get(instance_id) or ENV_NOTES.get(instance_id, "")
