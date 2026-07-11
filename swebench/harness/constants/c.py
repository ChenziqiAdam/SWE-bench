# Constants - Task Instance Installation Environment
SPECS_REDIS = {
    "13115": {
        "build": ["make distclean", "make"],
        "test_cmd": ["TERM=dumb ./runtest --durable --single unit/scripting"],
    },
    "12472": {
        "build": ["make distclean", "make"],
        "test_cmd": [
            'TERM=dumb ./runtest --durable --single unit/acl --only "/.*ACL GETUSER.*"'
        ],
    },
    "12272": {
        "build": ["make distclean", "make"],
        "test_cmd": [
            'TERM=dumb ./runtest --durable --single unit/type/string --only "/.*(GETRANGE|SETRANGE).*"'
        ],
    },
    "11734": {
        "build": ["make distclean", "make"],
        "test_cmd": ["TERM=dumb ./runtest --durable --single unit/bitops"],
    },
    "10764": {
        "build": ["make distclean", "make"],
        "test_cmd": [
            'TERM=dumb ./runtest --durable --single unit/type/zset --only "BZMPOP"'
        ],
    },
    "10095": {
        "build": ["make distclean", "make"],
        "test_cmd": [
            'TERM=dumb ./runtest --durable --single unit/type/list --only "/.*(LPOP|RPOP)"'
        ],
    },
    "9733": {
        "build": ["make distclean", "make"],
        "test_cmd": ["TERM=dumb ./runtest --durable --single unit/introspection-2"],
    },
    "10068": {
        "build": ["make distclean", "make"],
        "test_cmd": [
            'TERM=dumb ./runtest --durable --single unit/type/stream --only "/*XTRIM*"'
        ],
    },
    "11631": {
        "build": ["make distclean", "make"],
        "test_cmd": [
            'TERM=dumb ./runtest --durable --single unit/geo --only "/.*GEOSEARCH .*"'
        ],
    },
    "11510": {
        "build": ["make distclean", "make"],
        "test_cmd": [
            'TERM=dumb ./runtest --durable --single unit/introspection --only "/.*MONITOR.*"'
        ],
    },
    "11279": {
        "build": ["make distclean", "make"],
        "test_cmd": ["TERM=dumb ./runtest --durable --single unit/acl"],
    },
    "13338": {
        "build": ["make distclean", "make"],
        "test_cmd": ["TERM=dumb ./runtest --durable --single unit/type/stream-cgroups"],
    },
}

SPECS_JQ = {
    **{
        k: {
            "build": [
                "git submodule update --init",
                "autoreconf -fi",
                "./configure --with-oniguruma=builtin",
                "make clean",
                "touch src/parser.y src/lexer.l",  # force parser and lexer to be regenerated
                "make -j$(nproc)",
            ],
            "test_cmd": ["make check"],
        }
        for k in [
            "2839",
            "2650",
            "2235",
            "2658",
            "2750",
            "2681",
            "2919",
            "2598",
            "2728",
        ]
    }
}

SPECS_JSON = {
    "4237": {
        "build": [
            "mkdir -p build",
            "cd build",
            "cmake ..",
            "make test-udt_cpp11",
            "cd ..",
        ],
        "test_cmd": ["./build/tests/test-udt_cpp11 -s -r=xml"],
    },
}

