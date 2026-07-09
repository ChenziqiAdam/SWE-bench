from swebench.harness.constants import TestStatus
from swebench.harness.log_parsers.c import (
    parse_log_catch2,
    parse_log_openmm_binary_done,
)


def test_parse_log_catch2_reads_ctest_summary_rows():
    log = """
Test project /testbed/build
    Start 3: chemdrawCatchTest
3: All tests passed (281 assertions in 19 test cases)
1/1 Test #3: chemdrawCatchTest ................   Passed    0.69 sec
"""

    assert parse_log_catch2(log, None) == {
        "chemdrawCatchTest": TestStatus.PASSED.value
    }


def test_parse_log_catch2_reads_ctest_failed_rows():
    log = """
Test project /testbed/build
1/1 Test #48: canonTestsCatch ..................***Failed    7.18 sec
"""

    assert parse_log_catch2(log, None) == {
        "canonTestsCatch": TestStatus.FAILED.value
    }


def test_parse_log_catch2_reads_python_unittest_summary():
    log = """
+ RDBASE=/testbed
+ PYTHONPATH=/testbed
+ LD_LIBRARY_PATH=/testbed/lib:
+ python Code/GraphMol/RascalMCES/Wrap/testRascalMCES.py
....
----------------------------------------------------------------------
Ran 4 tests in 0.010s

OK
"""

    assert parse_log_catch2(log, None) == {
        "Code/GraphMol/RascalMCES/Wrap/testRascalMCES.py": TestStatus.PASSED.value
    }


def test_parse_log_openmm_binary_done_reads_multiple_targets():
    log = """
+ LD_LIBRARY_PATH=/testbed/build:
+ ./build/TestReferenceAmoebaAngleForce
Done
+ OPENMM_PLUGIN_DIR=/testbed/build
+ ./build/TestReferenceEwald
Done
"""

    assert parse_log_openmm_binary_done(log, None) == {
        "TestReferenceAmoebaAngleForce": TestStatus.PASSED.value,
        "TestReferenceEwald": TestStatus.PASSED.value,
    }
