from swebench.eval_pipeline.test_generation_eval import _special_repo_execution_plan
from swebench.harness.constants.c import SPECS_OPENMM, SPECS_QGIS, SPECS_RDKIT


def test_openmm_python_specs_install_with_test_interpreter():
    for pr in ("3303", "4188", "5155"):
        spec = SPECS_OPENMM[pr]
        pre_install = "\n".join(spec["pre_install"])

        assert "python -m pip install" in pre_install
        assert "openmm numpy scipy pytest" in pre_install
        assert "mkdir -p \"$SIMTK_SITE\"" in spec["build"][0]
        assert "rm -rf \"$SIMTK_SITE/app\"" in spec["build"][0]
        assert "compiled*" in spec["build"][0]
        assert "from openmm.vec3 import *" in spec["build"][0]
        assert "python -m lib2to3 -w -n \"$SIMTK_SITE/app\"" in spec["build"][0]
        assert spec["build"][0].index("/testbed/wrappers/python/openmm/app") < spec[
            "build"
        ][0].index("/testbed/wrappers/python/simtk/openmm/app")
        assert "python -m pytest" in spec["test_cmd"][0]


def test_openmm_gromacs_topfile_specs_install_gromacs_data():
    for pr in ("4188", "5155"):
        pre_install = "\n".join(SPECS_OPENMM[pr]["pre_install"])

        assert "apt-get install -y --no-install-recommends gromacs" in pre_install


def test_openmm_legacy_specs_use_targets_available_at_base_commit():
    assert "TestReferenceCustomIntegrator" in SPECS_OPENMM["1837"]["build_after_test_patch"][-1]
    assert "TestReferenceBAOABLangevinIntegrator" in SPECS_OPENMM["2561"]["build_after_test_patch"][-1]


def test_openmm_2802_uses_touched_api_unit_tests():
    spec = SPECS_OPENMM["2802"]
    test_cmd = SPECS_OPENMM["2802"]["test_cmd"][0]

    assert "-k 'PhysicalConstants'" not in test_cmd
    assert "testPhysicalConstants" not in test_cmd
    assert "TestAPIUnits.py::TestAPIUnits::testCustomGBForce" in test_cmd
    assert "TestAPIUnits.py::TestAPIUnits::testCustomNonbondedForce" in test_cmd
    assert spec["fail_to_pass"] == [
        "wrappers/python/tests/TestAPIUnits.py::TestAPIUnits::testCustomGBForce",
        "wrappers/python/tests/TestAPIUnits.py::TestAPIUnits::testCustomNonbondedForce",
    ]


def test_openmm_4188_selects_touched_vsite3_test():
    spec = SPECS_OPENMM["4188"]

    assert "-k 'test_Vsite3'" in spec["test_cmd"][0]
    assert spec["fail_to_pass"] == [
        "wrappers/python/tests/TestGromacsTopFile.py::TestGromacsTopFile::test_Vsite3"
    ]


def test_openmm_specs_execute_the_touched_regression_family():
    expected = {
        "1487": "TestReferenceAndersenThermostat",
        "2057": "TestReferenceCustomIntegrator",
        "2187": "TestReferenceCustomNonbondedForce",
        "4740": "TestReferenceLangevinMiddleIntegrator",
        "5278": "TestReferenceMonteCarloAnisotropicBarostat",
    }
    for pr, target in expected.items():
        assert SPECS_OPENMM[pr]["build_after_test_patch"][-1].endswith(target)
        assert target in SPECS_OPENMM[pr]["test_cmd"][0]

    assert "python -m pytest" in SPECS_OPENMM["2802"]["test_cmd"][0]