SPECS_MICROPYTHON = {
    "15898": {
        "pre_install": ["python -m venv .venv", "source .venv/bin/activate"],
        "build": [
            "source ./tools/ci.sh",
            "ci_unix_build_helper VARIANT=standard",
            "gcc -shared -o tests/ports/unix/ffi_lib.so tests/ports/unix/ffi_lib.c",
        ],
        "test_cmd": [
            "cd tests",
            "MICROPY_CPYTHON3=python3 MICROPY_MICROPYTHON=../ports/unix/build-standard/micropython ./run-tests.py -i string_format",
        ],
    },
    "13569": {
        "pre_install": ["python -m venv .venv", "source .venv/bin/activate"],
        "build": [
            "source ./tools/ci.sh",
            "ci_unix_build_helper VARIANT=standard",
            "gcc -shared -o tests/ports/unix/ffi_lib.so tests/ports/unix/ffi_lib.c",
        ],
        "test_cmd": [
            "cd tests",
            "MICROPY_CPYTHON3=python3 MICROPY_MICROPYTHON=../ports/unix/build-standard/micropython ./run-tests.py -i try",
        ],
    },
    "13039": {
        "pre_install": ["python -m venv .venv", "source .venv/bin/activate"],
        "build": [
            "source ./tools/ci.sh",
            "ci_unix_build_helper VARIANT=standard",
            "gcc -shared -o tests/unix/ffi_lib.so tests/unix/ffi_lib.c",
        ],
        "test_cmd": [
            "cd tests",
            "MICROPY_CPYTHON3=python3 MICROPY_MICROPYTHON=../ports/unix/build-standard/micropython ./run-tests.py -i slice",
        ],
    },
    "12158": {
        "pre_install": ["python -m venv .venv", "source .venv/bin/activate"],
        "build": [
            "source ./tools/ci.sh",
            "ci_unix_build_helper VARIANT=standard",
            "gcc -shared -o tests/unix/ffi_lib.so tests/unix/ffi_lib.c",
        ],
        "test_cmd": [
            "cd tests",
            "MICROPY_CPYTHON3=python3 MICROPY_MICROPYTHON=../ports/unix/build-standard/micropython ./run-tests.py -d thread",
        ],
    },
    "10095": {
        "pre_install": [
            "python -m venv .venv",
            "source .venv/bin/activate",
            # https://github.com/micropython/micropython/issues/10951
            "sed -i 's/uint mp_import_stat/mp_import_stat_t mp_import_stat/' mpy-cross/main.c",
        ],
        "build": ["source ./tools/ci.sh", "ci_unix_build_helper VARIANT=standard"],
        "test_cmd": [
            "cd tests",
            "MICROPY_CPYTHON3=python3 MICROPY_MICROPYTHON=../ports/unix/build-standard/micropython ./run-tests.py -i basics/fun",
        ],
    },
}

SPECS_VALKEY = {
    "928": {
        "build": ["make distclean", "make"],
        "test_cmd": [
            'TERM=dumb ./runtest --durable --single unit/cluster/replica-migration --only "/.*NOREPLICAS.*"'
        ],
    },
    "790": {
        "build": ["make distclean", "make"],
        "test_cmd": [
            "TERM=dumb ./runtest --durable --single unit/cluster/cluster-shards"
        ],
    },
    "1499": {
        "build": ["make distclean", "make"],
        "test_cmd": ["TERM=dumb ./runtest --durable --single unit/introspection-2"],
    },
    "1842": {
        "build": ["make distclean", "make"],
        "test_cmd": [
            'TERM=dumb ./runtest --durable --single unit/acl --only "/.*ACL LOAD.*"'
        ],
    },
}

SPECS_FMT = {
    **{
        k: {
            "build": [
                "mkdir -p build",
                "cmake -B build -S .",
                "cmake --build build --parallel $(nproc) --target ranges-test",
            ],
            "test_cmd": ["ctest --test-dir build -V -R ranges-test"],
        }
        for k in ["3863", "3158", "2457"]
    },
    **{
        k: {
            "build": [
                "mkdir -p build",
                "cmake -B build -S .",
                "cmake --build build --parallel $(nproc) --target format-test",
            ],
            "test_cmd": ["ctest --test-dir build -V -R format-test"],
        }
        for k in ["3901", "3750", "3248", "2317", "2310"]
    },
    "3272": {
        "build": [
            "mkdir -p build",
            "cmake -B build -S .",
            "cmake --build build --parallel $(nproc) --target xchar-test",
        ],
        "test_cmd": ["ctest --test-dir build -V -R xchar-test"],
    },
    "3729": {
        "build": [
            "mkdir -p build",
            "cmake -B build -S .",
            "cmake --build build --parallel $(nproc) --target std-test",
        ],
        "test_cmd": ["ctest --test-dir build -V -R std-test"],
    },
    "1683": {
        "build": [
            "mkdir -p build",
            "cmake -B build -S .",
            "cmake --build build --parallel $(nproc) --target printf-test",
        ],
        "test_cmd": ["ctest --test-dir build -V -R printf-test"],
    },
}

