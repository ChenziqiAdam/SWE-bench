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

SPECS_OPENMM = {
    # Add entries here: "<PR_NUMBER>": {"build": [...], "test_cmd": [...]}
    # Build pattern:
    #   "mkdir -p build",
    #   "cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug",
    #   "cmake --build build --parallel $(nproc) --target <test_target>",
    # Test pattern:
    #   "ctest --test-dir build -V -R <test_regex>"
}

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

# rdkit uses Catch2; binary name = first arg to rdkit_catch_test() in CMakeLists.txt
# PR 8957 touches Code/GraphMol/Chirality.cpp + catch_chirality.cpp
# → target: chiralityTestsCatch  (from rdkit_catch_test(chiralityTestsCatch ...))
SPECS_RDKIT = {
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
}

# Constants - Repository Specific Installation Instructions
MAP_REPO_TO_INSTALL_C = {}
