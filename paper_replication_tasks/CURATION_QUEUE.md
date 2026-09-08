# Paper Replication Curation Queue

Only papers published in the retained leading field venues are listed. A candidate
receives a task ID only after its official workflow and independent scientific audit pass.

## Validated tasks

| Repository | Task ID | Scope |
|---|---|---|
| `bjmorgan/kinisi` | `scibench_replication_0011_core` | Approximate Bayesian MSD regression with covariance reconditioning and a nonnegative diffusion posterior. Promoted under an explicit G7 blind-implementation waiver. |
| `paezha/Accessibility-Sobi-Hamilton` | `scibench_replication_0017_core` | Balanced floating catchment area accessibility and level of service under threshold and active-station configuration inputs |
| `tchen-research/fixed_sparsity_matrix_approximation` | `scibench_replication_0015_core` | Paper Section 2 core fixed-sparse-matrix approximation: shared Gaussian sketch and row-restricted least-squares recovery |
| `simunec/sketch-select-arnoldi` | `scibench_replication_0022_core` | Canonical pseudoinverse sketch-and-select Arnoldi basis construction with sparse coefficient support and sketch-norm normalization |
| `ahilbers/a_posteriori_tsa_storage` | `scibench_replication_0018_core` | Two-stage storage-aware a-posteriori representative-day aggregation and final capacity redesign over explicit numeric `x/n/p/q` inputs. G1-G6/G8 pass; promoted under an explicit G7 blind-implementation waiver with the 0.0/0.0 failure retained. |
| `yuwenli925/REIM` | `scibench_replication_0021_core` | rEIM Algorithm 2.1 greedy shared-basis construction and multi-target rational interpolation over explicit finite numerical dictionaries; excludes FEM, BDF2, ROGA, AAA, and figure replication. Two clean pinned replays, independent implementation, curator reference, and blind G7 submission agree across 3 public + 8 hidden cases. |

Identifier `scibench_replication_0010` is retired and is not reusable. Identifier
`0017` was used for the Accessibility-Sobi-Hamilton task to
avoid a collision with the then-still-deferred `0015`. `0018` was used for the
energy-TSA candidate once its full six-seed official-run workflow completed;
`0019` was used for StiefelCurvatureSIMAX to avoid a collision. `0020` was used
for the now-excluded covid19-environmental-correlates task. `0021` was used for
the REIM task.

## Excluded after core-algorithm review

| Repository | Archived task ID | Reason |
|---|---|---|
| `LinkaiMa/SMW` | `scibench_replication_0014` | The paper contributes stability theorems; the executable SMW update is established machinery rather than a unique new core algorithm. |
| `RalfZimmermannSDU/StiefelCurvatureSIMAX` | `scibench_replication_0019` | The paper's contribution is theorem-driven geometry; the curvature routines are supporting experiment functions rather than a unique new core algorithm. |
| `paezha/covid19-environmental-correlates` | `scibench_replication_0020` | Spatial SUR-SLM is the paper's applied scientific model. The repository uses 3SLS, but the paper permits ML or IV, so 3SLS is a replaceable estimator rather than a unique core algorithm; blind G6/G7 consistently selected ML. |

## Blocked

| Repository | Status |
|---|---|
| `bio-phys/DiffusionGLS` | Required paper trajectories are unavailable |
| `baddoo/piDMD` | Official repository lacks the paper experiments and raw inputs |
| `davydden/large-strain-matrix-free` | Central paper results (multigrid roofline/timing/scaling) require a named multi-node HPC cluster (Emmy RRZE, up to 64 nodes) with LIKWID hardware counters; wall-clock/hardware-dependent, not tolerance-checkable or budget-feasible. Only the small deterministic `tests/*.prm` regression cases are portable, but those check code correctness, not the paper's core contribution |

## Scoped pilots

| Repository | Scope |
|---|---|
| `paezha/Reproductive-Rate-and-Density-US-Reanalyzed` | Main mixed model, Heckman selection, and Moran-filter results |

## Collected candidates

- `simunec/sketch-select-arnoldi` — "A Sketch-and-Select Arnoldi Process" (Güttel & Simunec, SISC, doi:10.1137/23M1588007). SIAM reproducibility badge; MATLAB scripts reproduce all figures using real sparse matrices from the SuiteSparse Matrix Collection (via `ssget`) plus randomized sketching (SRHT). Needs verification before promotion: whether the sketching RNG/seed is controllable for exact reproducibility, and whether the required SuiteSparse matrices are stably available as pinned inputs.

## Acceptance gates

1. Reproduce central paper results from a pinned official checkout within budget.
2. Regenerate gold from official code and verify it independently.
3. Fix inputs, seeds, environments, hashes, and tolerances.
4. Require reference score `1.0` and public-only score at most `0.4`.