# Template spec for CMake+CTest/GoogleTest repos.
# Build commands and test targets must be filled in per PR.
# Keys are PR number strings.
SPECS_OPENBABEL = {
    # Add entries here: "<PR_NUMBER>": {"build": [...], "test_cmd": [...]}
    # Build pattern:
    #   "mkdir -p build",
    #   "cmake -B build -S . -DENABLE_TESTS=ON",
    #   "cmake --build build --parallel $(nproc) --target <test_target>",
    # Test pattern:
    #   "ctest --test-dir build -V -R <test_regex>"
}


def _openmm_python_app_spec(test_file: str, test_filter: str) -> dict:
    """Run OpenMM Python app tests against the patched pure-Python app package."""
    return {
        "pre_install": [
            "python -m pip install --no-cache-dir --upgrade pip setuptools wheel",
            "python -m pip install --no-cache-dir openmm numpy scipy pytest",
        ],
        "build": [
            "OPENMM_SITE=$(python -c 'import openmm, os; print(os.path.dirname(openmm.__file__))') && "
            "if [ -d /testbed/wrappers/python/openmm/app ]; then cp -r /testbed/wrappers/python/openmm/app \"$OPENMM_SITE/\"; fi && "
            "SIMTK_SITE=$(python -c 'import simtk.openmm, os; print(os.path.dirname(simtk.openmm.__file__))' 2>/dev/null || true) && "
            "if [ -n \"$SIMTK_SITE\" ] && [ -d /testbed/wrappers/python/simtk/openmm/app ]; then cp -r /testbed/wrappers/python/simtk/openmm/app \"$SIMTK_SITE/\"; fi",
        ],
        "test_cmd": [
            f"cd wrappers/python/tests && python -m pytest -xvs {test_file} -k '{test_filter}'",
        ],
    }


def _openmm_cpp_targets_spec(*targets: str) -> dict:
    """Build OpenMM without GPU backends and run selected C++ test executables."""
    return {
        "pre_install": [
            "apt-get update -q",
            "apt-get install -y --no-install-recommends cmake g++ make",
        ],
        "build_after_test_patch": [
            "cmake -B build -S . "
            "-DCMAKE_BUILD_TYPE=Release "
            "-DOPENMM_BUILD_CUDA_LIB=OFF "
            "-DOPENMM_BUILD_OPENCL_LIB=OFF "
            "-DOPENMM_BUILD_HIP_LIB=OFF "
            "-DOPENMM_BUILD_PYTHON_WRAPPERS=OFF "
            "-DOPENMM_BUILD_C_AND_FORTRAN_WRAPPERS=OFF",
            "cmake --build build --parallel $(nproc) --target " + " ".join(targets),
        ],
        "test_cmd": [
            f"LD_LIBRARY_PATH=$PWD/build:${{LD_LIBRARY_PATH:-}} "
            f"OPENMM_PLUGIN_DIR=$PWD/build "
            f"./build/{target}"
            for target in targets
        ],
    }


def _openmm_python_unit_spec(test_filter: str) -> dict:
    """Run OpenMM Python unit tests against patched simtk.unit modules."""
    return {
        "pre_install": [
            "python -m pip install --no-cache-dir --upgrade pip setuptools wheel",
            "python -m pip install --no-cache-dir openmm numpy scipy pytest",
        ],
        "build": [
            "SIMTK_SITE=$(python -c 'import simtk, os; print(os.path.dirname(simtk.__file__))') && "
            "if [ -d /testbed/wrappers/python/simtk/unit ]; then cp -r /testbed/wrappers/python/simtk/unit \"$SIMTK_SITE/\"; fi",
        ],
        "test_cmd": [
            f"cd wrappers/python/tests && python -m pytest -xvs TestAPIUnits.py -k '{test_filter}'",
        ],
    }


_RDKIT_PRE_INSTALL = [
    "apt-get update -q",
    "apt-get install -y --no-install-recommends "
    "cmake g++ make libboost-all-dev libeigen3-dev pkg-config libfreetype-dev",
]

_RDKIT_BOOST_183_PRE_INSTALL = [
    "apt-get update -q",
    "apt-get install -y --no-install-recommends ca-certificates gnupg",
    "echo 'deb https://ppa.launchpadcontent.net/mhier/libboost-latest/ubuntu jammy main' > /etc/apt/sources.list.d/mhier-libboost-latest.list",
    "apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 31F54F3E108EAD31",
    "apt-get update -q",
    "apt-get install -y --no-install-recommends "
    "cmake g++ make libboost1.83-all-dev libeigen3-dev pkg-config libfreetype-dev",
]

