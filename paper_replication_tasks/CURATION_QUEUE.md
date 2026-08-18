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

Identifier `scibench_replication_0010` is retired and is not reusable. Identifier
`0016` remains occupied by the deferred energy-TSA candidate below (its prior
working files and evidence directory predate a stale claim that no `0015`/`0016`
ID had been assigned); `0017` was used for the Accessibility-Sobi-Hamilton task to
avoid a collision with the then-still-deferred `0015`. `0018` is reserved for the
same energy-TSA candidate once its full six-seed official-run workflow completes;
`0019` was used for StiefelCurvatureSIMAX to avoid a collision.

## Blocked

| Repository | Status |
|---|---|
| `bio-phys/DiffusionGLS` | Required paper trajectories are unavailable |
| `baddoo/piDMD` | Official repository lacks the paper experiments and raw inputs |

## Scoped pilots

| Repository | Scope |
|---|---|
| `paezha/covid19-environmental-correlates` | Main spatial SUR model on frozen panel data |
| `paezha/Reproductive-Rate-and-Density-US-Reanalyzed` | Main mixed model, Heckman selection, and Moran-filter results |

## Collected candidates

- `davydden/large-strain-matrix-free`

## Deferred after reproduction pilot

| Repository | Reason |
|---|---|
| `ahilbers/a_posteriori_tsa_storage` | The 72-run dependent A–F workflow exceeds the proposed runtime budget; independent D–F agreement remains unverified |

## Acceptance gates

1. Reproduce central paper results from a pinned official checkout within budget.
2. Regenerate gold from official code and verify it independently.
3. Fix inputs, seeds, environments, hashes, and tolerances.
4. Require reference score `1.0` and public-only score at most `0.4`.
