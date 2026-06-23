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


MAP_REPO_TO_PARSER_C = {
    "redis/redis": parse_log_redis,
    "jqlang/jq": parse_log_jq,
    "nlohmann/json": parse_log_doctest,
    "micropython/micropython": parse_log_micropython_test,
    "valkey-io/valkey": parse_log_redis,
    "fmtlib/fmt": parse_log_googletest,
    "openbabel/openbabel": parse_log_googletest,
    "openmm/openmm": parse_log_googletest,
    "openmc-dev/openmc": parse_log_googletest,
    "qgis/QGIS": parse_log_googletest,
    "rdkit/rdkit": parse_log_catch2,
}
