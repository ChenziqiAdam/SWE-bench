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

## Public-dossier information boundary

A masked dossier must preserve every fact needed to define a unique scientific
experiment and submission, even when that fact originally appeared only in a
figure axis, caption, appendix, or official workflow. Masking may remove paper
identity, implementation identities, reference arrays, and final numerical
answers, but it must not turn a documented paper choice into a hidden parameter.

The public bundle must therefore state:

- experiment-specific parameter values that cannot be derived from the model;
- which model parameters are fixed and which are fitted;
- RNG family, seed, draw shape/order, and rejection/resampling rule whenever
  they affect a fixed stochastic reference;
- the exact scientific quantity being scored, including normalization, units,
  aggregation, and ordering conventions;
- artifact shape, dtype, axes or columns, and serialization semantics.

Agents remain responsible for deriving equations, correction terms, stable
numerical methods, and equivalent algorithms from the supplied scientific
definition. Public solvability does not require translating official source
code into the dossier. The governing test is whether two scientifically
competent implementations following the public information can reasonably be
expected to produce evaluator-equivalent artifacts without guessing a hidden
author choice.

## Task-specification audit decisions

### `scibench_replication_0007`

The first Claude Code run completed inference, trusted execution, and evaluation
successfully but scored `0.1`. This was a valid scientific failure rather than a
pipeline failure: the submission reported raw fitted rate constants near
`0.15`, while the evaluator expected the paper's dimensionless
`k_hat / k_true` summaries near `1`. Dividing the submitted values by the true
rate constant would have passed five of six scientific metrics. The remaining
nonlinear confidence-interval discrepancy came from holding `y_0` fixed instead
of jointly fitting `k` and `y_0`.

The original paper communicates normalization through its figure axis and
caption, while joint fitting and the fixed seed are confirmed by the official
workflow. Their omission from the rewritten dossier made multiple reasonable
implementations score differently. The public dossier now explicitly requires:

- joint nonlinear fitting of `k` and `y_0`;
- `numpy.random.default_rng(seed=1)`;
- aggregation of the normalized estimate `k_hat / k_true`, not raw `k_hat`.

Reference values remain hidden. This task is an easy-tier pipeline/calibration
task after the specification repair.

### `scibench_replication_0008`

The intended scientific challenge is high and should remain so. Agents should
derive coherent-state matrix elements, noncommutative corrections, partition-
function expansions, and stable quadrature themselves; the dossier should not
reproduce the official `analytic.py` implementation.

The current audit nevertheless found paper-defined information lost during
masking. The original Figure 1 caption states that `B_z = 1 T` for every figure,
and the plotted observable is the dimensionless normalized expectation
`<S_z> / (hbar s)`. The hidden TSV references also encode two columns:
temperature in kelvin followed by that normalized expectation. These are an
experimental setting, output semantics, and artifact contract—not quantities
that can be uniquely derived.

Before using task `0008` for a formal model comparison, its public dossier
should minimally add:

- `B_z = 1 T` for all curve groups;
- the scored observable `<S_z> / (hbar s)`;
- TSV columns ordered as temperature then normalized expectation;
- the paper's correction-order convention: the first correction includes the
  `S_z^2` noncommutative term, the second extends through `S_z^3`, and so on.

Until that repair is validated, a low score on `0008` may measure missing
specification rather than paper-replication ability.

## Current task difficulty assessment

- `0007`: easy; basic Monte Carlo regression and artifact production.
- `0009`: medium; deterministic ODE integration and rank-three exact DMD. Its
  current public specification is substantially complete.
- `0012`: medium-hard; deeper coherent-state mathematics and strict stable
  logarithmic/analytic-derivative numerics, but moderate runtime.
- `0011`: hard; the public protocol is detailed, but exact generation of all
  4096 seeded MSD curves requires efficient computation and careful linear
  algebra under tight tolerances.
- `0008`: intended hard, but pending the public-specification repair above.

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
