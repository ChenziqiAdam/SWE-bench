# OpenMM GPU-eval design: enabling real CUDA/OpenCL execution

Date: 2026-08-07
Status: draft, pending user review

## Background

`outputs/issues_no_tests_codex.log` (test-generation eval, 83 OpenMM/RDKit
instances) scored 41.3% (19/46 scorable). The largest single loss bucket is
30 `excluded` instances, 29 of which are OpenMM PRs whose gold patch touches
only `platforms/cuda/`, `platforms/opencl/`, or `platforms/common/` — GPU
compute paths. These get short-circuited to `non_evaluable_spec` because the
harness was written when eval containers had no GPU: OpenMM is always built
with `-DOPENMM_BUILD_CUDA_LIB=OFF -DOPENMM_BUILD_OPENCL_LIB=OFF`, and any
target that only exists on the GPU-only platforms is structurally
unreachable via the CPU-only `TestReference<Name>` fallback the harness
retargets everything onto.

The remote eval host now has 3× NVIDIA L40S GPUs. Verified end-to-end on
that host (podman, not docker):
- `nvidia-smi -L` shows 3 GPUs, driver 555.42.06 / CUDA 12.5.
- CDI is configured (`/var/run/cdi/nvidia.yaml` present); `podman run
  --device nvidia.com/gpu=0 ...` successfully passes a GPU into a container.
- Plain `ubuntu:22.04` (our existing `c_base_image`) installs the CUDA 12.4
  toolkit via the NVIDIA apt keyring cleanly; `nvcc` and `nvidia-smi` both
  work inside a container with `--device nvidia.com/gpu=0`.
- `docker_build.py`'s `_create_eval_container` (commit `ab3a058`) already
  round-robins a GPU index across containers requesting `run_args: {"gpu":
  True}`, with podman-vs-docker branching. It is currently dormant for
  OpenMM because no OpenMM spec sets that flag.
- **Gap found during verification:** `SWEBENCH_GPU_COUNT` is unset on the
  remote host, so `_next_gpu_index` defaults to divisor 1 — every
  GPU-requesting container would land on GPU 0 only. This must be exported
  as `3` wherever the eval pipeline runs, or the 3-GPU host is only used as
  a 1-GPU host.

This document scopes the fix in two parts, both approved by the user.

## Part 1 — Convert the 6 hardcoded `_openmm_gpu_non_evaluable_spec` stubs

PRs `1640`, `2152`, `2255`, `2829`, `4364`, `5302` currently resolve to
`echo 'not evaluable: ...' && false`. Inspected each gold patch + issue
text:

