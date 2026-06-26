import re
import xml.etree.ElementTree as ET

from swebench.harness.constants import TestStatus
from swebench.harness.test_spec.test_spec import TestSpec


def parse_log_redis(log: str, test_spec: TestSpec) -> dict[str, str]:
    """
    Args:
        log (str): log content
    Returns:
        dict: test case to test status mapping
    """
    test_status_map = {}

    pattern = r"^\[(ok|err|skip|ignore)\]:\s(.+?)(?:\s\((\d+\s*m?s)\))?$"

    for line in log.split("\n"):
        match = re.match(pattern, line.strip())
        if match:
            status, test_name, _duration = match.groups()
            if status == "ok":
                test_status_map[test_name] = TestStatus.PASSED.value
            elif status == "err":
                # Strip out file path information from failed test names
                test_name = re.sub(r"\s+in\s+\S+$", "", test_name)
                test_status_map[test_name] = TestStatus.FAILED.value
            elif status == "skip" or status == "ignore":
                test_status_map[test_name] = TestStatus.SKIPPED.value

    return test_status_map


def parse_log_jq(log: str, test_spec: TestSpec) -> dict[str, str]:
    """
    Args:
        log (str): log content
    Returns:
        dict: test case to test status mapping
    """
    test_status_map = {}

    pattern = r"^\s*(PASS|FAIL):\s(.+)$"

    for line in log.split("\n"):
        match = re.match(pattern, line.strip())
        if match:
            status, test_name = match.groups()
            if status == "PASS":
                test_status_map[test_name] = TestStatus.PASSED.value
            elif status == "FAIL":
                test_status_map[test_name] = TestStatus.FAILED.value
    return test_status_map


def parse_log_doctest(log: str, test_spec: TestSpec) -> dict[str, str]:
    """
    Assumes test binary runs with -s -r=xml.
    """
    test_status_map = {}

    # Extract XML content
    start_tag = "<doctest"
    end_tag = "</doctest>"
    start_index = log.find(start_tag)
    end_index = (
        log.find(end_tag, start_index) + len(end_tag) if start_index != -1 else -1
    )

    if start_index != -1 and end_index != -1:
        xml_string = log[start_index:end_index]
        root = ET.fromstring(xml_string)

        for testcase in root.findall(".//TestCase"):
            testcase_name = testcase.get("name")
            for subcase in testcase.findall(".//SubCase"):
                subcase_name = subcase.get("name")
                name = f"{testcase_name} > {subcase_name}"

                expressions = subcase.findall(".//Expression")
                subcase_passed = all(
                    expr.get("success") == "true" for expr in expressions
                )

                if subcase_passed:
                    test_status_map[name] = TestStatus.PASSED.value
                else:
                    test_status_map[name] = TestStatus.FAILED.value

    return test_status_map


def parse_log_micropython_test(log: str, test_spec: TestSpec) -> dict[str, str]:
    test_status_map = {}

    pattern = r"^(pass|FAIL|skip)\s+(.+)$"

    for line in log.split("\n"):
        match = re.match(pattern, line.strip())
        if match:
            status, test_name = match.groups()
            if status == "pass":
                test_status_map[test_name] = TestStatus.PASSED.value
            elif status == "FAIL":
                test_status_map[test_name] = TestStatus.FAILED.value
            elif status == "skip":
                test_status_map[test_name] = TestStatus.SKIPPED.value

    return test_status_map


def parse_log_catch2(log: str, test_spec: TestSpec) -> dict[str, str]:
    """Parse Catch2 test output (used by rdkit and other CMake+Catch2 repos).

    Catch2 v2/v3 emits lines like:
        PASSED: TestName
        FAILED: TestName
    and section headers like:
        -------------------------------------------------------------------------------
        TestName
        -------------------------------------------------------------------------------
    We use the explicit PASSED/FAILED markers which are reliable across versions.
    """
    test_status_map = {}
    passed_re = re.compile(r"^\s*PASSED:\s*\[([^\]]+)\]\s*(.+)$")
    failed_re = re.compile(r"^\s*FAILED:\s*\[([^\]]+)\]\s*(.+)$")
    # Catch2 also emits summary lines like "test cases: N | N passed | N failed"
    # and per-test lines "  TestName  -  N assertion(s) failed"
    per_test_re = re.compile(r"^\s*(PASSED|FAILED)\s*-\s*(.+)$")
    # v3 style: "PASSED  <TestName>" or "FAILED  <TestName>"
    simple_re = re.compile(r"^(PASSED|FAILED)\s{2,}(.+)$")

    for line in log.split("\n"):
        line = line.rstrip()
        for pattern, status_group, name_group in [
            (passed_re, 1, 2),
            (failed_re, 1, 2),
        ]:
            m = pattern.match(line)
            if m:
                name = m.group(name_group).strip()
                status = TestStatus.PASSED.value if "PASSED" in pattern.pattern else TestStatus.FAILED.value
                test_status_map[name] = status
                break
        else:
            m = simple_re.match(line)
            if m:
                status_str, name = m.group(1), m.group(2).strip()
                test_status_map[name] = (
                    TestStatus.PASSED.value if status_str == "PASSED" else TestStatus.FAILED.value
                )
    return test_status_map