_RDKIT_LEGACY_BOOST_ENDIAN_SHIM = (
    "mkdir -p /usr/include/boost/detail && "
    "printf '#pragma once\\n#include <boost/predef/other/endian.h>\\n"
    "#if BOOST_ENDIAN_BIG_BYTE\\n#define BOOST_BIG_ENDIAN\\n"
    "#elif BOOST_ENDIAN_LITTLE_BYTE\\n#define BOOST_LITTLE_ENDIAN\\n#endif\\n' "
    "> /usr/include/boost/detail/endian.hpp"
)

_RDKIT_CHEMDRAW_INCLUDE_COMPAT = (
    "if [ -d External/ChemDraw/chemdraw/chemdraw ]; then "
    "if [ ! -e External/ChemDraw/ChemDraw ]; then "
    "ln -s chemdraw/chemdraw External/ChemDraw/ChemDraw; fi; "
    "if [ ! -e External/ChemDraw/chemdraw/ChemDraw ]; then "
    "ln -s chemdraw External/ChemDraw/chemdraw/ChemDraw; fi; "
    "fi"
)

_RDKIT_BASE_CMAKE_FLAGS = (
    "-DCMAKE_BUILD_TYPE=Release "
    "-DRDK_INSTALL_INTREE=ON "
    "-DRDK_BUILD_CPP_TESTS=ON "
    "-DRDK_BUILD_PYTHON_WRAPPERS=OFF "
    "-DRDK_BUILD_INCHI_SUPPORT=OFF "
    "-DRDK_BUILD_CAIRO_SUPPORT=OFF "
    "-DRDK_BUILD_FREETYPE_SUPPORT=OFF "
    "-DRDK_BUILD_CHEMDRAW_SUPPORT=OFF "
    "-DRDK_BUILD_COORDGEN_SUPPORT=OFF "
    "-DRDK_BUILD_MAEPARSER_SUPPORT=OFF "
    "-DRDK_BUILD_AVALON_SUPPORT=OFF "
    "-DRDK_BUILD_YAEHMOP_SUPPORT=OFF "
    "-DRDK_BUILD_THREADSAFE_SSS=ON "
)


def _rdkit_cpp_targets_spec(
    *targets: str,
    extra_cmake: str = "",
    new_boost: bool = False,
    legacy_boost_endian: bool = False,
    chemdraw_include_compat: bool = False,
    defer_target_build: bool = False,
) -> dict:
    """Build RDKit C++ tests and run selected CTest targets."""
    pre_install = list(_RDKIT_BOOST_183_PRE_INSTALL if new_boost else _RDKIT_PRE_INSTALL)
    if legacy_boost_endian:
        pre_install.append(_RDKIT_LEGACY_BOOST_ENDIAN_SHIM)
    build = [
        "mkdir -p build",
        "cmake -B build -S . " + _RDKIT_BASE_CMAKE_FLAGS + extra_cmake,
    ]
    if chemdraw_include_compat:
        build.append(_RDKIT_CHEMDRAW_INCLUDE_COMPAT)
    target_build = "cmake --build build --parallel $(nproc) --target " + " ".join(targets)
    if not defer_target_build:
        build.append(target_build)
    spec = {
        "pre_install": pre_install,
        "build": build,
        "test_cmd": [
            f"RDBASE=$PWD LD_LIBRARY_PATH=$PWD/lib:${{LD_LIBRARY_PATH:-}} "
            f"ctest --test-dir build -V -R {target}"
            for target in targets
        ],
    }
    if defer_target_build:
        spec["build_after_test_patch"] = [target_build]
    return spec


def _rdkit_cpp_ctest_regex_spec(test_regex: str, new_boost: bool = False) -> dict:
    """Build RDKit C++ tests broadly, then run a focused CTest regex."""
    spec = _rdkit_cpp_targets_spec(extra_cmake="", new_boost=new_boost)
    spec["build"][-1] = "cmake --build build --parallel $(nproc)"
    spec["test_cmd"] = [
        f"RDBASE=$PWD LD_LIBRARY_PATH=$PWD/lib:${{LD_LIBRARY_PATH:-}} "
        f"ctest --test-dir build -V -R '{test_regex}'"
    ]
    return spec


