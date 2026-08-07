from collections import Counter
from pathlib import Path

import openpyxl

from swebench.eval_pipeline.test_generation_eval import (
    _special_repo_execution_plan,
)
from swebench.harness.constants import (
    MAP_REPO_TO_TEST_GENERATION_CAPABILITIES,
    MAP_REPO_VERSION_TO_SPECS,
)
from swebench.harness.log_parsers import MAP_REPO_TO_PARSER


ROOT = Path(__file__).parents[1]


def _workbook_pairs(filename):
    workbook = openpyxl.load_workbook(ROOT / filename, read_only=True, data_only=True)
    pairs = []
    for sheet in workbook:
        rows = sheet.iter_rows(values_only=True)
        header = next(rows)
        columns = {name: index for index, name in enumerate(header)}
        if "Repo" not in columns:
            continue
        for row in rows:
            repo = row[columns["Repo"]]
            pr = row[columns["Closing PR #"]]
            if repo and pr is not None:
                pairs.append((repo, str(pr)))
    return pairs


def test_no_tests_workbook_contract_is_fully_registered():
    split = _workbook_pairs("Issues_No_Tests_split.xlsx")
    v1 = _workbook_pairs("Issues_No_Tests_v1.xlsx")
    all_pairs = split + v1

    assert len(all_pairs) == 120
    assert len(set(all_pairs)) == 118
    assert Counter(repo for repo, _pr in all_pairs) == {
        "openmm/openmm": 76,
        "rdkit/rdkit": 7,
        "lammps/lammps": 33,
        "biopython/biopython": 4,
    }
    assert {pair for pair, count in Counter(all_pairs).items() if count == 2} == {
        ("lammps/lammps", "4339"),
        ("lammps/lammps", "4195"),
    }

    for repo, pr in set(all_pairs):
        spec = MAP_REPO_VERSION_TO_SPECS[repo][pr]
        assert spec["test_generation_capabilities"] == tuple(
            sorted(MAP_REPO_TO_TEST_GENERATION_CAPABILITIES[repo])
        )
        assert repo in MAP_REPO_TO_PARSER


def _plan(repo, patch, commands=()):
    return _special_repo_execution_plan(
        {"repo": repo, "version": "synthetic"}, patch, list(commands)
    )


def test_rdkit_patch_dispatches_python_cpp_and_mixed_independent_of_spec():
    python_patch = """diff --git a/rdkit/Chem/UnitTestGenerated.py b/rdkit/Chem/UnitTestGenerated.py
--- a/rdkit/Chem/UnitTestGenerated.py
+++ b/rdkit/Chem/UnitTestGenerated.py
@@ -0,0 +1,2 @@
+def test_generated():
+    assert True
"""
    cpp_patch = """diff --git a/Code/GraphMol/catch_generated.cpp b/Code/GraphMol/catch_generated.cpp
--- a/Code/GraphMol/catch_generated.cpp
+++ b/Code/GraphMol/catch_generated.cpp
@@ -0,0 +1 @@
+TEST_CASE("generated") {}
diff --git a/Code/GraphMol/CMakeLists.txt b/Code/GraphMol/CMakeLists.txt
--- a/Code/GraphMol/CMakeLists.txt
+++ b/Code/GraphMol/CMakeLists.txt
@@ -1 +1,2 @@
 old
+rdkit_catch_test(generatedCatch catch_generated.cpp LINK_LIBRARIES GraphMol)
"""
    python_plan = _plan("rdkit/rdkit", python_patch, ["ctest -R '^oldCpp$'"])
    cpp_plan = _plan("rdkit/rdkit", cpp_patch, ["python3 old_test.py"])
    mixed_plan = _plan(
        "rdkit/rdkit", python_patch + cpp_patch, ["python3 old_test.py"]
    )

    assert python_plan.languages == ("python",)
    assert cpp_plan.languages == ("cpp",)
    assert cpp_plan.build_targets == ("generatedCatch",)
    assert mixed_plan.languages == ("cpp", "python")
    assert len(mixed_plan.commands) == 2


