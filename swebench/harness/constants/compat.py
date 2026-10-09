"""Replayable build-environment repairs; scientific source is left untouched."""

import inspect
import shlex


def python_command(function, *args, interpreter="python3"):
    """Embed a standalone helper in an image spec, including its cache hash."""
    code = inspect.getsource(function) + "\n" + function.__name__ + "(" + ", ".join(
        repr(arg) for arg in args
    ) + ")\n"
    return interpreter + " -c " + shlex.quote(code)


def prepare_gtest(checkout, cache):
    import hashlib
    import re
    import subprocess
    from pathlib import Path

    module = Path(checkout) / "cmake/Modules/GTest.cmake"
    if not module.exists():
        return
    match = re.search(r"GIT_REPOSITORY\s+(\S+)\s+GIT_TAG\s+(\S+)", module.read_text())
    if not match:
        raise RuntimeError("Unrecognized historical GoogleTest dependency")
    repository, revision = match.groups()
    destination = Path(cache) / hashlib.sha256(
        (repository + "@" + revision).encode()
    ).hexdigest()[:16]
    if not (destination / ".git").exists():
        destination.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(destination)], check=True)
        subprocess.run(["git", "-C", str(destination), "fetch", "--depth=1",
                        repository, revision], check=True)
        subprocess.run(["git", "-C", str(destination), "checkout", "--detach",
                        "FETCH_HEAD"], check=True)


def use_cached_gtest(checkout, cache):
    import hashlib
    import re
    from pathlib import Path

    module = Path(checkout) / "cmake/Modules/GTest.cmake"
    if not module.exists():
        return
    text = module.read_text()
    pattern = r"GIT_REPOSITORY\s+(\S+)\s+GIT_TAG\s+(\S+)"
    match = re.search(pattern, text)
    if not match:
        raise RuntimeError("Unrecognized historical GoogleTest dependency")
    repository, revision = match.groups()
    source = Path(cache) / hashlib.sha256(
        (repository + "@" + revision).encode()
    ).hexdigest()[:16]
    if not (source / "googletest/include/gtest/gtest.h").is_file():
        raise RuntimeError("GoogleTest was not provisioned during image build")
    text = re.sub(pattern, 'DOWNLOAD_COMMAND "" UPDATE_COMMAND ""', text)
    text, count = re.subn(
        r'SOURCE_DIR\s+"?\$\{CMAKE_BINARY_DIR\}/gtest-src"?',
        'SOURCE_DIR "' + str(source) + '"', text,
    )
    if count != 1:
        raise RuntimeError("Unrecognized GoogleTest source directory")
    text = text.replace(
        "IMPORTED_LINK_INTERFACE_LIBRARIES ${CMAKE_THREAD_LIBS_INIT})",
        'IMPORTED_LINK_INTERFACE_LIBRARIES "${CMAKE_THREAD_LIBS_INIT}")',
    )
    module.write_text(text)


def prepare_pyscf_dependencies(checkout, cache):
    import hashlib
    import re
    import subprocess
    import urllib.request
    from pathlib import Path

    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    text = (Path(checkout) / "pyscf/lib/CMakeLists.txt").read_text()
    pattern = r"(?m)^[ \t]*GIT_REPOSITORY\s+(\S+)\s+(?:#[^\n]*\n\s*)*GIT_TAG\s+(\S+)"
    for repository, revision in re.findall(pattern, text):
        destination = cache / hashlib.sha256(
            (repository + "@" + revision).encode()
        ).hexdigest()[:16]
        if not (destination / ".git").exists():
            destination.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", str(destination)], check=True)
            subprocess.run(["git", "-C", str(destination), "fetch", "--depth=1",
                            repository, revision], check=True)
            subprocess.run(["git", "-C", str(destination), "checkout", "--detach",
                            "FETCH_HEAD"], check=True)
    archive = cache / "libxc-4.3.4.tar.gz"
    expected = "2d5878dd69f0fb68c5e97f46426581eed2226d1d86e3080f9aa99af604c65647"
    if not archive.exists():
        urllib.request.urlretrieve(
            "https://gitlab.com/libxc/libxc/-/archive/4.3.4/libxc-4.3.4.tar.gz",
            str(archive),
        )
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError("libxc 4.3.4 source archive checksum mismatch")


def use_cached_pyscf_dependencies(checkout, cache):
    import hashlib
    import re
    from pathlib import Path

    cache = Path(cache)
    module = Path(checkout) / "pyscf/lib/CMakeLists.txt"
    text = module.read_text()
    pattern = r"(?m)^[ \t]*GIT_REPOSITORY\s+(\S+)\s+(?:#[^\n]*\n\s*)*GIT_TAG\s+(\S+)"

    def cached_source(match):
        repository, revision = match.groups()
        source = cache / hashlib.sha256(
            (repository + "@" + revision).encode()
        ).hexdigest()[:16]
        if not (source / ".git").exists():
            raise RuntimeError("PySCF dependency was not provisioned: " + repository)
        return '    SOURCE_DIR "' + str(source) + '" DOWNLOAD_COMMAND "" UPDATE_COMMAND ""'

    text = re.sub(pattern, cached_source, text)
    archive = cache / "libxc-4.3.4.tar.gz"
    expected = "2d5878dd69f0fb68c5e97f46426581eed2226d1d86e3080f9aa99af604c65647"
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError("Missing or invalid cached libxc source archive")
    text, count = re.subn(
        r"(?m)^[ \t]*URL[ \t]+http\S*libxc-4\.3\.4\.tar\.gz\S*",
        '    URL "' + str(archive) + '"\n    URL_HASH SHA256=' + expected,
        text,
    )
    if count != 2:
        raise RuntimeError("Unrecognized PySCF libxc download declarations")
    # A GitLab source archive contains configure.ac, not a generated configure.
    text = text.replace(
        "CONFIGURE_COMMAND <SOURCE_DIR>/configure",
        "CONFIGURE_COMMAND autoreconf -i <SOURCE_DIR> COMMAND <SOURCE_DIR>/configure",
    )
    module.write_text(text)


def link_psi4_core(checkout):
    import sysconfig
    from pathlib import Path

    source = Path(checkout) / "psi4"
    installed = Path(sysconfig.get_path("platlib")) / "psi4"
    cores = list(installed.glob("core*.so"))
    if len(cores) != 1:
        raise RuntimeError("Expected exactly one installed Psi4 native core")
    destination = source / cores[0].name
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    destination.symlink_to(cores[0])

