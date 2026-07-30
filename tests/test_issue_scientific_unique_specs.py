import openpyxl

from swebench.eval_pipeline.ingest import load_spreadsheet_issues
from swebench.eval_pipeline.instance_builder import _split_patches
from swebench.harness.constants.c import SPECS_OPENMM, SPECS_QGIS, SPECS_RDKIT
from swebench.harness.dockerfiles import get_dockerfile_base
from swebench.harness.log_parsers.c import parse_log_qgis
from swebench.harness.test_spec.test_spec import TestSpec as HarnessTestSpec


def _spec_text(spec):
    return "\n".join(
        spec.get("pre_install", [])
        + spec.get("build", [])
        + spec.get("build_after_test_patch", [])
        + spec.get("test_cmd", [])
    )


def test_remaining_scientific_issue_specs_are_concrete():
    expected = {
        "openmm/openmm": {
            "3260": "TestReferenceMonteCarloAnisotropicBarostat",
            "4536": "test_Vsite3Func4",
            "4832": "testFlexibleConstraints",
            "4989": "test_CharmmLoad",
        },
        "rdkit/rdkit": {
            "986": "moldraw2DTest1",
            "1473": "smaTest1",
            "1521": "testMMPA.py",
            "1654": "UnitTestSmiles.py",
            "2255": "testAvalonTools.py",
            "2646": "graphmolTestsCatch",
            "2651": "testSubgraphs2",
            "3170": "testSGroup",
            "3237": "testMolDraw2D.py",
            "3507": "UnitTestMol3D.py",
            "3900": "testFMCS",
            "5425": "moldraw2DTestCatch",
            "5735": "testRGroupDecomp",
            "5775": "moldraw2DTestCatch",
            "5776": "moldraw2DTestCatch",
            "6247": "testRGroupDecomp",
            "6646": "testFMCS.py",
            "6897": "rxnTestCatch",
            "6972": "rough_test.py",
            "7166": "cffi_test",
            "7419": "testInchi",
            "8173": "molHashCatchTest",
            "8266": "UnitTestInchi.py",
        },
        "qgis/QGIS": {
            "40837": "ProcessingGrass7AlgorithmsVectorTest",
            "63639": "test_analysis_processingcheckgeometry",
            "66353": "PyQgsPostgresRasterProvider",
        },
    }
    maps = {
        "openmm/openmm": SPECS_OPENMM,
        "rdkit/rdkit": SPECS_RDKIT,
        "qgis/QGIS": SPECS_QGIS,
    }
    assert sum(len(prs) for prs in expected.values()) == 30
    for repo, prs in expected.items():
        for pr, marker in prs.items():
            spec = maps[repo][pr]
            text = _spec_text(spec)
            assert spec.get("fail_to_pass"), (repo, pr)
            assert marker in text, (repo, pr, marker)
            assert "not evaluable" not in text
            assert "no curated" not in text
            assert "placeholder" not in text


def test_current_scientific_issues_sheet_specs_are_concrete():
    expected = {
        "openmm/openmm": {
            "4138": "langevin_documentation_variance",
            "4618": "TestOpenCLMonteCarloFlexibleBarostat",
            "2318": "TestOpenCLNonbondedForce",
            "5219": "cm_motion_remover_documentation",
            "2322": "TestOpenCLCustomCentroidBondForce",
            "2257": "TestOpenCLNonbondedForce",
            "4440": "TestReferenceLangevinIntegrator",
            "1100": "TestReferenceSettle",
            "3151": "test_addSolventPeriodicBox",
            "5302": "GPU runtime",
            "4760": "absinth_force_field_removed",
            "4161": "test_IgnoreExternalBonds",
            "3851": "test_CharmmPolar",
            "3311": "test_Amoeba18BPTI",
            "3210": "test_NBFIX",
            "2897": "benchmark_hydrogen_mass",
            "3872": "TestOpenCLAmoebaVdwForce",
            "3659": "testChemCompBonds",
        },
        "rdkit/rdkit": {
            "9141": "fileParsersCatchTest",
            "7183": "molfileStereoCatchTest",
            "8904": "graphmolTestsCatch",
            "8957": "chiralityTestsCatch",
            "8736": "chiralityTestsCatch",
            "8247": "testRascalMCES",
            "8301": "molopsTestsCatch",
            "8257": "graphmolAdjustQueryCatch",
            "3018": "graphmolTestsCatch",
            "7990": "deprotectTest",
            "7347": "chiralityTestsCatch",
            "5560": "chiralityTestsCatch",
            "6240": "chiralityTestsCatch",
            "6892": "cdxmlParserCatchTest",
            "4806": "fileParsersCatchTest",
            "5407": "chiralityTestsCatch",
        },
        "qgis/QGIS": {
            "60631": "test_analysis_processingalgspt1",
            "35852": "PyQgsRasterColorRampShader",
        },
    }
    maps = {
        "openmm/openmm": SPECS_OPENMM,
        "rdkit/rdkit": SPECS_RDKIT,
        "qgis/QGIS": SPECS_QGIS,
    }

    assert sum(len(prs) for prs in expected.values()) == 36
    for repo, prs in expected.items():
        for pr, marker in prs.items():
            spec = maps[repo][pr]
            text = _spec_text(spec)
            assert spec.get("fail_to_pass"), (repo, pr)
            assert marker in text, (repo, pr, marker)
            if repo == "openmm/openmm" and pr == "5302":
                assert "not evaluable:" in text
            else:
                assert "not evaluable" not in text
            assert "no curated" not in text