def test_rdkit_specs_use_apt_boost_and_disable_fragile_downloads():
    for pr in ("2059", "6646", "8376"):
        spec = SPECS_RDKIT[pr]
        pre_install = "\n".join(spec["pre_install"])
        cmake = spec["build"][1]

        assert "libboost-all-dev" in pre_install
        assert "launchpadcontent" not in pre_install
        assert "apt-key" not in pre_install
        assert "-DBoost_NO_BOOST_CMAKE=ON" in cmake
        assert "-DRDK_BUILD_COORDGEN_SUPPORT=OFF" in cmake
        assert "-DRDK_BUILD_MAEPARSER_SUPPORT=OFF" in cmake
        assert "-DRDK_BUILD_CHEMDRAW_SUPPORT=OFF" in cmake


def test_newer_rdkit_specs_install_required_new_boost():
    for pr in ("8515", "8668", "8968", "9331"):
        spec = SPECS_RDKIT[pr]
        pre_install = "\n".join(spec["pre_install"])
        cmake = spec["build"][1]

        assert "libboost1.83-all-dev" in pre_install
        assert "launchpadcontent.net/mhier/libboost-latest" in pre_install
        assert "Acquire::Retries=5" in pre_install
        assert "signed-by=/usr/share/keyrings/mhier-libboost-latest.gpg" in pre_install
        assert "77520E7EB41800A93E3E0D9431F54F3E108EAD31" in pre_install
        assert "apt-key" not in pre_install
        assert "-DBoost_NO_BOOST_CMAKE=ON" in cmake
        assert "-DRDK_BUILD_COORDGEN_SUPPORT=OFF" in cmake
        assert "-DRDK_BUILD_MAEPARSER_SUPPORT=OFF" in cmake


def test_legacy_rdkit_catch_specs_disable_posix_signals():
    for pr in ("3018", "3412", "3615", "3930", "4414", "4806", "5063"):
        cmake = SPECS_RDKIT[pr]["build"][1]

        assert "-DCMAKE_CXX_FLAGS=-DCATCH_CONFIG_NO_POSIX_SIGNALS" in cmake


def test_rdkit_8968_disables_unneeded_chemdraw_support():
    spec = SPECS_RDKIT["8968"]

    assert "-DRDK_BUILD_CHEMDRAW_SUPPORT=OFF" in spec["build"][1]
    assert "ChemDraw" not in "\n".join(spec["build"][2:])


def test_rdkit_2059_uses_existing_smilesparse_target():
    spec = SPECS_RDKIT["2059"]
    pre_install = "\n".join(spec["pre_install"])

    assert "boost/detail/endian.hpp" in pre_install
    assert spec["build"][-1].endswith("--target smiTest1")
    assert spec["test_cmd"] == [
        "RDBASE=$PWD LD_LIBRARY_PATH=$PWD/lib:${LD_LIBRARY_PATH:-} "
        "ctest --test-dir build -V -R '^smiTest1$'"
    ]


def test_rdkit_ctest_selectors_do_not_match_prefixed_targets():
    assert SPECS_RDKIT["6247"]["test_cmd"] == [
        "RDBASE=$PWD LD_LIBRARY_PATH=$PWD/lib:${LD_LIBRARY_PATH:-} "
        "ctest --test-dir build -V -R '^testRGroupDecomp$'"
    ]


def test_qgis_ctest_runs_from_build_directory_for_legacy_cmake():
    spec = SPECS_QGIS["40837"]
    command = spec["test_cmd"][0]

    assert command.startswith("cd build && ")
    assert "ctest --test-dir" not in command
    assert spec["build"][-1] == "cmake --build build --parallel 8"


def test_qgis_60631_uses_modern_cmake_build_image():
    assert (
        SPECS_QGIS["60631"]["docker_specs"]["c_base_image"]
        == SPECS_QGIS["63639"]["docker_specs"]["c_base_image"]
    )


def test_openmm_opencl_specs_install_gl_headers():
    for pr in ("2257", "2318", "2322", "3872", "4618"):
        assert "libgl1-mesa-dev" in "\n".join(SPECS_OPENMM[pr]["pre_install"])


