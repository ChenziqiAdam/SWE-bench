# OpenMM GPU-Eval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable real CUDA/OpenCL GPU execution for OpenMM test-generation eval on the now-available 3x NVIDIA L40S remote host (podman + CDI), recovering the 6 hardcoded-non-evaluable instances (Part 1) and the 23 instances currently vetoed by a stale "no GPU" assumption (Part 2).

**Architecture:** Add a CUDA-toolkit `pre_install` helper and a `_openmm_cuda_targets_spec()` builder to `swebench/harness/constants/c.py`, mirroring the existing `_openmm_cpp_targets_spec`/`_openmm_opencl_targets_spec` pattern but with `-DOPENMM_BUILD_CUDA_LIB=ON` and `docker_specs.run_args.gpu=True`. Convert the 5 in-scope hardcoded stubs to use it (or the OpenCL builder, for the one OpenCL-only case). Give `_openmm_opencl_targets_spec` the same `run_args.gpu=True` treatment. Then relax `_special_repo_execution_plan`'s gold-patch veto in `test_generation_eval.py` so it only fires when no real (non-stub) curated spec exists for the instance, instead of unconditionally excluding every gold patch that touches `platforms/{cuda,opencl,common}/`.

**Tech Stack:** Python, pytest, OpenMM CMake build, podman+CDI GPU passthrough (verified working on remote host).

## Global Constraints

- `SWEBENCH_GPU_COUNT=3` must be exported in the pipeline's run environment before running eval on the remote host (documented, not code — see Task 5). Without it, `_next_gpu_index` in `docker_build.py` defaults to divisor 1 and all GPU work serializes onto GPU 0.
- PR `2255` stays on the hardcoded non-evaluable stub — its fix needs a timing/iteration-count comparison pattern, not pass/fail, and is out of scope for this plan (documented follow-up, per the approved design doc).
- HIP platform (`-DOPENMM_BUILD_HIP_LIB`) stays `OFF`/non-evaluable — no AMD GPU on this host.
- Do not touch RDKit `not_exercised` instances, the 4 `no-pred` instances, or the `gold_did_not_pass`/`base_did_not_fail` unresolved instances — all out of scope per the design doc.
- Follow existing code patterns exactly: builder-function style in `c.py`, `GeneratedTestExecutionPlan` dataclass shape in `test_generation_eval.py`, existing test file conventions (`tests/test_c_scientific_specs.py`, `tests/test_no_tests_execution_plan.py`).

---

## Task 1: CUDA toolkit pre_install helper + `_openmm_cuda_targets_spec()` builder

**Files:**
- Modify: `swebench/harness/constants/c.py` (insert after `_openmm_opencl_targets_spec`, before `_openmm_gpu_non_evaluable_spec` — i.e. after line 423, before line 426)
- Test: `tests/test_c_scientific_specs.py`

