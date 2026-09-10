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
            "if [ -d /testbed/wrappers/python/openmm/app ]; then "
            "rm -rf /tmp/swebench-openmm-internal && mkdir -p /tmp/swebench-openmm-internal && "
            "{ cp \"$OPENMM_SITE\"/app/internal/*.so /tmp/swebench-openmm-internal/ 2>/dev/null || true; } && "
            "rm -rf \"$OPENMM_SITE/app\" && cp -r /testbed/wrappers/python/openmm/app \"$OPENMM_SITE/\" && "
            "if [ -d \"$OPENMM_SITE/app/internal\" ]; then "
            "cp /tmp/swebench-openmm-internal/*.so \"$OPENMM_SITE/app/internal/\" 2>/dev/null || true; fi; fi && "
            "rm -rf \"$SIMTK_SITE/app\" && "
            "if [ -d /testbed/wrappers/python/openmm/app ]; then "
            "cp -r /testbed/wrappers/python/openmm/app \"$SIMTK_SITE/\"; "
            "elif [ -d /testbed/wrappers/python/simtk/openmm/app ]; then "
            "cp -r /testbed/wrappers/python/simtk/openmm/app \"$SIMTK_SITE/\"; "
            "python -m lib2to3 -w -n \"$SIMTK_SITE/app\" >/dev/null 2>&1 || true; fi && "
            "if [ -d \"$OPENMM_SITE/app/internal\" ] && [ -d \"$SIMTK_SITE/app/internal\" ]; then "
            "cp -n \"$OPENMM_SITE\"/app/internal/*.so \"$SIMTK_SITE/app/internal/\" 2>/dev/null || true; fi && "
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

_OPENMM_NVIDIA_ICD_DIR = "/tmp/swebench-opencl-vendors"
_OPENMM_NVIDIA_ICD_SETUP = (
    f"mkdir -p {_OPENMM_NVIDIA_ICD_DIR} && "
    f"printf '%s\\n' 'libnvidia-opencl.so.1' > {_OPENMM_NVIDIA_ICD_DIR}/nvidia.icd"
)
_OPENMM_NVIDIA_TEST_ENV = f"OCL_ICD_VENDORS={_OPENMM_NVIDIA_ICD_DIR} "
_OPENMM_NVIDIA_OPENCL_CHECK = (
    _OPENMM_NVIDIA_TEST_ENV
    + "clinfo -l 2>&1 | grep -qi NVIDIA || "
    "{ echo NVIDIA_OPENCL_UNAVAILABLE; exit 86; }; "
)