def _rdkit_python_wrapper_spec(test_path: str) -> dict:
    """Build RDKit in-tree with Python wrappers and run a focused Python test."""
    spec = _rdkit_cpp_targets_spec()
    spec["build"][1] = spec["build"][1].replace(
        "-DRDK_BUILD_PYTHON_WRAPPERS=OFF ",
        "-DRDK_BUILD_PYTHON_WRAPPERS=ON ",
    )
    spec["pre_install"].append("apt-get install -y --no-install-recommends python3-dev python3-numpy")
    spec["build"][-1] = "cmake --build build --parallel $(nproc)"
    spec["test_cmd"] = [
        "cp -a build/rdkit/. rdkit/ && "
        f"RDBASE=$PWD PYTHONPATH=$PWD LD_LIBRARY_PATH=$PWD/lib:${{LD_LIBRARY_PATH:-}} "
        f"python3 {test_path}"
    ]
    return spec


class _OpenMMSpecs(dict):
    """Return a non-evaluable placeholder for uncurated numeric OpenMM PR specs."""

    def __contains__(self, key):
        return super().__contains__(key) or str(key).isdigit()

    def __missing__(self, key):
        pr = str(key)
        if not pr.isdigit():
            raise KeyError(key)
        spec = {
            "pre_install": [],
            "build": [],
            "test_cmd": [
                f"echo 'openmm#{pr} not evaluable: no curated spec' && false",
            ],
        }
        self[pr] = spec
        return spec


