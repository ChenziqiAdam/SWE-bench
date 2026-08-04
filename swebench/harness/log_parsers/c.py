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


def _parse_python_unittest_summary(log: str) -> dict[str, str]:
    """Parse unittest summaries from shell-xtraced Python commands."""
    test_status_map = {}
    unittest_name = None
    command_re = re.compile(
        r"^\+\s+(?:\S+=\S+\s+)*(?:xvfb-run\s+-a\s+)?"
        r"(?:\S*/)?python3?\s+(\S+\.py)(?:\s+\S+)*\s*$"
    )
    for line in log.splitlines():
        match = command_re.match(line.strip())
        if match:
            unittest_name = match.group(1)
        elif unittest_name and re.match(r"^OK(?:\s+\(.+\))?$", line.strip()):
            test_status_map[unittest_name] = TestStatus.PASSED.value
        elif unittest_name and line.strip().startswith("FAILED"):
            test_status_map[unittest_name] = TestStatus.FAILED.value
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
    # v3 style: "PASSED  <TestName>" or "FAILED  <TestName>"
    simple_re = re.compile(r"^(PASSED|FAILED)\s{2,}(.+)$")
    ctest_re = re.compile(
        r"^\s*\d+/\d+\s+Test\s+#\d+:\s+(.+?)\s+\.+\s*(?:\*+)?(Passed|Failed)\b"
    )
    ctest_error_re = re.compile(
        r"^\s*\d+/\d+\s+Test\s+#\d+:\s+(.+?)\s+\.+.*"
        r"(?:Subprocess aborted|Exception|Timeout)\b"
    )

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
                continue
            m = ctest_re.match(line)
            if m:
                name, status_str = m.group(1).strip(), m.group(2)
                test_status_map[name] = (
                    TestStatus.PASSED.value if status_str == "Passed" else TestStatus.FAILED.value
                )
                continue
            m = ctest_error_re.match(line)
            if m:
                test_status_map[m.group(1).strip()] = TestStatus.FAILED.value
    # Some RDKit wrapper tests are Python unittest scripts. They print only
    # "OK" or "FAILED (...)" summaries, so use the xtrace command as the key.
    # Keep parsing after CTest rows because a generated patch can add both C++
    # and Python tests, and test-generation evaluation must retain both.
    test_status_map.update(_parse_python_unittest_summary(log))
    test_status_map.update(parse_log_pytest_nodeid(log, test_spec))
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


def parse_log_qgis(log: str, test_spec: TestSpec) -> dict[str, str]:
    """Parse QGIS GoogleTest output and CTest-wrapped Python test results."""
    test_status_map = parse_log_googletest(log, test_spec)
    ctest_re = re.compile(
        r"^\s*\d+/\d+\s+Test\s+#\d+:\s+(.+?)\s+\.+\s*"
        r"(?:\*+)?(Passed|Failed)\b"
    )
    ctest_error_re = re.compile(
        r"^\s*\d+/\d+\s+Test\s+#\d+:\s+(.+?)\s+\.+.*"
        r"(?:Subprocess aborted|Exception|Timeout)\b"
    )
    for line in log.splitlines():
        match = ctest_re.match(line)
        if match:
            name, status = match.groups()
            test_status_map[name.strip()] = (
                TestStatus.PASSED.value
                if status == "Passed"
                else TestStatus.FAILED.value
            )
            continue
        match = ctest_error_re.match(line)
        if match:
            test_status_map[match.group(1).strip()] = TestStatus.FAILED.value
    test_status_map.update(_parse_python_unittest_summary(log))
    test_status_map.update(parse_log_pytest_nodeid(log, test_spec))
    return test_status_map


def parse_log_openmm_binary_done(log: str, test_spec: TestSpec) -> dict[str, str]:
    """Parse OpenMM's legacy C++ test binaries.

    These tests are not GoogleTest. On success they print `Done` and exit 0.
    The harness log includes shell xtrace lines such as
    `+ ./build/TestReferenceMonteCarloMembraneBarostat`; use the executable name
    as the synthetic test key so mining/eval can compare the same key.
    """
    test_status_map = {}
    test_name = None
    for line in log.splitlines():
        match = re.match(r"^\+\s+(?:\S+=\S+\s+)*(\./build/\S+)\s*$", line.strip())
        if match:
            test_name = match.group(1).split("/")[-1]
        elif line.strip() == "Done":
            test_status_map[test_name or "OpenMMBinary"] = TestStatus.PASSED.value
        elif (
            re.match(r"^\+?\s*exception:", line.strip())
            or "No such file or directory" in line
            # An uncaught C++ exception (e.g. a raw std::runtime_error the
            # test doesn't wrap in OpenMM's own "exception:"-prefixed
            # printer) aborts the process via std::terminate instead of
            # printing "exception:" or "Done". Recognize that crash text too,
            # or a genuine test failure is left unparseable.
            or "terminate called after throwing an instance of" in line
        ):
            test_status_map[test_name or "OpenMMBinary"] = TestStatus.FAILED.value

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
        if tokens[0].upper() in status_words and len(tokens) > 1:
            status = status_words[tokens[0].upper()]
            nodeid = tokens[1]
            if "::" in nodeid:
                test_status_map[nodeid] = status
            continue
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
    """Combine Python and native statuses from OpenMM mixed patches."""
    status_map = parse_log_openmm_binary_done(log, test_spec)
    status_map.update(parse_log_googletest(log, test_spec))
    status_map.update(
        _reconcile_nodeids(parse_log_pytest_nodeid(log, test_spec), test_spec)
    )
    return status_map


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
    "qgis/QGIS": parse_log_qgis,
    "rdkit/rdkit": parse_log_catch2,
    "lammps/lammps": parse_log_qgis,
}
