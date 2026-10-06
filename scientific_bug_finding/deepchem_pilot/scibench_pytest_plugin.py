"""pytest plugin used by ``evaluate_submission.py`` to attribute triggers to tests.

Loaded with ``-p scibench_pytest_plugin``. It records, per test, the outcome of
every phase and the checker IDs appended to ``SCIBENCH_TRIGGER_LOG`` while that
test ran. A trigger only counts later if the whole test passed.
"""
import json
import os

import pytest

_LOG = os.environ["SCIBENCH_TRIGGER_LOG"]
_OUT = os.environ["SCIBENCH_RESULT_JSON"]
_records = []


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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    start = _size()
    yield
    phases = getattr(item, "_scibench_phases", {})
    passed = (phases.get("setup") == "passed" and phases.get("call") == "passed"
              and phases.get("teardown") == "passed")
    _records.append({"nodeid": item.nodeid, "phases": phases, "passed": passed,
                     "triggers": _ids_since(start)})


def pytest_sessionfinish(session):
    with open(_OUT, "w") as fh:
        json.dump(_records, fh)
