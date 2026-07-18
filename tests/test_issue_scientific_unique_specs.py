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


def test_qgis_specs_use_pinned_official_build_images():
    for pr in ("40837", "63639", "66353"):
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
