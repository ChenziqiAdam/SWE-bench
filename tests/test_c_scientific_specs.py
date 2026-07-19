from swebench.harness.constants.c import SPECS_OPENMM, SPECS_RDKIT


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
    for pr in ("3412", "3615", "3930", "4414", "5063"):
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
        "ctest --test-dir build -V -R smiTest1"
    ]


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
    assert "--target install" in spec["build_after_test_patch"][1]
    assert "PythonInstall" in spec["build_after_test_patch"][2]
    assert "import openmm, simtk.openmm" in spec["build_after_test_patch"][2]
    assert SPECS_OPENMM["1837"]["test_generation_use_spec_cmd"] is True


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


def test_rdkit_python_wrapper_specs_do_not_build_cpp_tests():
    for pr in ("6506", "6646", "6948", "7426", "8376", "8999"):
        cmake = SPECS_RDKIT[pr]["build"][1]
        assert "-DRDK_BUILD_PYTHON_WRAPPERS=ON" in cmake
        assert "-DRDK_BUILD_CPP_TESTS=OFF" in cmake


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
            assert f"-R {target}" in spec_text
            assert f"--target {' '.join(targets)}" in spec_text
        assert not any(regex in spec_text for regex in known_bad_regexes)
