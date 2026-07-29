# Paper Replication Curation Queue

This file records candidates selected for curator reproduction or a scoped
pilot. Selection does not mean that a benchmark task or gold output has already
been validated. A candidate receives a task ID only after its selected official
workflow runs successfully and the reference results pass an independent
scientific audit.

## Curator reproduction

| Repository | Selected scope | Required verification |
|---|---|---|
| `Ariel-Norambuena/Quantum-Dynamics-in-MATLAB` | Two deterministic open-system trajectories at commit `f0b375a4962342c2c56eea2974e01f6e29d9bbb0` | Independent SciPy evolution passes the paper's analytical checks, but licensed MATLAB reproduction is pending and the repository light-bath coherence expression disagrees with the paper. See [`curation_reports/quantum_dynamics_matlab.json`](curation_reports/quantum_dynamics_matlab.json). |
| `paezha/Accessibility-Sobi-Hamilton` | Deterministic BFCA/2SFCA calculations using the archived travel-time matrix | Restore the pinned R environment and reproduce selected accessibility summaries from a clean checkout |

## Validated

| Repository | Task ID | Validated scope |
|---|---|---|
| `arm61/msd-errors` | `scibench_replication_0011` | Full fixed-seed Figure 1 random-walk ensemble; MSD covariance and intercept-inclusive OLS/WLS/GLS estimates |
| `stonerlab/PIQSD-SingleSpinAnisotropy` | `scibench_replication_0012` | Deterministic paper core method: gauge-fixed exact logarithmic effective Hamiltonian and effective field over the Figure 2/3 parameter groups; stochastic ASD is explicitly excluded |

Identifier `scibench_replication_0010` is retired and is not reusable.

## Blocked

| Repository | Status | Evidence |
|---|---|---|
| `bio-phys/DiffusionGLS` | `blocked_missing_paper_data` | The repository example was reproduced, but the 4139 water trajectories and 2 microsecond ubiquitin trajectory used for Figures 2--6 are absent. See [`curation_reports/diffusiongls.json`](curation_reports/diffusiongls.json). |
| `baddoo/piDMD` | `blocked_missing_paper_experiments` | The pinned repository contains only a synthetic orthogonal example and a double-pendulum example absent from the paper; all six paper experiment workflows and raw inputs are missing. See [`curation_reports/pidmd.json`](curation_reports/pidmd.json). |

## Selected for scoped pilot

| Repository | Proposed paper-level scope | Explicit exclusions and blockers |
|---|---|---|
| `ThomasPak/cell-competition` | Analytic competition regimes plus one lightweight fixed-seed well-mixed experiment | Exclude the Chaste vertex workflow and large parameter sweeps; confirm that the retained scope still supports the paper's central winner/loser framework |
| `paezha/covid19-environmental-correlates` | Main spatial SUR model on frozen, model-independent panel data | Exclude raw GIS reconstruction, maps, and secondary robustness models; first validate the historical R dependency stack |
| `paezha/Reproductive-Rate-and-Density-US-Reanalyzed` | Main mixed model, Heckman selection, and Moran-filter results | Exclude the commented stochastic Tobit model, maps, and editorial material; first reproduce the selected tables in a clean pinned R environment |

## Acceptance gates

Every selected candidate must satisfy all of the following before promotion to a
formal task:

1. The pinned official code reproduces the selected paper results from a clean
   checkout using CPU resources within the benchmark budget.
2. The selected outputs correspond to named paper figures, tables, or central
   quantitative claims.
3. Public inputs contain only raw or model-independent processed data, never
   fitted values or result-derived features.
4. Gold artifacts are regenerated from the official workflow and independently
   checked with equations, a second implementation, or an equivalent numerical
   formulation.
5. Stochastic outputs have explicit seeds, sufficient sample sizes, and
   empirically justified cross-run tolerances. Otherwise they are removed.
6. The anonymized dossier passes identity, bibliographic, implementation, and
   result-leakage review while retaining enough information for a public-only
   clean-room implementation.
7. An official reference submission receives `score=1.0` and
   `full_success=true`, and a separate public-only implementation passes within
   the resource budget.

## Deferred candidates

`oliviergimenez/spatial-stream-network-occupancy-model` remains deferred until
its missing shapefile, external terrain data, online download, and absolute-path
dependencies are replaced by a complete auditable input bundle.