| PR | Gold patch touches | Nature |
|----|---|---|
| 1640 | `plugins/amoeba/platforms/cuda/...`, incl. a `.cu` kernel | CUDA-only perf/correctness fix (Amoeba DIIS) |
| 2152 | `plugins/amoeba/platforms/cuda/src/kernels/pmeMultipoleElectrostatics.cu` + Reference | CUDA-only numerical correctness (NaN on CUDA) |
| 2255 | `openmmapi/src/LocalEnergyMinimizer.cpp` (platform-agnostic!) | Perf regression only reproducible by comparing OpenCL vs Reference minimization behavior; fix itself is CPU-buildable |
| 2829 | `platforms/opencl/src/kernels/findInteractingBlocks.cl` | OpenCL-only, needs real GPU (AMD-specific memory-scale bug; POCL CPU emulation likely can't reproduce it) |
| 4364 | `platforms/common/src/CommonKernels.cpp` | Common (CUDA+OpenCL shared) kernel fix |
| 5302 | `plugins/amoeba/platforms/common/src/AmoebaCommonKernels.cpp` | Common kernel fix (atom reordering) |

Decision: convert all 6 to real GPU specs, since all six need to execute on
an actual CUDA or OpenCL device to be meaningfully tested (even 2255, whose
patched *file* is CPU-only, requires the OpenCL minimizer path to reproduce
the original slow-minimization symptom that the fix addresses).

**Mechanism (per spec, following the existing `_openmm_cpp_targets_spec` /
`_openmm_opencl_targets_spec` pattern in `c.py`):**

1. New shared helper `_OPENMM_CUDA_TOOLKIT_INSTALL_COMMAND`: apt-installs the
   NVIDIA CUDA keyring + `cuda-nvcc-12-4 cuda-cudart-dev-12-4` (mirrors the
   exact commands verified working on the remote host).
2. New spec-builder `_openmm_cuda_targets_spec(*targets, plugin=None)`,
   mirroring `_openmm_opencl_targets_spec`: `pre_install` adds the CUDA
   toolkit; `build_after_test_patch` configures with
   `-DOPENMM_BUILD_CUDA_LIB=ON -DOPENMM_BUILD_OPENCL_LIB=OFF` (+
   `-DOPENMM_BUILD_AMOEBA_PLUGIN=ON` when `plugin="amoeba"`); `test_cmd` runs
   the compiled `TestCuda<Name>` binary; **`docker_specs: {"run_args":
   {"gpu": True}}`** so `_create_eval_container` attaches a real GPU.
3. `2829` (OpenCL/AMD-specific) reuses the existing
   `_openmm_opencl_targets_spec` builder but that builder must also gain
   `docker_specs.run_args.gpu = True` — currently it relies purely on POCL
   CPU emulation and never requests a device. Since a real GPU is now
   available, prefer running these OpenCL targets against the real device
   too (POCL as build-time ICD stays fine; the runtime ICD loader will
   prefer the NVIDIA one when a real device is present via CDI — needs a
   validation run to confirm behavior, noted as an open risk below).
4. `2255` needs a new pattern: build a Reference-vs-OpenCL LocalEnergyMinimizer
   timing/iteration-count comparison rather than a simple binary pass/fail,
   since the original bug was a performance cliff, not a hard failure. Given
   this is materially different from the other 5, it is called out as a
   follow-up rather than blocking Part 1 — ship 1640/2152/2829/4364/5302
   first, handle 2255 as its own small spec once the CUDA path is proven.

## Part 2 — Relax the `_special_repo_execution_plan` veto (23 instances)

`test_generation_eval.py:737-773` currently short-circuits to
`non_evaluable_spec` whenever:
- (a) every path in the **generated test patch** is under
  `platforms/cuda/.../platforms/` (lines 737-748), or
- (b) every path in the **gold patch** matches
  `platforms/(cuda|opencl|common)/` (lines 762-773).

Both assume "no GPU, so any GPU-only target is dead." With a verified real
GPU now available, this assumption is stale for these 23 instances (spot
checked: 1382, 1679, 1682, 1924, 2257, 2318, 2322, 2819, 3057, 3428, 3460,
3771, 3834, 4079, 4090, 4119, 4148, 4249, 4618, 5069, 5117, 5242, 5346).

**Fix shape:**

1. Add a CUDA-aware branch to the generic build-command construction (around
   `test_generation_eval.py:1135-1139`, the `configure = configure or (...)`
   default), parallel to the existing `-DOPENMM_BUILD_CUDA_LIB=OFF` default:
   when the accepted C++ target paths for `openmm/openmm` include any
   `platforms/cuda/` or `platforms/common/` file (and the *generated* test
   patch — not just the gold patch — has a resolvable target there), build
   with `-DOPENMM_BUILD_CUDA_LIB=ON -DOPENMM_BUILD_OPENCL_LIB=ON` instead,
   using the same CUDA toolkit `pre_install` step from Part 1, and set
   `docker_specs.run_args.gpu = True` on the resolved test spec for that
   instance (this has to happen per-instance at eval time, not at
   `SPECS_OPENMM` authoring time, since the generic execution plan applies
   across arbitrary future OpenMM PRs, not just the 23 curated ones).
2. Rework the target-name resolution (`openmm_header_targets` /
   `_cmake_registered_cpp_targets`) so a generated test under
   `platforms/cuda/tests/TestCudaX.cpp` resolves to `TestCudaX` (already
   works — the existing code already reads the file's own class name), and a
   test that only touches `platforms/cuda/src/*.cu` kernel code (no
   standalone test file) maps to the nearest existing `TestCuda<Force>`
   binary that exercises that kernel, mirroring how the Reference-platform
   header-retargeting works today.
3. Keep the two vetoes as a **last-resort fallback**: only return
   `non_evaluable_spec` if, after attempting to resolve a CUDA/OpenCL/Common
   build target, no such target exists at all (e.g. path is under
   `platforms/hip/` — HIP genuinely has no vendor GPU on this host — or the
   file has no corresponding `Test*` binary anywhere in the CMake target
   graph). This preserves exclusion for genuinely-impossible cases instead
   of removing the safety net entirely.
4. `SWEBENCH_GPU_COUNT=3` must be set in the pipeline's run environment (see
   Background) — otherwise Part 2's higher concurrency (up to 23 instances
   now requesting a GPU, versus 6 in Part 1) will serialize onto a single
   GPU and could create contention/timeouts under `docker_workers=2`+.

## Open risks / things to validate during implementation

- **OpenCL device selection with both POCL and the NVIDIA OpenCL ICD
  installed**: need to confirm at runtime which ICD gets used by default
  (`clGetPlatformIDs` order) — may need `OPENCL_VENDOR_PATH` pinning so
  OpenCL targets actually hit the L40S rather than silently falling back to
  POCL/CPU, which would silently reintroduce the original problem under a
  different name.
- **Build-time vs run-time GPU access**: `cmake --build` (nvcc compilation)
  runs inside the *image build* step, which currently gets no `--gpus`/CDI
  device (only `_create_eval_container`, the post-build run step, does).
  This is fine for `nvcc` — compilation doesn't need a live device — but
  worth confirming no build step (e.g. a CMake device-query check) fails
  without one.
- **Test determinism on real hardware**: some of these are literally
  "unstable energies" / "NaN on CUDA" bugs. A test that fails intermittently
  on the buggy base and passes deterministically on gold is fine; a test
  that's flaky on *both* would need `coverage_flaky_runs`-style retry logic
  already present elsewhere in the pipeline — reuse it, don't invent new
  retry logic.
- **Concurrency**: 3 physical GPUs must serve however many
  `docker_workers`/`max_workers` are configured. If workers > 3 and several
  land on GPU-requesting instances simultaneously, `SWEBENCH_GPU_COUNT=3`
  round-robins by container-creation order, not by actual GPU load — two
  memory-heavy OpenCL AMOEBA tests could collide on one L40S. Not fixing
  this now (out of scope), but flagging it: if flaky GPU-OOM failures show
  up post-fix, that's the likely cause, not a spec bug.

## Out of scope

- The 4 `no-pred` instances (empty codex patches) — unrelated to GPU.
- The 24 `unresolved` (`gold_did_not_pass` / `base_did_not_fail`) instances —
  genuine test-authoring quality gap in the codex agent, not a harness
  issue.
- HIP platform (`-DOPENMM_BUILD_HIP_LIB`) — no AMD GPU on this host, stays
  `OFF`/non-evaluable.
- Non-OpenMM repos (RDKit `not_exercised` instances) — separate root cause,
  not GPU-related.
