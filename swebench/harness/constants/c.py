import re
from pathlib import Path

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


def _openmm_python_app_spec(
    test_file: str, test_filter: str, test_class: str | None = None
) -> dict:
    """Run OpenMM Python app tests against the patched pure-Python app package."""
    class_name = test_class or Path(test_file).stem
    fallback_tests = [
        f"wrappers/python/tests/{test_file}::{class_name}::{name}"
        for name in re.findall(r"test[A-Za-z0-9_]+", test_filter)
    ]
    pre_install = [
        "python -m pip install --no-cache-dir --upgrade pip setuptools wheel",
        "python -m pip install --no-cache-dir openmm numpy scipy pytest",
    ]
    if test_file == "TestGromacsTopFile.py":
        pre_install = [
            "apt-get update -q",
            "apt-get install -y --no-install-recommends gromacs",
            *pre_install,
        ]
    return {
        "pre_install": pre_install,
        "build": [
            "OPENMM_SITE=$(python -c 'import openmm, os; print(os.path.dirname(openmm.__file__))') && "
            "SIMTK_SITE=$(python -c 'import simtk.openmm, os; print(os.path.dirname(simtk.openmm.__file__))' 2>/dev/null || "
            "python -c 'import site; print(site.getsitepackages()[0] + \"/simtk/openmm\")') && "
            "mkdir -p \"$SIMTK_SITE\" && "
            "if [ ! -f \"$(dirname \"$SIMTK_SITE\")/__init__.py\" ]; then echo '' > \"$(dirname \"$SIMTK_SITE\")/__init__.py\"; fi && "
            "if [ ! -f \"$SIMTK_SITE/__init__.py\" ]; then echo 'from openmm import *' > \"$SIMTK_SITE/__init__.py\"; fi && "
            "if [ -d /testbed/wrappers/python/openmm/app ]; then cp -r /testbed/wrappers/python/openmm/app \"$OPENMM_SITE/\"; fi && "
            "rm -rf \"$SIMTK_SITE/app\" && "
            "if [ -d /testbed/wrappers/python/openmm/app ]; then "
            "cp -r /testbed/wrappers/python/openmm/app \"$SIMTK_SITE/\"; "
            "elif [ -d /testbed/wrappers/python/simtk/openmm/app ]; then "
            "cp -r /testbed/wrappers/python/simtk/openmm/app \"$SIMTK_SITE/\"; "
            "python -m lib2to3 -w -n \"$SIMTK_SITE/app\" >/dev/null 2>&1 || true; fi && "
            "if [ -d \"$OPENMM_SITE/app/internal\" ] && [ -d \"$SIMTK_SITE/app/internal\" ]; then "
            "cp -n \"$OPENMM_SITE\"/app/internal/compiled* \"$SIMTK_SITE/app/internal/\" 2>/dev/null || true; fi && "
            "for name in vec3 unit; do "
            "if [ -e \"$OPENMM_SITE/$name.py\" ]; then cp \"$OPENMM_SITE/$name.py\" \"$SIMTK_SITE/\"; fi; "
            "if [ -d \"$OPENMM_SITE/$name\" ]; then cp -r \"$OPENMM_SITE/$name\" \"$SIMTK_SITE/\"; fi; done && "
            "if [ ! -e \"$SIMTK_SITE/vec3.py\" ]; then echo 'from openmm.vec3 import *' > \"$SIMTK_SITE/vec3.py\"; fi && "
            "if [ ! -e \"$SIMTK_SITE/unit.py\" ] && [ ! -d \"$SIMTK_SITE/unit\" ]; then echo 'from openmm.unit import *' > \"$SIMTK_SITE/unit.py\"; fi",
        ],
        "test_cmd": [
            f"cd wrappers/python/tests && python -m pytest -xvs {test_file} -k '{test_filter}'",
        ],
        "fail_to_pass": fallback_tests,
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
        "fail_to_pass": list(targets),
    }


_OPENMM_OPENCL_COMPAT_HEADER_COMMAND = (
    "printf '%s\\n' "
    "'#ifndef CL_MAKE_VERSION' "
    "'#define CL_MAKE_VERSION(major, minor, patch) "
    "(((major) << 22) | ((minor) << 12) | (patch))' "
    "'#endif' > /tmp/swebench_opencl_compat.h"
)

_OPENMM_POCL_CPU_COMPAT_COMMAND = (
    "if [ \"$(uname -m)\" = x86_64 ]; then "
    "swebench_cpu=x86-64; "
    "if grep -q 'AuthenticAMD' /proc/cpuinfo && grep -qm1 '\\<avx2\\>' /proc/cpuinfo; "
    "then swebench_cpu=znver2; "
    "elif grep -q 'GenuineIntel' /proc/cpuinfo && grep -qm1 '\\<avx2\\>' /proc/cpuinfo; "
    "then swebench_cpu=haswell; "
    "elif grep -qm1 '\\<sse4_2\\>' /proc/cpuinfo; then swebench_cpu=nehalem; fi; "
    "printf '%s\\n' "
    "'#include <cstddef>' "
    "'namespace llvm {' "
    "'class StringRef {' "
    "'  const char* data_;' "
    "'  std::size_t size_;' "
    "' public:' "
    "'  StringRef(const char* data, std::size_t size) : data_(data), size_(size) {}' "
    "'};' "
    "'namespace sys {' "
    "'StringRef getHostCPUName() { return StringRef(\"'\"$swebench_cpu\"'\", "
    "sizeof(\"'\"$swebench_cpu\"'\")-1); }' "
    "'}' "
    "'}' > /tmp/swebench_pocl_cpu_compat.cpp && "
    "g++ -shared -fPIC -O2 /tmp/swebench_pocl_cpu_compat.cpp "
    "-o /tmp/swebench_pocl_cpu_compat.so; "
    "fi"
)

_OPENMM_POCL_TEST_ENV = (
    "LD_PRELOAD=${LD_PRELOAD:+$LD_PRELOAD:}"
    "/tmp/swebench_pocl_cpu_compat.so "
)


def _openmm_opencl_targets_spec(*targets: str, amoeba: bool = False, gpu: bool = False) -> dict:
    """Build OpenCL tests against POCL so GPU-kernel fixes remain CPU-evaluable.

    Ubuntu 22.04's POCL/LLVM combination reports ``generic`` for CPUs newer
    than its LLVM release (for example Zen 4), but ``generic`` is not a valid
    x86 LLVM CPU name.  A tiny process-local symbol interposer selects the
    closest LLVM-supported CPU baseline without changing OpenMM or the oracle.

    Recent bundled ``opencl.hpp`` revisions also use ``CL_MAKE_VERSION`` while
    Jammy's C OpenCL headers can expose the extension without that macro.  A
    forced compatibility header supplies the Khronos-defined encoding.

    OPEN RISK (documented, not fixed, in this pass -- see the OpenMM GPU
    eval design doc and the final whole-branch review): specs built here
    with ``gpu=True`` request a real GPU be attached to the container
    (docker_specs.run_args.gpu), but this function only installs the POCL
    CPU OpenCL ICD (``pocl-opencl-icd``) -- no NVIDIA/vendor OpenCL ICD
    package -- and every ``test_cmd`` unconditionally LD_PRELOADs the POCL
    CPU-baseline compatibility shim (``_OPENMM_POCL_TEST_ENV`` /
    ``/tmp/swebench_pocl_cpu_compat.so``). With no vendor ICD installed,
    OpenCL's runtime ICD loader will very likely still resolve to POCL
    (CPU) rather than the attached GPU, silently continuing to run these
    "gpu=True" targets on CPU. This is known-deferred pending a real-GPU
    validation run (e.g. PR 2829 is an AMD-specific memory-scale bug that
    POCL CPU emulation likely cannot reproduce, so it needs this verified,
    not assumed). A future engineer running the first real GPU eval should
    explicitly confirm OpenCL targets are actually binding to the GPU
    (e.g. via ``clinfo`` inside the container, or by checking which
    platform/device the test bound to at runtime, possibly requiring
    ``OPENCL_VENDOR_PATH`` pinning) rather than assuming ``gpu=True`` alone
    guarantees it.
    """
    cmake_targets = " ".join(targets)
    spec = {
        "pre_install": [
            "apt-get update -q",
            "apt-get install -y --no-install-recommends "
            "cmake g++ make libgl1-mesa-dev ocl-icd-opencl-dev pocl-opencl-icd",
        ],
        "build_after_test_patch": [
            _OPENMM_OPENCL_COMPAT_HEADER_COMMAND,
            _OPENMM_POCL_CPU_COMPAT_COMMAND,
            "cmake -B build -S . "
            "-DCMAKE_BUILD_TYPE=Release "
            "-DCMAKE_CXX_FLAGS='-include /tmp/swebench_opencl_compat.h' "
            "-DOPENMM_BUILD_CUDA_LIB=OFF "
            "-DOPENMM_BUILD_OPENCL_LIB=ON "
            "-DOPENMM_BUILD_HIP_LIB=OFF "
            "-DOPENMM_BUILD_PYTHON_WRAPPERS=OFF "
            "-DOPENMM_BUILD_C_AND_FORTRAN_WRAPPERS=OFF "
            + ("-DOPENMM_BUILD_AMOEBA_PLUGIN=ON " if amoeba else "")
            + "-DOPENMM_BUILD_EXAMPLES=OFF",
            f"cmake --build build --parallel $(nproc) --target {cmake_targets}",
        ],
        "test_cmd": [
            _OPENMM_POCL_TEST_ENV
            + "LD_LIBRARY_PATH=$PWD/build:${LD_LIBRARY_PATH:-} "
            "OPENMM_PLUGIN_DIR=$PWD/build "
            f"./build/{target}"
            for target in targets
        ],
        "fail_to_pass": list(targets),
        "test_generation_use_spec_cmd": True,
    }
    if gpu:
        spec["docker_specs"] = {"run_args": {"gpu": True}}
    return spec


