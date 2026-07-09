from swebench.harness.constants.c import SPECS_OPENMM, SPECS_RDKIT


def test_openmm_python_specs_install_with_test_interpreter():
    for pr in ("3303", "4188", "5155"):
        spec = SPECS_OPENMM[pr]
        pre_install = "\n".join(spec["pre_install"])

        assert "python -m pip install" in pre_install
        assert "openmm numpy scipy pytest" in pre_install
        assert "python -m pytest" in spec["test_cmd"][0]


def test_rdkit_specs_use_apt_boost_and_disable_fragile_downloads():
    for pr in ("2059", "6646", "8376", "8668", "8968", "9331"):
        spec = SPECS_RDKIT[pr]
        pre_install = "\n".join(spec["pre_install"])
        cmake = spec["build"][1]

        assert "libboost-all-dev" in pre_install
        assert "launchpadcontent" not in pre_install
        assert "apt-key" not in pre_install
        assert "-DRDK_BUILD_COORDGEN_SUPPORT=OFF" in cmake
        assert "-DRDK_BUILD_MAEPARSER_SUPPORT=OFF" in cmake


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
            "RDBASE=$PWD PYTHONPATH=$PWD LD_LIBRARY_PATH=$PWD/lib:${LD_LIBRARY_PATH:-} "
            f"python3 {test_path}"
        ]
