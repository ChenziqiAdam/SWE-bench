# Paper-replication curation process

The registry assigns one of four lifecycle states:

- `validated`: official workflow reproduced, independently checked, masking
  reviewed, and the evaluator passes.
- `blocked`: a concrete missing dependency or paper input prevents credible
  paper-level gold.
- `deferred`: prerequisites or scope remain unresolved.
- `retired`: the identifier is permanently unavailable.

Promotion to `validated` requires a pinned source revision, a paper-aligned
official reproduction, a second numerical formulation where practical,
recorded hashes and justified tolerances, public-only solvability, and a trusted
reference evaluation with `score=1.0`. A repository demonstration using data
different from the paper experiment cannot be promoted as paper gold.

`task_registry.py` is authoritative. `build_tasks.py`,
`prepare_masked_papers.py`, and `validate_tasks.py` derive task selection from
it. The builder and masker accept repeatable `--task` arguments.

Stochastic tasks regenerate the prescribed experiment, record the RNG and seed
rule, compare independent implementations, and set tolerances to ten times the
largest observed discrepancy or a documented floating-point floor, whichever
is larger.

## Current MATLAB candidate decisions

`Quantum-Dynamics-in-MATLAB` remains a curator candidate without a task ID. The
pinned repository and `1911.04906v2` source are audited, and
`curation_tools/verify_quantum_dynamics.py` independently reproduces the two
selected Liouvillian evolutions. Licensed MATLAB output is still required via
`curation_tools/export_quantum_dynamics_matlab.m`. Promotion is blocked if the
curve, RMSE, or unordered eigenvalue discrepancies exceed `1e-6`, `1e-7`, or
`1e-7`, respectively. The repository's analytical light-bath coherence omits a
sine multiplier present in the paper and currently violates those curve gates;
it must be resolved scientifically before masking or gold construction.

`piDMD` is `blocked_missing_paper_experiments` at commit
`743d8cbc5267799ed9f32145e2b5854f07960a20`. Its synthetic orthogonal and noisy
double-pendulum demonstrations are not substitutes for the paper's fluid-flow,
travelling-wave, Schrödinger, advection-diffusion, causal-dynamics, or channel-
flow experiments. It cannot receive a task ID, masked bundle, evaluator, or
gold until official paper scripts and raw inputs are available and reproduced.