def test_scientific_opencl_specs_use_a_cpu_opencl_runtime():
    for pr in ("4618", "2318", "2322", "2257", "3872"):
        text = _spec_text(SPECS_OPENMM[pr])
        assert "pocl-opencl-icd" in text
        assert "-DOPENMM_BUILD_OPENCL_LIB=ON" in text
        assert SPECS_OPENMM[pr]["test_generation_use_spec_cmd"] is True


def test_qgis_specs_use_pinned_official_build_images():
    for pr in ("35852", "40837", "60631", "63639", "66353"):
        image = SPECS_QGIS[pr]["docker_specs"]["c_base_image"]
        assert image.startswith("qgis/")
        assert "@sha256:" in image
        dockerfile = get_dockerfile_base(
            "linux/x86_64", "x86_64", "c", c_base_image=image
        )
        assert f"FROM --platform=linux/x86_64 {image}" in dockerfile


def test_qgis_parser_reads_ctest_wrapped_python_and_cpp_results():
    spec = HarnessTestSpec(
        instance_id="qgis__QGIS-1",
        repo="qgis/QGIS",
        version="1",
        env_script_list=[],
        repo_script_list=[],
        eval_script_list=[],
        arch="x86_64",
        FAIL_TO_PASS=[],
        PASS_TO_PASS=[],
        language="c",
        docker_specs={},
        namespace=None,
        base_image_tag="latest",
        env_image_tag="latest",
        instance_image_tag="latest",
    )
    log = """
1/2 Test #10: PyQgsPostgresRasterProvider ....***Failed  1.2 sec
2/2 Test #11: test_analysis_processingcheckgeometry ....   Passed  0.2 sec
"""
    assert parse_log_qgis(log, spec) == {
        "PyQgsPostgresRasterProvider": "FAILED",
        "test_analysis_processingcheckgeometry": "PASSED",
    }


def test_issue_sheet_groups_multiple_issues_for_one_pr(tmp_path):
    path = tmp_path / "issues.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Repo", "Issue Number", "Closing PR #", "Title", "Type"])
    ws.append(["rdkit/rdkit", 5411, 6646, "one", "1"])
    ws.append(["rdkit/rdkit", 5440, 6646, "two", "1"])
    ws.append(["openmm/openmm", 4827, 4832, "three", "1"])
    wb.save(path)

    rows = load_spreadsheet_issues(str(path))

    assert len(rows) == 2
    rdkit = next(row for row in rows if row["Repo"] == "rdkit/rdkit")
    assert rdkit["Issue Number"] == [5411, 5440]
    assert rdkit["Title"] == "one | two"


def test_split_patches_handles_unittest_without_stereo_false_positive():
    diff = """diff --git a/rdkit/Chem/EnumerateStereoisomers.py b/rdkit/Chem/EnumerateStereoisomers.py
--- a/rdkit/Chem/EnumerateStereoisomers.py
+++ b/rdkit/Chem/EnumerateStereoisomers.py
@@ -1 +1 @@
-old
+new
diff --git a/rdkit/Chem/UnitTestMol3D.py b/rdkit/Chem/UnitTestMol3D.py
--- a/rdkit/Chem/UnitTestMol3D.py
+++ b/rdkit/Chem/UnitTestMol3D.py
@@ -1 +1 @@
-old test
+new test
"""
    patch, test_patch = _split_patches(diff)
    assert "EnumerateStereoisomers.py" in patch
    assert "UnitTestMol3D.py" not in patch
    assert "UnitTestMol3D.py" in test_patch


def test_split_patches_recognizes_rdkit_catch_sources_as_tests():
    diff = """diff --git a/Code/GraphMol/MolOps.cpp b/Code/GraphMol/MolOps.cpp
--- a/Code/GraphMol/MolOps.cpp
+++ b/Code/GraphMol/MolOps.cpp
@@ -1 +1 @@
-old
+fixed
diff --git a/Code/GraphMol/catch_graphmol.cpp b/Code/GraphMol/catch_graphmol.cpp
--- a/Code/GraphMol/catch_graphmol.cpp
+++ b/Code/GraphMol/catch_graphmol.cpp
@@ -1 +1,2 @@
 old test
+new test
"""

    patch, test_patch = _split_patches(diff)

    assert "MolOps.cpp" in patch
    assert "catch_graphmol.cpp" not in patch
    assert "catch_graphmol.cpp" in test_patch