def parse_log_googletest(log: str, test_spec: TestSpec) -> dict[str, str]:
    test_status_map = {}

    pattern = r"^.*\[\s*(OK|FAILED)\s*\]\s(.*)\s\(.*\)$"

    for line in log.split("\n"):
        match = re.match(pattern, line.strip())
        if match:
            status, test_name = match.groups()
            if status == "OK":
                test_status_map[test_name] = TestStatus.PASSED.value
            elif status == "FAILED":
                test_status_map[test_name] = TestStatus.FAILED.value

    return test_status_map


def parse_log_pytest_nodeid(log: str, test_spec: TestSpec) -> dict[str, str]:
    """Parse `pytest -v` output where each line is `<nodeid> STATUS [pct]`.

    e.g. `path/Test.py::Cls::test_x PASSED` / `... FAILED` / `... SKIPPED`.
    The nodeid (which contains '::') is the key, matching FAIL_TO_PASS entries.
    """
    test_status_map = {}
    status_words = {
        "PASSED": TestStatus.PASSED.value,
        "FAILED": TestStatus.FAILED.value,
        "ERROR": TestStatus.ERROR.value,
        "SKIPPED": TestStatus.SKIPPED.value,
        "XFAIL": TestStatus.PASSED.value,
        "XPASS": TestStatus.PASSED.value,
    }
    for line in log.split("\n"):
        line = line.strip()
        if "::" not in line:
            continue
        tokens = line.split()
        nodeid = tokens[0]
        if "::" not in nodeid:
            continue
        # status may be token[1] (`nodeid PASSED`) or appear later (`PASSED nodeid`).
        for tok in tokens[1:]:
            tok_clean = tok.strip().upper()
            if tok_clean in status_words:
                test_status_map[nodeid] = status_words[tok_clean]
                break
    return test_status_map


def _reconcile_nodeids(status_map: dict, test_spec: TestSpec) -> dict:
    """Map parsed (possibly path-stripped) pytest nodeids back to the exact
    FAIL_TO_PASS/PASS_TO_PASS keys grading compares against.

    pytest prints nodeids relative to its CWD/rootdir, so a test_cmd that does
    `cd wrappers/python/tests && pytest TestX.py::...` yields a key without the
    `wrappers/python/tests/` prefix, which would not match the full-path key in
    FAIL_TO_PASS. Reconcile by suffix-match against the expected keys."""
    if test_spec is None:
        return status_map
    expected = list(getattr(test_spec, "FAIL_TO_PASS", []) or []) + list(
        getattr(test_spec, "PASS_TO_PASS", []) or []
    )
    if not expected:
        return status_map
    reconciled = dict(status_map)
    for parsed_key, status in status_map.items():
        if parsed_key in expected:
            continue
        for exp in expected:
            # exp is full-path nodeid; parsed_key may be the trailing portion.
            if exp == parsed_key or exp.endswith("/" + parsed_key) or exp.endswith(
                "::" + parsed_key
            ):
                reconciled[exp] = status
                break
    return reconciled


def parse_log_openmm(log: str, test_spec: TestSpec) -> dict[str, str]:
    """OpenMM has both pytest (Python PRs) and GoogleTest (C++ PRs) instances.
    Dispatch by detecting pytest nodeids; fall back to GoogleTest otherwise."""
    pytest_map = parse_log_pytest_nodeid(log, test_spec)
    if pytest_map:
        return _reconcile_nodeids(pytest_map, test_spec)
    return parse_log_googletest(log, test_spec)


MAP_REPO_TO_PARSER_C = {
    "redis/redis": parse_log_redis,
    "jqlang/jq": parse_log_jq,
    "nlohmann/json": parse_log_doctest,
    "micropython/micropython": parse_log_micropython_test,
    "valkey-io/valkey": parse_log_redis,
    "fmtlib/fmt": parse_log_googletest,
    "openbabel/openbabel": parse_log_googletest,
    "openmm/openmm": parse_log_openmm,
    "openmc-dev/openmc": parse_log_googletest,
    "qgis/QGIS": parse_log_googletest,
    "rdkit/rdkit": parse_log_catch2,
}