def test_openmm_lammps_and_biopython_dispatch_supported_languages():
    openmm_python = """diff --git a/wrappers/python/tests/TestGenerated.py b/wrappers/python/tests/TestGenerated.py
--- a/wrappers/python/tests/TestGenerated.py
+++ b/wrappers/python/tests/TestGenerated.py
@@ -0,0 +1 @@
+def test_generated(): pass
"""
    openmm_cpp = """diff --git a/platforms/reference/tests/TestGenerated.cpp b/platforms/reference/tests/TestGenerated.cpp
--- a/platforms/reference/tests/TestGenerated.cpp
+++ b/platforms/reference/tests/TestGenerated.cpp
@@ -0,0 +1 @@
+int main() {}
"""
    lammps_cpp = """diff --git a/unittest/commands/test_generated.cpp b/unittest/commands/test_generated.cpp
--- a/unittest/commands/test_generated.cpp
+++ b/unittest/commands/test_generated.cpp
@@ -0,0 +1 @@
+TEST(Generated, Regression) {}
"""
    lammps_python = """diff --git a/python/tests/test_generated.py b/python/tests/test_generated.py
--- a/python/tests/test_generated.py
+++ b/python/tests/test_generated.py
@@ -0,0 +1 @@
+def test_generated(): pass
"""
    biopython = """diff --git a/Tests/test_generated.py b/Tests/test_generated.py
--- a/Tests/test_generated.py
+++ b/Tests/test_generated.py
@@ -0,0 +1 @@
+def test_generated(): pass
"""

    assert _plan("openmm/openmm", openmm_python).languages == ("python",)
    assert _plan("openmm/openmm", openmm_cpp).languages == ("cpp",)
    assert _plan("openmm/openmm", openmm_python + openmm_cpp).languages == (
        "cpp", "python"
    )
    assert _plan("lammps/lammps", lammps_cpp + lammps_python).languages == (
        "cpp", "python"
    )
    assert _plan("biopython/biopython", biopython).languages == ("python",)


def test_unrelated_scratch_script_does_not_veto_a_valid_accepted_test():
    # Agents sometimes leave a throwaway debug script (e.g. hello.py used to
    # sanity-check the environment) in the final diff alongside a real,
    # correctly-wired test. That noise file must not veto the valid test:
    # only files that themselves look like a (broken/misplaced) test should
    # trigger unsupported_generated_test.
    patch = """diff --git a/hello.py b/hello.py
--- /dev/null
+++ b/hello.py
@@ -0,0 +1 @@
+print("hello from python")
diff --git a/unittest/commands/test_generated.cpp b/unittest/commands/test_generated.cpp
--- /dev/null
+++ b/unittest/commands/test_generated.cpp
@@ -0,0 +1 @@
+TEST(Generated, Regression) {}
"""
    plan = _plan("lammps/lammps", patch)

    assert plan.failure_reason is None
    assert plan.languages == ("cpp",)
    assert plan.paths == ("unittest/commands/test_generated.cpp",)


def test_lammps_force_style_yaml_fixtures_are_canonical():
    # LAMMPS's force-styles suite is data-driven: unittest/force-styles/
    # CMakeLists.txt file(GLOB CONFIGURE_DEPENDS ...) auto-registers each
    # tests/<prefix>-<name>.yaml fixture as a ctest against a pre-built
    # shared driver binary, with no accompanying .cpp file required. A
    # patch that only adds such YAML fixtures must be accepted, not
    # rejected as unsupported_generated_test.
    yaml_patch = """diff --git a/unittest/force-styles/tests/mol-pair-hbond_dreiding_lj.yaml b/unittest/force-styles/tests/mol-pair-hbond_dreiding_lj.yaml
--- /dev/null
+++ b/unittest/force-styles/tests/mol-pair-hbond_dreiding_lj.yaml
@@ -0,0 +1 @@
+pair_style: hbond/dreiding/lj 4 1.0 1.5 90.0
diff --git a/unittest/force-styles/tests/mol-pair-hbond_dreiding_morse.yaml b/unittest/force-styles/tests/mol-pair-hbond_dreiding_morse.yaml
--- /dev/null
+++ b/unittest/force-styles/tests/mol-pair-hbond_dreiding_morse.yaml
@@ -0,0 +1 @@
+pair_style: hbond/dreiding/morse 2 1.0 1.5 90.0
"""
    plan = _plan("lammps/lammps", yaml_patch)

    assert plan.failure_reason is None
    assert plan.languages == ("cpp",)
    assert plan.build_targets == ("test_pair_style",)
    assert plan.commands == (
        "ctest --test-dir build --output-on-failure "
        "-R '^(MolPairStyle:hbond_dreiding_lj|MolPairStyle:hbond_dreiding_morse)$'",
    )

    bond_patch = """diff --git a/unittest/force-styles/tests/bond-harmonic_generated.yaml b/unittest/force-styles/tests/bond-harmonic_generated.yaml
--- /dev/null
+++ b/unittest/force-styles/tests/bond-harmonic_generated.yaml
@@ -0,0 +1 @@
+bond_style: harmonic
"""
    bond_plan = _plan("lammps/lammps", bond_patch)
    assert bond_plan.failure_reason is None
    assert bond_plan.build_targets == ("test_bond_style",)
    assert bond_plan.commands == (
        "ctest --test-dir build --output-on-failure -R '^(BondStyle:harmonic_generated)$'",
    )

    # An unrecognized YAML prefix (no known force-styles driver) is still
    # rejected, since the harness would have no way to run it.
    unknown_prefix_patch = """diff --git a/unittest/force-styles/tests/mystery-thing.yaml b/unittest/force-styles/tests/mystery-thing.yaml
--- /dev/null
+++ b/unittest/force-styles/tests/mystery-thing.yaml
@@ -0,0 +1 @@
+pair_style: mystery
"""
    assert _plan("lammps/lammps", unknown_prefix_patch).failure_reason == (
        "unsupported_generated_test"
    )


