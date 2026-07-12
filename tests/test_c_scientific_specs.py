from swebench.harness.constants.c import SPECS_OPENMM, SPECS_RDKIT


def test_openmm_python_specs_install_with_test_interpreter():
    for pr in ("3303", "4188", "5155"):
        spec = SPECS_OPENMM[pr]
        pre_install = "\n".join(spec["pre_install"])

        assert "python -m pip install" in pre_install
        assert "openmm numpy scipy pytest" in pre_install
        assert "mkdir -p \"$SIMTK_SITE\"" in spec["build"][0]
        assert "compiled*" in spec["build"][0]
        assert "from openmm.vec3 import *" in spec["build"][0]
        assert "python -m pytest" in spec["test_cmd"][0]


def test_openmm_legacy_specs_use_targets_available_at_base_commit():
    assert "TestReferenceCustomIntegrator" in SPECS_OPENMM["1837"]["build_after_test_patch"][-1]
    assert "TestReferenceBAOABLangevinIntegrator" in SPECS_OPENMM["2561"]["build_after_test_patch"][-1]


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
        assert "-DRDK_BUILD_COORDGEN_SUPPORT=OFF" in cmake
        assert "-DRDK_BUILD_MAEPARSER_SUPPORT=OFF" in cmake
        assert "-DRDK_BUILD_CHEMDRAW_SUPPORT=OFF" in cmake


def test_newer_rdkit_specs_install_required_new_boost():
    for pr in ("8668", "8968", "9331"):
        spec = SPECS_RDKIT[pr]
        pre_install = "\n".join(spec["pre_install"])
        cmake = spec["build"][1]

        assert "libboost1.83-all-dev" in pre_install
        assert "launchpadcontent.net/mhier/libboost-latest" in pre_install
        assert "-DRDK_BUILD_COORDGEN_SUPPORT=OFF" in cmake
        assert "-DRDK_BUILD_MAEPARSER_SUPPORT=OFF" in cmake


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

    assert spec["build"][1].endswith(
        "-DRDK_BUILD_CHEMDRAW_SUPPORT=OFF -DRDK_BUILD_COORDGEN_SUPPORT=OFF "
        "-DRDK_BUILD_MAEPARSER_SUPPORT=OFF -DRDK_BUILD_AVALON_SUPPORT=OFF "
        "-DRDK_BUILD_YAEHMOP_SUPPORT=OFF -DRDK_BUILD_THREADSAFE_SSS=ON "
        "-DRDK_BUILD_CHEMDRAW_SUPPORT=ON "
    )
    assert "find External/ChemDraw -name chemdraw.h" in spec["build"][2]
    assert "External/ChemDraw/ChemDraw" in spec["build"][2]
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
        "5137": "TestOpenCLFFT",
        "5198": "TestCpuLocalEnergyMinimizer",
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
        "8795": "GraphMol|graphmol",
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
