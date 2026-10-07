"""pytest plugin used by ``evaluate_submission.py`` to attribute triggers to tests.

Loaded with ``-p scibench_pytest_plugin``. It records, per test, the outcome of
every phase and the checker IDs appended to ``SCIBENCH_TRIGGER_LOG`` while that
test ran. A trigger only counts later if the whole test passed.
"""
import json
import os
import sys

import pytest

_LOG = os.environ["SCIBENCH_TRIGGER_LOG"]
_OUT = os.environ["SCIBENCH_RESULT_JSON"]
_records = []
_SEEN = {}
# files added by the submission: only functions defined there count as test-defined production code
# (upstream production modules legitimately re-export helpers that live in ``tests/`` directories)
_SUBMITTED = {os.path.realpath(p) for p in os.environ.get("SCIBENCH_SUBMITTED", "").split(os.pathsep) if p}


def _size():
    return os.path.getsize(_LOG) if os.path.exists(_LOG) else 0


def _ids_since(start):
    if not os.path.exists(_LOG):
        return []
    with open(_LOG, "rb") as fh:
        fh.seek(start)
        out = []
        for line in fh.read().decode("utf-8", "replace").splitlines():
            try:
                out.append(json.loads(line)["checker_id"])
            except Exception:
                continue
        return out


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    phases = getattr(item, "_scibench_phases", None)
    if phases is None:
        phases = item._scibench_phases = {}
    phases[rep.when] = "xfailed" if hasattr(rep, "wasxfail") else rep.outcome


def _tampering():
    """Production code replaced at run time (SANITIZER.md 9.1: tests may not modify production code).

    Flags, in every loaded ``sunpy*`` module, mock objects, functions whose code was defined in the
    test tree, and callables whose identity changed since the module was first seen.
    """
    import types
    import unittest.mock as um

    found = []
    for name, mod in list(sys.modules.items()):
        if mod is None or not (name == "sunpy" or name.startswith("sunpy.")):
            continue
        # sunpy keeps its tests inside the package: they are not production code
        if ".tests" in name or name.endswith("conftest") or name.startswith("sunpy.tests"):
            continue
        try:
            attrs = dict(vars(mod))
        except TypeError:
            continue
        seen = _SEEN.setdefault(name, {k: id(v) for k, v in attrs.items()})
        for k, v in attrs.items():
            if isinstance(v, um.NonCallableMock):
                found.append(f"{name}.{k} is a mock")
            elif isinstance(v, types.FunctionType) and os.path.realpath(v.__code__.co_filename) in _SUBMITTED:
                found.append(f"{name}.{k} defined in {v.__code__.co_filename}")
            elif k in seen and seen[k] != id(v) and callable(v):
                found.append(f"{name}.{k} was replaced")
    return found


_EVENTS = []


def _is_production(name):
    return (name == "sunpy" or name.startswith("sunpy.")) and ".tests" not in name \
        and not name.endswith("conftest") and not name.startswith("sunpy.tests")


def _make_tracked():
    import types

    class _Tracked(types.ModuleType):
        """Records external attribute (re)assignment on a production module, even if it is undone later."""

        def __setattr__(self, key, value):
            old = self.__dict__.get(key)
            if callable(old) or callable(value):
                _EVENTS.append(f"{self.__name__}.{key} reassigned during the test")
            super().__setattr__(key, value)

        def __delattr__(self, key):
            _EVENTS.append(f"{self.__name__}.{key} deleted during the test")
            super().__delattr__(key)

    return _Tracked


_TRACKED = _make_tracked()


def _track_modules():
    import types

    for name, mod in list(sys.modules.items()):
        if mod is not None and _is_production(name) and type(mod) is types.ModuleType:
            try:
                mod.__class__ = _TRACKED
            except TypeError:
                pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    _tampering()  # first sighting of the modules loaded so far
    _track_modules()
    del _EVENTS[:]
    yield
    _track_modules()
    found = _tampering() + list(_EVENTS)
    if found:
        item._scibench_tampered = found


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    start = _size()
    yield
    phases = getattr(item, "_scibench_phases", {})
    passed = (phases.get("setup") == "passed" and phases.get("call") == "passed"
              and phases.get("teardown") == "passed")
    rec = {"nodeid": item.nodeid, "phases": phases, "passed": passed, "triggers": _ids_since(start)}
    if getattr(item, "_scibench_tampered", None):
        rec["tampered"] = item._scibench_tampered[:5]
    _records.append(rec)


def pytest_sessionfinish(session):
    with open(_OUT, "w") as fh:
        json.dump(_records, fh)