def _openmm_opencl_targets_spec(*targets: str, amoeba: bool = False, gpu: bool = False) -> dict:
    """Build OpenCL tests against either NVIDIA OpenCL or portable POCL.

    Ubuntu 22.04's POCL/LLVM combination reports ``generic`` for CPUs newer
    than its LLVM release (for example Zen 4), but ``generic`` is not a valid
    x86 LLVM CPU name.  A tiny process-local symbol interposer selects the
    closest LLVM-supported CPU baseline without changing OpenMM or the oracle.

    Recent bundled ``opencl.hpp`` revisions also use ``CL_MAKE_VERSION`` while
    Jammy's C OpenCL headers can expose the extension without that macro.  A
    forced compatibility header supplies the Khronos-defined encoding.

    GPU specs pin the ICD loader to an NVIDIA-only vendor directory and verify
    it with ``clinfo`` before running a test. CPU specs retain the POCL shim.
    This prevents a GPU-marked benchmark from silently executing on POCL.
    """
    cmake_targets = " ".join(targets)
    spec = {
        "pre_install": [
            "apt-get update -q",
            "apt-get install -y --no-install-recommends "
            "cmake g++ make libgl1-mesa-dev ocl-icd-opencl-dev "
            "pocl-opencl-icd clinfo",
        ],
        "build_after_test_patch": [
            _OPENMM_OPENCL_COMPAT_HEADER_COMMAND,
            *(
                [_OPENMM_NVIDIA_ICD_SETUP]
                if gpu
                else [_OPENMM_POCL_CPU_COMPAT_COMMAND]
            ),
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
            (
                _OPENMM_NVIDIA_OPENCL_CHECK + _OPENMM_NVIDIA_TEST_ENV
                if gpu
                else _OPENMM_POCL_TEST_ENV
            )
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
    "apt-get install -y --no-install-recommends cuda-nvcc-12-4 cuda-cudart-dev-12-4 "
    "cuda-nvrtc-dev-12-4 cuda-profiler-api-12-4 libcufft-dev-12-4"
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
    "4618": _openmm_opencl_targets_spec(
        "TestOpenCLMonteCarloFlexibleBarostat", gpu=True
    ),
    "2318": _openmm_opencl_targets_spec("TestOpenCLNonbondedForce", gpu=True),
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
    "3311": _openmm_native_python_spec(
        "TestForceField.py",
        "test_Amoeba18BPTI or test_Amoeba18Nucleic",
        amoeba=True,
    ),
    # ── Issues_No_Tests_split.xlsx: CPU/Reference regression families ──────
    # These PRs intentionally contain no authored tests.  Build and run the
    # narrowest registered CPU/Reference suite for the production subsystem
    # changed by each PR.
    **{
        pr: _openmm_cpp_targets_spec(*targets)
        for pr, targets in {
            "3326": (
                "TestReferenceHarmonicAngleForce",
                "TestReferenceNonbondedForce",
            ),
            "2644": ("TestReferenceCMAPTorsionForce",),
            "1592": ("TestCpuGBSAOBCForce",),
            "3280": ("TestReferenceCustomNonbondedForce",),
            "920": ("TestCpuNonbondedForce",),
            "3834": ("TestParser",),
            "3574": ("TestReferenceLangevinMiddleIntegrator",),
            "3321": ("TestReferenceNonbondedForce",),
            "2544": ("TestCpuNonbondedForce",),
            "2328": ("TestCpuNonbondedForce",),
        }.items()
    },
    # ── Issues_No_Tests_split.xlsx: Common/OpenCL regression families ──────
    # These specs request a real GPU and pin OpenCL to the NVIDIA ICD. POCL
    # remains installed only for the separately curated CPU-emulation specs.
    **{
        pr: _openmm_opencl_targets_spec(*targets, amoeba=amoeba, gpu=True)
        for pr, targets, amoeba in [
            ("5069", ("TestOpenCLNonbondedForce",), False),
            ("1679", ("TestOpenCLCustomIntegrator",), False),
            ("3240", ("TestOpenCLCustomExternalForce",), False),
            ("5242", ("TestOpenCLLocalEnergyMinimizer",), False),
            ("5346", ("TestOpenCLCustomCVForce",), False),
            ("5117", ("TestOpenCLCustomBondForce",), False),
            ("3460", ("TestOpenCLNonbondedForce",), False),
            (
                "3428",
                ("TestOpenCLNonbondedForce", "TestOpenCLAmoebaMultipoleForce"),
                True,
            ),
            ("4079", ("TestOpenCLRpmd",), False),
            ("4249", ("TestOpenCLCustomNonbondedForce",), False),
            ("4148", ("TestOpenCLCustomNonbondedForce",), False),
            ("4119", ("TestOpenCLMonteCarloBarostat",), False),
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
            ("4748", "TestModeller.py", "test_addExtraParticles"),
            ("4279", "TestForceField.py", "test_residueMatcher"),
            ("4104", "TestModeller.py", "test_addSolventIons"),
            ("3241", "TestModeller.py", "test_addSolventPeriodicBox"),
            ("2639", "TestStateDataReporter.py", "testAppend"),
            ("2429", "TestCharmmFiles.py", "test_Drude"),
        ]
    },
    "1640": _openmm_cuda_targets_spec(
        "TestCudaAmoebaMultipoleForce", plugin="amoeba"
    ),
    "2152": _openmm_cuda_targets_spec(
        "TestCudaAmoebaMultipoleForce", plugin="amoeba"
    ),
    "4364": _openmm_cuda_targets_spec("TestCudaCustomNonbondedForce"),
    "3057": _openmm_cuda_targets_spec("TestCudaNonbondedForce"),
    "3428": _openmm_cuda_targets_spec("TestCudaNonbondedForce"),
    "3771": _openmm_cuda_targets_spec("TestCudaNonbondedForce"),
    "5069": _openmm_cuda_targets_spec("TestCudaNonbondedForce"),
    "5346": _openmm_cuda_targets_spec("TestCudaCustomCVForce"),
})


# Issues_No_Tests_new.xlsx: PR 2038 (2018) is a pure-Python fix to
# simtk/openmm/app/modeller.py::addMembrane -> exercised by
# wrappers/python/tests/TestModeller.py. Same pattern as the curated PR 3151.
SPECS_OPENMM["2038"] = _openmm_python_app_spec(
    "TestModeller.py", "test_addMembrane or test_addSolventPeriodicBox"
)