def test_rdkit_9331_enables_chemdraw_with_include_compatibility():
    spec = SPECS_RDKIT["9331"]

    assert (
        "-DRDK_BUILD_CHEMDRAW_SUPPORT=OFF -DRDK_BUILD_COORDGEN_SUPPORT=OFF "
        "-DRDK_BUILD_MAEPARSER_SUPPORT=OFF -DRDK_BUILD_AVALON_SUPPORT=OFF "
        "-DRDK_BUILD_YAEHMOP_SUPPORT=OFF -DRDK_BUILD_THREADSAFE_SSS=ON "
        "-DRDK_BUILD_CHEMDRAW_SUPPORT=ON "
        in spec["build"][1]
    )
    assert "find External/ChemDraw -name chemdraw.h" in spec["build"][2]
    assert "External/ChemDraw/ChemDraw" in spec["build"][2]
    assert "-DCMAKE_CXX_FLAGS=-I/testbed/External/ChemDraw" in spec["build"][1]
    assert 'if [ "$REL" = "$HEADER_DIR" ]; then REL=.; fi' in spec["build"][2]
    assert "ln -s \"$REL\" External/ChemDraw/ChemDraw" in spec["build"][2]
    assert spec["build_after_test_patch"] == [
        "cmake --build build --parallel $(nproc) --target chemdrawCatchTest"
    ]


def test_rdkit_python_wrapper_specs_build_wrappers_once():
    for pr, test_path in {
        "6646": "Code/GraphMol/FMCS/Wrap/testFMCS.py",
        "8376": "Code/GraphMol/RascalMCES/Wrap/testRascalMCES.py",
    }.items():
        spec = SPECS_RDKIT[pr]
        cmake = spec["build"][1]

        assert "-DRDK_BUILD_PYTHON_WRAPPERS=ON" in cmake
        assert "-DRDK_BUILD_PYTHON_WRAPPERS=OFF" not in cmake
        assert spec["test_cmd"] == [
            "cp -a build/rdkit/. rdkit/ && "
            "RDBASE=$PWD PYTHONPATH=$PWD LD_LIBRARY_PATH=$PWD/lib:${LD_LIBRARY_PATH:-} "
            f"python3 {test_path}"
        ]


def test_rdkit_generated_python_test_plan_copies_built_extension():
    # Regression test for the batch2 run (2026-08-04 15:24-16:38): generated
    # Python tests for rdkit/rdkit were executed with PYTHONPATH=$PWD but no
    # prior copy of the CMake-built extension (rdBase, etc.) from build/rdkit/
    # into the in-tree rdkit/ package, so `import rdkit` hit a circular-import
    # ImportError for rdBase on every affected instance (rdkit-5103, -5261,
    # -7814, -8166, -8796). Fixed in 84c826f; this pins the fix in place.
    instance = {"repo": "rdkit/rdkit", "version": ""}
    generated_patch = (
        "diff --git a/rdkit/Chem/UnitTestPandasTools.py "
        "b/rdkit/Chem/UnitTestPandasTools.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/rdkit/Chem/UnitTestPandasTools.py\n"
        "+++ b/rdkit/Chem/UnitTestPandasTools.py\n"
        "@@ -1,3 +1,10 @@\n"
        " import unittest\n"
        "+class TestPandasTools(unittest.TestCase):\n"
        "+    def test_moleculeImagesInReprHtml(self):\n"
        "+        pass\n"
    )
    commands = [
        "RDBASE=$PWD PYTHONPATH=$PWD LD_LIBRARY_PATH=$PWD/lib:${LD_LIBRARY_PATH:-} "
        "python3 rdkit/Chem/UnitTestPandasTools.py"
    ]
    plan = _special_repo_execution_plan(instance, generated_patch, commands)

    assert plan is not None
    assert plan.failure_reason is None
    assert len(plan.commands) == 1
    assert plan.commands[0].startswith("cp -a build/rdkit/. rdkit/ && ")