_OPENMM_CUDA_TOOLKIT_INSTALL_COMMAND = (
    "apt-get install -y --no-install-recommends wget gnupg ca-certificates && "
    "wget -q https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb "
    "-O /tmp/cuda-keyring_1.1-1_all.deb && "
    "dpkg -i /tmp/cuda-keyring_1.1-1_all.deb && "
    "apt-get update -q && "
    "apt-get install -y --no-install-recommends cuda-nvcc-12-4 cuda-cudart-dev-12-4"
)


def _openmm_cuda_targets_spec(*targets: str, plugin: str | None = None) -> dict:
    """Build OpenMM with the CUDA platform and run selected C++ test executables
    against a real GPU device (attached at container-run time via
    docker_specs.run_args.gpu -- see docker_build.py's _create_eval_container).
    """
    cmake_targets = " ".join(targets)
    return {
        "pre_install": [
            "apt-get update -q",
            "apt-get install -y --no-install-recommends cmake g++ make",
            _OPENMM_CUDA_TOOLKIT_INSTALL_COMMAND,
        ],
        "build_after_test_patch": [
            "export PATH=/usr/local/cuda/bin:$PATH && "
            "cmake -B build -S . "
            "-DCMAKE_BUILD_TYPE=Release "
            "-DOPENMM_BUILD_CUDA_LIB=ON "
            "-DOPENMM_BUILD_OPENCL_LIB=OFF "
            "-DOPENMM_BUILD_HIP_LIB=OFF "
            "-DOPENMM_BUILD_PYTHON_WRAPPERS=OFF "
            "-DOPENMM_BUILD_C_AND_FORTRAN_WRAPPERS=OFF "
            + (f"-DOPENMM_BUILD_{plugin.upper()}_PLUGIN=ON " if plugin else "")
            + "-DOPENMM_BUILD_EXAMPLES=OFF",
            f"cmake --build build --parallel $(nproc) --target {cmake_targets}",
        ],
        "test_cmd": [
            f"LD_LIBRARY_PATH=$PWD/build:${{LD_LIBRARY_PATH:-}} "
            f"OPENMM_PLUGIN_DIR=$PWD/build "
            f"./build/{target}"
            for target in targets
        ],
        "fail_to_pass": list(targets),
        "test_generation_use_spec_cmd": True,
        "docker_specs": {"run_args": {"gpu": True}},
    }


def _openmm_gpu_non_evaluable_spec(reason: str) -> dict:
    """Exclude a GPU-only regression when no faithful GPU runtime is available."""
    return {
        "pre_install": [],
        "build": [],
        "test_cmd": [f"echo 'not evaluable: {reason}' && false"],
        "fail_to_pass": ["scientific_spec::gpu_runtime_required"],
        "test_generation_use_spec_cmd": True,
    }


def _openmm_source_check_spec(name: str, condition: str) -> dict:
    """Expose a source/data/documentation-only correction as a parsed test."""
    nodeid = f"scientific_spec::{name}"
    return {
        "pre_install": [],
        "build": [],
        "test_cmd": [
            f"if {condition}; then echo '{nodeid} PASSED'; "
            f"else echo '{nodeid} FAILED'; false; fi"
        ],
        "fail_to_pass": [nodeid],
        # In bug-reproduction mode the generated pytest must supply the oracle;
        # do not let this fixed source check resolve an empty/irrelevant patch.
        "test_generation_requires_generated_pytest": True,
    }


def _openmm_native_python_spec(
    test_file: str, test_filter: str, *, amoeba: bool = False
) -> dict:
    """Build native OpenMM Python wrappers for generated API tests."""
    return {
        "pre_install": [
            "apt-get update -q",
            "apt-get install -y --no-install-recommends cmake g++ make swig doxygen python3-dev",
            "python -m pip install --no-cache-dir 'numpy<2' cython pytest setuptools wheel",
        ],
        "build_after_test_patch": [
            "cmake -B build -S . "
            "-DCMAKE_BUILD_TYPE=Release "
            "-DOPENMM_BUILD_CUDA_LIB=OFF "
            "-DOPENMM_BUILD_OPENCL_LIB=OFF "
            "-DOPENMM_BUILD_HIP_LIB=OFF "
            "-DOPENMM_BUILD_PYTHON_WRAPPERS=ON "
            "-DOPENMM_BUILD_C_AND_FORTRAN_WRAPPERS=OFF "
            f"{'-DOPENMM_BUILD_AMOEBA_PLUGIN=ON ' if amoeba else ''}"
            "-DBUILD_TESTING=OFF "
            "-DOPENMM_BUILD_EXAMPLES=OFF",
            # OpenMM 7.0's generated SWIG input contains a prose line beginning
            # with '# Look'. Modern SWIG treats it as an unknown directive.
            # CMake copies this file fresh from the source tree
            # (wrappers/python/src/swig_doxygen/swig_lib/python/extend.i) into
            # build/python/src/swig_doxygen/swig_lib/python/extend.i on every
            # build, so the source copy must be patched -- sed'ing only the
            # build-tree copy is silently overwritten before SWIG runs.
            # The offending line is indented (it sits inside a Python method
            # body), so the pattern must allow leading whitespace -- an
            # anchor of '^# Look' misses it and silently no-ops.
            "if [ -f wrappers/python/src/swig_doxygen/swig_lib/python/extend.i ]; then "
            "sed -i 's/^\\([ \\t]*\\)# Look/\\1\\/\\/ Look/' "
            "wrappers/python/src/swig_doxygen/swig_lib/python/extend.i; fi",
            # PythonInstall links against the configured install prefix.  Some
            # OpenMM versions incorrectly return success when setup.py linking
            # failed, so install the native libraries first and verify import.
            "cmake --build build --parallel $(nproc) --target install",
            # Pre-7.0 OpenMM revisions ship only the legacy `simtk.openmm`
            # package -- there is no top-level `openmm` module to import.
            # Require simtk.openmm always, and the modern `openmm` package
            # only when it actually exists on disk.
            "cmake --build build --parallel $(nproc) --target PythonInstall && "
            "python -c 'import simtk.openmm; "
            "import importlib.util as u, os; "
            "assert not os.path.isdir(\"wrappers/python/openmm\") "
            "or u.find_spec(\"openmm\") is not None'",
        ],
        "test_cmd": [
            "LD_LIBRARY_PATH=$PWD/build:${LD_LIBRARY_PATH:-} "
            "OPENMM_PLUGIN_DIR=$PWD/build "
            f"python -m pytest -xvs wrappers/python/tests/{test_file} -k '{test_filter}'"
        ],
        "fail_to_pass": [f"wrappers/python/tests/{test_file}"],
        "test_generation_use_spec_cmd": True,
    }


def _openmm_python_unit_spec(test_filter: str | list[str]) -> dict:
    """Run OpenMM Python unit tests against patched simtk.unit modules."""
    if isinstance(test_filter, list):
        test_names = test_filter
    else:
        test_names = re.findall(r"test[A-Za-z0-9_]+|test_[A-Za-z0-9_]+", test_filter)
    fallback_tests = [
        f"wrappers/python/tests/TestAPIUnits.py::TestAPIUnits::{name}"
        for name in test_names
    ]
    test_selector = " ".join(
        f"TestAPIUnits.py::TestAPIUnits::{name}" for name in test_names
    ) or "TestAPIUnits.py"
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
            f"cd wrappers/python/tests && python -m pytest -xvs {test_selector}",
        ],
        "fail_to_pass": fallback_tests,
    }


