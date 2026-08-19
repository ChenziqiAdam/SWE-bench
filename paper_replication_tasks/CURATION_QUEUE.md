# Paper Replication Curation Queue

Only papers published in the retained leading field venues are listed. A candidate
receives a task ID only after its official workflow and independent scientific audit pass.

## Validated tasks

| Repository | Task ID | Scope |
|---|---|---|
| `arm61/msd-errors` | `scibench_replication_0011` | Seeded random walks, MSD, and OLS/WLS/GLS diffusion estimates |
| `LinkaiMa/SMW` | `scibench_replication_0014` | SMW forward/backward errors and stability bounds |
| `paezha/Accessibility-Sobi-Hamilton` | `scibench_replication_0017` | Deterministic BFCA/2SFCA accessibility and level-of-service using the archived travel-time matrix |
| `tchen-research/fixed_sparsity_matrix_approximation` | `scibench_replication_0015` | Gaussian-sketch fixed-sparsity matrix approximation: off-pattern error, recovery RMSE/quantiles, and Theorem 1 bound curves |
| `RalfZimmermannSDU/StiefelCurvatureSIMAX` | `scibench_replication_0019` | Sectional curvature of Grassmann, Stiefel (canonical/Euclidean), and SO(n) manifolds via the four pinned `seccurv_*.m` functions (Sections 4.1 and 4.3; the unseeded, non-bit-reproducible Figure 2 random-averaging experiment is out of scope) |
| `ahilbers/a_posteriori_tsa_storage` | `scibench_replication_0018` | Six-region energy-system design capacities and unserved energy under time-series-aggregation methods A-F (a priori and storage-aware a posteriori), across six MT19937-resampled seed/year cases, via the pinned Calliope/CBC `get_design_estimate`+`get_operate_variables` workflow; independently audited by reimplementing the deterministic clustering pipeline and matching Calliope's own recovered day-to-cluster assignment (exact partition match, all 6 methods, all 6 cases) |
| `paezha/covid19-environmental-correlates` | `scibench_replication_0020` | Panel spatial-SUR-SLM 3SLS estimation (province-level COVID-19 incidence vs. climatic lags) via the pinned `spsur::spsurtime()` workflow across three lag specifications, with and without the paper's cross-equation equality restrictions; independently audited by a from-scratch NumPy 3SLS reimplementation (max coefficient error ~1e-7 across all 6 cases) |

Identifier `scibench_replication_0010` is retired and is not reusable. Identifier
`0017` was used for the Accessibility-Sobi-Hamilton task to
avoid a collision with the then-still-deferred `0015`. `0018` was used for the
energy-TSA candidate once its full six-seed official-run workflow completed;
`0019` was used for StiefelCurvatureSIMAX to avoid a collision. `0020` was used
for the covid19-environmental-correlates task (only 6 distinct paper-faithful
input combinations exist for this task's parameter space, so it ships 1 public
+ 5 hidden case instead of the usual 3 public + 5 hidden).

## Blocked

| Repository | Status |
|---|---|
| `bio-phys/DiffusionGLS` | Required paper trajectories are unavailable |
| `baddoo/piDMD` | Official repository lacks the paper experiments and raw inputs |

## Scoped pilots

| Repository | Scope |
|---|---|
| `paezha/Reproductive-Rate-and-Density-US-Reanalyzed` | Main mixed model, Heckman selection, and Moran-filter results |

## Collected candidates

- `davydden/large-strain-matrix-free`

## Acceptance gates

1. Reproduce central paper results from a pinned official checkout within budget.
2. Regenerate gold from official code and verify it independently.
3. Fix inputs, seeds, environments, hashes, and tolerances.
4. Require reference score `1.0` and public-only score at most `0.4`.