**Interfaces:**
- Produces: `_OPENMM_CUDA_TOOLKIT_INSTALL_COMMAND` (module-level string constant, list of apt commands joined the way `_OPENMM_OPENCL_COMPAT_HEADER_COMMAND` is — a single command string).
- Produces: `_openmm_cuda_targets_spec(*targets: str, plugin: str | None = None) -> dict` — same return shape as `_openmm_cpp_targets_spec`/`_openmm_opencl_targets_spec` (`pre_install`, `build_after_test_patch`, `test_cmd`, `fail_to_pass`, plus `test_generation_use_spec_cmd: True` and `docker_specs: {"run_args": {"gpu": True}}`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_c_scientific_specs.py`:

```python
def test_openmm_cuda_targets_spec_requests_gpu_and_installs_toolkit():
    from swebench.harness.constants.c import _openmm_cuda_targets_spec

    spec = _openmm_cuda_targets_spec("TestCudaAmoebaMultipoleForce")

    assert spec["docker_specs"] == {"run_args": {"gpu": True}}
    assert spec["test_generation_use_spec_cmd"] is True
    pre_install = "\n".join(spec["pre_install"])
    assert "cuda-keyring" in pre_install
    assert "cuda-nvcc-12-4" in pre_install
    assert "cuda-cudart-dev-12-4" in pre_install
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


def test_openmm_cuda_targets_spec_enables_plugin():
    from swebench.harness.constants.c import _openmm_cuda_targets_spec

    spec = _openmm_cuda_targets_spec("TestCudaAmoebaMultipoleForce", plugin="amoeba")

    build = "\n".join(spec["build_after_test_patch"])
    assert "-DOPENMM_BUILD_AMOEBA_PLUGIN=ON" in build
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_c_scientific_specs.py -k cuda_targets_spec -v`
Expected: FAIL with `ImportError: cannot import name '_openmm_cuda_targets_spec'`

- [ ] **Step 3: Write the implementation**

In `swebench/harness/constants/c.py`, insert this block immediately after the `_openmm_opencl_targets_spec` function ends (after line 423, before the `def _openmm_gpu_non_evaluable_spec` at line 426):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_c_scientific_specs.py -k cuda_targets_spec -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add swebench/harness/constants/c.py tests/test_c_scientific_specs.py
git commit -m "Add CUDA-toolkit pre_install and _openmm_cuda_targets_spec builder"
```

---

## Task 2: Give `_openmm_opencl_targets_spec` a real-GPU option

**Files:**
- Modify: `swebench/harness/constants/c.py:380-423`
- Test: `tests/test_c_scientific_specs.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_openmm_opencl_targets_spec(*targets, amoeba=False, gpu=False)` — new `gpu` kwarg. When `True`, adds `"docker_specs": {"run_args": {"gpu": True}}` to the returned dict. Default stays `False` so all 23 currently-passing curated OpenCL specs are unchanged in Task 2 (they get `gpu=True` explicitly in Task 4).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_c_scientific_specs.py`:

```python
def test_openmm_opencl_targets_spec_gpu_flag_sets_run_args():
    from swebench.harness.constants.c import _openmm_opencl_targets_spec

    cpu_spec = _openmm_opencl_targets_spec("TestOpenCLNonbondedForce")
    gpu_spec = _openmm_opencl_targets_spec("TestOpenCLNonbondedForce", gpu=True)

    assert "docker_specs" not in cpu_spec
    assert gpu_spec["docker_specs"] == {"run_args": {"gpu": True}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_c_scientific_specs.py -k opencl_targets_spec_gpu_flag -v`
Expected: FAIL with `TypeError: _openmm_opencl_targets_spec() got an unexpected keyword argument 'gpu'`

- [ ] **Step 3: Write the implementation**

In `swebench/harness/constants/c.py`, change the `_openmm_opencl_targets_spec` signature and return (lines 380 and 414-423):

```python
def _openmm_opencl_targets_spec(*targets: str, amoeba: bool = False, gpu: bool = False) -> dict:
```

(docstring unchanged), and at the end of the function body, change the return block:

```python
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
```

Note: this is a pure refactor of the existing tail of the function (previously a bare `return {...}`) into a `spec = {...}` + conditional + `return spec`. No other lines in the function change.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_c_scientific_specs.py -k opencl_targets_spec_gpu_flag -v`
Expected: PASS

Also run the full existing OpenCL-spec test to confirm no regression:
Run: `python -m pytest tests/test_c_scientific_specs.py -k opencl -v`
Expected: PASS (all, including pre-existing `test_openmm_opencl_specs_install_gl_headers`)

- [ ] **Step 5: Commit**

```bash
git add swebench/harness/constants/c.py tests/test_c_scientific_specs.py
git commit -m "Add gpu kwarg to _openmm_opencl_targets_spec for real-device execution"
```

---

## Task 3: Convert the 5 in-scope hardcoded stubs to real GPU specs

**Files:**
- Modify: `swebench/harness/constants/c.py:792-794` (PR 5302), `swebench/harness/constants/c.py:1008-1022` (PRs 1640, 2152, 2255, 2829, 4364)
- Test: `tests/test_c_scientific_specs.py`

**Interfaces:**
- Consumes: `_openmm_cuda_targets_spec` (Task 1), `_openmm_opencl_targets_spec(..., gpu=True)` (Task 2).
- Produces: `SPECS_OPENMM["1640"]`, `SPECS_OPENMM["2152"]`, `SPECS_OPENMM["2829"]`, `SPECS_OPENMM["4364"]`, `SPECS_OPENMM["5302"]` now real GPU specs. `SPECS_OPENMM["2255"]` stays untouched (`_openmm_gpu_non_evaluable_spec`, deferred).

Target resolution (from gold-patch inspection already done during design):

| PR | Builder | Target(s) | plugin/amoeba |
|----|---------|-----------|----------------|
| 1640 | `_openmm_cuda_targets_spec` | `TestCudaAmoebaMultipoleForce` | `plugin="amoeba"` |
| 2152 | `_openmm_cuda_targets_spec` | `TestCudaAmoebaMultipoleForce` | `plugin="amoeba"` |
| 2829 | `_openmm_opencl_targets_spec` | `TestOpenCLNonbondedForce` | `gpu=True` |
| 4364 | `_openmm_cuda_targets_spec` | `TestCudaCustomNonbondedForce` | none |
| 5302 | `_openmm_cuda_targets_spec` | `TestCudaAmoebaMultipoleForce` | `plugin="amoeba"` |

Rationale: 1640/2152/5302 all patch Amoeba CUDA/common multipole kernels (`multipoleInducedField.cu`, `pmeMultipoleElectrostatics.cu`, `AmoebaCommonKernels.cpp`) — `TestCudaAmoebaMultipoleForce` is the existing OpenMM CUDA test binary that exercises the Amoeba multipole/PME kernel family (mirrors how `_openmm_opencl_targets_spec("TestOpenCLAmoebaMultipoleForce", amoeba=True)` is already used elsewhere in this file for the OpenCL/common Amoeba multipole family — grep `TestOpenCLAmoebaMultipoleForce` in `c.py` to confirm the sibling pattern before writing). 2829 patches `platforms/opencl/src/kernels/findInteractingBlocks.cl`, which is exercised by the nonbonded-force nearest-neighbor search — reuse `TestOpenCLNonbondedForce`, the same target already used for PRs 2257/2318/3057/etc. in this file. 4364 patches `platforms/common/src/CommonKernels.cpp` (the shared Custom*Force kernel infrastructure) — `TestCudaCustomNonbondedForce` is the CUDA-platform test exercising that shared code path.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_c_scientific_specs.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_c_scientific_specs.py -k "hardcoded_gpu_stubs or pr_2255" -v`
Expected: `test_hardcoded_gpu_stubs_converted_to_real_specs` FAILS (still has `"not evaluable"` in spec text); `test_pr_2255_stays_non_evaluable_pending_follow_up` PASSES already (baseline).

- [ ] **Step 3: Write the implementation**

In `swebench/harness/constants/c.py`, replace line 792-794 (PR 5302 entry):

```python
    "5302": _openmm_cuda_targets_spec(
        "TestCudaAmoebaMultipoleForce", plugin="amoeba"
    ),
```

Replace lines 1005-1022 (the comment block + 5 stub entries) with:

```python
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
```

(2255's entry is unchanged in content — it stays a stub. It is re-listed here only because the surrounding comment changed; keep the dict key order the same as before if editing in place rather than re-typing the whole block.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_c_scientific_specs.py -k "hardcoded_gpu_stubs or pr_2255" -v`
Expected: PASS (both tests)

Also run the full spec test file to confirm no collateral breakage:
Run: `python -m pytest tests/test_c_scientific_specs.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add swebench/harness/constants/c.py tests/test_c_scientific_specs.py
git commit -m "Convert 5 hardcoded GPU-non-evaluable OpenMM stubs to real CUDA/OpenCL specs"
```

---

## Task 4: Set `gpu=True` on the 23 curated OpenCL specs targeted by Part 2

**Files:**
- Modify: `swebench/harness/constants/c.py:773-783` (four standalone `_openmm_opencl_targets_spec` calls: 4618, 2318, 2322, 2257), `swebench/harness/constants/c.py:944-969` (the comprehension covering 2819, 5069, 1679, 1382, 5346, 5117, 3460, 3428, 1924, 4079, 4249, 4148, 4119, 4090, 3771, 3057, 1682)
- Test: `tests/test_c_scientific_specs.py`

PR `3872` (line 814, already `amoeba=True`) is NOT in the design doc's 23-instance Part 2 list — leave it untouched in this task.

**Interfaces:**
- Consumes: `_openmm_opencl_targets_spec(..., gpu=True)` (Task 2).
- Produces: `SPECS_OPENMM[pr]["docker_specs"]["run_args"]["gpu"] is True` for all 23 instances named in the design doc's Part 2 spot-check list: `1382, 1679, 1682, 1924, 2257, 2318, 2322, 2819, 3057, 3428, 3460, 3771, 3834, 4079, 4090, 4119, 4148, 4249, 4618, 5069, 5117, 5242, 5346`.

First, confirm exactly which of these 23 PR keys are curated via `_openmm_opencl_targets_spec` versus some other builder. Pre-confirmed during planning (re-verify with the grep in Step 1 before editing, since `c.py` may have changed):
- `3834` → `TestParser` (not an OpenCL spec, a different builder) — out of scope for this task.
- `5242` → `TestCpuLocalEnergyMinimizer` (Reference/CPU target, not OpenCL) — out of scope for this task.
- All other 21 PRs (`1382, 1679, 1682, 1924, 2257, 2318, 2322, 2819, 3057, 3428, 3460, 3771, 4079, 4090, 4119, 4148, 4249, 4618, 5069, 5117, 5346`) ARE `_openmm_opencl_targets_spec`-backed (confirmed: the standalone calls at lines 773-783 plus the comprehension at lines 944-969, which includes `3428`).

`3834` and `5242` need no spec change — they're purely unblocked by Task 5's veto relaxation once a real (non-stub) curated spec is confirmed to exist for them, which it does (just not a GPU one).

- [ ] **Step 1: Identify exact curated call sites**

Run:
```bash
grep -n '"1382"\|"1679"\|"1682"\|"1924"\|"2257"\|"2318"\|"2322"\|"2819"\|"3057"\|"3428"\|"3460"\|"3771"\|"3834"\|"4079"\|"4090"\|"4119"\|"4148"\|"4249"\|"4618"\|"5069"\|"5117"\|"5242"\|"5346"' swebench/harness/constants/c.py
```
Record which of these keys map to `_openmm_opencl_targets_spec(...)` calls (directly or via the `pr: _openmm_opencl_targets_spec(*targets, amoeba=amoeba) for pr, targets, amoeba in [...]` loop around line 945-967) versus any other builder. Only the `_openmm_opencl_targets_spec`-backed ones are in scope for this task; the rest are handled purely by Task 5's veto relaxation (no spec change needed since Reference-header retargeting already produces a real target).

- [ ] **Step 2: Write the failing test**

Append to `tests/test_c_scientific_specs.py`, using the exact key list confirmed in Step 1 (this example assumes all 23 resolve to `_openmm_opencl_targets_spec` — adjust the list down if Step 1 finds otherwise):

```python
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
```

(`3834` and `5242` are intentionally excluded — they resolve to non-OpenCL builders, see Step 1. If Step 1's re-verification finds any other key in this list no longer maps to `_openmm_opencl_targets_spec`, drop it here and note why in the commit message.)

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_c_scientific_specs.py -k part2_curated_opencl -v`
Expected: FAIL (none of these specs have `docker_specs` yet)

- [ ] **Step 4: Write the implementation**

For each standalone call site found in Step 1 (e.g. lines 773-783), add `, gpu=True` as a kwarg:

```python
    "4618": _openmm_opencl_targets_spec(
        "TestOpenCLMonteCarloFlexibleBarostat", gpu=True
    ),
    "2318": _openmm_opencl_targets_spec("TestOpenCLNonbondedForce", gpu=True),
    "2322": _openmm_opencl_targets_spec("TestOpenCLCustomCentroidBondForce", gpu=True),
    "2257": _openmm_opencl_targets_spec("TestOpenCLNonbondedForce", gpu=True),
```

For the loop-built block (around line 940-967), read the actual current code first (it wasn't fully captured above — re-read `swebench/harness/constants/c.py:940-970` before editing) and add `gpu=True` to the comprehension's call to `_openmm_opencl_targets_spec`, e.g. change:

```python
        pr: _openmm_opencl_targets_spec(*targets, amoeba=amoeba)
```

to:

```python
        pr: _openmm_opencl_targets_spec(*targets, amoeba=amoeba, gpu=True)
```

applied to the single comprehension that builds all these entries — this flips `gpu=True` for every PR in that loop's source list in one edit, not per-PR.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_c_scientific_specs.py -k part2_curated_opencl -v`
Expected: PASS

Run the full spec test file again:
Run: `python -m pytest tests/test_c_scientific_specs.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add swebench/harness/constants/c.py tests/test_c_scientific_specs.py
git commit -m "Request real GPU device for Part 2 curated OpenCL OpenMM specs"
```

---

## Task 5: Relax the gold-patch veto in `_special_repo_execution_plan`

**Files:**
- Modify: `swebench/eval_pipeline/test_generation_eval.py:750-773`
- Test: `tests/test_no_tests_execution_plan.py`

**Interfaces:**
- Consumes: `MAP_REPO_VERSION_TO_SPECS` (already imported in `test_generation_eval.py` — confirm via `grep -n "MAP_REPO_VERSION_TO_SPECS" swebench/eval_pipeline/test_generation_eval.py` before editing; if not imported at module level, add the import).
- Produces: `_special_repo_execution_plan` no longer unconditionally returns `non_evaluable_spec` for gold patches touching `platforms/{cuda,opencl,common}/` when a real (non-stub) curated spec exists for that instance's `(repo, version)` key. It still returns `non_evaluable_spec` when no curated spec exists, or when the curated spec's own `test_cmd` contains `"not evaluable:"` (i.e. still a stub, like PR 2255).

Current code (lines 750-773):

```python
    # OpenMM's per-force/integrator C++ regression tests are shared
    # tests/TestX.h headers that this harness always retargets onto the
    # Reference-platform build target "TestReference<Name>" (see
    # openmm_header_targets below), since that's the only variant this
    # no-GPU environment can build. If the *gold* patch that actually fixes
    # the issue touches only platforms/cuda/, platforms/opencl/, or
    # platforms/common/ (GPU-only shared kernel code with no Reference
    # equivalent), the Reference binary's observable behavior never changes
    # between base and gold: the generated test is structurally incapable
    # of proving anything regardless of what it asserts. Without this check
    # such cases surface as spurious "base_did_not_fail"/"gold_did_not_pass"
    # model failures instead of the hardware-capability gap they really are.
    gold_patch_paths = _patch_paths(instance.get("patch", "") or "")
    if repo == "openmm/openmm" and gold_patch_paths and all(
        re.search(r"(?:^|/)platforms/(?:cuda|opencl|common)/", path) is not None
        for path in gold_patch_paths
    ):
        return GeneratedTestExecutionPlan(
            failure_reason="non_evaluable_spec",
            evidence={
                "spec_commands": tuple(commands),
                "gold_patch_paths": tuple(gold_patch_paths),
            },
        )
```

New code — the veto now only fires when the instance's own curated spec is itself still a stub (no real command to run), not merely because the gold patch touches a GPU platform path:

```python
    # OpenMM's per-force/integrator C++ regression tests are shared
    # tests/TestX.h headers that this harness always retargets onto the
    # Reference-platform build target "TestReference<Name>". Historically
    # this environment had no GPU, so if the *gold* patch that fixes the
    # issue touched only platforms/cuda/, platforms/opencl/, or
    # platforms/common/ (GPU-only shared kernel code with no Reference
    # equivalent), the Reference binary's observable behavior would never
    # change between base and gold and the generated test would be
    # structurally incapable of proving anything. A real GPU is now
    # available (see docker_specs.run_args.gpu on the curated specs in
    # c.py), so this only remains a hard veto when the instance's curated
    # spec is itself still a non-evaluable stub (`commands` already carries
    # a "not evaluable:" marker, caught above) or when no curated spec
    # exists for this (repo, version) at all -- in both cases there is no
    # real command this harness could run regardless of GPU availability.
    gold_patch_paths = _patch_paths(instance.get("patch", "") or "")
    has_curated_spec = bool(
        MAP_REPO_VERSION_TO_SPECS.get(repo, {}).get(str(instance.get("version", "")))
    )
    if (
        repo == "openmm/openmm"
        and gold_patch_paths
        and not has_curated_spec
        and all(
            re.search(r"(?:^|/)platforms/(?:cuda|opencl|common)/", path) is not None
            for path in gold_patch_paths
        )
    ):
        return GeneratedTestExecutionPlan(
            failure_reason="non_evaluable_spec",
            evidence={
                "spec_commands": tuple(commands),
                "gold_patch_paths": tuple(gold_patch_paths),
            },
        )
```

Note: the `"not evaluable:" in command for command in commands` check at line 724 (top of the function, unchanged) already catches the case where a curated spec exists but is still a stub (2255) — it fires first and returns before reaching this block, so no additional stub-detection logic is needed here. The only behavior change is dropping the blanket veto when a real curated spec exists.

Also examine the sibling veto immediately above this one (lines 730-748, the *generated*-patch-only-touches-`platforms/cuda/` check) — leave it unchanged for this task. That veto guards the generic (non-curated-spec) build path documented in Task 6, not the curated-spec path; changing it is Task 6's job, not this one.

- [ ] **Step 1: Confirm the import**

Run: `grep -n "^from swebench.harness.constants\|MAP_REPO_VERSION_TO_SPECS" swebench/eval_pipeline/test_generation_eval.py | head -5`

If `MAP_REPO_VERSION_TO_SPECS` is not already imported at module level, add it to the existing `from swebench.harness.constants import (...)` block (find the exact existing import block first with `grep -n "^from swebench.harness.constants import" -A 5 swebench/eval_pipeline/test_generation_eval.py`).

- [ ] **Step 2: Write the failing test**

Append to `tests/test_no_tests_execution_plan.py`:

```python
def test_gold_patch_gpu_veto_yields_to_a_real_curated_spec():
    # PR 2318 has a real curated _openmm_opencl_targets_spec (gpu=True after
    # Task 4) whose gold patch touches only platforms/opencl/. The veto must
    # not fire just because the gold patch is GPU-only -- a real spec exists.
    instance = {
        "repo": "openmm/openmm",
        "version": "2318",
        "patch": (
            "diff --git a/platforms/opencl/src/kernels/nonbonded.cl "
            "b/platforms/opencl/src/kernels/nonbonded.cl\n"
            "--- a/platforms/opencl/src/kernels/nonbonded.cl\n"
            "+++ b/platforms/opencl/src/kernels/nonbonded.cl\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        ),
    }
    generated_patch = (
        "diff --git a/wrappers/python/tests/TestNonbondedForce.py "
        "b/wrappers/python/tests/TestNonbondedForce.py\n"
        "--- a/wrappers/python/tests/TestNonbondedForce.py\n"
        "+++ b/wrappers/python/tests/TestNonbondedForce.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def test_generated():\n"
        "+    assert True\n"
    )
    commands = [
        "LD_LIBRARY_PATH=$PWD/build:${LD_LIBRARY_PATH:-} "
        "OPENMM_PLUGIN_DIR=$PWD/build ./build/TestOpenCLNonbondedForce"
    ]
    plan = _special_repo_execution_plan(instance, generated_patch, commands)

    assert plan is None or plan.failure_reason != "non_evaluable_spec"


def test_gold_patch_gpu_veto_still_fires_with_no_curated_spec():
    # No curated spec exists for this synthetic (repo, version) key, so the
    # veto must still protect against an unresolvable GPU-only gold patch.
    instance = {
        "repo": "openmm/openmm",
        "version": "synthetic-no-spec",
        "patch": (
            "diff --git a/platforms/opencl/src/kernels/nonbonded.cl "
            "b/platforms/opencl/src/kernels/nonbonded.cl\n"
            "--- a/platforms/opencl/src/kernels/nonbonded.cl\n"
            "+++ b/platforms/opencl/src/kernels/nonbonded.cl\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        ),
    }
    generated_patch = (
        "diff --git a/wrappers/python/tests/TestNonbondedForce.py "
        "b/wrappers/python/tests/TestNonbondedForce.py\n"
        "--- a/wrappers/python/tests/TestNonbondedForce.py\n"
        "+++ b/wrappers/python/tests/TestNonbondedForce.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def test_generated():\n"
        "+    assert True\n"
    )
    plan = _special_repo_execution_plan(instance, generated_patch, [])

    assert plan is not None
    assert plan.failure_reason == "non_evaluable_spec"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_no_tests_execution_plan.py -k "gold_patch_gpu_veto" -v`
Expected: `test_gold_patch_gpu_veto_yields_to_a_real_curated_spec` FAILS (veto still fires unconditionally); `test_gold_patch_gpu_veto_still_fires_with_no_curated_spec` PASSES already (baseline, confirms no accidental over-relaxation before the fix).

- [ ] **Step 4: Write the implementation**

Apply the code change shown above to `swebench/eval_pipeline/test_generation_eval.py:762-773`, and add the import if Step 1 found it missing.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_no_tests_execution_plan.py -k "gold_patch_gpu_veto" -v`
Expected: PASS (both tests)

Run the full execution-plan test suite to confirm no regression:
Run: `python -m pytest tests/test_no_tests_execution_plan.py tests/test_test_generation_eval.py tests/test_c_scientific_specs.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add swebench/eval_pipeline/test_generation_eval.py tests/test_no_tests_execution_plan.py
git commit -m "Relax gold-patch GPU veto when a real curated OpenMM spec exists"
```

---

## Task 6: Document `SWEBENCH_GPU_COUNT` requirement and confirm pipeline wiring

**Files:**
- Modify: `docs/issues_no_tests_offline_pilot.md` (or the closest existing pipeline-run doc — check `grep -rn "SWEBENCH_GPU_COUNT" docs/ swebench/` first to see if it's documented anywhere already)
- No test (documentation-only task; the underlying `_next_gpu_index` behavior already has coverage in `docker_build.py`'s existing tests if any — check with `grep -rln "_next_gpu_index\|SWEBENCH_GPU_COUNT" tests/`)

**Interfaces:**
- Consumes: nothing.
- Produces: a documented, discoverable requirement that `SWEBENCH_GPU_COUNT=3` must be exported before running OpenMM GPU-eval on the 3-GPU remote host.

- [ ] **Step 1: Check for existing test coverage of `_next_gpu_index`**

Run: `grep -rln "_next_gpu_index\|SWEBENCH_GPU_COUNT" tests/`

If a test file already exists (e.g. `tests/test_docker_build.py`), read it and confirm it covers the divisor-1 default behavior. If no such test exists, add one:

```python
def test_gpu_index_round_robins_across_configured_gpu_count(monkeypatch):
    from swebench.harness.docker_build import _next_gpu_index

    indices = [_next_gpu_index(3) for _ in range(6)]

    assert indices == [0, 1, 2, 0, 1, 2] or len(set(indices[:3])) == 3
```

(Use the existing counter's actual semantics — read `_next_gpu_index`'s current implementation at `swebench/harness/docker_build.py:64-68` before asserting exact values, since it's a shared module-level counter and other tests in the same process may have already advanced it; prefer asserting `len(set(_next_gpu_index(3) for _ in range(30))) == 3` to avoid order-dependence across the test suite.)

Place this in `tests/test_docker_build.py` if it exists, else create it following the shape of other harness unit tests (check `tests/test_c_scientific_specs.py` for import/assert style).

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/test_docker_build.py -k gpu_index -v`
Expected: PASS

- [ ] **Step 3: Add the documentation note**

Find the closest existing doc describing how to run the OpenMM/RDKit eval pipeline on the remote host:

Run: `grep -rln "issues_no_tests\|remote server\|docker_workers" docs/*.md`

Add a short section (append, don't restructure the existing doc) stating:

```markdown
## GPU configuration (remote eval host)

The remote eval host has 3x NVIDIA L40S GPUs (podman + CDI). Before running
OpenMM test-generation eval, export:

    export SWEBENCH_GPU_COUNT=3

Without this, `_next_gpu_index` in `swebench/harness/docker_build.py`
defaults to a divisor of 1 and every GPU-requesting container is assigned
GPU index 0, serializing all CUDA/OpenCL OpenMM eval onto a single card
regardless of how many are physically available.
```

- [ ] **Step 4: Commit**

```bash
git add docs/issues_no_tests_offline_pilot.md tests/test_docker_build.py
git commit -m "Document SWEBENCH_GPU_COUNT requirement for OpenMM GPU eval"
```

---

## Task 7: Full-suite verification

**Files:** none modified — verification only.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass, including every test added in Tasks 1-6 and every pre-existing test (no regressions).

- [ ] **Step 2: Spot-check the design doc's 6+23 instance count is preserved**

Run:
```bash
python3 -c "
from swebench.harness.constants.c import SPECS_OPENMM
stub_prs = [pr for pr in ('1640','2152','2255','2829','4364','5302')
            if 'not evaluable' in '\n'.join(SPECS_OPENMM[pr].get('test_cmd', []))]
print('still-stub PRs (expect only 2255):', stub_prs)
"
```
Expected output: `still-stub PRs (expect only 2255): ['2255']`

- [ ] **Step 3: Report back to the user**

Summarize: which of the 6 stubs were converted (5) and which remains deferred (2255, with reason). Which of the 23 Part-2 instances got `gpu=True` via spec change (Task 4) versus which are unblocked purely by the veto relaxation (Task 5) with no spec change needed (Reference-header-retargeted instances). Remind the user that `SWEBENCH_GPU_COUNT=3` must be exported on the remote host before the next eval run, and that actually running the eval pipeline against real GPU hardware to confirm these pass is a necessary follow-up this plan does not itself perform (no GPU available in this development environment).