def test_current_testgen_openmm_placeholders_have_concrete_specs():
    expected_targets = {
        "1495": "TestReferenceCustomExternalForce",
        "1802": "TestReferenceEwald",
        "2241": "TestReferenceCustomIntegrator",
        "3286": "TestReferenceGBSAOBCForce",
        "4732": "TestReferenceNonbondedForce",
        "4881": "TestReferenceMonteCarloBarostat",
        "5031": "TestReferenceCustomCentroidBondForce",
        "5137": "TestOpenCLFFT",
        "5198": "TestCpuLocalEnergyMinimizer",
        "5322": "TestReferenceMonteCarloFlexibleBarostat",
    }
    for pr, target in expected_targets.items():
        spec_text = "\n".join(
            SPECS_OPENMM[pr].get("build", [])
            + SPECS_OPENMM[pr].get("build_after_test_patch", [])
            + SPECS_OPENMM[pr].get("test_cmd", [])
        )
        assert "not evaluable" not in spec_text
        assert target in spec_text


def test_current_testgen_rdkit_placeholders_have_concrete_specs():
    expected = {
        "6506": "rdkit/Chem/UnitTestRegistrationHash.py",
        "6948": "Code/GraphMol/Wrap/rough_test.py",
        "7426": "rdkit/Chem/UnitTestRegistrationHash.py",
        "8791": "ForceField|forceField",
        "8795": "graphmolTestsCatch",
        "8999": "External/pubchem_shape/Wrap/test_rdshapealign.py",
    }
    for pr, marker in expected.items():
        spec_text = "\n".join(
            SPECS_RDKIT[pr].get("build", [])
            + SPECS_RDKIT[pr].get("build_after_test_patch", [])
            + SPECS_RDKIT[pr].get("test_cmd", [])
        )
        assert "not evaluable" not in spec_text
        assert marker in spec_text


def test_testgen_specs_avoid_stale_or_broad_targets():
    assert "smiTestCatch" in " ".join(SPECS_RDKIT["5468"]["test_cmd"])
    assert "graphmolTestsCatch" in " ".join(SPECS_RDKIT["8795"]["test_cmd"])
    assert "GraphMol|graphmol" not in " ".join(SPECS_RDKIT["8795"]["test_cmd"])


def test_openmm_native_python_api_spec_builds_wrappers():
    spec = SPECS_OPENMM["4870"]
    assert spec["test_generation_use_spec_cmd"] is True
    assert "-DOPENMM_BUILD_PYTHON_WRAPPERS=ON" in spec["build_after_test_patch"][0]
    assert "-DBUILD_TESTING=OFF" in spec["build_after_test_patch"][0]
    assert "--target install" in spec["build_after_test_patch"][2]
    assert "PythonInstall" in spec["build_after_test_patch"][3]
    import_check = spec["build_after_test_patch"][3]
    assert "import simtk.openmm" in import_check
    # Pre-7.0 OpenMM revisions ship only `simtk.openmm`, with no top-level
    # `openmm` package on disk -- the check must not hard-require `import
    # openmm` unconditionally, only when wrappers/python/openmm exists.
    assert "wrappers/python/openmm" in import_check
    assert SPECS_OPENMM["1837"]["test_generation_use_spec_cmd"] is True


def test_openmm_826_builds_matching_amoeba_python_bindings():
    spec = SPECS_OPENMM["826"]
    configure = spec["build_after_test_patch"][0]

    assert "-DOPENMM_BUILD_PYTHON_WRAPPERS=ON" in configure
    assert "-DOPENMM_BUILD_AMOEBA_PLUGIN=ON" in configure
    assert "python -m pip install --no-cache-dir openmm" not in "\n".join(
        spec["pre_install"]
    )
    assert "OPENMM_PLUGIN_DIR=$PWD/build" in spec["test_cmd"][0]
    assert "test_RigidWater" in spec["test_cmd"][0]
    # Must tolerate the offending "# Look" line being indented (as it is in
    # some OpenMM revisions), not just at column 0.
    import re as _re
    import subprocess as _subprocess

    sed_command = next(
        part for part in spec["build_after_test_patch"][1].split(" && ") if "sed -i" in part
    )
    sed_expr = _re.search(r"sed -i '([^']*)'", sed_command).group(1)
    sample = "      # Look for the first tag to figure out what type of object it is.\n"
    patched = _subprocess.run(
        ["sed", sed_expr], input=sample, capture_output=True, text=True, check=True
    ).stdout
    assert patched == "      // Look for the first tag to figure out what type of object it is.\n"


