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


def test_parse_log_catch2_reads_python_unittest_ok_with_skips():
    log = """
+ python3 Code/GraphMol/Wrap/rough_test.py
....
----------------------------------------------------------------------
Ran 248 tests in 7.006s

OK (skipped=10)
"""

    assert parse_log_catch2(log, None) == {
        "Code/GraphMol/Wrap/rough_test.py": TestStatus.PASSED.value
    }


def test_parse_log_catch2_reads_python_unittest_failed_summary():
    log = """
+ python3 Code/GraphMol/Wrap/rough_test.py
....
======================================================================
FAIL: testFindMolChiralCentersHonorsLegacyFlag (__main__.TestCase)
----------------------------------------------------------------------
AssertionError: 0 != 1

FAILED (failures=1, skipped=10)
"""

    assert parse_log_catch2(log, None) == {
        "Code/GraphMol/Wrap/rough_test.py": TestStatus.FAILED.value
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


def test_parse_log_openmm_binary_done_reads_assertion_failure():
    log = """
+ ./build/TestReferenceNonbondedForce
 ./build/TestReferenceNonbondedForce
 exception: Assertion failure at TestNonbondedForce.h:856.  Expected 1, found 2
 : '>>>>> End Test Output'
"""

    assert parse_log_openmm_binary_done(log, None) == {
        "TestReferenceNonbondedForce": TestStatus.FAILED.value,
    }


def test_parse_log_openmm_binary_done_reads_runtime_exception():
    log = """
+ LD_LIBRARY_PATH=/testbed/build:
+ ./build/TestReferenceCustomExternalForce
exception: Parse error in expression "atan2(x, y)": unknown function: atan2
"""

    assert parse_log_openmm_binary_done(log, None) == {
        "TestReferenceCustomExternalForce": TestStatus.FAILED.value,
    }


def test_parse_log_openmm_binary_done_reads_missing_binary():
    log = """
+ ./build/platforms/opencl/tests/TestOpenCLFFT
/base_generated_tests.sh: line 13: ./build/platforms/opencl/tests/TestOpenCLFFT: No such file or directory
"""

    assert parse_log_openmm_binary_done(log, None) == {
        "TestOpenCLFFT": TestStatus.FAILED.value,
    }