_RDKIT_PRE_INSTALL = [
    "apt-get update -q",
    "apt-get install -y --no-install-recommends "
    "cmake g++ make libboost-all-dev libeigen3-dev pkg-config libfreetype-dev",
]

_RDKIT_APT_RETRY = (
    "apt_retry() { local attempt; for attempt in 1 2 3 4 5; do "
    "apt-get -o Acquire::Retries=5 \"$@\" && return 0; "
    "sleep $((attempt * 5)); done; return 1; }"
)

_RDKIT_BOOST_183_KEY_FINGERPRINT = "77520E7EB41800A93E3E0D9431F54F3E108EAD31"

_RDKIT_BOOST_183_PRE_INSTALL = [
    _RDKIT_APT_RETRY,
    "apt_retry update -q",
    "apt_retry install -y --no-install-recommends ca-certificates gnupg wget",
    "wget --tries=5 --timeout=30 --waitretry=5 --retry-connrefused "
    "--retry-on-http-error=429,500,502,503,504 -O /tmp/mhier-libboost-latest.asc "
    f"'https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x{_RDKIT_BOOST_183_KEY_FINGERPRINT}'",
    "gpg --batch --show-keys --with-colons /tmp/mhier-libboost-latest.asc | "
    f"grep -q 'fpr:::::::::{_RDKIT_BOOST_183_KEY_FINGERPRINT}:'",
    "gpg --batch --yes --dearmor "
    "--output /usr/share/keyrings/mhier-libboost-latest.gpg /tmp/mhier-libboost-latest.asc",
    "echo 'deb [signed-by=/usr/share/keyrings/mhier-libboost-latest.gpg] "
    "https://ppa.launchpadcontent.net/mhier/libboost-latest/ubuntu jammy main' "
    "> /etc/apt/sources.list.d/mhier-libboost-latest.list",
    "apt_retry update -q",
    "apt_retry install -y --no-install-recommends "
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
    "HEADER=$(find External/ChemDraw -name chemdraw.h | head -n 1) && "
    "if [ -n \"$HEADER\" ]; then "
    "HEADER_DIR=$(dirname \"$HEADER\") && "
    "REL=${HEADER_DIR#External/ChemDraw/} && "
    "if [ \"$REL\" = \"$HEADER_DIR\" ]; then REL=.; fi && "
    "if [ ! -e External/ChemDraw/ChemDraw ]; then "
    "ln -s \"$REL\" External/ChemDraw/ChemDraw; fi; "
    "if [ -d External/ChemDraw/chemdraw ] && [ ! -e External/ChemDraw/chemdraw/ChemDraw ]; then "
    "if [ \"$REL\" = . ]; then ln -s .. External/ChemDraw/chemdraw/ChemDraw; "
    "else ln -s \"../$REL\" External/ChemDraw/chemdraw/ChemDraw; fi; fi; "
    "fi"
)

_RDKIT_BASE_CMAKE_FLAGS = (
    "-DCMAKE_BUILD_TYPE=Release "
    "-DRDK_INSTALL_INTREE=ON "
    "-DBoost_NO_BOOST_CMAKE=ON "
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

_RDKIT_LEGACY_CATCH_CMAKE = "-DCMAKE_CXX_FLAGS=-DCATCH_CONFIG_NO_POSIX_SIGNALS "


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
            f"ctest --test-dir build -V -R '^{re.escape(target)}$'"
            for target in targets
        ],
        "fail_to_pass": list(targets),
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
    spec["fail_to_pass"] = [test_regex]
    return spec


def _rdkit_python_wrapper_spec(
    test_path: str | tuple[str, ...],
    new_boost: bool = False,
    extra_cmake: str = "",
    legacy_boost_endian: bool = False,
    extra_apt_packages: tuple[str, ...] = (),
) -> dict:
    """Build RDKit in-tree with Python wrappers and run a focused Python test."""
    test_paths = (test_path,) if isinstance(test_path, str) else test_path
    spec = _rdkit_cpp_targets_spec(
        extra_cmake=extra_cmake,
        new_boost=new_boost,
        legacy_boost_endian=legacy_boost_endian,
    )
    spec["build"][1] = spec["build"][1].replace(
        "-DRDK_BUILD_CPP_TESTS=ON ",
        "-DRDK_BUILD_CPP_TESTS=OFF ",
    )
    spec["build"][1] = spec["build"][1].replace(
        "-DRDK_BUILD_PYTHON_WRAPPERS=OFF ",
        "-DRDK_BUILD_PYTHON_WRAPPERS=ON ",
    )
    spec["pre_install"].append("apt-get install -y --no-install-recommends python3-dev python3-numpy")
    if extra_apt_packages:
        spec["pre_install"].append(
            "apt-get install -y --no-install-recommends "
            + " ".join(extra_apt_packages)
        )
    spec["build"][-1] = "cmake --build build --parallel $(nproc)"
    runtime = "RDBASE=$PWD PYTHONPATH=$PWD LD_LIBRARY_PATH=$PWD/lib:${LD_LIBRARY_PATH:-} "
    spec["test_cmd"] = [
        ("cp -a build/rdkit/. rdkit/ && " if index == 0 else "")
        + runtime
        + f"python3 {path}"
        for index, path in enumerate(test_paths)
    ]
    spec["fail_to_pass"] = list(test_paths)
    return spec


def _rdkit_mixed_tests_spec(
    cpp_targets: tuple[str, ...],
    python_tests: tuple[str, ...],
    new_boost: bool = False,
    extra_cmake: str = "",
    legacy_boost_endian: bool = False,
) -> dict:
    """Build and run generated RDKit tests spanning C++ and Python wrappers."""
    spec = _rdkit_cpp_targets_spec(
        *cpp_targets,
        extra_cmake=extra_cmake,
        new_boost=new_boost,
        legacy_boost_endian=legacy_boost_endian,
    )
    spec["build"][1] = spec["build"][1].replace(
        "-DRDK_BUILD_PYTHON_WRAPPERS=OFF ",
        "-DRDK_BUILD_PYTHON_WRAPPERS=ON ",
    )
    spec["pre_install"].append(
        "apt-get install -y --no-install-recommends python3-dev python3-numpy"
    )
    # A full build is required to create both wrapper modules and C++ targets.
    spec["build"][-1] = "cmake --build build --parallel $(nproc)"
    runtime = "RDBASE=$PWD PYTHONPATH=$PWD LD_LIBRARY_PATH=$PWD/lib:${LD_LIBRARY_PATH:-} "
    spec["test_cmd"].extend(
        [
            ("cp -a build/rdkit/. rdkit/ && " if index == 0 else "")
            + runtime
            + f"python3 {path}"
            for index, path in enumerate(python_tests)
        ]
    )
    spec["fail_to_pass"] = [*cpp_targets, *python_tests]
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
            "pre_install": [
                "python -m pip install --no-cache-dir --upgrade pip setuptools wheel",
                "python -m pip install --no-cache-dir openmm numpy scipy pytest",
            ],
            "build": [],
            "test_cmd": [
                f"echo 'openmm#{pr} has no curated generated-test target' && false",
            ],
        }
        self[pr] = spec
        return spec


