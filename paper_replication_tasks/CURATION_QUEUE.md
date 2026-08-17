# Paper Replication Curation Queue

Only papers published in the retained leading field venues are listed. A candidate
receives a task ID only after its official workflow and independent scientific audit pass.

## Validated tasks

| Repository | Task ID | Scope |
|---|---|---|
| `arm61/msd-errors` | `scibench_replication_0011` | Seeded random walks, MSD, and OLS/WLS/GLS diffusion estimates |
| `LinkaiMa/SMW` | `scibench_replication_0014` | SMW forward/backward errors and stability bounds |

Identifier `scibench_replication_0010` is retired and is not reusable.

## Curator reproduction

| Repository | Scope |
|---|---|
| `paezha/Accessibility-Sobi-Hamilton` | Deterministic BFCA/2SFCA calculations using the archived travel-time matrix |

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
- `RalfZimmermannSDU/StiefelCurvatureSIMAX`

## Deferred after reproduction pilot

| Repository | Reason |
|---|---|
| `tchen-research/fixed_sparsity_matrix_approximation` | Two seeded official Figure 4 runs exceed the 7,200-second total budget before independent validation |
| `ahilbers/a_posteriori_tsa_storage` | The 72-run dependent A–F workflow exceeds the proposed runtime budget; independent D–F agreement remains unverified |

## Acceptance gates

1. Reproduce central paper results from a pinned official checkout within budget.
2. Regenerate gold from official code and verify it independently.
3. Fix inputs, seeds, environments, hashes, and tolerances.
4. Require reference score `1.0` and public-only score at most `0.4`.