def test_noncanonical_unknown_and_unresolved_targets_fail_explicitly():
    root_script = """diff --git a/repro.py b/repro.py
--- a/repro.py
+++ b/repro.py
@@ -0,0 +1 @@
+def test_bug(): pass
"""
    unknown = """diff --git a/Tests/test_generated.js b/Tests/test_generated.js
--- a/Tests/test_generated.js
+++ b/Tests/test_generated.js
@@ -0,0 +1 @@
+test('bug', () => {})
"""
    unresolved_cpp = """diff --git a/Code/GraphMol/catch_unmapped.cpp b/Code/GraphMol/catch_unmapped.cpp
--- a/Code/GraphMol/catch_unmapped.cpp
+++ b/Code/GraphMol/catch_unmapped.cpp
@@ -0,0 +1 @@
+TEST_CASE("bug") {}
"""

    # A root-level, non-test-named script (no accompanying real test in the
    # patch) is debug noise, not an attempted-but-broken test: it produces
    # no_tests_selected (nothing runnable was found), not
    # unsupported_generated_test (which is reserved for files that look like
    # tests but land in the wrong place/format and would veto real tests
    # elsewhere in the same patch).
    assert _plan("biopython/biopython", root_script).failure_reason == (
        "no_tests_selected"
    )
    assert _plan("biopython/biopython", unknown).failure_reason == (
        "unsupported_generated_test"
    )
    assert _plan("rdkit/rdkit", unresolved_cpp).failure_reason == (
        "unsupported_generated_test"
    )


def test_mixed_scientific_parsers_keep_python_and_cpp_results():
    rdkit_log = """
1/1 Test #1: generatedCatch .... Passed 0.1 sec
rdkit/Chem/UnitTestGenerated.py::test_generated FAILED [100%]
"""
    lammps_log = """
[       OK ] Generated.Native (1 ms)
python/tests/test_generated.py::test_generated PASSED [100%]
"""
    openmm_log = """
+ ./build/TestGenerated
Done
TestGenerated.py::test_generated PASSED [100%]
"""

    assert MAP_REPO_TO_PARSER["rdkit/rdkit"](rdkit_log, None) == {
        "generatedCatch": "PASSED",
        "rdkit/Chem/UnitTestGenerated.py::test_generated": "FAILED",
    }
    assert MAP_REPO_TO_PARSER["lammps/lammps"](lammps_log, None) == {
        "Generated.Native": "PASSED",
        "python/tests/test_generated.py::test_generated": "PASSED",
    }
    assert MAP_REPO_TO_PARSER["openmm/openmm"](openmm_log, None) == {
        "TestGenerated": "PASSED",
        "TestGenerated.py::test_generated": "PASSED",
    }