def test_openmm_5137_runs_cmake_runtime_output():
    command = SPECS_OPENMM["5137"]["test_cmd"][0]
    pre_install = "\n".join(SPECS_OPENMM["5137"]["pre_install"])

    assert "./build/TestOpenCLFFT" in command
    assert "./build/platforms/opencl/tests/TestOpenCLFFT" not in command
    assert "pocl-opencl-icd" in pre_install


def test_legacy_rdkit_specs_install_boost_endian_compatibility_header():
    for pr in ("2083", "2377"):
        assert any("boost/detail/endian.hpp" in cmd for cmd in SPECS_RDKIT[pr]["pre_install"])


def test_issues_testgen_rdkit_rows_have_concrete_specs():
    prs = {
        "2083", "2377", "2548", "3015", "3050", "3098", "3354",
        "3729", "3749", "5570", "6021", "6193", "6199", "6686",
        "7116", "7152", "7384", "7975", "8192", "8210", "8211",
        "8264", "8266", "8269", "8289", "8294", "8367", "8385",
        "8493", "8542", "8550", "8587", "8652", "8680", "8767",
        "8808", "8824", "8907", "8974", "9002", "9119", "9120",
        "9228", "9302", "9325", "9332",
    }

    for pr in prs:
        spec = SPECS_RDKIT[pr]
        spec_text = "\n".join(
            spec.get("build", [])
            + spec.get("build_after_test_patch", [])
            + spec.get("test_cmd", [])
        )
        assert spec.get("fail_to_pass")
        assert "not evaluable" not in spec_text


def test_rdkit_python_wrapper_specs_enable_both_generated_test_languages():
    for pr in ("6506", "6646", "6948", "7426", "8376", "8999"):
        cmake = SPECS_RDKIT[pr]["build"][1]
        assert "-DRDK_BUILD_PYTHON_WRAPPERS=ON" in cmake
        assert "-DRDK_BUILD_CPP_TESTS=ON" in cmake


def test_sci_cc_001_excluded_specs_have_concrete_fallbacks():
    openmm_prs = ("2187", "2802", "4188", "5155")
    rdkit_prs = (
        "3196",
        "3412",
        "3615",
        "3930",
        "4303",
        "4414",
        "5063",
        "5232",
        "5468",
        "6231",
        "6250",
        "7137",
        "7571",
        "8179",
        "8217",
        "8515",
        "8588",
        "8734",
        "8874",
        "9012",
        "9022",
        "9125",
        "9300",
        "9348",
        "9355",
    )

    for pr in openmm_prs:
        spec = SPECS_OPENMM[pr]
        spec_text = "\n".join(spec.get("test_cmd", []))
        assert "not evaluable" not in spec_text
        assert spec.get("fail_to_pass")

    for pr in rdkit_prs:
        spec = SPECS_RDKIT[pr]
        spec_text = "\n".join(
            spec.get("build", [])
            + spec.get("build_after_test_patch", [])
            + spec.get("test_cmd", [])
        )
        assert "not evaluable" not in spec_text
        assert "no curated spec" not in spec_text
        assert spec.get("fail_to_pass")


