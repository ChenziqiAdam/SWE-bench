# Constants - Testing Commands
TEST_PYTEST = "pytest --no-header -rA --tb=no -p no:cacheprovider"
TEST_PYTEST_VERBOSE = "pytest -rA --tb=long -p no:cacheprovider"
TEST_ASTROPY_PYTEST = "pytest -rA -vv -o console_output_style=classic --tb=no"
TEST_DJANGO = "./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1"
TEST_DJANGO_NO_PARALLEL = "./tests/runtests.py --verbosity 2"
TEST_SEABORN = "pytest --no-header -rA"
TEST_SEABORN_VERBOSE = "pytest -rA --tb=long"
TEST_PYTEST = "pytest -rA"
TEST_PYTEST_VERBOSE = "pytest -rA --tb=long"
TEST_SPHINX = "tox --current-env -epy39 -v --"
TEST_SYMPY = (
    "PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose"
)
TEST_SYMPY_VERBOSE = "bin/test -C --verbose"


# Constants - Installation Specifications
SPECS_SKLEARN = {
    k: {
        "python": "3.6",
        "packages": "numpy scipy cython pytest pandas matplotlib",
        "install": "python -m pip install -v --no-use-pep517 --no-build-isolation -e .",
        "pip_packages": [
            "cython",
            "numpy==1.19.2",
            "setuptools",
            "scipy==1.5.2",
        ],
        "test_cmd": TEST_PYTEST,
    }
    for k in ["0.20", "0.21", "0.22"]
}
SPECS_SKLEARN.update(
    {
        "1.1": {
            "python": "3.9",
            "packages": "'pip<24' 'setuptools<74' 'numpy==1.19.2' 'scipy==1.5.2' 'cython<3' pytest 'pandas<2.0.0' 'matplotlib<3.9.0' joblib threadpoolctl",
            "install": "python -m pip install -v --no-build-isolation -e .",
            "pip_packages": ["cython<3", "setuptools<74", "numpy<2", "scipy"],
            "test_cmd": TEST_PYTEST,
        },
    }
)
SPECS_SKLEARN.update(
    {
        # sklearn 1.2's _libsvm.pyx uses legacy Cython 2 syntax (e.g. `IF ... ELIF`
        # blocks) that Cython 3.x rejects with a CompileError. Pin cython<3 here.
        "1.2": {
            "python": "3.9",
            "packages": "'pip<24' 'setuptools<74' 'numpy==1.19.2' 'scipy==1.5.2' 'cython<3' pytest 'pandas<2.0.0' 'matplotlib<3.9.0' pytest joblib threadpoolctl",
            "install": "python -m pip install -v --no-build-isolation -e .",
            "pip_packages": ["cython<3", "setuptools<74", "numpy<2", "scipy"],
            "test_cmd": TEST_PYTEST,
        },
    }
)
SPECS_SKLEARN.update(
    {
        k: {
            "python": "3.9",
            # pip<24: newer pip uses dataclass(slots=) which is 3.10+ only
            # setuptools<74: numpy.distutils needs distutils.msvccompiler, dropped in setuptools 74
            "packages": "'pip<24' 'setuptools<74' 'numpy==1.19.2' 'scipy==1.5.2' 'cython==3.0.10' pytest 'pandas<2.0.0' 'matplotlib<3.9.0' pytest joblib threadpoolctl",
            "install": "python -m pip install -v --no-build-isolation -e .",
            # pin numpy<2 to keep numpy.distutils available (removed in numpy 2.0)
            "pip_packages": ["cython", "setuptools<74", "numpy<2", "scipy"],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["1.3", "1.4", "1.5"]
    }
)
SPECS_SKLEARN.update(
    {
        "1.6": {
            "python": "3.9",
            # pip<24: newer pip uses dataclass(slots=) which is 3.10+ only
            # numpy>=1.19.5: sklearn 1.6 meson build requires it (rejects 1.19.2)
            # scipy>=1.6.0: sklearn 1.6's meson.build asserts scipy>=1.6.0 (rejects 1.5.2)
            "packages": "'pip<24' 'numpy==1.19.5' 'scipy>=1.6,<1.12' 'cython==3.0.10' pytest 'pandas<2.0.0' 'matplotlib<3.9.0' setuptools pytest joblib threadpoolctl",
            "install": "python -m pip install -v --no-build-isolation -e .",
            # sklearn 1.6 switched to meson build backend
            "pip_packages": ["cython", "setuptools", "numpy<2", "scipy>=1.6,<1.12", "meson-python", "ninja"],
            "test_cmd": TEST_PYTEST,
        }
    }
)
SPECS_SKLEARN.update(
    {
        k: {
            "python": "3.11",
            "packages": "numpy scipy cython pytest pandas matplotlib setuptools joblib threadpoolctl",
            "install": "python -m pip install --no-build-isolation -e .",
            "pip_packages": ["cython", "setuptools", "numpy", "scipy", "meson-python", "ninja"],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["1.7", "1.8", "1.9"]
    }
)

SPECS_FLASK = {
    "2.0": {
        "python": "3.9",
        "packages": "requirements.txt",
        "install": "python -m pip install -e .",
        "pip_packages": [
            "setuptools==70.0.0",
            "Werkzeug==2.3.7",
            "Jinja2==3.0.1",
            "itsdangerous==2.1.2",
            "click==8.0.1",
            "MarkupSafe==2.1.3",
        ],
        "test_cmd": TEST_PYTEST,
    },
    "2.1": {
        "python": "3.10",
        "packages": "requirements.txt",
        "install": "python -m pip install -e .",
        "pip_packages": [
            "setuptools==70.0.0",
            "click==8.1.3",
            "itsdangerous==2.1.2",
            "Jinja2==3.1.2",
            "MarkupSafe==2.1.1",
            "Werkzeug==2.3.7",
        ],
        "test_cmd": TEST_PYTEST,
    },
}
SPECS_FLASK.update(
    {
        k: {
            "python": "3.11",
            "packages": "requirements.txt",
            "install": "python -m pip install -e .",
            "pip_packages": [
                "setuptools==70.0.0",
                "click==8.1.3",
                "itsdangerous==2.1.2",
                "Jinja2==3.1.2",
                "MarkupSafe==2.1.1",
                "Werkzeug==2.3.7",
            ],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["2.2", "2.3", "3.0", "3.1"]
    }
)

SPECS_DJANGO = {
    k: {
        "python": "3.5",
        "packages": "requirements.txt",
        "pre_install": [
            "apt-get update && apt-get install -y locales",
            "echo 'en_US UTF-8' > /etc/locale.gen",
            "locale-gen en_US.UTF-8",
        ],
        "install": "python setup.py install",
        "pip_packages": ["setuptools"],
        "eval_commands": [
            "export LANG=en_US.UTF-8",
            "export LC_ALL=en_US.UTF-8",
            "export PYTHONIOENCODING=utf8",
            "export LANGUAGE=en_US:en",
        ],
        "test_cmd": TEST_DJANGO,
    }
    for k in ["1.7", "1.8", "1.9", "1.10", "1.11", "2.0", "2.1", "2.2"]
}
SPECS_DJANGO.update(
    {
        k: {
            "python": "3.5",
            "install": "python setup.py install",
            "test_cmd": TEST_DJANGO,
        }
        for k in ["1.4", "1.5", "1.6"]
    }
)
SPECS_DJANGO.update(
    {
        k: {
            "python": "3.6",
            "packages": "requirements.txt",
            "install": "python -m pip install -e .",
            "eval_commands": [
                "sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && locale-gen",
                "export LANG=en_US.UTF-8",
                "export LANGUAGE=en_US:en",
                "export LC_ALL=en_US.UTF-8",
            ],
            "test_cmd": TEST_DJANGO,
        }
        for k in ["3.0", "3.1", "3.2"]
    }
)
SPECS_DJANGO.update(
    {
        k: {
            "python": "3.8",
            "packages": "requirements.txt",
            "install": "python -m pip install -e .",
            "test_cmd": TEST_DJANGO,
        }
        for k in ["4.0"]
    }
)
SPECS_DJANGO.update(
    {
        k: {
            "python": "3.9",
            "packages": "requirements.txt",
            "install": "python -m pip install -e .",
            "test_cmd": TEST_DJANGO,
        }
        for k in ["4.1", "4.2"]
    }
)
SPECS_DJANGO.update(
    {
        k: {
            "python": "3.11",
            "packages": "requirements.txt",
            "install": "python -m pip install -e .",
            "test_cmd": TEST_DJANGO,
        }
        for k in ["5.0", "5.1", "5.2"]
    }
)
SPECS_DJANGO["1.9"]["test_cmd"] = TEST_DJANGO_NO_PARALLEL

SPECS_REQUESTS = {
    k: {
        "python": "3.9",
        "packages": "pytest",
        "install": "python -m pip install .",
        "test_cmd": TEST_PYTEST,
    }
    for k in ["0.7", "0.8", "0.9", "0.11", "0.13", "0.14", "1.1", "1.2", "2.0", "2.2"]
    + ["2.3", "2.4", "2.5", "2.7", "2.8", "2.9", "2.10", "2.11", "2.12", "2.17"]
    + ["2.18", "2.19", "2.22", "2.26", "2.25", "2.27", "2.31", "3.0"]
}

SPECS_SEABORN = {
    k: {
        "python": "3.9",
        "install": "python -m pip install -e .",
        "pip_packages": [
            "contourpy==1.1.0",
            "cycler==0.11.0",
            "fonttools==4.42.1",
            "importlib-resources==6.0.1",
            "kiwisolver==1.4.5",
            "matplotlib==3.7.2",
            "numpy==1.25.2",
            "packaging==23.1",
            "pandas==1.3.5",  # 2.0.3
            "pillow==10.0.0",
            "pyparsing==3.0.9",
            "pytest",
            "python-dateutil==2.8.2",
            "pytz==2023.3.post1",
            "scipy==1.11.2",
            "six==1.16.0",
            "tzdata==2023.1",
            "zipp==3.16.2",
        ],
        "test_cmd": TEST_SEABORN,
    }
    for k in ["0.11"]
}
SPECS_SEABORN.update(
    {
        k: {
            "python": "3.9",
            "install": "python -m pip install -e .[dev]",
            "pip_packages": [
                "contourpy==1.1.0",
                "cycler==0.11.0",
                "fonttools==4.42.1",
                "importlib-resources==6.0.1",
                "kiwisolver==1.4.5",
                "matplotlib==3.7.2",
                "numpy==1.25.2",
                "packaging==23.1",
                "pandas==2.0.0",
                "pillow==10.0.0",
                "pyparsing==3.0.9",
                "pytest",
                "python-dateutil==2.8.2",
                "pytz==2023.3.post1",
                "scipy==1.11.2",
                "six==1.16.0",
                "tzdata==2023.1",
                "zipp==3.16.2",
            ],
            "test_cmd": TEST_SEABORN,
        }
        for k in ["0.12", "0.13", "0.14"]
    }
)

SPECS_PYTEST = {
    k: {
        "python": "3.9",
        "install": "python -m pip install -e .",
        "test_cmd": TEST_PYTEST,
    }
    for k in [
        "4.4",
        "4.5",
        "4.6",
        "5.0",
        "5.1",
        "5.2",
        "5.3",
        "5.4",
        "6.0",
        "6.2",
        "6.3",
        "7.0",
        "7.1",
        "7.2",
        "7.4",
        "8.0",
        "8.1",
        "8.2",
        "8.3",
        "8.4",
    ]
}
SPECS_PYTEST["4.4"]["pip_packages"] = [
    "atomicwrites==1.4.1",
    "attrs==23.1.0",
    "more-itertools==10.1.0",
    "pluggy==0.13.1",
    "py==1.11.0",
    "setuptools==68.0.0",
    "six==1.16.0",
]
SPECS_PYTEST["4.5"]["pip_packages"] = [
    "atomicwrites==1.4.1",
    "attrs==23.1.0",
    "more-itertools==10.1.0",
    "pluggy==0.11.0",
    "py==1.11.0",
    "setuptools==68.0.0",
    "six==1.16.0",
    "wcwidth==0.2.6",
]
SPECS_PYTEST["4.6"]["pip_packages"] = [
    "atomicwrites==1.4.1",
    "attrs==23.1.0",
    "more-itertools==10.1.0",
    "packaging==23.1",
    "pluggy==0.13.1",
    "py==1.11.0",
    "six==1.16.0",
    "wcwidth==0.2.6",
]
for k in ["5.0", "5.1", "5.2"]:
    SPECS_PYTEST[k]["pip_packages"] = [
        "atomicwrites==1.4.1",
        "attrs==23.1.0",
        "more-itertools==10.1.0",
        "packaging==23.1",
        "pluggy==0.13.1",
        "py==1.11.0",
        "wcwidth==0.2.6",
    ]
SPECS_PYTEST["5.3"]["pip_packages"] = [
    "attrs==23.1.0",
    "more-itertools==10.1.0",
    "packaging==23.1",
    "pluggy==0.13.1",
    "py==1.11.0",
    "wcwidth==0.2.6",
]
SPECS_PYTEST["5.4"]["pip_packages"] = [
    "py==1.11.0",
    "packaging==23.1",
    "attrs==23.1.0",
    "more-itertools==10.1.0",
    "pluggy==0.13.1",
]
SPECS_PYTEST["6.0"]["pip_packages"] = [
    "attrs==23.1.0",
    "iniconfig==2.0.0",
    "more-itertools==10.1.0",
    "packaging==23.1",
    "pluggy==0.13.1",
    "py==1.11.0",
    "toml==0.10.2",
]
for k in ["6.2", "6.3"]:
    SPECS_PYTEST[k]["pip_packages"] = [
        "attrs==23.1.0",
        "iniconfig==2.0.0",
        "packaging==23.1",
        "pluggy==0.13.1",
        "py==1.11.0",
        "toml==0.10.2",
    ]
SPECS_PYTEST["7.0"]["pip_packages"] = [
    "attrs==23.1.0",
    "iniconfig==2.0.0",
    "packaging==23.1",
    "pluggy==0.13.1",
    "py==1.11.0",
]
for k in ["7.1", "7.2"]:
    SPECS_PYTEST[k]["pip_packages"] = [
        "attrs==23.1.0",
        "iniconfig==2.0.0",
        "packaging==23.1",
        "pluggy==0.13.1",
        "py==1.11.0",
        "tomli==2.0.1",
    ]
for k in ["7.4", "8.0", "8.1", "8.2", "8.3", "8.4"]:
    SPECS_PYTEST[k]["pip_packages"] = [
        "iniconfig==2.0.0",
        "packaging==23.1",
        "pluggy==1.3.0",
        "exceptiongroup==1.1.3",
        "tomli==2.0.1",
    ]
SPECS_PYTEST["6.3"]["pre_install"] = ["sed -i 's/>=>=/>=/' setup.cfg"]

SPECS_MATPLOTLIB = {
    k: {
        "python": "3.11",
        "packages": "environment.yml",
        "install": "python -m pip install -e .",
        "pre_install": [
            "apt-get -y update && apt-get -y upgrade && DEBIAN_FRONTEND=noninteractive apt-get install -y imagemagick ffmpeg texlive texlive-latex-extra texlive-fonts-recommended texlive-xetex texlive-luatex cm-super dvipng",
            'QHULL_URL="http://www.qhull.org/download/qhull-2020-src-8.0.2.tgz"',
            'QHULL_TAR="/tmp/qhull-2020-src-8.0.2.tgz"',
            'QHULL_BUILD_DIR="/testbed/build"',
            'wget -O "$QHULL_TAR" "$QHULL_URL"',
            'mkdir -p "$QHULL_BUILD_DIR"',
            'tar -xvzf "$QHULL_TAR" -C "$QHULL_BUILD_DIR"',
        ],
        "pip_packages": [
            "contourpy==1.1.0",
            "cycler==0.11.0",
            "fonttools==4.42.1",
            "ghostscript",
            "kiwisolver==1.4.5",
            "numpy==1.25.2",
            "packaging==23.1",
            "pillow==10.0.0",
            "pikepdf",
            "pyparsing==3.0.9",
            "python-dateutil==2.8.2",
            "six==1.16.0",
            "setuptools==68.1.2",
            "setuptools-scm==7.1.0",
            "typing-extensions==4.7.1",
        ],
        "test_cmd": TEST_PYTEST,
    }
    for k in ["3.5", "3.6", "3.7", "3.8", "3.9"]
}
SPECS_MATPLOTLIB.update(
    {
        k: {
            "python": "3.8",
            "packages": "requirements.txt",
            "install": "python -m pip install -e .",
            "pre_install": [
                "apt-get -y update && apt-get -y upgrade && DEBIAN_FRONTEND=noninteractive apt-get install -y imagemagick ffmpeg libfreetype6-dev pkg-config texlive texlive-latex-extra texlive-fonts-recommended texlive-xetex texlive-luatex cm-super",
                'QHULL_URL="http://www.qhull.org/download/qhull-2020-src-8.0.2.tgz"',
                'QHULL_TAR="/tmp/qhull-2020-src-8.0.2.tgz"',
                'QHULL_BUILD_DIR="/testbed/build"',
                'wget -O "$QHULL_TAR" "$QHULL_URL"',
                'mkdir -p "$QHULL_BUILD_DIR"',
                'tar -xvzf "$QHULL_TAR" -C "$QHULL_BUILD_DIR"',
            ],
            "pip_packages": ["pytest", "ipython"],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["3.1", "3.2", "3.3", "3.4"]
    }
)
SPECS_MATPLOTLIB.update(
    {
        k: {
            "python": "3.7",
            "packages": "requirements.txt",
            "install": "python -m pip install -e .",
            "pre_install": [
                "apt-get -y update && apt-get -y upgrade && apt-get install -y imagemagick ffmpeg libfreetype6-dev pkg-config",
                'QHULL_URL="http://www.qhull.org/download/qhull-2020-src-8.0.2.tgz"',
                'QHULL_TAR="/tmp/qhull-2020-src-8.0.2.tgz"',
                'QHULL_BUILD_DIR="/testbed/build"',
                'wget -O "$QHULL_TAR" "$QHULL_URL"',
                'mkdir -p "$QHULL_BUILD_DIR"',
                'tar -xvzf "$QHULL_TAR" -C "$QHULL_BUILD_DIR"',
            ],
            "pip_packages": ["pytest"],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["3.0"]
    }
)
SPECS_MATPLOTLIB.update(
    {
        k: {
            "python": "3.5",
            "install": "python setup.py build; python setup.py install",
            "pre_install": [
                "apt-get -y update && apt-get -y upgrade && && apt-get install -y imagemagick ffmpeg"
            ],
            "pip_packages": ["pytest"],
            "execute_test_as_nonroot": True,
            "test_cmd": TEST_PYTEST,
        }
        for k in ["2.0", "2.1", "2.2", "1.0", "1.1", "1.2", "1.3", "1.4", "1.5"]
    }
)
for k in ["3.8", "3.9"]:
    SPECS_MATPLOTLIB[k]["install"] = (
        'python -m pip install --no-build-isolation -e ".[dev]"'
    )

SPECS_SPHINX = {
    k: {
        "python": "3.9",
        "pip_packages": ["tox==4.16.0", "tox-current-env==0.0.11", "Jinja2==3.0.3"],
        "install": "python -m pip install -e .[test]",
        "pre_install": ["sed -i 's/pytest/pytest -rA/' tox.ini"],
        "test_cmd": TEST_SPHINX,
    }
    for k in ["1.5", "1.6", "1.7", "1.8", "2.0", "2.1", "2.2", "2.3", "2.4", "3.0"]
    + ["3.1", "3.2", "3.3", "3.4", "3.5", "4.0", "4.1", "4.2", "4.3", "4.4"]
    + ["4.5", "5.0", "5.1", "5.2", "5.3", "6.0", "6.2", "7.0", "7.1", "7.2"]
    + ["7.3", "7.4", "8.0", "8.1"]
}
for k in ["3.0", "3.1", "3.2", "3.3", "3.4", "3.5", "4.0", "4.1", "4.2", "4.3", "4.4"]:
    SPECS_SPHINX[k]["pre_install"].extend(
        [
            "sed -i 's/Jinja2>=2.3/Jinja2<3.0/' setup.py",
            "sed -i 's/sphinxcontrib-applehelp/sphinxcontrib-applehelp<=1.0.7/' setup.py",
            "sed -i 's/sphinxcontrib-devhelp/sphinxcontrib-devhelp<=1.0.5/' setup.py",
            "sed -i 's/sphinxcontrib-qthelp/sphinxcontrib-qthelp<=1.0.6/' setup.py",
            "sed -i 's/alabaster>=0.7,<0.8/alabaster>=0.7,<0.7.12/' setup.py",
            "sed -i \"s/'packaging',/'packaging', 'markupsafe<=2.0.1',/\" setup.py",
        ]
    )
    if k in ["4.2", "4.3", "4.4"]:
        SPECS_SPHINX[k]["pre_install"].extend(
            [
                "sed -i 's/sphinxcontrib-htmlhelp>=2.0.0/sphinxcontrib-htmlhelp>=2.0.0,<=2.0.4/' setup.py",
                "sed -i 's/sphinxcontrib-serializinghtml>=1.1.5/sphinxcontrib-serializinghtml>=1.1.5,<=1.1.9/' setup.py",
            ]
        )
    elif k == "4.1":
        SPECS_SPHINX[k]["pre_install"].extend(
            [
                (
                    "grep -q 'sphinxcontrib-htmlhelp>=2.0.0' setup.py && "
                    "sed -i 's/sphinxcontrib-htmlhelp>=2.0.0/sphinxcontrib-htmlhelp>=2.0.0,<=2.0.4/' setup.py || "
                    "sed -i 's/sphinxcontrib-htmlhelp/sphinxcontrib-htmlhelp<=2.0.4/' setup.py"
                ),
                (
                    "grep -q 'sphinxcontrib-serializinghtml>=1.1.5' setup.py && "
                    "sed -i 's/sphinxcontrib-serializinghtml>=1.1.5/sphinxcontrib-serializinghtml>=1.1.5,<=1.1.9/' setup.py || "
                    "sed -i 's/sphinxcontrib-serializinghtml/sphinxcontrib-serializinghtml<=1.1.9/' setup.py"
                ),
            ]
        )
    else:
        SPECS_SPHINX[k]["pre_install"].extend(
            [
                "sed -i 's/sphinxcontrib-htmlhelp/sphinxcontrib-htmlhelp<=2.0.4/' setup.py",
                "sed -i 's/sphinxcontrib-serializinghtml/sphinxcontrib-serializinghtml<=1.1.9/' setup.py",
            ]
        )
for k in ["7.2", "7.3", "7.4", "8.0", "8.1"]:
    SPECS_SPHINX[k]["pre_install"] += ["apt-get update && apt-get install -y graphviz"]
for k in ["8.0", "8.1"]:
    SPECS_SPHINX[k]["python"] = "3.10"

SPECS_ASTROPY = {
    k: {
        "python": "3.9",
        "install": "python -m pip install -e .[test] --verbose",
        "pip_packages": [
            "attrs==23.1.0",
            "exceptiongroup==1.1.3",
            "execnet==2.0.2",
            "hypothesis==6.82.6",
            "iniconfig==2.0.0",
            "numpy==1.25.2",
            "packaging==23.1",
            "pluggy==1.3.0",
            "psutil==5.9.5",
            "pyerfa==2.0.0.3",
            "pytest-arraydiff==0.5.0",
            "pytest-astropy-header==0.2.2",
            "pytest-astropy==0.10.0",
            "pytest-cov==4.1.0",
            "pytest-doctestplus==1.0.0",
            "pytest-filter-subpackage==0.1.2",
            "pytest-mock==3.11.1",
            "pytest-openfiles==0.5.0",
            "pytest-remotedata==0.4.0",
            "pytest-xdist==3.3.1",
            "pytest==7.4.0",
            "PyYAML==6.0.1",
            "setuptools==68.0.0",
            "sortedcontainers==2.4.0",
            "tomli==2.0.1",
        ],
        "test_cmd": TEST_PYTEST,
    }
    for k in ["3.0", "3.1", "3.2", "4.1", "4.2", "4.3", "5.0", "5.1", "5.2", "v5.3"]
}
SPECS_ASTROPY.update(
    {
        k: {
            "python": "3.6",
            "install": "python -m pip install -e .[test] --verbose",
            "packages": "setuptools==38.2.4",
            "pip_packages": [
                "attrs==17.3.0",
                "exceptiongroup==0.0.0a0",
                "execnet==1.5.0",
                "hypothesis==3.44.2",
                "cython==0.27.3",
                "jinja2==2.10",
                "MarkupSafe==1.0",
                "numpy==1.16.0",
                "packaging==16.8",
                "pluggy==0.6.0",
                "psutil==5.4.2",
                "pyerfa==1.7.0",
                "pytest-arraydiff==0.1",
                "pytest-astropy-header==0.1",
                "pytest-astropy==0.2.1",
                "pytest-cov==2.5.1",
                "pytest-doctestplus==0.1.2",
                "pytest-filter-subpackage==0.1",
                "pytest-forked==0.2",
                "pytest-mock==1.6.3",
                "pytest-openfiles==0.2.0",
                "pytest-remotedata==0.2.0",
                "pytest-xdist==1.20.1",
                "pytest==3.3.1",
                "PyYAML==3.12",
                "sortedcontainers==1.5.9",
                "tomli==0.2.0",
            ],
            "test_cmd": TEST_ASTROPY_PYTEST,
        }
        for k in ["0.1", "0.2", "0.3", "0.4", "1.1", "1.2", "1.3"]
    }
)
for k in ["4.1", "4.2", "4.3", "5.0", "5.1", "5.2", "v5.3"]:
    SPECS_ASTROPY[k]["pre_install"] = [
        'sed -i \'s/requires = \\["setuptools",/requires = \\["setuptools==68.0.0",/\' pyproject.toml'
    ]
for k in ["v5.3"]:
    SPECS_ASTROPY[k]["python"] = "3.10"

# Issues_No_Tests_v2.xlsx additions: recent (2024-2025) PRs against main,
# built with modern astropy's own [test] extra rather than the old pinned
# dep sets above (which target much older astropy commits).
_ASTROPY_TEST_GENERATION_SPEC = {
    "python": "3.11",
    "install": "python -m pip install -e .[test] --verbose",
    # NumPy 2.x removed np.in1d, which these base commits still use while
    # importing Astropy's pytest support.
    "pip_packages": [
        "pytest",
        "numpy==1.26.4",
        "scipy==1.11.4",
        "matplotlib==3.8.4",
        # matplotlib 3.8.4 still calls pyparsing's deprecated parseString();
        # pyparsing>=3.1.2 turns that into a PyparsingDeprecationWarning, and
        # astropy/conftest.py's warnings-as-errors config promotes it into a
        # collection-time ImportError on `import matplotlib`, failing every
        # generated test identically on both base and gold. Pin the last
        # release before that deprecation wrapper was added.
        "pyparsing==3.1.1",
    ],
    "validation_cmd": "python -c 'import astropy; import numpy'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_ASTROPY.update(
    {
        pr: dict(_ASTROPY_TEST_GENERATION_SPEC)
        for pr in ("17209",)
    }
)

SPECS_SYMPY = {
    k: {
        "python": "3.9",
        "packages": "mpmath flake8",
        "pip_packages": ["mpmath==1.3.0", "flake8-comprehensions"],
        "install": "python -m pip install -e .",
        "test_cmd": TEST_SYMPY,
    }
    for k in ["0.7", "1.0", "1.1", "1.10", "1.11", "1.12", "1.2", "1.4", "1.5", "1.6"]
    + ["1.7", "1.8", "1.9"]
    + ["1.10", "1.11", "1.12", "1.13", "1.14"]
}
SPECS_SYMPY.update(
    {
        k: {
            "python": "3.9",
            "packages": "requirements.txt",
            "install": "python -m pip install -e .",
            "pip_packages": ["mpmath==1.3.0"],
            "test_cmd": TEST_SYMPY,
        }
        for k in ["1.13", "1.14"]
    }
)

SPECS_PYLINT = {
    k: {
        "python": "3.9",
        "packages": "requirements.txt",
        "install": "python -m pip install -e .",
        "test_cmd": TEST_PYTEST,
    }
    for k in [
        "2.10",
        "2.11",
        "2.13",
        "2.14",
        "2.15",
        "2.16",
        "2.17",
        "2.8",
        "2.9",
        "3.0",
        "3.1",
        "3.2",
        "3.3",
        "4.0",
    ]
}
SPECS_PYLINT["2.8"]["pip_packages"] = ["pyenchant==3.2"]
SPECS_PYLINT["2.8"]["pre_install"] = [
    "apt-get update && apt-get install -y libenchant-2-dev hunspell-en-us"
]
SPECS_PYLINT.update(
    {
        k: {
            **SPECS_PYLINT[k],
            "pip_packages": ["astroid==3.0.0a6", "setuptools"],
        }
        for k in ["3.0", "3.1", "3.2", "3.3", "4.0"]
    }
)
for v in ["2.14", "2.15", "2.17", "3.0", "3.1", "3.2", "3.3", "4.0"]:
    SPECS_PYLINT[v]["nano_cpus"] = int(2e9)

SPECS_XARRAY = {
    k: {
        "python": "3.10",
        "packages": "environment.yml",
        "install": "python -m pip install -e .",
        "pip_packages": [
            "numpy==1.23.0",
            "packaging==23.1",
            "pandas==1.5.3",
            "pytest==7.4.0",
            "python-dateutil==2.8.2",
            "pytz==2023.3",
            "six==1.16.0",
            "scipy==1.11.1",
            "setuptools==68.0.0",
            "dask==2022.8.1",
        ],
        "no_use_env": True,
        "test_cmd": TEST_PYTEST,
    }
    for k in [
        "0.12",
        "0.18",
        "0.19",
        "0.20",
        "2022.03",
        "2022.06",
        "2022.09",
        "2023.07",
        "2024.05",
    ]
}

SPECS_SQLFLUFF = {
    k: {
        "python": "3.9",
        "packages": "requirements.txt",
        "install": "python -m pip install -e .",
        "test_cmd": TEST_PYTEST,
    }
    for k in [
        "0.10",
        "0.11",
        "0.12",
        "0.13",
        "0.4",
        "0.5",
        "0.6",
        "0.8",
        "0.9",
        "1.0",
        "1.1",
        "1.2",
        "1.3",
        "1.4",
        "2.0",
        "2.1",
        "2.2",
    ]
}

SPECS_DBT_CORE = {
    k: {
        "python": "3.9",
        "packages": "requirements.txt",
        "install": "python -m pip install -e .",
    }
    for k in [
        "0.13",
        "0.14",
        "0.15",
        "0.16",
        "0.17",
        "0.18",
        "0.19",
        "0.20",
        "0.21",
        "1.0",
        "1.1",
        "1.2",
        "1.3",
        "1.4",
        "1.5",
        "1.6",
        "1.7",
    ]
}

SPECS_PYVISTA = {
    k: {
        "python": "3.9",
        "install": "python -m pip install -e .",
        "pip_packages": ["pytest"],
        "test_cmd": TEST_PYTEST,
    }
    for k in ["0.20", "0.21", "0.22", "0.23"]
}
SPECS_PYVISTA.update(
    {
        k: {
            "python": "3.9",
            "packages": "requirements.txt",
            "install": "python -m pip install -e .",
            "pip_packages": ["pytest"],
            "test_cmd": TEST_PYTEST,
            "pre_install": [
                "apt-get update && apt-get install -y ffmpeg libsm6 libxext6 libxrender1"
            ],
        }
        for k in [
            "0.24",
            "0.25",
            "0.26",
            "0.27",
            "0.28",
            "0.29",
            "0.30",
            "0.31",
            "0.32",
            "0.33",
            "0.34",
            "0.35",
            "0.36",
            "0.37",
            "0.38",
            "0.39",
            "0.40",
            "0.41",
            "0.42",
            "0.43",
        ]
    }
)

SPECS_ASTROID = {
    k: {
        "python": "3.9",
        "install": "python -m pip install -e .",
        "pip_packages": ["pytest"],
        "test_cmd": TEST_PYTEST,
    }
    for k in [
        "2.10",
        "2.12",
        "2.13",
        "2.14",
        "2.15",
        "2.16",
        "2.5",
        "2.6",
        "2.7",
        "2.8",
        "2.9",
        "3.0",
    ]
}

SPECS_MARSHMALLOW = {
    k: {
        "python": "3.9",
        "install": "python -m pip install -e '.[dev]'",
        "test_cmd": TEST_PYTEST,
    }
    for k in [
        "2.18",
        "2.19",
        "2.20",
        "3.0",
        "3.1",
        "3.10",
        "3.11",
        "3.12",
        "3.13",
        "3.15",
        "3.16",
        "3.19",
        "3.2",
        "3.4",
        "3.8",
        "3.9",
    ]
}

SPECS_PVLIB = {
    k: {
        "python": "3.9",
        "install": "python -m pip install -e .[all]",
        "packages": "pandas scipy",
        "pip_packages": ["jupyter", "ipython", "matplotlib", "pytest", "flake8"],
        "test_cmd": TEST_PYTEST,
    }
    for k in ["0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9"]
}

SPECS_PYDICOM = {
    k: {
        "python": "3.6",
        "install": "python -m pip install -e .",
        "packages": "numpy",
        "pip_packages": ["pytest"],
        "test_cmd": TEST_PYTEST,
    }
    for k in [
        "1.0",
        "1.1",
        "1.2",
        "1.3",
        "1.4",
        "2.0",
        "2.1",
        "2.2",
        "2.3",
        "2.4",
        "3.0",
    ]
}
SPECS_PYDICOM.update({k: {**SPECS_PYDICOM[k], "python": "3.8"} for k in ["1.4", "2.0"]})
SPECS_PYDICOM.update({k: {**SPECS_PYDICOM[k], "python": "3.9"} for k in ["2.1", "2.2"]})
SPECS_PYDICOM.update({k: {**SPECS_PYDICOM[k], "python": "3.10"} for k in ["2.3"]})
SPECS_PYDICOM.update(
    {k: {**SPECS_PYDICOM[k], "python": "3.11"} for k in ["2.4", "3.0"]}
)

SPECS_HUMANEVAL = {k: {"python": "3.9", "test_cmd": "python"} for k in ["1.0"]}

# scipy — legacy versions (setuptools/numpy.distutils + f2py via setup.py).
# Python 3.8 is the last version supporting these old build chains.
# - pip<24: prevents PEP 660 enforcement on editable installs (setuptools<60 lacks build_editable).
# - setuptools<60: keeps legacy distutils helpers that old setup.py files rely on.
# - export FFLAGS=-fcommon: GCC ≥10 changed default from -fcommon to -fno-common. Old scipy
#   Fortran sources (ARPACK, VODE) have duplicate symbol definitions that -fno-common rejects.
#   Exporting FFLAGS in pre_install makes it available to numpy.distutils at build time.
# - touch *.c trick: scipy 0.x tools/cythonize.py checks mtime(.c) vs mtime(.pyx). Touching
#   all .c files after install makes them look newer than .pyx, so cythonize is skipped on
#   repeat runs. But the first install still runs cythonize. To skip it on the first pass,
#   we touch the .pyx files to a very old date so .c files (already committed at any mtime)
#   appear newer — forcing cythonize.py to skip re-generation and use committed .c files.
#   This avoids "Signature not compatible" (streams.pyx:203) which is a Cython 0.29 strictness
#   issue with syntax used in scipy 0.x .pyx files.
_SCIPY_LEGACY_APT = "apt-get update && apt-get install -y gfortran libopenblas-dev liblapack-dev pkg-config"
# GCC 10+ also rejects ARPACK calls like svout(scalar) vs svout(array) as Rank mismatch.
# -fallow-argument-mismatch downgrades that to a warning so the build proceeds.
_SCIPY_LEGACY_FFLAGS = "export FFLAGS='-fcommon -fallow-argument-mismatch' && export FCFLAGS='-fcommon -fallow-argument-mismatch'"
_SCIPY_LEGACY_PRE_INSTALL = [
    _SCIPY_LEGACY_APT,
    "python -m pip install --no-deps 'pip<24'",
    _SCIPY_LEGACY_FFLAGS,
]
SPECS_SCIPY = {}
# scipy 0.x: streams.pyx uses pre-Cython-0.27 syntax that newer Cython rejects with
# "Signature not compatible". Pin Cython to 0.25 which still accepts the old syntax.
SPECS_SCIPY.update(
    {
        k: {
            "python": "3.8",
            "packages": "numpy cython pytest",
            "pre_install": _SCIPY_LEGACY_PRE_INSTALL,
            "install": "python -m pip install -v --no-build-isolation -e .",
            "pip_packages": ["cython==0.25.2", "setuptools<60", "wheel", "numpy<1.20", "pytest", "pytest-xdist", "pybind11"],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["0.11", "0.12", "0.13", "0.14", "0.15", "0.16", "0.17", "0.19"]
    }
)
# scipy 1.0–1.6: cythonize works fine; only need -fcommon for Fortran linker.
SPECS_SCIPY.update(
    {
        k: {
            "python": "3.8",
            "packages": "numpy cython pytest",
            "pre_install": _SCIPY_LEGACY_PRE_INSTALL,
            "install": "python -m pip install -v --no-build-isolation -e .",
            "pip_packages": ["cython<3", "setuptools<60", "wheel", "numpy<2", "pytest", "pytest-xdist", "pybind11"],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6"]
    }
)
# scipy 1.7–1.8: setuptools-based, Python 3.9; still needs -fcommon for Fortran linker.
SPECS_SCIPY.update(
    {
        k: {
            "python": "3.9",
            "packages": "numpy cython pytest",
            "pre_install": [
                "apt-get update && apt-get install -y gfortran pkg-config libopenblas-dev",
                "git submodule update --init",
                _SCIPY_LEGACY_FFLAGS,
            ],
            "install": "python -m pip install -v --no-build-isolation -e .",
            "pip_packages": ["cython<3", "setuptools", "numpy<2", "pybind11", "pythran", "pytest", "pytest-xdist"],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["1.7", "1.8"]
    }
)
# scipy 1.9–1.10: repo already has pyproject.toml+meson; the setuptools path fails with
# "BackendUnavailable: Cannot import 'mesonpy'". Use meson-python like 1.11.
SPECS_SCIPY.update(
    {
        k: {
            "python": "3.11",
            "packages": "numpy cython pytest",
            "pre_install": [
                "apt-get update && apt-get install -y gfortran pkg-config libopenblas-dev",
                "git submodule update --init",
                _SCIPY_LEGACY_FFLAGS,
            ],
            "install": "python -m pip install --no-build-isolation -e .",
            "pip_packages": [
                "meson-python", "ninja", "pybind11", "pythran",
                "numpy>=1.22,<2.0", "cython>=0.29.33", "pytest", "pytest-xdist", "pooch",
            ],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["1.9", "1.10"]
    }
)
# scipy — meson-based (1.11–1.13): Python 3.11
SPECS_SCIPY.update(
    {
        k: {
            "python": "3.11",
            "packages": "numpy cython pytest",
            "pre_install": [
                "apt-get update && apt-get install -y gfortran pkg-config libopenblas-dev",
                "git submodule update --init",
                _SCIPY_LEGACY_FFLAGS,
            ],
            "install": "python -m pip install --no-build-isolation -e .",
            "pip_packages": [
                "meson-python", "ninja", "pybind11", "pythran",
                "numpy>=1.22,<2.0", "cython>=0.29.33", "pytest", "pytest-xdist", "pooch",
            ],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["1.11", "1.12", "1.13"]
    }
)
# scipy — meson-based (1.14+): Python 3.12
SPECS_SCIPY.update(
    {
        k: {
            "python": "3.12",
            "packages": "numpy cython pytest",
            "pre_install": [
                "apt-get update && apt-get install -y gfortran pkg-config libopenblas-dev",
                "git submodule update --init",
                _SCIPY_LEGACY_FFLAGS,
            ],
            "install": "python -m pip install --no-build-isolation -e .",
            "pip_packages": [
                "meson-python", "ninja", "pybind11", "pythran",
                "numpy>=2.0", "cython>=3.0", "pytest", "pytest-xdist", "pooch",
            ],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["1.14", "1.15", "1.16", "1.17", "1.18", "1.19"]
    }
)

# numpy — old versions (pre-meson, setuptools-based).
# numpy.distutils was removed in Python 3.12, so old versions must use ≤3.10.
# setuptools >=60 removed legacy distutils helpers these versions rely on, so pin <60.
# pip>=24 requires the PEP 660 `build_editable` hook for `-e .`, which
# setuptools<60 does not implement — so we must pin pip<24 to allow legacy
# editable installs to succeed. Editable mode is required so that patches
# applied to /testbed/numpy/* take effect at test time.
_NUMPY_LEGACY_PRE_INSTALL = [
    # glibc 2.26+ removed xlocale.h; old numpy C sources include it. Symlink locale.h.
    "apt-get update && apt-get install -y gcc gfortran libopenblas-dev liblapack-dev pkg-config",
    "ln -sf /usr/include/locale.h /usr/include/xlocale.h",
    "python -m pip install --no-deps 'pip<24'",
]
# version='0' covers very old PRs (2012–2019) whose version tag was unresolvable.
# They span numpy 1.7–1.16 era; use Python 3.8 + legacy pip/setuptools.
SPECS_NUMPY = {
    "0": {
        "python": "3.8",
        "packages": "numpy cython pytest",
        "pre_install": _NUMPY_LEGACY_PRE_INSTALL,
        "install": "python -m pip install -v --no-build-isolation -e .",
        "pip_packages": [
            "cython<3", "setuptools<60", "wheel", "pytest", "pytest-xdist",
        ],
        "test_cmd": TEST_PYTEST,
    },
}
SPECS_NUMPY.update(
    {
        k: {
            "python": "3.9" if k in ("1.17", "1.20", "1.22") else "3.10",
            "packages": "numpy cython pytest",
            "pre_install": _NUMPY_LEGACY_PRE_INSTALL,
            "install": "python -m pip install -v --no-build-isolation -e .",
            "pip_packages": [
                "cython<3", "setuptools<60", "wheel", "pytest", "pytest-xdist",
            ],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["1.17", "1.18", "1.19", "1.20", "1.21", "1.22", "1.23", "1.24", "1.25"]  # 1.25 still uses numpy.distutils
    }
)
# numpy — modern versions use meson-python build system, require Python 3.12+.
# The vendored meson lives in a git submodule; init it before pip can use it.
# meson detects BLAS via pkg-config; install openblas + pkg-config (and cmake fallback).
_NUMPY_MESON_PRE_INSTALL = [
    "apt-get update && apt-get install -y gfortran pkg-config cmake libopenblas-dev liblapack-dev",
    "git submodule update --init --recursive || true",
]
SPECS_NUMPY.update(
    {
        k: {
            "python": "3.12",
            "packages": "cython pytest",
            "pre_install": _NUMPY_MESON_PRE_INSTALL,
            "install": "python -m pip install --no-build-isolation -e .",
            "pip_packages": [
                "meson-python", "ninja", "cython", "pytest", "pytest-xdist",
            ],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["1.26", "2.0", "2.1", "2.2", "2.3", "2.4", "2.5"]
    }
)

# pandas — modern versions use meson-python build system, require Python 3.12+
_PANDAS_MESON_PRE_INSTALL = [
    # pandas meson build calls `generate_version.py --print`, which does:
    #   sys.path.insert(0, "")
    #   try: import _version_meson
    #   except ImportError: versioneer.get_version()
    # versioneer fails when the checkout has no annotated tag. Belt-and-suspenders:
    # (1) create a synthetic annotated tag so versioneer can succeed if it runs;
    # (2) pre-seed `_version_meson.py` at the repo root (cwd of generate_version.py)
    #     so the `try: import _version_meson` branch short-circuits versioneer entirely.
    "git -c user.email=ci@swebench -c user.name=swebench tag -a v0.0.0 -m stub 2>/dev/null || true",
    "printf '__version__=\"0.0.0+stub\"\\n__git_version__=\"unknown\"\\n' > _version_meson.py",
    "printf '__version__=\"0.0.0+stub\"\\n__git_version__=\"unknown\"\\n' > pandas/_version_meson.py",
]
SPECS_PANDAS = {
    k: {
        "python": "3.12",
        "packages": "numpy cython pytest",
        "pre_install": _PANDAS_MESON_PRE_INSTALL,
        "install": "python -m pip install --no-build-isolation -e .",
        "pip_packages": [
            "meson-python", "ninja", "cython", "numpy",
            "python-dateutil", "pytz", "pytest", "pytest-xdist", "hypothesis",
        ],
        "test_cmd": TEST_PYTEST,
    }
    for k in ["1.5", "2.0", "2.1", "2.2", "3.0"]
}
# pandas — old versions (pre-meson, setuptools-based)
# These setup.py files contain non-PEP-440 install_requires specs (e.g. "pytz >= 2011k").
# Modern setuptools rejects them, and modern pip>=24 requires PEP 660 for editable
# installs. Pin both to legacy versions to allow `pip install -e .` to succeed.
_PANDAS_LEGACY_PRE_INSTALL = [
    "python -m pip install --no-deps 'pip<24'",
]
SPECS_PANDAS.update(
    {
        k: {
            "python": "3.8",
            "packages": "numpy cython pytest",
            "pre_install": _PANDAS_LEGACY_PRE_INSTALL,
            "install": "python -m pip install -v --no-build-isolation -e .",
            "pip_packages": ["cython<3", "setuptools<58", "numpy", "python-dateutil", "pytz", "pytest"],
            "test_cmd": TEST_PYTEST,
        }
        for k in ["0.6", "0.24", "1.0", "1.3"]
    }
)
# pandas 3.1 (same meson-python setup as 3.0)
SPECS_PANDAS.update(
    {
        "3.1": {
            "python": "3.12",
            "packages": "numpy cython pytest",
            "pre_install": _PANDAS_MESON_PRE_INSTALL,
            "install": "python -m pip install --no-build-isolation -e .",
            "pip_packages": [
                "meson-python", "ninja", "cython", "numpy",
                "python-dateutil", "pytz", "pytest", "pytest-xdist", "hypothesis",
            ],
            "test_cmd": TEST_PYTEST,
        },
    }
)

SPECS_MDTRAJ = {
    k: {
        "python": "3.11",
        # Use pkgs/main only — avoids pkgs/r and pkgs/msys2 which time out on restricted networks
        "conda_channels": ["https://repo.anaconda.com/pkgs/main"],
        "install": "pip install -e . --no-build-isolation",
        "pip_packages": [
            "versioneer", "cython>=3.0", "numpy>=2.0,<3", "setuptools", "wheel",
            "scipy", "pandas", "networkx", "pyparsing", "netCDF4",
            "tables", "gsd>=2.8", "pytest", "pytest-xdist",
        ],
        "test_cmd": TEST_PYTEST,
    }
    for k in ["1.9", "1.10", "1.11"]
}


_BIOPYTHON_TEST_GENERATION_SPEC = {
    "python": "3.9",
    "packages": "pytest",
    "pip_packages": ["pytest"],
    "install": "python -m pip install --no-build-isolation -e .",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}

SPECS_BIOPYTHON = {
    pr: dict(_BIOPYTHON_TEST_GENERATION_SPEC)
    for pr in ("3761",)
}


# Issues_No_Tests_v2.xlsx: PRs 2620/2132/1896/1769 only touch
# deepchem/{hyper,dock,metrics,feat,data} -- none require the heavy optional
# torch/tensorflow/jax/dqc extras, so the plain base install is sufficient.
_DEEPCHEM_TEST_GENERATION_SPEC = {
    "python": "3.8",
    # deepchem/models/tensorgraph/tensor_graph.py does
    # `from tensorflow.python.pywrap_tensorflow_internal import
    # NewCheckpointReader` at import time (pulled in unconditionally via
    # deepchem/__init__.py -> deepchem.metalearning -> deepchem.models ->
    # deepchem.models.tensorgraph, same forced-import pattern as the
    # scipy.linalg.pinv2 issue below). That symbol was a TF1-era internal
    # export; TF2.x (including the pinned 2.13.1) never re-exposes it from
    # pywrap_tensorflow_internal, only as the public, stable
    # `tensorflow.train.NewCheckpointReader`. Since these 4 PRs never
    # exercise TensorGraph, permanently append a re-export shim to the
    # installed pywrap_tensorflow_internal.py file after tensorflow-cpu is
    # installed (pip_packages install runs before this `install` step) --
    # editing the file on disk, not `setattr` in-process, because
    # validation/test commands each start a fresh interpreter. Idempotency
    # and "is it actually importable" are both checked the same way the
    # symbol will really be used (`python -c "from ... import
    # NewCheckpointReader"`, not a text grep, which could false-positive on
    # an unrelated string/comment containing the same name) so a rerun or a
    # future TF version that already provides the symbol is a no-op.
    "install": (
        "python -m pip install -e . && "
        "if ! python -c 'from tensorflow.python.pywrap_tensorflow_internal "
        "import NewCheckpointReader' 2>/dev/null; then "
        "TF_INTERNAL=$(python -c 'import tensorflow.python.pywrap_tensorflow_internal as m; print(m.__file__)') && "
        "printf '%s\\n' "
        "'' "
        "'# swebench shim: TF2 moved this symbol to tensorflow.train.NewCheckpointReader' "
        "'from tensorflow.train import NewCheckpointReader' "
        ">> \"$TF_INTERNAL\"; fi"
    ),
    # These old DeepChem setup.py files do not declare their runtime/test
    # dependencies.  In particular, importing deepchem eagerly imports the
    # TensorFlow-backed modules.
    #
    # pyGPGO is intentionally omitted: deepchem.hyper.gaussian_process only
    # imports it lazily inside GaussianProcessHyperparamOpt.fit (behind a
    # try/except ImportError), and pyGPGO==0.1.2 has since been pulled from
    # PyPI (only 0.1.0.dev1/0.3.0.dev1/0.4.0.dev1/0.5.0/0.5.1 remain, and
    # 0.5.x restructured the pyGPGO.covfunc/GPGO module layout the pinned
    # code path expects). Since these PRs only touch
    # deepchem/{hyper,dock,metrics,feat,data} and never exercise
    # GaussianProcessHyperparamOpt, the package isn't needed here.
    "pip_packages": [
        "pytest",
        "numpy==1.23.5",
        "pandas==1.5.3",
        # scipy>=1.9 removed scipy.linalg.pinv2, which
        # sklearn==0.22.2.post1's cross_decomposition._pls still imports at
        # module load time (deepchem/models/sklearn_models pulls this in
        # unconditionally). 1.8.1 is the last 1.8.x release and still
        # supports Python 3.8 / numpy 1.23.5.
        "scipy==1.8.1",
        "tensorflow-cpu==2.13.1",
        "tensorflow-probability==0.21.0",
        "flaky==3.8.1",
        "joblib==1.4.2",
        "rdkit==2023.9.6",
        # deepchem/utils/save.py does `from sklearn.externals import
        # joblib as old_joblib` at import time. sklearn.externals.joblib was
        # removed in scikit-learn 0.23 (2020); 0.22.2.post1 is the last
        # release that still ships it, and it's the import chain
        # deepchem/data/datasets.py pulls in unconditionally.
        "scikit-learn==0.22.2.post1",
    ],
    "validation_cmd": "python -c 'import deepchem'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_DEEPCHEM = {
    pr: dict(_DEEPCHEM_TEST_GENERATION_SPEC)
    for pr in ("2132", "1896", "1769")
}


# Issues_No_Tests_v2.xlsx: qutip PRs span 3 build eras.
# - "modern" (PRs 2303 through 2582, 2023-2024): setuptools.build_meta +
#   Cython-built C extensions (qutip/cy/*.pyx or qutip/core/data/*.pyx),
#   needs a C compiler but otherwise a normal `pip install -e .`.
# - "legacy" (PRs 1195 through 2011, 2020-2022): isolated build metadata
#   requests dependencies incompatible with the Python needed by the commit.
# - "ancient" (PRs 259, 428, 2014-2016): pre-setuptools numpy.distutils
#   build (qutip 3.x), requires old numpy/Python since numpy.distutils was
#   removed in numpy>=1.26 and Python 3.12.
_QUTIP_MODERN_TEST_GENERATION_SPEC = {
    "python": "3.11",
    "pre_install": ["apt-get update -q", "apt-get install -y --no-install-recommends gcc g++"],
    "install": "python -m pip install -e .",
    # Keep the ABI/API versions used by the 2021-2024 QuTiP commits. Newer
    # NumPy/SciPy releases removed numpy.__config__ fields and sph_harm.
    "pip_packages": [
        "pytest",
        "cython<3.1",
        "numpy==1.25.2",
        "scipy==1.11.4",
        # This build era's setup.py calls packaging.version.LegacyVersion,
        # which was removed in packaging 22.0; without this pin pip resolves
        # the current (>=22) release and the editable install fails at
        # "Getting requirements to build editable".
        "packaging<22",
    ],
    "validation_cmd": "python -c 'import qutip'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
_QUTIP_LEGACY_TEST_GENERATION_SPEC = {
    "python": "3.9",
    "pre_install": ["apt-get update -q", "apt-get install -y --no-install-recommends gcc g++"],
    # Historical QuTiP pyproject files request build-only NumPy/packaging
    # versions that cannot run on the selected Python. Use the already pinned
    # environment instead of letting pip create an incompatible isolated one.
    "install": "python -m pip install --no-build-isolation -e .",
    "pip_packages": [
        "pytest",
        "cython==0.29.37",
        # numpy>=1.22 wheels switched their bundled OpenBLAS build to the
        # ILP64 naming scheme and no longer expose numpy.__config__.blas_opt_info
        # (only openblas64__info/blas_ilp64_opt_info). This build era's
        # qutip/_mkl/utilities.py._blas_info() reads config.blas_opt_info
        # directly at import time, so anything >=1.22 raises AttributeError
        # for every instance in this spec. 1.21.6 is the last release whose
        # wheel still sets blas_opt_info, and satisfies scipy==1.10.1's
        # numpy<1.27.0,>=1.19.5 requirement.
        "numpy==1.21.6",
        "scipy==1.10.1",
        "packaging<22",
        "setuptools<69",
        "wheel",
    ],
    "validation_cmd": "python -c 'import qutip'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_QUTIP = {
    **{
        pr: dict(_QUTIP_MODERN_TEST_GENERATION_SPEC)
        for pr in ("2466",)
    },
    **{
        pr: dict(_QUTIP_LEGACY_TEST_GENERATION_SPEC)
        for pr in ("1195",)
    },
}


# Issues_No_Tests_v2.xlsx: qiskit-terra's core is a PyO3/Rust extension
# (qiskit._accelerate) built via setuptools-rust; both target PRs (2024-era,
# rust-version = "1.70" per Cargo.toml) need a Rust toolchain regardless of
# which Python files they touch, since the package must import cleanly.
# Use rustup rather than the distro-packaged rustc to guarantee a
# sufficiently recent compiler.
_QISKIT_TEST_GENERATION_SPEC = {
    "python": "3.11",
    "pre_install": [
        "apt-get update -q",
        "apt-get install -y --no-install-recommends curl build-essential",
        "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | "
        "sh -s -- -y --default-toolchain stable",
    ],
    "install": (
        '. "$HOME/.cargo/env" && '
        "python -m pip install -e . --no-build-isolation"
    ),
    "pip_packages": ["pytest", "setuptools-rust", "ddt==1.7.2"],
    "validation_cmd": "python -c 'import ddt; import qiskit'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_QISKIT = {
    pr: dict(_QISKIT_TEST_GENERATION_SPEC)
    for pr in ("12387",)
}

# ---------------------------------------------------------------------------
# Issues_No_Tests_new.xlsx additions (2026-09-09).
# Per-PR eval test specs keyed by pull_number for the 68 new instances that
# lacked one. Static authoring (verify-later): Python version and dependency
# pins chosen for each repo's build era; every target PR touches only Python
# source, so a plain editable install of the base checkout is sufficient
# unless the repo ships compiled extensions (pyscf).
# ---------------------------------------------------------------------------

# qiskit-terra build eras (verified against setup.py at each base commit):
#  - 845 (0.6.0, 2018): setup.py.in template + CMake-built C++ simulator; a
#    plain `pip install -e .` cannot work. Non-evaluable until the CMake
#    build is curated.
#  - 1940 / 3419 / 4803 / 5166 (2019-2020, terra 0.8-0.16): Cython-only
#    setuptools build, `setup_requires=['Cython>=0.27.1']`, no Rust/CMake.
#    Test suite is unittest-based (QiskitTestCase -> fixtures/testtools),
#    normally run via stestr; pytest collects it fine. `ddt` is required for
#    the parametrised tests.
#  - 8447 / 10866 (2022-2023): setuptools-rust build (qiskit._accelerate),
#    needs a Rust toolchain -> reuse _QISKIT_TEST_GENERATION_SPEC.
#  - 12387 already curated; 15604 / 16103 (2026, PyO3 core) -> Rust toolchain.
_QISKIT_CYTHON_SPEC = {
    "python": "3.8",
    "install": (
        "python -m pip install 'Cython<3' 'setuptools<66' wheel && "
        "python -m pip install -e . --no-build-isolation"
    ),
    "pip_packages": [
        "pytest",
        "ddt==1.4.4",
        "fixtures",
        "testtools",
        "numpy==1.21.6",
        "scipy==1.7.3",
        "sympy==1.9",
        "retworkx==0.11.0",
        "python-constraint>=1.4",
        "python-dateutil",
    ],
    "validation_cmd": "python -c 'import ddt; import qiskit'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_QISKIT["845"] = {
    "python": "3.8",
    "install": "true",
    "test_cmd": (
        "echo 'qiskit#845 not evaluable: terra 0.6.0 setup.py.in + CMake "
        "C++ simulator build needs curation' && false"
    ),
    "_curation_todo": "terra 0.6.0 CMake C++ simulator build",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_QISKIT.update(
    {pr: dict(_QISKIT_CYTHON_SPEC) for pr in ("1940", "3419", "4803", "5166")}
)
SPECS_QISKIT.update(
    {
        pr: dict(_QISKIT_TEST_GENERATION_SPEC)  # setuptools-rust / PyO3 era
        for pr in ("8447", "10866", "15604", "16103")
    }
)

# qutip:
#  - 1058 (2019, QuTiP 4.4): Cython at setup import; reuse the legacy 4.x
#    template (cython 0.29 / numpy 1.21 / --no-build-isolation).
#  - 2574 (2024) & 2826 (2026, QuTiP 5.x): pyproject requires numpy>=2 for
#    the build and setuptools>=77 (2826); the existing "modern" template
#    pins numpy 1.25 / packaging<22, which is wrong here.
_QUTIP_5X_TEST_GENERATION_SPEC = {
    "python": "3.11",
    "pre_install": [
        "apt-get update -q",
        "apt-get install -y --no-install-recommends gcc g++",
    ],
    "install": "python -m pip install -e .",
    "pip_packages": [
        "pytest",
        "cython>=0.29.20",
        "numpy>=2.0",
        "scipy>=1.9",
        "setuptools>=77.0.3",
    ],
    "validation_cmd": "python -c 'import qutip'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_QUTIP.update(
    {
        "1058": dict(_QUTIP_LEGACY_TEST_GENERATION_SPEC),
        "2574": dict(_QUTIP_5X_TEST_GENERATION_SPEC),
        "2826": dict(_QUTIP_5X_TEST_GENERATION_SPEC),
    }
)

# astropy: verified python_requires at each base commit.
#  - 5612 (2016, astropy 1.3-dev, py2.7/3.4-3.5), 6045/6400 (2017, astropy
#    2.0-3.0), 8108/8111 (2018, astropy 3.1, py3.5-3.7): reuse the proven
#    pinned pre-4.0 dict from the existing "0.1..1.3" block (py3.6 + numpy
#    1.16 + Cython 0.27.3).
#  - 9079 (2019, astropy 4.0-dev, requires-python>=3.6, numpy>=1.13): py3.8
#    + numpy 1.19 + Cython 0.29.
#  - 12525 (2021, py>=3.8, numpy>=1.18, scipy>=1.3), 16529 (2024, py>=3.10,
#    numpy>=1.23/build numpy>=2.0rc1): modern [test] extra.
_ASTROPY_PRE4_GEN_SPEC = {
    **SPECS_ASTROPY["1.3"],  # py3.6 / setuptools 38.2.4 / numpy 1.16 / Cython 0.27.3
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
_ASTROPY_4X_GEN_SPEC = {
    "python": "3.8",
    "install": "python -m pip install -e .[test] --verbose",
    "pre_install": [
        "python -m pip install 'setuptools<60' 'setuptools_scm<7' wheel "
        "'Cython<3' 'numpy==1.19.5'",
    ],
    "pip_packages": [
        "pytest==7.1.2",
        "numpy==1.19.5",
        "pyerfa==2.0.0.1",
        "PyYAML==6.0",
        "packaging==21.3",
    ],
    "validation_cmd": "python -c 'import astropy; import numpy'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
_ASTROPY_5X_GEN_SPEC = {
    "python": "3.11",
    "install": "python -m pip install -e .[test] --verbose",
    "pip_packages": [
        "pytest",
        "numpy==1.26.4",
        "scipy==1.11.4",
        "pyparsing==3.1.1",
    ],
    "validation_cmd": "python -c 'import astropy; import numpy'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_ASTROPY.update(
    {
        pr: dict(_ASTROPY_PRE4_GEN_SPEC)
        for pr in ("5612", "6045", "6400", "8108", "8111")
    }
)
SPECS_ASTROPY["9079"] = dict(_ASTROPY_4X_GEN_SPEC)
SPECS_ASTROPY.update(
    {pr: dict(_ASTROPY_5X_GEN_SPEC) for pr in ("12525", "16529")}
)

# pyscf: setup.py runs CMake at install to build/download libcint + libxc
# (needs a compiler, gfortran, cmake, BLAS and network). PRs touch only
# Python.  551 = pyscf 1.7.1 (2020); 794/1143/1164/1219 = 2021-2022
# (classifiers py3.6-3.9).
_PYSCF_BASE_PRE_INSTALL = [
    "apt-get update -q",
    "apt-get install -y --no-install-recommends "
    "gcc g++ gfortran cmake make curl libblas-dev liblapack-dev",
]
_PYSCF_17_GEN_SPEC = {
    "python": "3.8",
    "pre_install": _PYSCF_BASE_PRE_INSTALL
    + ["python -m pip install 'numpy==1.21.6' 'setuptools<60' wheel cmake"],
    "install": "python -m pip install -e . --no-build-isolation",
    "pip_packages": ["pytest", "numpy==1.21.6", "scipy==1.7.3", "h5py==3.1.0"],
    "validation_cmd": "python -c 'import pyscf'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
_PYSCF_2X_GEN_SPEC = {
    "python": "3.9",
    "pre_install": _PYSCF_BASE_PRE_INSTALL
    + ["python -m pip install 'numpy==1.23.5' setuptools wheel cmake"],
    "install": "python -m pip install -e . --no-build-isolation",
    "pip_packages": ["pytest", "numpy==1.23.5", "scipy==1.9.3", "h5py==3.7.0"],
    "validation_cmd": "python -c 'import pyscf'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_PYSCF = {"551": dict(_PYSCF_17_GEN_SPEC)}
SPECS_PYSCF.update(
    {pr: dict(_PYSCF_2X_GEN_SPEC) for pr in ("794", "1143", "1164", "1219")}
)

# obspy: verified python classifiers at base commits.
#  - 956 (2015, obspy 0.10): Python 2.6/2.7/3.3/3.4 only -> cannot build on
#    any harness Python. Non-evaluable.
#  - 2560 / 2570 (2020, obspy 1.1/1.2): Python 3.4-3.8, setup.py uses
#    numpy.distutils (removed in numpy>=1.26 / py3.12). Build on Python 3.8
#    with numpy pinned and installed before the editable build.
_OBSPY_GEN_SPEC = {
    "python": "3.8",
    "pre_install": [
        "apt-get update -q",
        "apt-get install -y --no-install-recommends gcc gfortran",
        # numpy.distutils must exist and NumPy must be importable before
        # `pip install -e .` runs setup.py.
        "python -m pip install 'numpy==1.21.6' 'setuptools<60' wheel",
    ],
    "install": "python -m pip install -e . --no-build-isolation",
    "pip_packages": [
        "pytest",
        "numpy==1.21.6",
        "scipy==1.7.3",
        "matplotlib==3.5.3",
        "lxml==4.9.2",
        "sqlalchemy==1.4.46",
        "requests==2.28.2",
        "decorator==5.1.1",
    ],
    "validation_cmd": "python -c 'import obspy'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_OBSPY = {pr: dict(_OBSPY_GEN_SPEC) for pr in ("2560", "2570")}
SPECS_OBSPY["956"] = {
    "python": "3.8",
    "install": "true",
    "test_cmd": (
        "echo 'obspy#956 not evaluable: obspy 0.10 supports only "
        "Python 2.6-3.4' && false"
    ),
    "_curation_todo": "obspy 0.10 legacy Python",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}

# psi4: PR 2453 (2022) touches only psi4/driver/procrouting (pure Python).
# The compiled core is heavy; install the conda-forge binary and run the
# generated test against the Python driver layer.
_PSI4_GEN_SPEC = {
    "python": "3.9",
    "conda_channels": ["conda-forge"],
    "install": "conda install -y -c conda-forge psi4 && python -m pip install -e . --no-deps --no-build-isolation || true",
    "pip_packages": ["pytest", "numpy==1.23.5"],
    "validation_cmd": "python -c 'import psi4'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_PSI4 = {"2453": dict(_PSI4_GEN_SPEC)}
# PRs 1244 (2018) & 3005 (2023) touch compiled C++ (dfocc / libfock). Building
# psi4 from source is a multi-hour CMake job; mark non-evaluable until a
# curated base image + ctest target exists.
SPECS_PSI4.update(
    {
        pr: {
            "python": "3.9",
            "install": "true",
            "test_cmd": (
                f"echo 'psi4#{pr} not evaluable: needs psi4 source-build "
                f"image + ctest target' && false"
            ),
            "_curation_todo": "psi4 source build image + ctest target",
            "oracle_kind": "generated_test",
            "test_generation_capabilities": ("cpp",),
        }
        for pr in ("1244", "3005")
    }
)

# scanpy: pure-Python, four distinct dependency eras (verified against
# setup.py / pyproject.toml at each base commit):
#  - 1464 (2020, scanpy 1.6, py>=3.6, pandas 1.x): flat layout, [test] extra.
#  - 2832 (2024-01, scanpy 1.9.8, py>=3.9, pandas>=2.1.3, anndata>=0.7.4):
#    numba must match numpy; use numba 0.59 / numpy 1.26.
#  - 3771 (2025, scanpy 1.11, py>=3.11, src/ layout).
#  - 4231 (2026, scanpy 1.12-dev, py>=3.12, numpy>=2.1, scipy>=1.15).
_SCANPY_16_SPEC = {
    "python": "3.8",
    "install": "python -m pip install -e .[test]",
    "pip_packages": [
        "pytest",
        "numpy==1.21.6",
        "scipy==1.7.3",
        "pandas==1.3.5",
        "anndata==0.7.8",
        "scikit-learn==1.0.2",
        "numba==0.55.2",
        "llvmlite==0.38.1",
        "matplotlib==3.5.3",
        "h5py==3.7.0",
        "networkx==2.6.3",
        "natsort",
        "joblib",
        "patsy",
        "statsmodels",
        "tables",
    ],
    "validation_cmd": "python -c 'import scanpy'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
_SCANPY_198_SPEC = {
    "python": "3.10",
    "install": "python -m pip install -e .[test]",
    "pip_packages": [
        "pytest",
        "numpy==1.26.4",
        "scipy==1.11.4",
        "pandas==2.1.4",
        "anndata==0.10.5",
        "scikit-learn==1.3.2",
        "numba==0.59.1",
        "matplotlib==3.8.2",
        "h5py==3.10.0",
        "networkx==3.2.1",
        "natsort",
        "joblib",
        "session-info",
        "legacy-api-wrap",
    ],
    "validation_cmd": "python -c 'import scanpy'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
_SCANPY_111_SPEC = {  # 3771 (2025, scanpy 1.11, py3.11-3.13)
    "python": "3.11",
    "install": "python -m pip install -e .[test]",
    "pip_packages": ["pytest", "numpy<2.2", "scipy", "pandas", "anndata", "scikit-learn", "numba", "matplotlib", "legacy-api-wrap", "session-info", "h5py", "natsort", "joblib"],
    "validation_cmd": "python -c 'import scanpy'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
_SCANPY_112_SPEC = {  # 4231 (2026, scanpy >=1.12 dev, requires-python>=3.12)
    **_SCANPY_111_SPEC,
    "python": "3.12",
    "pip_packages": ["pytest", "numpy>=2.1", "scipy>=1.15", "pandas", "anndata", "scikit-learn", "numba", "matplotlib", "legacy-api-wrap", "session-info2", "h5py", "natsort", "joblib"],
}
SPECS_SCANPY = {
    "1464": dict(_SCANPY_16_SPEC),
    "2832": dict(_SCANPY_198_SPEC),
    "3771": dict(_SCANPY_111_SPEC),
    "4231": dict(_SCANPY_112_SPEC),
}

# sunpy:
#  - 1505 (2015, sunpy 0.6): Python 2.7 / early 3.x, numpy.distutils era.
#    Non-evaluable on harness Pythons.
#  - 4260 (2020, sunpy 2.0, py3.6-3.8): modern setuptools_scm build.
_SUNPY_GEN_SPEC = {
    "python": "3.8",
    "install": "python -m pip install -e .[all,tests]",
    "pip_packages": [
        "pytest",
        "numpy==1.21.6",
        "scipy==1.7.3",
        "astropy==4.3.1",
        "matplotlib==3.5.3",
        "pandas==1.3.5",
        "parfive==1.5.1",
    ],
    "validation_cmd": "python -c 'import sunpy'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_SUNPY = {"4260": dict(_SUNPY_GEN_SPEC)}
SPECS_SUNPY["1505"] = {
    "python": "3.8",
    "install": "true",
    "test_cmd": (
        "echo 'sunpy#1505 not evaluable: sunpy 0.6 (2015) predates "
        "supported Python' && false"
    ),
    "_curation_todo": "sunpy 0.6 legacy Python",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}

# yt: pure-Python + Cython C extensions built at install.
#  - 2128 (2019) / 2485 (2020): yt 3.5/3.6, classifiers only 3.4/3.5,
#    setup.py hard-checks Cython>=0.24 / numpy>=1.10; builds fail on a
#    modern toolchain. Non-evaluable pending a curated py3.7 + old-numpy env.
#  - 3532 / 3556 (2021): yt 4.0, py3.6-3.9.
#  - 5221 (2025): yt 4.4+, py>=3.10, numpy 2.
_YT_40_GEN_SPEC = {
    "python": "3.9",
    "pre_install": [
        "apt-get update -q",
        "apt-get install -y --no-install-recommends gcc g++",
        "python -m pip install 'cython<3' 'numpy==1.21.6' 'setuptools<66' wheel",
    ],
    "install": "python -m pip install -e . --no-build-isolation",
    "pip_packages": [
        "pytest",
        "cython<3",
        "numpy==1.21.6",
        "scipy==1.7.3",
        "matplotlib==3.5.3",
        "sympy==1.9",
        "unyt==2.8.0",
        "more-itertools==8.13.0",
        "packaging==21.3",
        "tomli==2.0.1",
    ],
    "validation_cmd": "python -c 'import yt'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
_YT_MODERN_GEN_SPEC = {
    "python": "3.11",
    "pre_install": [
        "apt-get update -q",
        "apt-get install -y --no-install-recommends gcc g++",
    ],
    "install": "python -m pip install -e . --no-build-isolation",
    "pip_packages": ["pytest", "cython>=3.0.3", "numpy>=2.0", "setuptools>=61.2", "scipy", "matplotlib", "sympy", "unyt", "more-itertools", "packaging", "ewah-bool-utils"],
    "validation_cmd": "python -c 'import yt'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
_YT_NONEVAL = lambda pr: {
    "python": "3.9",
    "install": "true",
    "test_cmd": (
        f"echo 'yt#{pr} not evaluable: yt 3.x Cython build needs curated "
        f"py3.7 + numpy<1.20 env' && false"
    ),
    "_curation_todo": "yt 3.x legacy Cython build",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_YT = {
    "2128": _YT_NONEVAL("2128"),
    "2485": _YT_NONEVAL("2485"),
    "3532": dict(_YT_40_GEN_SPEC),
    "3556": dict(_YT_40_GEN_SPEC),
    "5221": dict(_YT_MODERN_GEN_SPEC),
}

# nilearn: pure-Python, nilearn 0.7 (2020-2021). No [test] extra at that tag;
# install plainly and add test deps. py3.6-3.9 -> use 3.8.
_NILEARN_GEN_SPEC = {
    "python": "3.8",
    "install": "python -m pip install -e .",
    "pip_packages": [
        "pytest",
        "numpy==1.21.6",
        "scipy==1.7.3",
        "scikit-learn==1.0.2",
        "pandas==1.3.5",
        "nibabel==3.2.2",
        "matplotlib==3.5.3",
        "joblib==1.1.1",
    ],
    "validation_cmd": "python -c 'import nilearn'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_NILEARN = {pr: dict(_NILEARN_GEN_SPEC) for pr in ("2431", "2706")}

# mne-python: pure-Python.
#  - 9459 (2021-06, mne 0.24, py3.7-3.10): setup.py builds install_requires
#    from requirements.txt; only numpy/scipy are hard. `import mne` also
#    pulls packaging/decorator/pooch/tqdm/jinja2; the touched viz code needs
#    matplotlib.
#  - 13123 (2025, mne 1.9, hatchling, py>=3.10): numpy>=1.25, lazy-loader.
_MNE_LEGACY_SPEC = {
    "python": "3.9",
    "install": "python -m pip install -e .",
    "pip_packages": [
        "pytest",
        "numpy==1.22.4",
        "scipy==1.8.1",
        "matplotlib==3.5.3",
        "scikit-learn==1.1.3",
        "pooch==1.7.0",
        "decorator==5.1.1",
        "packaging==23.1",
        "tqdm",
        "jinja2",
    ],
    "validation_cmd": "python -c 'import mne'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
_MNE_MODERN_SPEC = {
    "python": "3.12",
    "install": "python -m pip install -e . --config-settings editable_mode=compat",
    "pip_packages": ["pytest", "numpy>=1.25,<3", "scipy>=1.11", "matplotlib", "scikit-learn", "pooch", "decorator", "packaging", "lazy-loader", "jinja2"],
    "validation_cmd": "python -c 'import mne'",
    "test_cmd": "pytest -rA --tb=long -p no:cacheprovider",
    "oracle_kind": "generated_test",
    "test_generation_capabilities": ("python",),
}
SPECS_MNE = {"9459": dict(_MNE_LEGACY_SPEC), "13123": dict(_MNE_MODERN_SPEC)}

# Constants - Task Instance Instllation Environment
MAP_REPO_VERSION_TO_SPECS_PY = {
    "astropy/astropy": SPECS_ASTROPY,
    "dbt-labs/dbt-core": SPECS_DBT_CORE,
    "django/django": SPECS_DJANGO,
    "matplotlib/matplotlib": SPECS_MATPLOTLIB,
    "marshmallow-code/marshmallow": SPECS_MARSHMALLOW,
    "mwaskom/seaborn": SPECS_SEABORN,
    "pallets/flask": SPECS_FLASK,
    "psf/requests": SPECS_REQUESTS,
    "pvlib/pvlib-python": SPECS_PVLIB,
    "pydata/xarray": SPECS_XARRAY,
    "pydicom/pydicom": SPECS_PYDICOM,
    "pylint-dev/astroid": SPECS_ASTROID,
    "pylint-dev/pylint": SPECS_PYLINT,
    "pytest-dev/pytest": SPECS_PYTEST,
    "pyvista/pyvista": SPECS_PYVISTA,
    "numpy/numpy": SPECS_NUMPY,
    "pandas-dev/pandas": SPECS_PANDAS,
    "scikit-learn/scikit-learn": SPECS_SKLEARN,
    "scipy/scipy": SPECS_SCIPY,
    "sphinx-doc/sphinx": SPECS_SPHINX,
    "sqlfluff/sqlfluff": SPECS_SQLFLUFF,
    "swe-bench/humaneval": SPECS_HUMANEVAL,
    "sympy/sympy": SPECS_SYMPY,
    "mdtraj/mdtraj": SPECS_MDTRAJ,
    "biopython/biopython": SPECS_BIOPYTHON,
    "deepchem/deepchem": SPECS_DEEPCHEM,
    "qutip/qutip": SPECS_QUTIP,
    "qiskit/qiskit": SPECS_QISKIT,
    "pyscf/pyscf": SPECS_PYSCF,
    "obspy/obspy": SPECS_OBSPY,
    "psi4/psi4": SPECS_PSI4,
    "scverse/scanpy": SPECS_SCANPY,
    "sunpy/sunpy": SPECS_SUNPY,
    "yt-project/yt": SPECS_YT,
    "nilearn/nilearn": SPECS_NILEARN,
    "mne-tools/mne-python": SPECS_MNE,
}

# Constants - Repository Specific Installation Instructions
MAP_REPO_TO_INSTALL_PY = {}


# Constants - Task Instance Requirements File Paths
MAP_REPO_TO_REQS_PATHS = {
    "dbt-labs/dbt-core": ["dev-requirements.txt", "dev_requirements.txt"],
    "django/django": ["tests/requirements/py3.txt"],
    "matplotlib/matplotlib": [
        "requirements/dev/dev-requirements.txt",
        "requirements/testing/travis_all.txt",
    ],
    "pallets/flask": ["requirements/dev.txt"],
    "pylint-dev/pylint": ["requirements_test.txt"],
    "pyvista/pyvista": ["requirements_test.txt", "requirements.txt"],
    "sqlfluff/sqlfluff": ["requirements_dev.txt"],
    "sympy/sympy": ["requirements-dev.txt", "requirements-test.txt"],
}


# Constants - Task Instance environment.yml File Paths
MAP_REPO_TO_ENV_YML_PATHS = {
    "matplotlib/matplotlib": ["environment.yml"],
    "pydata/xarray": ["ci/requirements/environment.yml", "environment.yml"],
}

USE_X86_PY = {
    "astropy__astropy-7973",
    "django__django-10087",
    "django__django-10097",
    "django__django-10213",
    "django__django-10301",
    "django__django-10316",
    "django__django-10426",
    "django__django-11383",
    "django__django-12185",
    "django__django-12497",
    "django__django-13121",
    "django__django-13417",
    "django__django-13431",
    "django__django-13447",
    "django__django-14155",
    "django__django-14164",
    "django__django-14169",
    "django__django-14170",
    "django__django-15180",
    "django__django-15199",
    "django__django-15280",
    "django__django-15292",
    "django__django-15474",
    "django__django-15682",
    "django__django-15689",
    "django__django-15695",
    "django__django-15698",
    "django__django-15781",
    "django__django-15925",
    "django__django-15930",
    "django__django-5158",
    "django__django-5470",
    "django__django-7188",
    "django__django-7475",
    "django__django-7530",
    "django__django-8326",
    "django__django-8961",
    "django__django-9003",
    "django__django-9703",
    "django__django-9871",
    "matplotlib__matplotlib-13983",
    "matplotlib__matplotlib-13984",
    "matplotlib__matplotlib-13989",
    "matplotlib__matplotlib-14043",
    "matplotlib__matplotlib-14471",
    "matplotlib__matplotlib-22711",
    "matplotlib__matplotlib-22719",
    "matplotlib__matplotlib-22734",
    "matplotlib__matplotlib-22767",
    "matplotlib__matplotlib-22815",
    "matplotlib__matplotlib-22835",
    "matplotlib__matplotlib-22865",
    "matplotlib__matplotlib-22871",
    "matplotlib__matplotlib-22883",
    "matplotlib__matplotlib-22926",
    "matplotlib__matplotlib-22929",
    "matplotlib__matplotlib-22931",
    "matplotlib__matplotlib-22945",
    "matplotlib__matplotlib-22991",
    "matplotlib__matplotlib-23031",
    "matplotlib__matplotlib-23047",
    "matplotlib__matplotlib-23049",
    "matplotlib__matplotlib-23057",
    "matplotlib__matplotlib-23088",
    "matplotlib__matplotlib-23111",
    "matplotlib__matplotlib-23140",
    "matplotlib__matplotlib-23174",
    "matplotlib__matplotlib-23188",
    "matplotlib__matplotlib-23198",
    "matplotlib__matplotlib-23203",
    "matplotlib__matplotlib-23266",
    "matplotlib__matplotlib-23267",
    "matplotlib__matplotlib-23288",
    "matplotlib__matplotlib-23299",
    "matplotlib__matplotlib-23314",
    "matplotlib__matplotlib-23332",
    "matplotlib__matplotlib-23348",
    "matplotlib__matplotlib-23412",
    "matplotlib__matplotlib-23476",
    "matplotlib__matplotlib-23516",
    "matplotlib__matplotlib-23562",
    "matplotlib__matplotlib-23563",
    "matplotlib__matplotlib-23573",
    "matplotlib__matplotlib-23740",
    "matplotlib__matplotlib-23742",
    "matplotlib__matplotlib-23913",
    "matplotlib__matplotlib-23964",
    "matplotlib__matplotlib-23987",
    "matplotlib__matplotlib-24013",
    "matplotlib__matplotlib-24026",
    "matplotlib__matplotlib-24088",
    "matplotlib__matplotlib-24111",
    "matplotlib__matplotlib-24149",
    "matplotlib__matplotlib-24177",
    "matplotlib__matplotlib-24189",
    "matplotlib__matplotlib-24224",
    "matplotlib__matplotlib-24250",
    "matplotlib__matplotlib-24257",
    "matplotlib__matplotlib-24265",
    "matplotlib__matplotlib-24334",
    "matplotlib__matplotlib-24362",
    "matplotlib__matplotlib-24403",
    "matplotlib__matplotlib-24431",
    "matplotlib__matplotlib-24538",
    "matplotlib__matplotlib-24570",
    "matplotlib__matplotlib-24604",
    "matplotlib__matplotlib-24619",
    "matplotlib__matplotlib-24627",
    "matplotlib__matplotlib-24637",
    "matplotlib__matplotlib-24691",
    "matplotlib__matplotlib-24749",
    "matplotlib__matplotlib-24768",
    "matplotlib__matplotlib-24849",
    "matplotlib__matplotlib-24870",
    "matplotlib__matplotlib-24912",
    "matplotlib__matplotlib-24924",
    "matplotlib__matplotlib-24970",
    "matplotlib__matplotlib-24971",
    "matplotlib__matplotlib-25027",
    "matplotlib__matplotlib-25052",
    "matplotlib__matplotlib-25079",
    "matplotlib__matplotlib-25085",
    "matplotlib__matplotlib-25122",
    "matplotlib__matplotlib-25126",
    "matplotlib__matplotlib-25129",
    "matplotlib__matplotlib-25238",
    "matplotlib__matplotlib-25281",
    "matplotlib__matplotlib-25287",
    "matplotlib__matplotlib-25311",
    "matplotlib__matplotlib-25332",
    "matplotlib__matplotlib-25334",
    "matplotlib__matplotlib-25340",
    "matplotlib__matplotlib-25346",
    "matplotlib__matplotlib-25404",
    "matplotlib__matplotlib-25405",
    "matplotlib__matplotlib-25425",
    "matplotlib__matplotlib-25430",
    "matplotlib__matplotlib-25433",
    "matplotlib__matplotlib-25442",
    "matplotlib__matplotlib-25479",
    "matplotlib__matplotlib-25498",
    "matplotlib__matplotlib-25499",
    "matplotlib__matplotlib-25515",
    "matplotlib__matplotlib-25547",
    "matplotlib__matplotlib-25551",
    "matplotlib__matplotlib-25565",
    "matplotlib__matplotlib-25624",
    "matplotlib__matplotlib-25631",
    "matplotlib__matplotlib-25640",
    "matplotlib__matplotlib-25651",
    "matplotlib__matplotlib-25667",
    "matplotlib__matplotlib-25712",
    "matplotlib__matplotlib-25746",
    "matplotlib__matplotlib-25772",
    "matplotlib__matplotlib-25775",
    "matplotlib__matplotlib-25779",
    "matplotlib__matplotlib-25785",
    "matplotlib__matplotlib-25794",
    "matplotlib__matplotlib-25859",
    "matplotlib__matplotlib-25960",
    "matplotlib__matplotlib-26011",
    "matplotlib__matplotlib-26020",
    "matplotlib__matplotlib-26024",
    "matplotlib__matplotlib-26078",
    "matplotlib__matplotlib-26089",
    "matplotlib__matplotlib-26101",
    "matplotlib__matplotlib-26113",
    "matplotlib__matplotlib-26122",
    "matplotlib__matplotlib-26160",
    "matplotlib__matplotlib-26184",
    "matplotlib__matplotlib-26208",
    "matplotlib__matplotlib-26223",
    "matplotlib__matplotlib-26232",
    "matplotlib__matplotlib-26249",
    "matplotlib__matplotlib-26278",
    "matplotlib__matplotlib-26285",
    "matplotlib__matplotlib-26291",
    "matplotlib__matplotlib-26300",
    "matplotlib__matplotlib-26311",
    "matplotlib__matplotlib-26341",
    "matplotlib__matplotlib-26342",
    "matplotlib__matplotlib-26399",
    "matplotlib__matplotlib-26466",
    "matplotlib__matplotlib-26469",
    "matplotlib__matplotlib-26472",
    "matplotlib__matplotlib-26479",
    "matplotlib__matplotlib-26532",
    "pydata__xarray-2905",
    "pydata__xarray-2922",
    "pydata__xarray-3095",
    "pydata__xarray-3114",
    "pydata__xarray-3151",
    "pydata__xarray-3156",
    "pydata__xarray-3159",
    "pydata__xarray-3239",
    "pydata__xarray-3302",
    "pydata__xarray-3305",
    "pydata__xarray-3338",
    "pydata__xarray-3364",
    "pydata__xarray-3406",
    "pydata__xarray-3520",
    "pydata__xarray-3527",
    "pydata__xarray-3631",
    "pydata__xarray-3635",
    "pydata__xarray-3637",
    "pydata__xarray-3649",
    "pydata__xarray-3677",
    "pydata__xarray-3733",
    "pydata__xarray-3812",
    "pydata__xarray-3905",
    "pydata__xarray-3976",
    "pydata__xarray-3979",
    "pydata__xarray-3993",
    "pydata__xarray-4075",
    "pydata__xarray-4094",
    "pydata__xarray-4098",
    "pydata__xarray-4182",
    "pydata__xarray-4184",
    "pydata__xarray-4248",
    "pydata__xarray-4339",
    "pydata__xarray-4356",
    "pydata__xarray-4419",
    "pydata__xarray-4423",
    "pydata__xarray-4442",
    "pydata__xarray-4493",
    "pydata__xarray-4510",
    "pydata__xarray-4629",
    "pydata__xarray-4683",
    "pydata__xarray-4684",
    "pydata__xarray-4687",
    "pydata__xarray-4695",
    "pydata__xarray-4750",
    "pydata__xarray-4758",
    "pydata__xarray-4759",
    "pydata__xarray-4767",
    "pydata__xarray-4802",
    "pydata__xarray-4819",
    "pydata__xarray-4827",
    "pydata__xarray-4879",
    "pydata__xarray-4911",
    "pydata__xarray-4939",
    "pydata__xarray-4940",
    "pydata__xarray-4966",
    "pydata__xarray-4994",
    "pydata__xarray-5033",
    "pydata__xarray-5126",
    "pydata__xarray-5131",
    "pydata__xarray-5180",
    "pydata__xarray-5187",
    "pydata__xarray-5233",
    "pydata__xarray-5362",
    "pydata__xarray-5365",
    "pydata__xarray-5455",
    "pydata__xarray-5580",
    "pydata__xarray-5662",
    "pydata__xarray-5682",
    "pydata__xarray-5731",
    "pydata__xarray-6135",
    "pydata__xarray-6386",
    "pydata__xarray-6394",
    "pydata__xarray-6400",
    "pydata__xarray-6461",
    "pydata__xarray-6548",
    "pydata__xarray-6598",
    "pydata__xarray-6599",
    "pydata__xarray-6601",
    "pydata__xarray-6721",
    "pydata__xarray-6744",
    "pydata__xarray-6798",
    "pydata__xarray-6804",
    "pydata__xarray-6823",
    "pydata__xarray-6857",
    "pydata__xarray-6882",
    "pydata__xarray-6889",
    "pydata__xarray-6938",
    "pydata__xarray-6971",
    "pydata__xarray-6992",
    "pydata__xarray-6999",
    "pydata__xarray-7003",
    "pydata__xarray-7019",
    "pydata__xarray-7052",
    "pydata__xarray-7089",
    "pydata__xarray-7101",
    "pydata__xarray-7105",
    "pydata__xarray-7112",
    "pydata__xarray-7120",
    "pydata__xarray-7147",
    "pydata__xarray-7150",
    "pydata__xarray-7179",
    "pydata__xarray-7203",
    "pydata__xarray-7229",
    "pydata__xarray-7233",
    "pydata__xarray-7347",
    "pydata__xarray-7391",
    "pydata__xarray-7393",
    "pydata__xarray-7400",
    "pydata__xarray-7444",
    "pytest-dev__pytest-10482",
    "scikit-learn__scikit-learn-10198",
    "scikit-learn__scikit-learn-10297",
    "scikit-learn__scikit-learn-10306",
    "scikit-learn__scikit-learn-10331",
    "scikit-learn__scikit-learn-10377",
    "scikit-learn__scikit-learn-10382",
    "scikit-learn__scikit-learn-10397",
    "scikit-learn__scikit-learn-10427",
    "scikit-learn__scikit-learn-10428",
    "scikit-learn__scikit-learn-10443",
    "scikit-learn__scikit-learn-10452",
    "scikit-learn__scikit-learn-10459",
    "scikit-learn__scikit-learn-10471",
    "scikit-learn__scikit-learn-10483",
    "scikit-learn__scikit-learn-10495",
    "scikit-learn__scikit-learn-10508",
    "scikit-learn__scikit-learn-10558",
    "scikit-learn__scikit-learn-10577",
    "scikit-learn__scikit-learn-10581",
    "scikit-learn__scikit-learn-10687",
    "scikit-learn__scikit-learn-10774",
    "scikit-learn__scikit-learn-10777",
    "scikit-learn__scikit-learn-10803",
    "scikit-learn__scikit-learn-10844",
    "scikit-learn__scikit-learn-10870",
    "scikit-learn__scikit-learn-10881",
    "scikit-learn__scikit-learn-10899",
    "scikit-learn__scikit-learn-10908",
    "scikit-learn__scikit-learn-10913",
    "scikit-learn__scikit-learn-10949",
    "scikit-learn__scikit-learn-10982",
    "scikit-learn__scikit-learn-10986",
    "scikit-learn__scikit-learn-11040",
    "scikit-learn__scikit-learn-11042",
    "scikit-learn__scikit-learn-11043",
    "scikit-learn__scikit-learn-11151",
    "scikit-learn__scikit-learn-11160",
    "scikit-learn__scikit-learn-11206",
    "scikit-learn__scikit-learn-11235",
    "scikit-learn__scikit-learn-11243",
    "scikit-learn__scikit-learn-11264",
    "scikit-learn__scikit-learn-11281",
    "scikit-learn__scikit-learn-11310",
    "scikit-learn__scikit-learn-11315",
    "scikit-learn__scikit-learn-11333",
    "scikit-learn__scikit-learn-11346",
    "scikit-learn__scikit-learn-11391",
    "scikit-learn__scikit-learn-11496",
    "scikit-learn__scikit-learn-11542",
    "scikit-learn__scikit-learn-11574",
    "scikit-learn__scikit-learn-11578",
    "scikit-learn__scikit-learn-11585",
    "scikit-learn__scikit-learn-11596",
    "scikit-learn__scikit-learn-11635",
    "scikit-learn__scikit-learn-12258",
    "scikit-learn__scikit-learn-12421",
    "scikit-learn__scikit-learn-12443",
    "scikit-learn__scikit-learn-12462",
    "scikit-learn__scikit-learn-12471",
    "scikit-learn__scikit-learn-12486",
    "scikit-learn__scikit-learn-12557",
    "scikit-learn__scikit-learn-12583",
    "scikit-learn__scikit-learn-12585",
    "scikit-learn__scikit-learn-12625",
    "scikit-learn__scikit-learn-12626",
    "scikit-learn__scikit-learn-12656",
    "scikit-learn__scikit-learn-12682",
    "scikit-learn__scikit-learn-12704",
    "scikit-learn__scikit-learn-12733",
    "scikit-learn__scikit-learn-12758",
    "scikit-learn__scikit-learn-12760",
    "scikit-learn__scikit-learn-12784",
    "scikit-learn__scikit-learn-12827",
    "scikit-learn__scikit-learn-12834",
    "scikit-learn__scikit-learn-12860",
    "scikit-learn__scikit-learn-12908",
    "scikit-learn__scikit-learn-12938",
    "scikit-learn__scikit-learn-12961",
    "scikit-learn__scikit-learn-12973",
    "scikit-learn__scikit-learn-12983",
    "scikit-learn__scikit-learn-12989",
    "scikit-learn__scikit-learn-13010",
    "scikit-learn__scikit-learn-13013",
    "scikit-learn__scikit-learn-13017",
    "scikit-learn__scikit-learn-13046",
    "scikit-learn__scikit-learn-13087",
    "scikit-learn__scikit-learn-13124",
    "scikit-learn__scikit-learn-13135",
    "scikit-learn__scikit-learn-13142",
    "scikit-learn__scikit-learn-13143",
    "scikit-learn__scikit-learn-13157",
    "scikit-learn__scikit-learn-13165",
    "scikit-learn__scikit-learn-13174",
    "scikit-learn__scikit-learn-13221",
    "scikit-learn__scikit-learn-13241",
    "scikit-learn__scikit-learn-13253",
    "scikit-learn__scikit-learn-13280",
    "scikit-learn__scikit-learn-13283",
    "scikit-learn__scikit-learn-13302",
    "scikit-learn__scikit-learn-13313",
    "scikit-learn__scikit-learn-13328",
    "scikit-learn__scikit-learn-13333",
    "scikit-learn__scikit-learn-13363",
    "scikit-learn__scikit-learn-13368",
    "scikit-learn__scikit-learn-13392",
    "scikit-learn__scikit-learn-13436",
    "scikit-learn__scikit-learn-13439",
    "scikit-learn__scikit-learn-13447",
    "scikit-learn__scikit-learn-13454",
    "scikit-learn__scikit-learn-13467",
    "scikit-learn__scikit-learn-13472",
    "scikit-learn__scikit-learn-13485",
    "scikit-learn__scikit-learn-13496",
    "scikit-learn__scikit-learn-13497",
    "scikit-learn__scikit-learn-13536",
    "scikit-learn__scikit-learn-13549",
    "scikit-learn__scikit-learn-13554",
    "scikit-learn__scikit-learn-13584",
    "scikit-learn__scikit-learn-13618",
    "scikit-learn__scikit-learn-13620",
    "scikit-learn__scikit-learn-13628",
    "scikit-learn__scikit-learn-13641",
    "scikit-learn__scikit-learn-13704",
    "scikit-learn__scikit-learn-13726",
    "scikit-learn__scikit-learn-13779",
    "scikit-learn__scikit-learn-13780",
    "scikit-learn__scikit-learn-13828",
    "scikit-learn__scikit-learn-13864",
    "scikit-learn__scikit-learn-13877",
    "scikit-learn__scikit-learn-13910",
    "scikit-learn__scikit-learn-13915",
    "scikit-learn__scikit-learn-13933",
    "scikit-learn__scikit-learn-13960",
    "scikit-learn__scikit-learn-13974",
    "scikit-learn__scikit-learn-13983",
    "scikit-learn__scikit-learn-14012",
    "scikit-learn__scikit-learn-14024",
    "scikit-learn__scikit-learn-14053",
    "scikit-learn__scikit-learn-14067",
    "scikit-learn__scikit-learn-14087",
    "scikit-learn__scikit-learn-14092",
    "scikit-learn__scikit-learn-14114",
    "scikit-learn__scikit-learn-14125",
    "scikit-learn__scikit-learn-14141",
    "scikit-learn__scikit-learn-14237",
    "scikit-learn__scikit-learn-14309",
    "scikit-learn__scikit-learn-14430",
    "scikit-learn__scikit-learn-14450",
    "scikit-learn__scikit-learn-14458",
    "scikit-learn__scikit-learn-14464",
    "scikit-learn__scikit-learn-14496",
    "scikit-learn__scikit-learn-14520",
    "scikit-learn__scikit-learn-14544",
    "scikit-learn__scikit-learn-14591",
    "scikit-learn__scikit-learn-14629",
    "scikit-learn__scikit-learn-14704",
    "scikit-learn__scikit-learn-14706",
    "scikit-learn__scikit-learn-14710",
    "scikit-learn__scikit-learn-14732",
    "scikit-learn__scikit-learn-14764",
    "scikit-learn__scikit-learn-14806",
    "scikit-learn__scikit-learn-14869",
    "scikit-learn__scikit-learn-14878",
    "scikit-learn__scikit-learn-14890",
    "scikit-learn__scikit-learn-14894",
    "scikit-learn__scikit-learn-14898",
    "scikit-learn__scikit-learn-14908",
    "scikit-learn__scikit-learn-14983",
    "scikit-learn__scikit-learn-14999",
    "scikit-learn__scikit-learn-15028",
    "scikit-learn__scikit-learn-15084",
    "scikit-learn__scikit-learn-15086",
    "scikit-learn__scikit-learn-15094",
    "scikit-learn__scikit-learn-15096",
    "scikit-learn__scikit-learn-15100",
    "scikit-learn__scikit-learn-15119",
    "scikit-learn__scikit-learn-15120",
    "scikit-learn__scikit-learn-15138",
    "scikit-learn__scikit-learn-15393",
    "scikit-learn__scikit-learn-15495",
    "scikit-learn__scikit-learn-15512",
    "scikit-learn__scikit-learn-15524",
    "scikit-learn__scikit-learn-15535",
    "scikit-learn__scikit-learn-15625",
    "scikit-learn__scikit-learn-3840",
    "scikit-learn__scikit-learn-7760",
    "scikit-learn__scikit-learn-8554",
    "scikit-learn__scikit-learn-9274",
    "scikit-learn__scikit-learn-9288",
    "scikit-learn__scikit-learn-9304",
    "scikit-learn__scikit-learn-9775",
    "scikit-learn__scikit-learn-9939",
    "sphinx-doc__sphinx-11311",
    "sphinx-doc__sphinx-7910",
    "sympy__sympy-12812",
    "sympy__sympy-14248",
    "sympy__sympy-15222",
    "sympy__sympy-19201",
}