_QGIS_QT6_BUILD_IMAGE = (
    "qgis/qgis3-build-deps-ubuntu-qt6@"
    "sha256:81b4d845b8704c068e2cc94238d45fee4fcd8d603744d635edea8a2966202005"
)
# QGIS with Python bindings compiles the full project. Keep the default
# conservative on shared evaluation hosts while allowing an explicit override.
_QGIS_BUILD_JOBS = "${SWEBENCH_QGIS_BUILD_JOBS:-4}"


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
        # The build-deps base image's system libspatialindex has drifted to
        # >=2.1, which QGIS's own CMakeLists.txt (see
        # https://github.com/libspatialindex/libspatialindex/issues/276)
        # hard-refuses to build against. Build QGIS's vendored copy instead
        # of relying on the (too-new) system package.
        "-DWITH_INTERNAL_SPATIALINDEX=TRUE",
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
    "64781": _qgis_spec(
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
            "3098",
            "9228",
        ]
    },
    "7990": _rdkit_cpp_targets_spec("deprotectTest", new_boost=True),
    "7814": _rdkit_cpp_targets_spec(
        "testMMFFForceField",
        extra_cmake="-DRDK_TEST_MMFF_COMPLIANCE=ON ",
        new_boost=True,
    ),
    "2021": _rdkit_cpp_targets_spec("graphmolMolOpsTest", legacy_boost_endian=True),
    "3855": _rdkit_cpp_targets_spec("graphmolMolOpsTest", legacy_boost_endian=True),
    "3176": _rdkit_cpp_targets_spec("testMolAlign", legacy_boost_endian=True),
    "3098": _rdkit_cpp_targets_spec(
        "rxnTestCatch", extra_cmake=_RDKIT_LEGACY_CATCH_CMAKE
    ),
    "9228": _rdkit_cpp_targets_spec("testUFFForceField", new_boost=True),
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
    # Generated regressions frequently use add_mpi_test() even when the issue
    # is not in an MPI-named package. Keep MPI uniformly available so the
    # planner can honor the registration instead of running the binary on one
    # rank and producing a false failure.
    mpi_packages = " libopenmpi-dev openmpi-bin"
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
            f"-D BUILD_MPI=ON -D ENABLE_TESTING=ON "
            f"{kokkos_flags} {package_flags}",
            "cmake --build build --parallel $(nproc)",
        ],
        "test_cmd": ["ctest --test-dir build --output-on-failure"],
        "test_generation_use_spec_cmd": True,
        "oracle_kind": "generated_test",
        "test_generation_capabilities": ("cpp", "python"),
    }


SPECS_LAMMPS = {
    "5042": _lammps_test_generation_spec("SPIN", "KSPACE"),
    "4887": _lammps_test_generation_spec("GPU"),
    "4590": _lammps_test_generation_spec("SRD"),
    "4861": _lammps_test_generation_spec("RHEO"),
    "4768": _lammps_test_generation_spec("KOKKOS", kokkos=True),
    "4760": _lammps_test_generation_spec("RIGID"),
    "4732": _lammps_test_generation_spec("MOLECULE"),
    "4545": _lammps_test_generation_spec("RHEO"),
    "4481": _lammps_test_generation_spec(),
    "2026": _lammps_test_generation_spec("GPU", "ASPHERE"),
    "2105": _lammps_test_generation_spec(),
    "2367": _lammps_test_generation_spec("RIGID"),
    "4443": _lammps_test_generation_spec("REAXFF"),
    "4312": _lammps_test_generation_spec("REAXFF"),
    "4346": _lammps_test_generation_spec("KOKKOS", "GRANULAR", kokkos=True),
    "4339": _lammps_test_generation_spec("GRANULAR", "RHEO", "EXTRA-FIX"),
    "4202": _lammps_test_generation_spec(),
    "4195": _lammps_test_generation_spec("GRANULAR", "BPM"),
    "4123": _lammps_test_generation_spec("RIGID"),
    "4120": _lammps_test_generation_spec("ASPHERE"),
    "3553": _lammps_test_generation_spec(),
    "3931": _lammps_test_generation_spec(),
    "3941": _lammps_test_generation_spec("MANYBODY", "KOKKOS", kokkos=True),
    "4407": _lammps_test_generation_spec("EXTRA-FIX", "BPM", "GRANULAR"),
    "4507": _lammps_test_generation_spec("REAXFF", "OPENMP"),
    "4485": _lammps_test_generation_spec("EXTRA-PAIR"),
    "3129": _lammps_test_generation_spec("GPU"),
    "597": _lammps_test_generation_spec("GPU"),
    "4319": _lammps_test_generation_spec("GPU"),
    "4370": _lammps_test_generation_spec("BPM", "GRANULAR", "SPH"),
    "4152": _lammps_test_generation_spec(),
    "1237": _lammps_test_generation_spec("EXTRA-COMPUTE", "MISC"),
    "1374": _lammps_test_generation_spec(
        "CLASS2", "KSPACE", "MOLECULE", "FEP", "MOFFF", "SMTBQ"
    ),
    "1388": _lammps_test_generation_spec(),
    "1452": _lammps_test_generation_spec("MANYBODY", "INTEL", "OPENMP"),
    "1719": _lammps_test_generation_spec("KSPACE", "OPENMP"),
    "1746": _lammps_test_generation_spec("ASPHERE", "INTEL"),
    "1750": _lammps_test_generation_spec("GRANULAR"),
    "1759": _lammps_test_generation_spec(),
    "1928": _lammps_test_generation_spec("KIM", "MESSAGE", "INTEL"),
    "2010": _lammps_test_generation_spec("KSPACE"),
    "2181": _lammps_test_generation_spec("KSPACE"),
    "2187": _lammps_test_generation_spec("GPU"),
    "3699": _lammps_test_generation_spec(),
}