def test_sci_cc_001_rdkit_specs_use_registered_ctest_targets():
    expected_targets = {
        "3412": ("chiralityTestsCatch",),
        "3615": ("fileParsersCatchTest", "moldraw2DTestCatch"),
        "3930": ("moldraw2DTestCatch",),
        "4414": ("rxnTestCatch",),
        "5063": ("moldraw2DTestCatch",),
        "5232": ("rgroupCatchTests",),
        "6231": (
            "graphmolOrganometallicsCatch",
            "graphmolMolOpsTest",
            "moldraw2DTestCatch",
        ),
        "7137": ("canonTestsCatch",),
        "7571": ("moldraw2DTestCatch",),
        "8179": ("molfileStereoCatchTest", "moldraw2DTestCatch"),
        "8217": ("moldraw2DTestCatch",),
        "8588": ("testMMPA",),
        "8734": ("molTransformsTestCatch",),
        "9012": (
            "testSynthonSpaceSubstructureSearch",
            "testSynthonSpaceFingerprintSearch",
            "testSynthonSpaceRascalSearch",
        ),
        "9022": (
            "testSynthonSpaceSubstructureSearch",
            "testSynthonSpaceFingerprintSearch",
            "testSynthonSpaceRascalSearch",
        ),
        "9125": ("graphmolMolOpsTest", "molopsTestsCatch"),
        "9300": ("moldraw2DTestCatch",),
    }
    known_bad_regexes = (
        "MolDraw2D|moldraw",
        "Reaction|reaction|ChemReactions",
        "RGroup|rgroup",
        "ChemTransforms|chemtransforms|Synthon",
        "GraphMol|graphmol",
    )

    for pr, targets in expected_targets.items():
        spec_text = "\n".join(
            SPECS_RDKIT[pr].get("build", [])
            + SPECS_RDKIT[pr].get("build_after_test_patch", [])
            + SPECS_RDKIT[pr].get("test_cmd", [])
        )
        for target in targets:
            assert f"-R '^{target}$'" in spec_text
            assert f"--target {' '.join(targets)}" in spec_text
        assert not any(regex in spec_text for regex in known_bad_regexes)


def test_issues_no_tests_batches_have_concrete_specs():
    gpu_only = {"2255"}
    batch_1_openmm = {
        "4138", "2819", "2255", "4294", "4618", "4079", "5069",
        "1640", "1540", "3326", "3923", "2318", "1679", "2781",
        "2644", "1932", "1592", "3280", "1382", "5242", "920",
        "5346", "5117", "5219", "4748", "3630", "3460", "3428",
        "2829", "1924", "2322", "2257", "2152", "4440", "5302",
        "5359", "5213", "5221", "4760", "4364", "4293", "5149",
    }
    batch_2_openmm = {
        "4986", "4249", "4279", "4148", "4161", "4119", "4104",
        "4090", "3872", "3834", "3771", "3574", "3442", "3311",
        "3321", "3240", "3241", "3198", "3151", "3057", "3041",
        "2639", "2575", "2544", "2563", "2363", "2429", "2328",
        "1957", "1363", "1100", "1682", "1250", "631",
    }
    batch_2_rdkit = {
        "8796", "8166", "7990", "7814", "5261", "5103", "4793",
    }

    assert len(batch_1_openmm) == 42
    assert len(batch_2_openmm) == 34
    assert len(batch_2_rdkit) == 7
    for specs, prs in (
        (SPECS_OPENMM, batch_1_openmm | batch_2_openmm),
        (SPECS_RDKIT, batch_2_rdkit),
    ):
        for pr in prs:
            spec = specs[pr]
            text = "\n".join(
                spec.get("build", [])
                + spec.get("build_after_test_patch", [])
                + spec.get("test_cmd", [])
            )
            assert spec.get("fail_to_pass"), pr
            if pr in gpu_only:
                assert "not evaluable:" in text, pr
            else:
                assert "not evaluable" not in text, pr
            assert "no curated" not in text, pr