SPECS_OPENMM = _OpenMMSpecs({
    # Current Scientific Issues sheet.  PRs without authored tests use the
    # closest registered subsystem suite; source-only fixes get a narrow
    # parsed check so they do not fall through to the non-evaluable placeholder.
    "4138": _openmm_source_check_spec(
        "langevin_documentation_variance",
        "grep -Fq 'normal distribution with mean zero and unit variance' "
        "docs-source/usersguide/theory/04_integrators.rst",
    ),
    "4618": _openmm_opencl_targets_spec(
        "TestOpenCLMonteCarloFlexibleBarostat", gpu=True
    ),
    "2318": _openmm_opencl_targets_spec("TestOpenCLNonbondedForce", gpu=True),
    "5219": _openmm_source_check_spec(
        "cm_motion_remover_documentation",
        "grep -Fq 'not a rigorous constraint' "
        "docs-source/usersguide/theory/02_standard_forces.rst",
    ),
    "2322": _openmm_opencl_targets_spec("TestOpenCLCustomCentroidBondForce", gpu=True),
    "2257": _openmm_opencl_targets_spec("TestOpenCLNonbondedForce", gpu=True),
    "4440": _openmm_cpp_targets_spec(
        "TestReferenceLangevinIntegrator",
        "TestReferenceVariableLangevinIntegrator",
    ),
    "1100": _openmm_cpp_targets_spec("TestReferenceSettle"),
    "3151": _openmm_python_app_spec(
        "TestModeller.py", "test_addSolventPeriodicBox"
    ),
    "5302": _openmm_cuda_targets_spec(
        "TestCudaAmoebaMultipoleForce", plugin="amoeba"
    ),
    "4760": _openmm_source_check_spec(
        "absinth_force_field_removed",
        "test ! -e wrappers/python/openmm/app/data/absinth.xml "
        "-a ! -e wrappers/python/simtk/openmm/app/data/absinth.xml",
    ),
    "4161": _openmm_python_app_spec(
        "TestForceField.py", "test_IgnoreExternalBonds"
    ),
    "3851": _openmm_python_app_spec("TestForceField.py", "test_CharmmPolar"),
    "3311": _openmm_python_app_spec(
        "TestForceField.py",
        "test_Amoeba18BPTI or test_Amoeba18Nucleic",
        test_class="AmoebaTestForceField",
    ),
    "3210": _openmm_python_app_spec("TestCharmmFiles.py", "test_NBFIX"),
    "2897": _openmm_source_check_spec(
        "benchmark_hydrogen_mass",
        "grep -Fq 'hydrogenMass = 1.5*unit.amu' examples/benchmark.py",
    ),
    "3872": _openmm_opencl_targets_spec("TestOpenCLAmoebaVdwForce", amoeba=True),
    "3659": _openmm_python_app_spec(
        "TestPdbxFile.py", "testChemCompBonds or testMultiChain"
    ),
    "2802": _openmm_python_unit_spec(
        ["testCustomGBForce", "testCustomNonbondedForce"]
    ),
    "3260": _openmm_cpp_targets_spec(
        "TestReferenceMonteCarloAnisotropicBarostat"
    ),
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
        "fail_to_pass": [
            "wrappers/python/tests/TestAmberPrmtopFile.py::TestAmberPrmtopFile::testFlexibleConstraints"
        ],
    },
    "4989": _openmm_python_app_spec(
        "TestForceField.py", "test_CharmmLoad or test_CharmmVersionMismatchCheck"
    ),
    "4881": _openmm_cpp_targets_spec(
        "TestReferenceMonteCarloAnisotropicBarostat",
        "TestReferenceMonteCarloBarostat",
        "TestReferenceMonteCarloFlexibleBarostat",
        "TestReferenceMonteCarloMembraneBarostat",
    ),
    "4870": _openmm_native_python_spec(
        "TestAPIUnits.py", "testConstantPotentialForce"
    ),
    # PR #5137 only modifies OpenCL FFT coverage. Keep a concrete CPU-buildable
    # spec so test-generation mode can apply/diagnose generated patches, but do
    # not pretend a GPU/OpenCL runtime is available.
    "5137": {
        "pre_install": [
            "apt-get update -q",
            "apt-get install -y --no-install-recommends "
            "cmake g++ make ocl-icd-opencl-dev pocl-opencl-icd",
        ],
        "build_after_test_patch": [
            _OPENMM_OPENCL_COMPAT_HEADER_COMMAND,
            _OPENMM_POCL_CPU_COMPAT_COMMAND,
            "cmake -B build -S . "
            "-DCMAKE_BUILD_TYPE=Release "
            "-DCMAKE_CXX_FLAGS='-include /tmp/swebench_opencl_compat.h' "
            "-DOPENMM_BUILD_CUDA_LIB=OFF "
            "-DOPENMM_BUILD_OPENCL_LIB=ON "
            "-DOPENMM_BUILD_HIP_LIB=OFF "
            "-DOPENMM_BUILD_PYTHON_WRAPPERS=OFF "
            "-DOPENMM_BUILD_C_AND_FORTRAN_WRAPPERS=OFF",
            "cmake --build build --parallel $(nproc) --target TestOpenCLFFT",
        ],
        "test_cmd": [
            _OPENMM_POCL_TEST_ENV
            + "LD_LIBRARY_PATH=$PWD/build:$PWD/build/platforms/opencl:${LD_LIBRARY_PATH:-} "
            "OPENMM_PLUGIN_DIR=$PWD/build/platforms/opencl "
            "./build/TestOpenCLFFT",
        ],
    },
    # ── Generated-test fallback specs for issue rows without mined F2P ───────
    "1495": _openmm_cpp_targets_spec("TestReferenceCustomExternalForce", "TestParser"),
    "1802": _openmm_cpp_targets_spec("TestReferenceEwald"),
    "2241": _openmm_cpp_targets_spec("TestReferenceCustomIntegrator"),
    "3286": _openmm_cpp_targets_spec(
        "TestReferenceGBSAOBCForce",
        "TestReferenceHarmonicAngleForce",
        "TestReferenceHarmonicBondForce",
        "TestReferenceNonbondedForce",
        "TestReferencePeriodicTorsionForce",
    ),
    "4732": _openmm_cpp_targets_spec("TestReferenceNonbondedForce"),
    "5031": _openmm_cpp_targets_spec("TestReferenceCustomCentroidBondForce"),
    "5198": _openmm_cpp_targets_spec("TestCpuLocalEnergyMinimizer"),
    "5322": _openmm_cpp_targets_spec("TestReferenceMonteCarloFlexibleBarostat"),
    # ── Issues_No_Tests_split.xlsx: CPU/Reference regression families ──────
    # These PRs intentionally contain no authored tests.  Build and run the
    # narrowest registered CPU/Reference suite for the production subsystem
    # changed by each PR.
    **{
        pr: _openmm_cpp_targets_spec(*targets)
        for pr, targets in {
            "4294": ("TestReferenceEwald",),
            "3326": (
                "TestReferenceHarmonicAngleForce",
                "TestReferenceNonbondedForce",
            ),
            "2781": ("TestCpuNonbondedForce",),
            "2644": ("TestReferenceCMAPTorsionForce",),
            "1592": ("TestCpuGBSAOBCForce",),
            "3280": ("TestReferenceCustomNonbondedForce",),
            "5242": ("TestCpuLocalEnergyMinimizer",),
            "920": ("TestCpuNonbondedForce",),
            "3834": ("TestParser",),
            "3574": ("TestReferenceLangevinMiddleIntegrator",),
            "3321": ("TestReferenceNonbondedForce",),
            "3240": ("TestReferenceCustomExternalForce",),
            "2544": ("TestCpuNonbondedForce",),
            "2328": ("TestCpuNonbondedForce",),
            "631": ("TestCpuGBSAOBCForce",),
        }.items()
    },
    # ── Issues_No_Tests_split.xlsx: Common/OpenCL regression families ──────
    # These specs pass gpu=True, requesting a real GPU device be attached to
    # the evaluation container (see docker_specs.run_args.gpu). POCL
    # (pocl-opencl-icd) remains installed here as part of the OpenCL
    # toolchain/build dependencies -- it is not what is meant to service
    # these kernels at runtime once a GPU is attached. See the open risk
    # recorded at _openmm_opencl_targets_spec above: since no vendor OpenCL
    # ICD is installed and the POCL CPU-baseline compatibility shim
    # (_OPENMM_POCL_TEST_ENV) stays unconditionally active in every
    # test_cmd, the OpenCL ICD loader may still silently resolve to POCL
    # (CPU) instead of the attached GPU even though gpu=True requests one.
    **{
        pr: _openmm_opencl_targets_spec(*targets, amoeba=amoeba, gpu=True)
        for pr, targets, amoeba in [
            ("2819", ("TestOpenCLNonbondedForce",), False),
            ("5069", ("TestOpenCLNonbondedForce",), False),
            ("1679", ("TestOpenCLCustomIntegrator",), False),
            ("1382", ("TestOpenCLCustomExternalForce",), False),
            ("5346", ("TestOpenCLCustomCVForce",), False),
            ("5117", ("TestOpenCLCustomBondForce",), False),
            ("3460", ("TestOpenCLNonbondedForce",), False),
            (
                "3428",
                ("TestOpenCLNonbondedForce", "TestOpenCLAmoebaMultipoleForce"),
                True,
            ),
            ("1924", ("TestOpenCLNonbondedForce",), False),
            ("4079", ("TestOpenCLRpmd",), False),
            ("4249", ("TestOpenCLCustomNonbondedForce",), False),
            ("4148", ("TestOpenCLCustomNonbondedForce",), False),
            ("4119", ("TestOpenCLMonteCarloBarostat",), False),
            ("4090", ("TestOpenCLRpmd",), False),
            ("3771", ("TestOpenCLNonbondedForce",), False),
            ("3057", ("TestOpenCLNonbondedForce",), False),
            ("1682", ("TestOpenCLNonbondedForce",), False),
        ]
    },
    # ── Issues_No_Tests_split.xlsx: pure-Python app regression families ────
    **{
        pr: _openmm_python_app_spec(test_file, test_filter)
        for pr, test_file, test_filter in [
            ("1540", "TestForceField.py", "test_ImplicitSolvent"),
            ("1932", "TestTopology.py", "test_getters"),
            ("3630", "TestGromacsTopFile.py", "test_NonbondedMethod"),
            ("4293", "TestModeller.py", "testNestedVirtualSites"),
            ("4748", "TestModeller.py", "test_addExtraParticles"),
            ("5149", "TestPdbxFile.py", "test_FormatConversion"),
            ("5213", "TestPdbFile.py", "test_WriteFile"),
            ("5221", "TestModeller.py", "test_addHydrogensPdb3"),
            ("5359", "TestStateDataReporter.py", "testAppend"),
            ("4986", "TestForceField.py", "test_CustomNonbondedGenerator"),
            ("4279", "TestForceField.py", "test_residueMatcher"),
            ("4104", "TestModeller.py", "test_addSolventIons"),
            ("3442", "TestForceField.py", "test_Forces"),
            ("3241", "TestModeller.py", "test_addSolventPeriodicBox"),
            ("3198", "TestGromacsTopFile.py", "test_NonbondedMethod"),
            ("3041", "TestAmberPrmtopFile.py", "test_NonbondedMethod"),
            ("2639", "TestStateDataReporter.py", "testAppend"),
            ("2575", "TestPdbxFile.py", "test_FormatConversion"),
            ("2563", "TestPdbxFile.py", "test_FormatConversion"),
            ("2429", "TestCharmmFiles.py", "test_Drude"),
            ("2363", "TestForceField.py", "test_ImplicitSolventParameters"),
            ("1957", "TestPdbFile.py", "test_Triclinic"),
            ("1363", "TestForceField.py", "test_ImpropersOrdering"),
            ("1250", "TestForceField.py", "test_RigidWaterAndConstraints"),
        ]
    },
    # PR 3923 changes the SWIG exposure of AmoebaVdwForce parameters, so the
    # patched native wrappers (rather than a pip app overlay) must be built.
    "3923": _openmm_native_python_spec(
        "TestAPIUnits.py", "testAmoebaVdwForce", amoeba=True
    ),
    # These regressions depend on CUDA/OpenCL kernel behavior; they now run
    # against the real GPU devices available on the eval host instead of the
    # POCL CPU-emulation path used for other OpenCL targets.
    "1640": _openmm_cuda_targets_spec(
        "TestCudaAmoebaMultipoleForce", plugin="amoeba"
    ),
    "2152": _openmm_cuda_targets_spec(
        "TestCudaAmoebaMultipoleForce", plugin="amoeba"
    ),
    "2255": _openmm_gpu_non_evaluable_spec(
        "GPU minimizer performance regression requires a supported GPU runtime"
    ),
    "2829": _openmm_opencl_targets_spec("TestOpenCLNonbondedForce", gpu=True),
    "4364": _openmm_cuda_targets_spec("TestCudaCustomNonbondedForce"),
    # ── Exact Python wrapper tests ───────────────────────────────────────────
    # These PRs add or modify focused Python app tests. Use pip's compiled
    # OpenMM package for native libraries, then overlay the patched pure-Python
    # app package from /testbed before running the exact pytest selector.
    **{
        pr: (
            _openmm_native_python_spec(test_file, test_filter, amoeba=True)
            if pr == "826"
            else _openmm_python_app_spec(test_file, test_filter)
        )
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
            ("4188", "TestGromacsTopFile.py", "test_Vsite3"),
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

# Generated patch 1837 touches both Python and native tests.  The gold patch
# changes native kernels, so force the concrete in-tree C++ command instead of
# the pip-backed dynamic pytest path.
SPECS_OPENMM["1837"]["test_generation_use_spec_cmd"] = True

SPECS_OPENMC = {
    # Add entries here: "<PR_NUMBER>": {"build": [...], "test_cmd": [...]}
    # Build pattern:
    #   "mkdir -p build",
    #   "cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug",
    #   "cmake --build build --parallel $(nproc)",
    # Test pattern:
    #   "cd tests && python -m pytest -v <test_file>"
}

_QGIS_316_BUILD_IMAGE = (
    "qgis/qgis3-build-deps@"
    "sha256:2bb32b415971fcc63124eb5993c48777cf024f1478d6e414c601a1d8afb9c3eb"
)
_QGIS_QT6_BUILD_IMAGE = (
    "qgis/qgis3-build-deps-ubuntu-qt6@"
    "sha256:81b4d845b8704c068e2cc94238d45fee4fcd8d603744d635edea8a2966202005"
)
_QGIS_BUILD_JOBS = 8


def _qgis_spec(
    targets: tuple[str, ...],
    *,
    ctest_regex: str,
    base_image: str,
    bindings: bool = False,
    grass: bool = False,
    postgres: bool = False,
    python_test_path: str | None = None,
) -> dict:
    """Build and run concrete QGIS CTest targets in QGIS's build-deps image."""
    cmake_flags = [
        "-GNinja",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DENABLE_TESTS=ON",
        "-DWITH_ANALYSIS=ON",
        "-DWITH_GUI=ON",
        "-DWITH_DESKTOP=OFF",
        "-DWITH_SERVER=OFF",
        "-DWITH_3D=OFF",
        "-DWITH_QUICK=OFF",
        "-DWITH_PDAL=OFF",
        "-DWITH_ORACLE=OFF",
        "-DWITH_HANA=OFF",
        "-DWITH_MSSQL=OFF",
        "-DWITH_QSPATIALITE=OFF",
        f"-DWITH_BINDINGS={'ON' if bindings else 'OFF'}",
        f"-DWITH_GRASS7={'ON' if grass else 'OFF'}",
        "-DWITH_GRASS8=OFF",
    ]
    if grass:
        cmake_flags.append("-DGRASS_PREFIX7=$(grass --config path)")
    build_target = (
        f"cmake --build build --parallel {_QGIS_BUILD_JOBS}"
        if bindings
        else f"cmake --build build --parallel {_QGIS_BUILD_JOBS} --target "
        + " ".join(targets)
    )
    spec = {
        "docker_specs": {"c_base_image": base_image},
        "pre_install": [],
        "build": [
            "cmake -B build -S . " + " ".join(cmake_flags),
            build_target,
        ],
        "test_cmd": [
            "cd build && QT_QPA_PLATFORM=offscreen xvfb-run -a "
            f"ctest -V --output-on-failure -R '{ctest_regex}'"
        ],
        "fail_to_pass": list(targets),
        "test_generation_use_spec_cmd": True,
    }
    if postgres:
        spec["pre_install"] = [
            "apt-get update -q",
            "apt-get install -y --no-install-recommends postgresql postgresql-contrib postgis",
        ]
        spec["eval_commands"] = [
            "service postgresql start",
            "su postgres -c \"psql -tc \\\"SELECT 1 FROM pg_roles WHERE rolname='docker'\\\" | grep -q 1 || createuser -s docker\"",
            "su postgres -c \"psql -c \\\"ALTER ROLE docker PASSWORD 'docker'\\\"\"",
            "su postgres -c \"psql -tc \\\"SELECT 1 FROM pg_database WHERE datname='qgis_test'\\\" | grep -q 1 || createdb -O docker qgis_test\"",
            "printf '[qgis_test]\\nhost=localhost\\nport=5432\\ndbname=qgis_test\\nuser=docker\\npassword=docker\\n' > /root/.pg_service.conf",
            "PGHOST=localhost PGUSER=docker PGPASSWORD=docker PGDATABASE=qgis_test tests/testdata/provider/testdata_pg.sh",
        ]
    if python_test_path:
        spec["test_generation_python_test"] = python_test_path
    return spec


SPECS_QGIS = {
    # Scientific Issues sheet: focused suites for the affected raster paths.
    "60631": _qgis_spec(
        ("test_analysis_processingalgspt1",),
        ctest_regex="^test_analysis_processingalgspt1$",
        base_image=_QGIS_QT6_BUILD_IMAGE,
    ),
    "35852": _qgis_spec(
        ("PyQgsRasterColorRampShader",),
        ctest_regex="^PyQgsRasterColorRampShader$",
        base_image=_QGIS_316_BUILD_IMAGE,
        bindings=True,
    ),
    "40837": _qgis_spec(
        ("ProcessingGrass7AlgorithmsVectorTest",),
        ctest_regex="^ProcessingGrass7AlgorithmsVectorTest$",
        base_image=_QGIS_316_BUILD_IMAGE,
        bindings=True,
        grass=True,
        python_test_path=(
            "python/plugins/processing/tests/Grass7AlgorithmsVectorTest.py"
        ),
    ),
    "63639": _qgis_spec(
        (
            "test_analysis_processingcheckgeometry",
            "test_geometry_checker_geometrychecks",
        ),
        ctest_regex=(
            "^(test_analysis_processingcheckgeometry|"
            "test_geometry_checker_geometrychecks)$"
        ),
        base_image=_QGIS_QT6_BUILD_IMAGE,
    ),
    "66353": _qgis_spec(
        ("PyQgsPostgresRasterProvider",),
        ctest_regex="^PyQgsPostgresRasterProvider$",
        base_image=_QGIS_QT6_BUILD_IMAGE,
        bindings=True,
        postgres=True,
    ),
    # Issues_No_Tests_v2.xlsx additions: native:concavehull / native:xyztiles
    # are both exercised by python/plugins/processing/tests/QgisAlgorithmsTest4.py
    # (testdata/qgis_algorithm_tests4.yaml), registered as CTest target
    # ProcessingQgisAlgorithmsTestPt4.
    "64781": _qgis_spec(
        ("ProcessingQgisAlgorithmsTestPt4",),
        ctest_regex="^ProcessingQgisAlgorithmsTestPt4$",
        base_image=_QGIS_QT6_BUILD_IMAGE,
        bindings=True,
    ),
    "66606": _qgis_spec(
        ("ProcessingQgisAlgorithmsTestPt4",),
        ctest_regex="^ProcessingQgisAlgorithmsTestPt4$",
        base_image=_QGIS_QT6_BUILD_IMAGE,
        bindings=True,
    ),
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
    # Current Scientific Issues sheet: exact Catch2/CTest targets touched by
    # each closing PR.  PR 8957 is defined separately below.
    "9141": _rdkit_cpp_targets_spec("fileParsersCatchTest", new_boost=True),
    "7183": _rdkit_cpp_targets_spec(
        "molfileStereoCatchTest", "chiralityTestsCatch"
    ),
    "8904": _rdkit_cpp_targets_spec(
        "graphmolTestsCatch", "fileParsersCatchTest", new_boost=True
    ),
    "8736": _rdkit_cpp_targets_spec("chiralityTestsCatch", new_boost=True),
    "8247": _rdkit_cpp_targets_spec("testRascalMCES", new_boost=True),
    "8301": _rdkit_cpp_targets_spec(
        "molopsTestsCatch", "fileParsersCatchTest", new_boost=True
    ),
    "8257": _rdkit_cpp_targets_spec("graphmolAdjustQueryCatch", new_boost=True),
    "3018": _rdkit_cpp_targets_spec(
        "graphmolTestsCatch", extra_cmake=_RDKIT_LEGACY_CATCH_CMAKE
    ),
    "7990": _rdkit_cpp_targets_spec("deprotectTest", new_boost=True),
    "7347": _rdkit_cpp_targets_spec("chiralityTestsCatch"),
    "5560": _rdkit_cpp_targets_spec("chiralityTestsCatch"),
    "6240": _rdkit_cpp_targets_spec("chiralityTestsCatch"),
    "6892": _rdkit_cpp_targets_spec("cdxmlParserCatchTest"),
    "4806": _rdkit_cpp_targets_spec(
        "graphmolTestsCatch",
        "fileParsersCatchTest",
        extra_cmake=_RDKIT_LEGACY_CATCH_CMAKE,
    ),
    "5407": _rdkit_cpp_targets_spec("chiralityTestsCatch"),
    # Scientific Issues sheet: concrete targets from each PR's base CMake files.
    "986": _rdkit_cpp_targets_spec(
        "moldraw2DTest1", legacy_boost_endian=True
    ),
    "1473": _rdkit_cpp_targets_spec("smaTest1", legacy_boost_endian=True),
    "1521": _rdkit_python_wrapper_spec(
        "Code/GraphMol/MMPA/Wrap/testMMPA.py", legacy_boost_endian=True
    ),
    "1654": _rdkit_mixed_tests_spec(
        ("smiTest1",),
        ("rdkit/Chem/UnitTestSmiles.py",),
        legacy_boost_endian=True,
    ),
    "2255": _rdkit_mixed_tests_spec(
        ("testAvalonLib1",),
        ("External/AvalonTools/Wrap/testAvalonTools.py",),
        extra_cmake="-DRDK_BUILD_AVALON_SUPPORT=ON ",
        legacy_boost_endian=True,
    ),
    "2646": _rdkit_cpp_targets_spec("graphmolTestsCatch"),
    "2651": _rdkit_cpp_targets_spec("testSubgraphs2"),
    "3170": _rdkit_cpp_targets_spec("testSGroup"),
    "3237": _rdkit_python_wrapper_spec(
        "Code/GraphMol/MolDraw2D/Wrap/testMolDraw2D.py"
    ),
    "3507": _rdkit_python_wrapper_spec("rdkit/Chem/UnitTestMol3D.py"),
    "3900": _rdkit_mixed_tests_spec(
        ("testFMCS",), ("Code/GraphMol/FMCS/Wrap/testFMCS.py",)
    ),
    "5425": _rdkit_cpp_targets_spec("moldraw2DTestCatch"),
    "5735": _rdkit_cpp_targets_spec("testRGroupDecomp"),
    "5775": _rdkit_cpp_targets_spec("moldraw2DTestCatch"),
    "5776": _rdkit_cpp_targets_spec("moldraw2DTestCatch"),
    "6247": _rdkit_cpp_targets_spec("testRGroupDecomp"),
    "6897": _rdkit_cpp_targets_spec("rxnTestCatch"),
    "6972": _rdkit_python_wrapper_spec("Code/GraphMol/Wrap/rough_test.py"),
    "7166": _rdkit_cpp_targets_spec(
        "cffi_test", extra_cmake="-DRDK_BUILD_CFFI_LIB=ON "
    ),
    "7419": _rdkit_cpp_targets_spec(
        "testInchi", extra_cmake="-DRDK_BUILD_INCHI_SUPPORT=ON "
    ),
    "8173": _rdkit_cpp_targets_spec("molHashCatchTest", new_boost=True),
    "6646": _rdkit_python_wrapper_spec("Code/GraphMol/FMCS/Wrap/testFMCS.py"),
    "8376": _rdkit_python_wrapper_spec(
        "Code/GraphMol/RascalMCES/Wrap/testRascalMCES.py"
    ),
    "8668": _rdkit_cpp_targets_spec("atropisomersCatch", new_boost=True),
    "8968": _rdkit_cpp_ctest_regex_spec(
        "smiTest|Smi|MolOps|molops", new_boost=True
    ),
    "8957": _rdkit_cpp_targets_spec("chiralityTestsCatch", new_boost=True),
    "9331": _rdkit_cpp_targets_spec(
        "chemdrawCatchTest",
        extra_cmake=(
            "-DRDK_BUILD_CHEMDRAW_SUPPORT=ON "
            "-DCMAKE_CXX_FLAGS=-I/testbed/External/ChemDraw "
        ),
        new_boost=True,
        chemdraw_include_compat=True,
        defer_target_build=True,
    ),
    "6506": _rdkit_python_wrapper_spec("rdkit/Chem/UnitTestRegistrationHash.py"),
    "6948": _rdkit_python_wrapper_spec("Code/GraphMol/Wrap/rough_test.py"),
    "7426": _rdkit_python_wrapper_spec(
        "rdkit/Chem/UnitTestRegistrationHash.py",
        new_boost=True,
    ),
    "8791": _rdkit_cpp_ctest_regex_spec("ForceField|forceField", new_boost=True),
    "8795": _rdkit_cpp_targets_spec("graphmolTestsCatch", new_boost=True),
    "8999": _rdkit_python_wrapper_spec(
        "External/pubchem_shape/Wrap/test_rdshapealign.py",
        new_boost=True,
    ),
    # ── Issues_No_Tests_split.xlsx fallback regression families ────────────
    "8796": _rdkit_python_wrapper_spec(
        "rdkit/Chem/UnitTestPandasTools.py",
        new_boost=True,
        extra_apt_packages=(
            "python3-pandas",
            "python3-openpyxl",
            "python3-xlsxwriter",
        ),
    ),
    "8166": _rdkit_python_wrapper_spec(
        "rdkit/Chem/Draw/UnitTestIPython.py",
        new_boost=True,
        extra_apt_packages=("python3-ipython", "python3-pil"),
    ),
    "7814": _rdkit_cpp_targets_spec(
        "testMMFFForceField",
        extra_cmake="-DRDK_TEST_MMFF_COMPLIANCE=ON ",
        new_boost=True,
    ),
    "5261": _rdkit_python_wrapper_spec(
        "rdkit/Chem/Draw/UnitTestDraw.py",
        extra_apt_packages=("python3-pil",),
    ),
    "5103": _rdkit_python_wrapper_spec(
        "rdkit/Chem/UnitTestPandasTools.py",
        extra_apt_packages=(
            "python3-pandas",
            "python3-openpyxl",
            "python3-xlsxwriter",
        ),
    ),
    "4793": _rdkit_python_wrapper_spec(
        "rdkit/Chem/Draw/UnitTestDraw.py",
        extra_apt_packages=("python3-pil",),
    ),
    # ── issues_testgen_001 generated-test specs ────────────────────────────
    # These targets correspond to the test files touched by the generated
    # patches.  Keeping them concrete avoids excluding valid generated tests
    # through the numeric non-evaluable fallback above.
    "2083": _rdkit_cpp_targets_spec("fileParsersTest1", legacy_boost_endian=True),
    "2377": _rdkit_cpp_targets_spec("testReaction", legacy_boost_endian=True),
    "2548": _rdkit_mixed_tests_spec(
        ("testReaction",),
        ("Code/GraphMol/ChemReactions/Wrap/testSanitize.py",),
        extra_cmake=_RDKIT_LEGACY_CATCH_CMAKE,
    ),
    "3015": _rdkit_python_wrapper_spec("rdkit/Chem/UnitTestMol3D.py"),
    "3050": _rdkit_cpp_targets_spec("testReaction"),
    "3098": _rdkit_cpp_targets_spec(
        "rxnTestCatch", extra_cmake=_RDKIT_LEGACY_CATCH_CMAKE
    ),
    "3354": _rdkit_cpp_targets_spec("resMolSupplierTest"),
    "3729": _rdkit_cpp_targets_spec("testReaction"),
    "3749": _rdkit_python_wrapper_spec("Code/GraphMol/FMCS/Wrap/testFMCS.py"),
    "5570": _rdkit_python_wrapper_spec(
        "Code/GraphMol/RGroupDecomposition/Wrap/test_rgroups.py"
    ),
    "6021": _rdkit_cpp_targets_spec(
        "rxnTestCatch", extra_cmake=_RDKIT_LEGACY_CATCH_CMAKE
    ),
    "6193": _rdkit_cpp_targets_spec("testReaction"),
    "6199": _rdkit_python_wrapper_spec(
        "Code/GraphMol/ChemReactions/Wrap/testReactionWrapper.py"
    ),
    "6686": _rdkit_cpp_targets_spec(
        "moldraw2DTestCatch", extra_cmake=_RDKIT_LEGACY_CATCH_CMAKE
    ),
    "7116": _rdkit_python_wrapper_spec(
        "Code/GraphMol/ChemReactions/Wrap/testSanitize.py"
    ),
    "7152": _rdkit_python_wrapper_spec(
        "Code/GraphMol/ChemReactions/Wrap/testReactionWrapper.py"
    ),
    "7384": _rdkit_mixed_tests_spec(
        ("rxnTestCatch", "smiTestCatch", "cxsmilesTest"),
        (
            "Code/GraphMol/ChemReactions/Wrap/testReactionWrapper.py",
            "Code/GraphMol/Wrap/rough_test.py",
        ),
        extra_cmake=_RDKIT_LEGACY_CATCH_CMAKE,
    ),
    "7975": _rdkit_cpp_targets_spec("molopsTestsCatch", new_boost=True),
    "8192": _rdkit_python_wrapper_spec(
        "Code/GraphMol/ChemReactions/Wrap/testReactionWrapper.py",
        new_boost=True,
    ),
    "8210": _rdkit_cpp_targets_spec("moldraw2DTestCatch", new_boost=True),
    "8211": _rdkit_cpp_targets_spec("moldraw2DTestCatch", new_boost=True),
    "8264": _rdkit_python_wrapper_spec(
        "Code/GraphMol/ForceFieldHelpers/Wrap/testHelpers.py", new_boost=True
    ),
    "8266": _rdkit_python_wrapper_spec(
        "rdkit/Chem/UnitTestInchi.py",
        new_boost=True,
        extra_cmake="-DRDK_BUILD_INCHI_SUPPORT=ON ",
    ),
    "8269": _rdkit_cpp_targets_spec("fileParsersCatchTest", new_boost=True),
    "8289": _rdkit_mixed_tests_spec(
        ("chemTransformsTestCatch",),
        ("Code/GraphMol/Wrap/rough_test.py",),
        new_boost=True,
    ),
    "8294": _rdkit_python_wrapper_spec(
        "Code/GraphMol/MolDraw2D/Wrap/testMolDraw2D.py", new_boost=True
    ),
    "8367": _rdkit_cpp_targets_spec("cxsmilesTest", new_boost=True),
    "8385": _rdkit_cpp_targets_spec("testReducedGraphs", new_boost=True),
    "8493": _rdkit_mixed_tests_spec(
        ("tautomerQueryTestCatch",),
        ("Code/GraphMol/TautomerQuery/Wrap/rough_test.py",),
        new_boost=True,
    ),
    "8542": _rdkit_cpp_targets_spec("graphmolTestsCatch", new_boost=True),
    "8550": _rdkit_cpp_targets_spec(
        "testSynthonSpaceSubstructureSearch", new_boost=True
    ),
    "8587": _rdkit_python_wrapper_spec(
        "Code/GraphMol/Wrap/rough_test.py", new_boost=True
    ),
    "8652": _rdkit_cpp_targets_spec(
        "testSynthonSpaceSubstructureSearch", new_boost=True
    ),
    "8680": _rdkit_python_wrapper_spec(
        "Code/GraphMol/MolDraw2D/Wrap/testMolDraw2D.py", new_boost=True
    ),
    "8767": _rdkit_mixed_tests_spec(
        ("chiralityTestsCatch",),
        ("Code/GraphMol/Wrap/test_cdxml.py",),
        new_boost=True,
    ),
    "8808": _rdkit_cpp_targets_spec(
        "cffi_test",
        extra_cmake="-DRDK_BUILD_CFFI_LIB=ON ",
        new_boost=True,
    ),
    "8824": _rdkit_cpp_targets_spec("fileParsersCatchTest", new_boost=True),
    "8907": _rdkit_cpp_targets_spec("cxsmilesTest", new_boost=True),
    "8974": _rdkit_cpp_targets_spec("testAtropisomers", new_boost=True),
    "9002": _rdkit_cpp_targets_spec("cxsmilesTest", new_boost=True),
    "9119": _rdkit_python_wrapper_spec(
        "Code/GraphMol/MolStandardize/Wrap/testMolStandardize.py",
        new_boost=True,
    ),
    "9120": _rdkit_cpp_targets_spec(
        "determineBondsCatchTest",
        extra_cmake="-DRDK_BUILD_XYZ2MOL_SUPPORT=ON ",
        new_boost=True,
    ),
    "9228": _rdkit_cpp_targets_spec("testUFFForceField", new_boost=True),
    "9302": _rdkit_cpp_targets_spec("moldraw2DTestCatch", new_boost=True),
    "9325": _rdkit_cpp_targets_spec("moldraw2DTestCatch", new_boost=True),
    "9332": _rdkit_python_wrapper_spec(
        "Code/GraphMol/MolDraw2D/Wrap/testMolDraw2D.py", new_boost=True
    ),
    # ── sci_cc_001 concrete fallback specs ──────────────────────────────────
    # These rows previously inherited explicit non-evaluable placeholders.
    # Use the touched test family as the scorable key so fix-mode evaluation
    # does not silently exclude them when dynamic mining observes zero F2P.
    "3196": _rdkit_python_wrapper_spec(
        "Code/GraphMol/ChemReactions/Wrap/testReactionWrapper.py"
    ),
    "3412": _rdkit_cpp_targets_spec(
        "chiralityTestsCatch", extra_cmake=_RDKIT_LEGACY_CATCH_CMAKE
    ),
    "3615": _rdkit_cpp_targets_spec(
        "fileParsersCatchTest",
        "moldraw2DTestCatch",
        extra_cmake=_RDKIT_LEGACY_CATCH_CMAKE,
    ),
    "3930": _rdkit_cpp_targets_spec(
        "moldraw2DTestCatch", extra_cmake=_RDKIT_LEGACY_CATCH_CMAKE
    ),
    "4303": _rdkit_python_wrapper_spec(
        "Code/GraphMol/MolTransforms/Wrap/testMolTransforms.py"
    ),
    "4414": _rdkit_cpp_targets_spec(
        "rxnTestCatch", extra_cmake=_RDKIT_LEGACY_CATCH_CMAKE
    ),
    "5063": _rdkit_cpp_targets_spec(
        "moldraw2DTestCatch", extra_cmake=_RDKIT_LEGACY_CATCH_CMAKE
    ),
    "5232": _rdkit_cpp_targets_spec("rgroupCatchTests"),
    "5468": _rdkit_cpp_targets_spec("smiTestCatch"),
    "6231": _rdkit_cpp_targets_spec(
        "graphmolOrganometallicsCatch",
        "graphmolMolOpsTest",
        "moldraw2DTestCatch",
    ),
    "6250": _rdkit_python_wrapper_spec(
        "Code/GraphMol/ChemReactions/Wrap/testReactionWrapper.py"
    ),
    "7137": _rdkit_cpp_targets_spec("canonTestsCatch"),
    "7571": _rdkit_cpp_targets_spec("moldraw2DTestCatch"),
    "8179": _rdkit_cpp_targets_spec(
        "molfileStereoCatchTest",
        "moldraw2DTestCatch",
        new_boost=True,
    ),
    "8217": _rdkit_cpp_targets_spec("moldraw2DTestCatch", new_boost=True),
    "8515": _rdkit_python_wrapper_spec(
        "Code/GraphMol/Wrap/rough_test.py", new_boost=True
    ),
    "8588": _rdkit_cpp_targets_spec("testMMPA", new_boost=True),
    "8734": _rdkit_cpp_targets_spec("molTransformsTestCatch", new_boost=True),
    "8874": _rdkit_python_wrapper_spec("Code/GraphMol/Wrap/rough_test.py", new_boost=True),
    "9012": _rdkit_cpp_targets_spec(
        "testSynthonSpaceSubstructureSearch",
        "testSynthonSpaceFingerprintSearch",
        "testSynthonSpaceRascalSearch",
        new_boost=True,
    ),
    "9022": _rdkit_cpp_targets_spec(
        "testSynthonSpaceSubstructureSearch",
        "testSynthonSpaceFingerprintSearch",
        "testSynthonSpaceRascalSearch",
        new_boost=True,
    ),
    "9125": _rdkit_cpp_targets_spec(
        "graphmolMolOpsTest",
        "molopsTestsCatch",
        new_boost=True,
    ),
    "9300": _rdkit_cpp_targets_spec("moldraw2DTestCatch", new_boost=True),
    "9348": _rdkit_cpp_targets_spec(
        "chemdrawCatchTest",
        extra_cmake=(
            "-DRDK_BUILD_CHEMDRAW_SUPPORT=ON "
            "-DCMAKE_CXX_FLAGS=-I/testbed/External/ChemDraw "
        ),
        new_boost=True,
        chemdraw_include_compat=True,
        defer_target_build=True,
    ),
    "9355": _rdkit_cpp_targets_spec(
        "chemdrawCatchTest",
        extra_cmake=(
            "-DRDK_BUILD_CHEMDRAW_SUPPORT=ON "
            "-DCMAKE_CXX_FLAGS=-I/testbed/External/ChemDraw "
        ),
        new_boost=True,
        chemdraw_include_compat=True,
        defer_target_build=True,
    ),
})


# Every no-test spec must be able to build whichever canonical test language a
# generated patch selects, independent of the original PR's authored test.
for _spec in SPECS_OPENMM.values():
    _spec["test_generation_capabilities"] = ("cpp", "python")
    _pre_install = _spec.setdefault("pre_install", [])
    _toolchain = (
        "apt-get update -q && apt-get install -y --no-install-recommends "
        "cmake g++ make swig doxygen python3-dev"
    )
    if _toolchain not in _pre_install:
        _pre_install.append(_toolchain)
    _python_deps = (
        "python -m pip install --no-cache-dir 'numpy<2' scipy cython pytest "
        "setuptools wheel"
    )
    if _python_deps not in _pre_install:
        _pre_install.append(_python_deps)

for _spec in SPECS_RDKIT.values():
    _spec["test_generation_capabilities"] = ("cpp", "python")
    _pre_install = _spec.setdefault("pre_install", [])
    _python_deps = (
        "apt-get install -y --no-install-recommends python3-dev python3-numpy "
        "python3-pytest"
    )
    if _python_deps not in _pre_install:
        _pre_install.append(_python_deps)
    for _command_group in ("build", "build_after_test_patch"):
        _spec[_command_group] = [
            command.replace(
                "-DRDK_BUILD_CPP_TESTS=OFF", "-DRDK_BUILD_CPP_TESTS=ON"
            ).replace(
                "-DRDK_BUILD_PYTHON_WRAPPERS=OFF",
                "-DRDK_BUILD_PYTHON_WRAPPERS=ON",
            )
            for command in _spec.get(_command_group, [])
        ]


def _lammps_test_generation_spec(*packages: str, kokkos: bool = False) -> dict:
    """Build LAMMPS after applying an agent-generated regression-test patch."""
    package_flags = " ".join(f"-D PKG_{package}=ON" for package in packages)
    kokkos_flags = "-D BUILD_KOKKOS=ON -D Kokkos_ENABLE_SERIAL=ON" if kokkos else ""
    mpi_enabled = "GPU" in packages
    mpi_packages = " libopenmpi-dev openmpi-bin" if mpi_enabled else ""
    mpi_flag = "ON" if mpi_enabled else "OFF"
    return {
        "pre_install": [
            "apt-get update -q",
            "apt-get install -y --no-install-recommends cmake g++ make ninja-build "
            "python3 python3-pytest libfftw3-dev libjpeg-dev libpng-dev libgtest-dev "
            f"ocl-icd-opencl-dev{mpi_packages}",
        ],
        "build_after_test_patch": [
            *(["git submodule update --init --recursive lib/kokkos"] if kokkos else []),
            "cmake -S cmake -B build -G Ninja -D CMAKE_BUILD_TYPE=Release "
            f"-D BUILD_MPI={mpi_flag} -D ENABLE_TESTING=ON "
            f"{kokkos_flags} {package_flags}",
            "cmake --build build --parallel $(nproc)",
        ],
        "test_cmd": ["ctest --test-dir build --output-on-failure"],
        "test_generation_use_spec_cmd": True,
        "oracle_kind": "generated_test",
        "test_generation_capabilities": ("cpp", "python"),
    }


SPECS_LAMMPS = {
    "5039": _lammps_test_generation_spec("MANYBODY"),
    "5042": _lammps_test_generation_spec("SPIN", "KSPACE"),
    "4887": _lammps_test_generation_spec("GPU"),
    "4590": _lammps_test_generation_spec("SRD"),
    "4861": _lammps_test_generation_spec("RHEO"),
    "4768": _lammps_test_generation_spec("KOKKOS", kokkos=True),
    "4760": _lammps_test_generation_spec("RIGID"),
    "4732": _lammps_test_generation_spec("MOLECULE"),
    "4019": _lammps_test_generation_spec("MC", "RIGID"),
    "4545": _lammps_test_generation_spec("RHEO"),
    "4481": _lammps_test_generation_spec(),
    "2026": _lammps_test_generation_spec("GPU", "ASPHERE"),
    "2105": _lammps_test_generation_spec(),
    "2367": _lammps_test_generation_spec("RIGID"),
    "4443": _lammps_test_generation_spec("REAXFF"),
    "4310": _lammps_test_generation_spec("MOLECULE", "EXTRA-MOLECULE", "OPENMP"),
    "4312": _lammps_test_generation_spec("REAXFF"),
    "4346": _lammps_test_generation_spec("KOKKOS", "GRANULAR", kokkos=True),
    "4339": _lammps_test_generation_spec("GRANULAR", "RHEO", "EXTRA-FIX"),
    "4243": _lammps_test_generation_spec("SPH", "DPD-MESO", "DPD-SMOOTH", "MACHDYN"),
    "4239": _lammps_test_generation_spec(),
    "4202": _lammps_test_generation_spec(),
    "4195": _lammps_test_generation_spec("GRANULAR", "BPM"),
    "4134": _lammps_test_generation_spec("MANYBODY"),
    "4123": _lammps_test_generation_spec("RIGID"),
    "4120": _lammps_test_generation_spec("ASPHERE"),
    "3553": _lammps_test_generation_spec(),
    "3931": _lammps_test_generation_spec(),
    "3941": _lammps_test_generation_spec("MANYBODY", "KOKKOS", kokkos=True),
    "4407": _lammps_test_generation_spec("EXTRA-FIX", "BPM", "GRANULAR"),
    "3930": _lammps_test_generation_spec("KOKKOS", kokkos=True),
    # Issues_No_Tests_v2.xlsx additions
    "4715": _lammps_test_generation_spec(
        "DIELECTRIC", "DIPOLE", "KOKKOS", "SPIN", kokkos=True
    ),
    "4507": _lammps_test_generation_spec("REAXFF", "OPENMP"),
    "4485": _lammps_test_generation_spec("EXTRA-PAIR"),
    "3129": _lammps_test_generation_spec("GPU"),
    "597": _lammps_test_generation_spec("GPU"),
    "4319": _lammps_test_generation_spec("GPU"),
    "4370": _lammps_test_generation_spec("BPM", "GRANULAR", "SPH"),
    "4291": _lammps_test_generation_spec("REPLICA"),
    "4152": _lammps_test_generation_spec(),
    "3898": _lammps_test_generation_spec("KOKKOS", kokkos=True),
}

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
    "lammps/lammps": SPECS_LAMMPS,  # c++
}

# Constants - Repository Specific Installation Instructions
MAP_REPO_TO_INSTALL_C = {}