# ---------------------------------------------------------------------------
# Issues_No_Tests_new.xlsx additions (2026-09-09).
# ---------------------------------------------------------------------------

# samtools: autotools build against a sibling htslib checkout; the regression
# suite is test/test.pl. PR 2099 (2024) touches bam_consensus.c.
_SAMTOOLS_GEN_SPEC = {
    "pre_install": [
        "apt-get update -q",
        "apt-get install -y --no-install-recommends "
        "autoconf automake make gcc perl zlib1g-dev libbz2-dev liblzma-dev "
        "libcurl4-openssl-dev libncurses5-dev git",
        "git clone --depth 1 https://github.com/samtools/htslib.git ../htslib "
        "&& (cd ../htslib && git submodule update --init --recursive && "
        "autoreconf -i && ./configure && make -j\"$(nproc)\")",
    ],
    "build": [
        "autoreconf -i",
        "./configure --with-htslib=../htslib",
        "make -j\"$(nproc)\"",
    ],
    "test_cmd": ["make test"],
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("c",),
}
SPECS_SAMTOOLS = {"2099": dict(_SAMTOOLS_GEN_SPEC)}


def _not_evaluable_c(repo: str, pr: str, needs: str) -> dict:
    """Explicit non-evaluable placeholder (mirrors the RDKit convention).

    Keeps the pipeline from silently relying on a fallback; `needs` records
    what curation is still required before this PR can be scored.
    """
    return {
        "pre_install": [],
        "build": [],
        "test_cmd": [
            f"echo '{repo}#{pr} not evaluable: {needs}' && false",
        ],
        "_curation_todo": needs,
    }


# QGIS: 2023-2024 core C++ changes. Each needs the CTest target / Python test
# that exercises the touched path plus a matching build-deps image for that
# QGIS minor (no Qt5 3.30/3.34 image constant exists yet).
SPECS_QGIS.update(
    {
        pr: _not_evaluable_c("qgis", pr, needs)
        for pr, needs in {
            # 52476: same geometry_checker subsystem as the curated PR 63639
            #   (targets test_analysis_processingcheckgeometry /
            #   test_geometry_checker_geometrychecks) -- reuse once a Qt5
            #   QGIS 3.30 build-deps image is pinned.
            # 57840: PyQgsSensorThingsProvider python test covers this path.
            "52213": "QGIS 3.30 (Qt5) build-deps image; no clean unit test for elevation-shading renderer (GUI)",
            "52303": "QGIS 3.30 (Qt5) build-deps image; layout/canvas move-item-content has no isolated unit test",
            "52476": "QGIS 3.30 (Qt5) build-deps image; then reuse PR 63639 targets (geometry_checker)",
            "57840": "QGIS 3.38 build-deps image; target PyQgsSensorThingsProvider",
        }.items()
    }
)

# fenics/dolfinx: PR 1264 (2020) touches cpp/dolfinx/fem/assemble_vector_impl.h.
# DOLFINx needs the full FEniCS stack (basix, ufl, ffcx, PETSc/MPI); use the
# upstream dolfinx dev image once pinned.
SPECS_DOLFINX = {
    "1264": _not_evaluable_c(
        "dolfinx", "1264",
        "dolfinx/dev-env image (basix/ufl/ffcx/PETSc) + cpp demo/unit ctest target",
    ),
}


MAP_REPO_VERSION_TO_SPECS_C = {
    "redis/redis": SPECS_REDIS,  # c
    "jqlang/jq": SPECS_JQ,  # c
    "nlohmann/json": SPECS_JSON,  # c++
    "micropython/micropython": SPECS_MICROPYTHON,  # c
    "valkey-io/valkey": SPECS_VALKEY,  # c
    "fmtlib/fmt": SPECS_FMT,  # c++
    "openmm/openmm": SPECS_OPENMM,  # c++
    "qgis/QGIS": SPECS_QGIS,  # c++
    "rdkit/rdkit": SPECS_RDKIT,  # c++
    "lammps/lammps": SPECS_LAMMPS,  # c++
    "samtools/samtools": SPECS_SAMTOOLS,  # c
    "fenics/dolfinx": SPECS_DOLFINX,  # c++ (non-evaluable placeholder)
}

# Constants - Repository Specific Installation Instructions
MAP_REPO_TO_INSTALL_C = {}