def test_openmm_cuda_targets_spec_requests_gpu_and_installs_toolkit():
    from swebench.harness.constants.c import _openmm_cuda_targets_spec

    spec = _openmm_cuda_targets_spec("TestCudaAmoebaMultipoleForce")

    assert spec["docker_specs"] == {"run_args": {"gpu": True}}
    assert spec["test_generation_use_spec_cmd"] is True
    pre_install = "\n".join(spec["pre_install"])
    assert "cuda-keyring" in pre_install
    assert "cuda-nvcc-12-4" in pre_install
    assert "cuda-cudart-dev-12-4" in pre_install
    assert "cuda-nvrtc-dev-12-4" in pre_install
    assert "libcufft-dev-12-4" in pre_install
    build = "\n".join(spec["build_after_test_patch"])
    assert "-DOPENMM_BUILD_CUDA_LIB=ON" in build
    assert "-DOPENMM_BUILD_OPENCL_LIB=OFF" in build
    assert "TestCudaAmoebaMultipoleForce" in build
    assert spec["test_cmd"] == [
        "LD_LIBRARY_PATH=$PWD/build:${LD_LIBRARY_PATH:-} "
        "OPENMM_PLUGIN_DIR=$PWD/build "
        "./build/TestCudaAmoebaMultipoleForce"
    ]
    assert spec["fail_to_pass"] == ["TestCudaAmoebaMultipoleForce"]


def test_openmm_source_check_python_overlay_replaces_installed_app():
    spec = SPECS_OPENMM["4760"]

    assert any("pip install --no-cache-dir openmm" in c for c in spec["pre_install"])
    overlay = "\n".join(spec["build"])
    assert 'rm -rf "$OPENMM_SITE/app"' in overlay


def test_rdkit_pandas_tools_spec_installs_pillow():
    from swebench.harness.constants.c import SPECS_RDKIT

    pre_install = "\n".join(SPECS_RDKIT["5103"]["pre_install"])
    assert "python3-pil" in pre_install


def test_openmm_cuda_targets_spec_enables_plugin():
    from swebench.harness.constants.c import _openmm_cuda_targets_spec

    spec = _openmm_cuda_targets_spec("TestCudaAmoebaMultipoleForce", plugin="amoeba")

    build = "\n".join(spec["build_after_test_patch"])
    assert "-DOPENMM_BUILD_AMOEBA_PLUGIN=ON" in build


def test_openmm_opencl_targets_spec_gpu_flag_sets_run_args():
    from swebench.harness.constants.c import _openmm_opencl_targets_spec

    cpu_spec = _openmm_opencl_targets_spec("TestOpenCLNonbondedForce")
    gpu_spec = _openmm_opencl_targets_spec("TestOpenCLNonbondedForce", gpu=True)

    assert "docker_specs" not in cpu_spec
    assert gpu_spec["docker_specs"] == {"run_args": {"gpu": True}}


def test_hardcoded_gpu_stubs_converted_to_real_specs():
    from swebench.harness.constants.c import SPECS_OPENMM

    expected = {
        "1640": "TestCudaAmoebaMultipoleForce",
        "2152": "TestCudaAmoebaMultipoleForce",
        "2829": "TestOpenCLNonbondedForce",
        "4364": "TestCudaCustomNonbondedForce",
        "5302": "TestCudaAmoebaMultipoleForce",
    }
    for pr, target in expected.items():
        spec = SPECS_OPENMM[pr]
        spec_text = "\n".join(
            spec.get("pre_install", [])
            + spec.get("build", [])
            + spec.get("build_after_test_patch", [])
            + spec.get("test_cmd", [])
        )
        assert "not evaluable" not in spec_text, pr
        assert target in spec_text, pr
        assert spec["docker_specs"]["run_args"]["gpu"] is True, pr


def test_pr_2255_stays_non_evaluable_pending_follow_up():
    from swebench.harness.constants.c import SPECS_OPENMM

    spec_text = "\n".join(SPECS_OPENMM["2255"].get("test_cmd", []))
    assert "not evaluable" in spec_text


def test_part2_curated_opencl_specs_request_real_gpu():
    from swebench.harness.constants.c import SPECS_OPENMM

    part2_prs = [
        "1382", "1679", "1682", "1924", "2257", "2318", "2322", "2819",
        "3057", "3428", "3460", "3771", "4079", "4090", "4119", "4148",
        "4249", "4618", "5069", "5117", "5346",
    ]
    for pr in part2_prs:
        spec = SPECS_OPENMM[pr]
        assert spec.get("docker_specs", {}).get("run_args", {}).get("gpu") is True, pr
