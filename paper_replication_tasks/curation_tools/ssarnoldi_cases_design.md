# Case design for scibench_replication_0022 (sketch-and-select Arnoldi)

Single `case_type`: `arnoldi_cond_growth`. Curator-chosen parameters:
`matrix`, `p`, `s`, `t`, `condbound` (listed per case below). Each case's
`v0`/`D`/`perm` (the SRHT random inputs) are generated once via a real
Octave `rng('default')` draw and baked permanently into that case's
`input.json` by `build_ssarnoldi_task.py`'s `case()` helper -- NOT derived
independently by each side from a shared seed. This was a required design
change (not a convenience choice): `scientific.py`'s `solve(task_id,
value)` dispatcher, used by `reference_cli.py` at evaluation time, only
ever receives the raw case JSON with no access to a live Octave RNG state,
so both the official adapter and the independent NumPy audit must be
handed the identical realized random values rather than attempting to
bit-match MATLAB/Octave's MT19937 stream in NumPy (see
`ssarnoldi_common.py`'s and `ssarnoldi_scientific.py`'s module docstrings
for the full rationale). Three pinned matrices available:
`Norris/torso3` (n=259156, the paper's own test1a/1b matrix -- `ids(46)`
under the live SuiteSparse filter, confirmed to still resolve to this
matrix at pinning time), `Bai/cryg10000` (n=10000, small), `Norris/torso1`
(n=116158, large -- swapped in for the originally-considered `Kim/kim2`,
n=456976: `kim2` turned out to be a genuinely complex-valued matrix
(`iscomplex(Problem.A)=1` with nonzero imaginary parts, not just flagged
complex with a zero imaginary part), which both breaks the real-arithmetic
task description below and was independently observed to trigger
intermittent OpenBLAS segfaults on this machine's Apple-Silicon
`libopenblas`/complex-BLAS kernel at that scale. `Norris/torso1` is
real-valued, same SuiteSparse group as the primary `torso3` matrix, and
was verified stable across repeated runs).

## Measured numerical hazards (not decorative parameter coverage)

Direct measurement on the pinned matrices before finalizing case
selection (see PROGRESS.md for the full methodology):

1. **Truncation parameter `t` vs. basis conditioning** (`Bai/cryg10000`,
   truncated-Arnoldi variant, `p=50`): `t=2` -> `cond(V)~3.3e13`;
   `t=5` -> `~6.2e12`; `t=10` -> `~2.0e12`; `t=20` -> `~2.0e8`. Monotonic,
   large effect. At the paper's own default `p=100, t=2` on this matrix,
   `cond(V)` reaches `~8.16e15` -- within a factor of ~2 of the double-
   precision ceiling (`1/eps~4.5e15`), i.e. the basis is numerically
   singular. This is the paper's own central empirical claim (truncated
   Arnoldi is unstable for small `t`), not an edge case outside the
   paper's scope.
2. **Oversampling factor `s` vs. sketched-basis conditioning**
   (`Bai/cryg10000`, `select_pinv` variant, `p=40, t=5`): `s=1`
   (embed dim 40, barely larger than `t`) -> `cond(V)~5.4e3`; `s=4`
   (embed dim 160) -> `cond(V)~80`. Monotonic; undersampling the SRHT
   embedding relative to the selection budget is a real, paper-relevant
   hazard (the paper's own guidance is `s` between `2m` and `4m`, so
   `s=1` sits just outside the paper's own recommended range -- a genuine
   boundary case, not an arbitrary stress value).

## Case plan

Public cases (3, mirroring the paper's own primary example):
- `case_01`: `matrix=Norris/torso3, p=100, s=2, t=2, condbound="inf"` --
  the paper's own `test1a.m` defaults on its own primary example matrix.
- `case_02`: `matrix=Norris/torso3, p=100, s=2, t=5, condbound="inf"` --
  the paper's own `test1b.m` (only `t` changed).
- `case_03`: `matrix=Bai/cryg10000, p=50, s=2, t=10, condbound="inf"` --
  a smaller/faster sanity case on a different matrix, moderate `t`.

Hidden cases (5), each isolating a distinct measured hazard rather than an
arbitrary parameter value:
- `case_01`: `matrix=Bai/cryg10000, p=100, s=2, t=2, condbound="inf"` --
  the near-double-precision-ceiling truncated-basis hazard measured above
  (`cond~8.16e15` for the `truncated` variant); exercises whether an
  implementation correctly propagates a near-singular (but still finite)
  condition number instead of diverging/NaN-ing, and whether the
  `select_*` variants' stabilization actually helps relative to
  `truncated`/`sketch_truncate` on the same matrix/p/t.
- `case_02`: `matrix=Bai/cryg10000, p=40, s=1, t=5, condbound="inf"` --
  the undersampled-SRHT hazard measured above (`s=1`, embed dim only 8x
  `t`, just below the paper's own `s in [2m,4m]` guidance); exercises
  whether the sketch dimension is handled correctly at `round(s*p)` for a
  non-conservative `s`, and whether the resulting worse-but-still-useful
  conditioning is reproduced.
- `case_03`: `matrix=Norris/torso3, p=149, s=2, t=2, condbound=1e12` --
  largest `p` used anywhere in the paper's scripts (`test3a`/`3b` use
  `p=149`), combined with the harshest `t=2`, plus a *finite* `condbound`
  (unlike the public cases' `inf`) to exercise the early-stopping logic
  (record basis size at the last `mod(j,10)==0` checkpoint below bound,
  not literally `p`) on the paper's own primary matrix.
- `case_04`: `matrix=Norris/torso1, p=60, s=3, t=8, condbound="inf"` --
  the largest pinned matrix (n=116158), moderate/well-conditioned
  parameter choice; exercises correctness at a different matrix scale/
  sparsity structure than `torso3` (same SuiteSparse group, different
  matrix), without combining it with a second hazard (isolates the
  "large matrix" dimension cleanly).
- `case_05`: `matrix=Bai/cryg10000, p=80, s=1.2, t=3, condbound=100` --
  a very tight finite `condbound` (`100`, far below typical basis
  conditioning even at moderate `j`) forcing early stopping for most/all
  9 variants well before `j` reaches double digits; exercises whether the
  checkpoint-based early-stopping logic (`mod(j,10)==0` sampling, not
  every iteration) is reproduced exactly, since a naive implementation
  that checks every iteration instead of every 10th will disagree on the
  exact recorded basis size.

## Rejected alternatives

- A hidden case combining `s=1` AND `t=2` (stacking both measured hazards)
  was considered but rejected: at `p>=50` this combination was observed to
  occasionally produce a fully-Inf condition number for several variants
  simultaneously (basis collapses to numerical rank 0 for the crudest
  variants), which would make the case *less* discriminating (most
  implementations, correct or buggy, converge to the same "Inf" output)
  rather than more. Each hazard is kept isolated in its own case instead.
- Using the full ~80-matrix SuiteSparse sweep for hidden cases (matching
  `test2a`-`test3b`'s scope) was considered and deferred: the FWHT
  vectorization fix makes this newly tractable in principle, but the
  marginal benefit over the 3-matrix set above (which already spans a
  50x range in matrix size and both paper-default and paper-boundary
  parameter regimes) is low relative to the added pinning/download/
  runtime cost of ~80 matrices. Revisit only if evaluation results
  suggest the current case set under-discriminates.