SPECS_OPENMM = _OpenMMSpecs({
    "2802": _openmm_python_unit_spec("PhysicalConstants"),
    # PR #4832: flexibleConstraints option for AmberPrmtopFile (Python-only change).
    # The C base image has python3/pip but NO conda, so install OpenMM via pip
    # to get the compiled `_openmm` extension + native libs. The patch edits the
    # pure-Python `openmm/app/amberprmtopfile.py` in /testbed; overlay that package
    # onto the installed copy in site-packages so the patch takes effect without a
    # full C++ build, then run the pytest FAIL_TO_PASS test against it.
    "4832": {
        # pre_install runs at IMAGE BUILD time (before the model patch). Install the
        # compiled OpenMM (native _openmm*.so + libs) here — heavy, patch-independent.
        "pre_install": [
            # scipy: the test loads an Amber NetCDF restart via scipy.io.netcdf_file.
            "python -m pip install --no-cache-dir --upgrade pip setuptools wheel",
            "python -m pip install --no-cache-dir openmm numpy scipy pytest",
        ],
        # build runs in eval.sh, AFTER the model patch is applied to /testbed. Overlay
        # the *patched* pure-Python openmm package onto the pip-installed copy so the
        # test imports the patched code (keeps pip's compiled _openmm*.so untouched).
        "build": [
            "SITE=$(python -c 'import openmm, os; print(os.path.dirname(openmm.__file__))') && "
            "cp -r /testbed/wrappers/python/openmm/app \"$SITE/\"",
        ],
        # The test reads data files via RELATIVE paths ('systems/...inpcrd'), so we
        # MUST cd into wrappers/python/tests for them to resolve. That makes pytest
        # emit a path-stripped nodeid (TestAmberPrmtopFile.py::...), which won't match
        # the full-path FAIL_TO_PASS key directly — the log parser's _reconcile_nodeids
        # suffix-matches it back to the real key. The harness's post-test `git checkout`
        # runs from /testbed (eval.sh re-cd's), so the subdir cd here is safe.
        "test_cmd": [
            "cd wrappers/python/tests && python -m pytest -xvs TestAmberPrmtopFile.py::TestAmberPrmtopFile::testFlexibleConstraints",
        ],
    },
    # PR #4881: computeCurrentPressure() for MonteCarloBarostat.
    # NOT evaluable in this environment: the instance has an EMPTY FAIL_TO_PASS set
    # and every test in the test_patch targets CUDA/HIP/OpenCL platforms, which need
    # a GPU. There is no Reference-platform test to fall back on, so no patch can be
    # scored here. Spec is a no-op placeholder; expect EMPTY/unresolved in reports.
    "4881": {
        "pre_install": [
            "pip install --no-cache-dir numpy",
        ],
        "build": [],
        "test_cmd": [
            "echo 'openmm#4881 not evaluable: empty FAIL_TO_PASS, GPU-only tests' && false",
        ],
    },
    # ── Not evaluable (no functional test patch) ──────────────────────────────
    # Issues.xlsx rows without curated per-PR scientific test specs are included
    # here as explicit placeholders. No FAIL_TO_PASS can be scored — these are
    # no-op placeholders so the batch run doesn't crash on a missing key.
    # Expect them to report unresolved/empty; drop from the eval set later.
    **{
        pr: {
            "pre_install": [],
            "build": [],
            "test_cmd": [
                f"echo 'openmm#{pr} not evaluable: no functional test patch' && false",
            ],
        }
        for pr in [
            "1235",
            "1495",
            "1802",
            "2241",
            "2452",
            "2695",
            "3286",
            "3299",
            "3480",
            "3493",
            "3506",
            "4168",
            "4219",
            "4870",
            "4899",
            "5031",
            "5137",
            "5198",
            "5322",
            "5342",
        ]
    },
    # ── Exact Python wrapper tests ───────────────────────────────────────────
    # These PRs add or modify focused Python app tests. Use pip's compiled
    # OpenMM package for native libraries, then overlay the patched pure-Python
    # app package from /testbed before running the exact pytest selector.
    **{
        pr: _openmm_python_app_spec(test_file, test_filter)
        for pr, test_file, test_filter in [
            ("826", "TestForceField.py", "test_RigidWater"),
            ("1302", "TestPdbFile.py", "test_ExtraParticles"),
            (
                "1668",
                "TestTopology.py",
                "test_bondtype_singleton or test_residue_bonds",
            ),
            ("2040", "TestForceField.py", "test_Disulfides"),
            (
                "2362",
                "TestAmberPrmtopFile.py",
                "test_ImplicitSolventZeroSA or test_HydrogenMass",
            ),
            ("2381", "TestCharmmFiles.py", "test_NBXMod"),
            ("2511", "TestForceField.py", "test_ImpropersOrdering_smirnoff"),
            ("2738", "TestForceField.py", "test_CharmmPolar"),
            ("3214", "TestForceField.py", "test_ImplicitSolventForces"),
            ("4188", "TestGromacsTopFile.py", "test_Vsite3Func4"),
            (
                "3303",
                "TestForceField.py TestModeller.py",
                "test_Glycam or test_addHydrogensGlycam",
            ),
            ("3313", "TestForceField.py", "test_Amoeba18Nucleic"),
            ("3324", "TestCharmmFiles.py", "test_NBFIX14"),
            ("4028", "TestGromacsTopFile.py", "test_GROMOS"),
            (
                "4536",
                "TestGromacsTopFile.py",
                "test_Vsite3Func1 or test_Vsite3Func4",
            ),
            ("4794", "TestXtcFile.py", "test_xtc_small"),
            ("4852", "TestForceField.py", "test_CMAPTorsionGeneratorMapAssignment"),
            ("5155", "TestGromacsTopFile.py", "test_Vsite3Func3"),
            ("5236", "TestForceField.py", "test_TemplateConstraintsMultipleMols"),
        ]
    },
    # ── Exact C++ CPU/Reference/serialization tests ─────────────────────────
    # These avoid CUDA/OpenCL/HIP and run the C++ test executables touched by
    # the PR's test patch. Plugin-heavy/GPU-only cases stay as placeholders.
    **{
        pr: _openmm_cpp_targets_spec(*targets)
        for pr, targets in {
            "1487": ("TestReferenceAndersenThermostat",),
            "1858": ("TestReferenceVirtualSites", "TestSerializeSystem"),
            "2057": ("TestReferenceCustomIntegrator",),
            "2105": ("TestReferenceNonbondedForce",),
            "2187": ("TestReferenceCustomNonbondedForce",),
            "2561": (
                "TestReferenceBAOABLangevinIntegrator",
                "TestSerializeIntegrator",
            ),
            "2570": ("TestReferenceNonbondedForce", "TestSerializeNonbondedForce"),
            "2806": ("TestCpuNonbondedForce",),
            "2818": ("TestReferenceVerletIntegrator",),
            "4523": ("TestReferenceDrudeForce",),
            "4740": ("TestReferenceLangevinMiddleIntegrator",),
            "4907": ("TestReferenceEwald",),
            "5251": ("TestReferenceMonteCarloFlexibleBarostat",),
            "5278": ("TestReferenceMonteCarloAnisotropicBarostat",),
        }.items()
    },
    # ── Full C++ Reference-platform builds ────────────────────────────────────
    # 1837 (CustomCVForce), 5278 (MonteCarloMembraneBarostat), 4799 (DPDIntegrator)
    # each add a Reference-platform C++ test (Test<Name>.cpp under
    # platforms/reference/tests/). Unlike 4832's pip-overlay, these need a real
    # in-tree OpenMM build. Some tests are new files from test_patch, so the
    # CMake configure/build must run only after test_patch is applied. Keep
    # pre_install limited to toolchain deps so base image validation does not try
    # to build a target that cannot exist yet.
    **{
        pr: {
            "pre_install": [
                "apt-get update -q",
                "apt-get install -y --no-install-recommends cmake g++ make",
            ],
            "build_after_test_patch": [
                "cmake -B build -S . "
                "-DCMAKE_BUILD_TYPE=Release "
                "-DOPENMM_BUILD_CUDA_LIB=OFF "
                "-DOPENMM_BUILD_OPENCL_LIB=OFF "
                "-DOPENMM_BUILD_HIP_LIB=OFF "
                "-DOPENMM_BUILD_PYTHON_WRAPPERS=OFF "
                "-DOPENMM_BUILD_C_AND_FORTRAN_WRAPPERS=OFF",
                f"cmake --build build --parallel $(nproc) --target {target}",
            ],
            "test_cmd": [
                f"LD_LIBRARY_PATH=$PWD/build:${{LD_LIBRARY_PATH:-}} "
                f"OPENMM_PLUGIN_DIR=$PWD/build "
                f"./build/{target}",
            ],
        }
        for pr, target in {
            "1837": "TestReferenceCustomIntegrator",
            "4799": "TestReferenceDPDIntegrator",
        }.items()
    },
})