def test_gold_patch_gpu_veto_yields_to_a_real_curated_spec():
    # PR 2318 has a real curated _openmm_opencl_targets_spec (gpu=True after
    # Task 4) whose gold patch touches only platforms/opencl/. The veto must
    # not fire just because the gold patch is GPU-only -- a real spec exists.
    instance = {
        "repo": "openmm/openmm",
        "version": "2318",
        "patch": (
            "diff --git a/platforms/opencl/src/kernels/nonbonded.cl "
            "b/platforms/opencl/src/kernels/nonbonded.cl\n"
            "--- a/platforms/opencl/src/kernels/nonbonded.cl\n"
            "+++ b/platforms/opencl/src/kernels/nonbonded.cl\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        ),
    }
    generated_patch = (
        "diff --git a/wrappers/python/tests/TestNonbondedForce.py "
        "b/wrappers/python/tests/TestNonbondedForce.py\n"
        "--- a/wrappers/python/tests/TestNonbondedForce.py\n"
        "+++ b/wrappers/python/tests/TestNonbondedForce.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def test_generated():\n"
        "+    assert True\n"
    )
    commands = [
        "LD_LIBRARY_PATH=$PWD/build:${LD_LIBRARY_PATH:-} "
        "OPENMM_PLUGIN_DIR=$PWD/build ./build/TestOpenCLNonbondedForce"
    ]
    plan = _special_repo_execution_plan(instance, generated_patch, commands)

    assert plan is None or plan.failure_reason != "non_evaluable_spec"


def test_gold_patch_gpu_veto_still_fires_with_no_curated_spec():
    # "999999" is a numeric PR-shaped version string (as every real OpenMM
    # instance's version is) that is guaranteed absent from SPECS_OPENMM's
    # curated entries. Using a numeric key here (rather than a non-numeric
    # placeholder like the previous "synthetic-no-spec") is required: only a
    # numeric key exercises the real production code path, where
    # _OpenMMSpecs.__missing__ fabricates a placeholder spec instead of
    # raising KeyError. A non-numeric version can never occur for a real
    # OpenMM instance and previously let this test pass for the wrong reason.
    instance = {
        "repo": "openmm/openmm",
        "version": "999999",
        "patch": (
            "diff --git a/platforms/opencl/src/kernels/nonbonded.cl "
            "b/platforms/opencl/src/kernels/nonbonded.cl\n"
            "--- a/platforms/opencl/src/kernels/nonbonded.cl\n"
            "+++ b/platforms/opencl/src/kernels/nonbonded.cl\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        ),
    }
    generated_patch = (
        "diff --git a/wrappers/python/tests/TestNonbondedForce.py "
        "b/wrappers/python/tests/TestNonbondedForce.py\n"
        "--- a/wrappers/python/tests/TestNonbondedForce.py\n"
        "+++ b/wrappers/python/tests/TestNonbondedForce.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def test_generated():\n"
        "+    assert True\n"
    )
    plan = _special_repo_execution_plan(instance, generated_patch, [])

    assert plan is not None
    assert plan.failure_reason == "non_evaluable_spec"


def test_gold_patch_gpu_veto_still_fires_after_build_script_caches_placeholder():
    # Regression test for the exact bug the final review flagged: SPECS_OPENMM
    # is an _OpenMMSpecs(dict) subclass whose __missing__ fabricates AND
    # CACHES ("self[pr] = spec") a non-evaluable placeholder the first time a
    # numeric, uncurated PR key is looked up via __getitem__. In production,
    # _build_script performs exactly that lookup
    # (MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]])
    # before calling _special_repo_execution_plan for the same instance. A
    # has_curated_spec check based on mere presence (dict.get(...) truthiness)
    # would see the now-cached placeholder and incorrectly treat it as a real
    # curated spec, permanently defeating this veto. Simulate that exact
    # call order here -- trigger the cache first, then assert the veto still
    # fires -- to prove the fix is immune to caching/call order.
    version = "999998"
    # Force _OpenMMSpecs.__missing__ to fabricate and cache a placeholder for
    # this key, exactly as _build_script's `[...][...]` lookup does.
    MAP_REPO_VERSION_TO_SPECS["openmm/openmm"][version]

    instance = {
        "repo": "openmm/openmm",
        "version": version,
        "patch": (
            "diff --git a/platforms/opencl/src/kernels/nonbonded.cl "
            "b/platforms/opencl/src/kernels/nonbonded.cl\n"
            "--- a/platforms/opencl/src/kernels/nonbonded.cl\n"
            "+++ b/platforms/opencl/src/kernels/nonbonded.cl\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        ),
    }
    generated_patch = (
        "diff --git a/wrappers/python/tests/TestNonbondedForce.py "
        "b/wrappers/python/tests/TestNonbondedForce.py\n"
        "--- a/wrappers/python/tests/TestNonbondedForce.py\n"
        "+++ b/wrappers/python/tests/TestNonbondedForce.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def test_generated():\n"
        "+    assert True\n"
    )
    plan = _special_repo_execution_plan(instance, generated_patch, [])

    assert plan is not None
    assert plan.failure_reason == "non_evaluable_spec"