SPECS_OPENMC = {
    # Add entries here: "<PR_NUMBER>": {"build": [...], "test_cmd": [...]}
    # Build pattern:
    #   "mkdir -p build",
    #   "cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug",
    #   "cmake --build build --parallel $(nproc)",
    # Test pattern:
    #   "cd tests && python -m pytest -v <test_file>"
}

SPECS_QGIS = {
    # Add entries here: "<PR_NUMBER>": {"build": [...], "test_cmd": [...]}
    # Build pattern:
    #   "mkdir -p build",
    #   "cmake -B build -S . -DENABLE_TESTS=ON -DWITH_QTWEBKIT=OFF",
    #   "cmake --build build --parallel $(nproc) --target <test_target>",
    # Test pattern:
    #   "ctest --test-dir build -V -R <test_regex>"
}

class _RDKitSpecs(dict):
    """Return a non-evaluable placeholder for uncurated numeric RDKit PR specs."""

    def __contains__(self, key):
        return super().__contains__(key) or str(key).isdigit()

    def __missing__(self, key):
        pr = str(key)
        if not pr.isdigit():
            raise KeyError(key)
        spec = {
            "pre_install": [],
            "build": [],
            "test_cmd": [
                f"echo 'rdkit#{pr} not evaluable: no curated spec' && false",
            ],
        }
        self[pr] = spec
        return spec


# rdkit uses Catch2; binary name = first arg to rdkit_catch_test() in CMakeLists.txt
# PR 8957 touches Code/GraphMol/Chirality.cpp + catch_chirality.cpp
# → target: chiralityTestsCatch  (from rdkit_catch_test(chiralityTestsCatch ...))
SPECS_RDKIT = _RDKitSpecs({
    # Explicit placeholders for Issues.xlsx rows without curated runnable
    # harness specs. These keep the pipeline from silently relying on the
    # numeric fallback while preserving non-scorable behavior.
    **{
        pr: {
            "pre_install": [],
            "build": [],
            "test_cmd": [
                f"echo 'rdkit#{pr} not evaluable: no curated spec' && false",
            ],
        }
        for pr in [
            "2083",
            "2377",
            "2548",
            "3015",
            "3050",
            "3098",
            "3196",
            "3354",
            "3412",
            "3615",
            "3729",
            "3749",
            "3930",
            "4303",
            "4414",
            "5063",
            "5232",
            "5468",
            "5570",
            "6021",
            "6193",
            "6199",
            "6231",
            "6250",
            "6506",
            "6686",
            "6948",
            "7116",
            "7137",
            "7152",
            "7384",
            "7426",
            "7571",
            "7975",
            "8179",
            "8192",
            "8210",
            "8211",
            "8217",
            "8264",
            "8266",
            "8269",
            "8289",
            "8294",
            "8367",
            "8385",
            "8493",
            "8515",
            "8542",
            "8550",
            "8587",
            "8588",
            "8652",
            "8680",
            "8734",
            "8767",
            "8795",
            "8808",
            "8824",
            "8874",
            "8907",
            "8974",
            "8999",
            "9002",
            "9012",
            "9022",
            "9119",
            "9120",
            "9125",
            "9228",
            "9300",
            "9302",
            "9325",
            "9332",
            "9348",
            "9355",
        ]
    },
    "2059": _rdkit_cpp_targets_spec("smiTest1", legacy_boost_endian=True),
    "6646": _rdkit_python_wrapper_spec("Code/GraphMol/FMCS/Wrap/testFMCS.py"),
    "8376": _rdkit_python_wrapper_spec(
        "Code/GraphMol/RascalMCES/Wrap/testRascalMCES.py"
    ),
    "8668": _rdkit_cpp_targets_spec("atropisomersCatch", new_boost=True),
    "8968": _rdkit_cpp_ctest_regex_spec(
        "smiTest|Smi|MolOps|molops", new_boost=True
    ),
    "8957": {
        # Ubuntu 22.04 apt ships Boost 1.74; RDKit requires >= 1.81.
        # Refresh apt cache, install software-properties-common, then add Boost PPA.
        "pre_install": [
            "apt-get update -q",
            "apt-get install -y libeigen3-dev pkg-config libfreetype-dev",
            # Add Boost PPA repo file directly (avoids add-apt-repository's launchpadlib SSL dependency)
            "echo 'deb https://ppa.launchpadcontent.net/mhier/libboost-latest/ubuntu jammy main' > /etc/apt/sources.list.d/mhier-libboost-latest.list",
            "apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 31F54F3E108EAD31",
            "apt-get update -q",
            "apt-get install -y libboost1.83-all-dev",
        ],
        "build": [
            "mkdir -p build",
            (
                "cmake -B build -S . "
                "-DCMAKE_BUILD_TYPE=Release "
                "-DRDK_INSTALL_INTREE=ON "
                "-DRDK_BUILD_CPP_TESTS=ON "
                "-DRDK_BUILD_PYTHON_WRAPPERS=OFF "
                "-DRDK_BUILD_INCHI_SUPPORT=OFF "
                "-DRDK_BUILD_CAIRO_SUPPORT=OFF "
                "-DRDK_BUILD_THREADSAFE_SSS=ON"
            ),
            "cmake --build build --parallel $(nproc) --target chiralityTestsCatch",
        ],
        "test_cmd": [
            "RDBASE=$PWD LD_LIBRARY_PATH=$PWD/lib:${LD_LIBRARY_PATH:-} "
            "ctest --test-dir build -V -R chiralityTestsCatch"
        ],
    },
    "9331": _rdkit_cpp_targets_spec(
        "chemdrawCatchTest",
        extra_cmake="-DRDK_BUILD_CHEMDRAW_SUPPORT=ON ",
        new_boost=True,
        chemdraw_include_compat=True,
        defer_target_build=True,
    ),
})

MAP_REPO_VERSION_TO_SPECS_C = {
    "redis/redis": SPECS_REDIS,  # c
    "jqlang/jq": SPECS_JQ,  # c
    "nlohmann/json": SPECS_JSON,  # c++
    "micropython/micropython": SPECS_MICROPYTHON,  # c
    "valkey-io/valkey": SPECS_VALKEY,  # c
    "fmtlib/fmt": SPECS_FMT,  # c++
    "openbabel/openbabel": SPECS_OPENBABEL,  # c++
    "openmm/openmm": SPECS_OPENMM,  # c++
    "openmc-dev/openmc": SPECS_OPENMC,  # c++
    "qgis/QGIS": SPECS_QGIS,  # c++
    "rdkit/rdkit": SPECS_RDKIT,  # c++
}

# Constants - Repository Specific Installation Instructions
MAP_REPO_TO_INSTALL_C = {}
