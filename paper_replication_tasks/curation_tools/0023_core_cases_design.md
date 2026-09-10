# Case design for scibench_replication_0023_core (random time-shift distributions)

3 public + 8 hidden cases. Single implicit `case_type`: compute the CDF of the
limiting random variable `W` of a supercritical multi-type branching process, its
first five moments of `W` conditioned on non-extinction, the ultimate extinction probability, and the Malthusian
parameter (paper: Morris, Maclean & Black, J. Math. Biol. 2024).

Curator-chosen per-case inputs: `mean_matrix`, `linear_terms`, `quadratic_terms`,
`lifetimes`, `initial_condition`, `n_moments`, `embedding_step`, `taylor_epsilon`,
`cdf_grid`, `cme_coefficients`.

## Fixed data baked into every case

`cme_coefficients` = the 21-term concentrated-matrix-exponential quadrature
(the min-`cv2` entry with `n + 1 <= 21`, `n = 20`) copied verbatim from
`RandomTimeShifts.jl` commit `baf6da64` file `src/iltcme_ext.json`
(SHA-256 `483a16dcb6c1378b1ce6b3ff003b2008bdfa419fa4d7dc5e394950faacd9d3b8`,
originally from http://inverselaplace.org/). This is a fixed numerical table the
paper does not derive; it is supplied as raw input, not explained in `task.md`.
It is identical across all 11 cases.

## Model families used

- **SIR** (1 type): infective lifetime `a = beta + gamma`, progeny GF
  `f(s) = gamma/a + (beta/a) s^2` (`quadratic_terms = [[1,1,1,beta]]`, no linear
  term), `mean_matrix = [[beta - gamma]]`. Has a closed-form `W` distribution
  (paper Eq. 41-42): conditional on non-extinction `W* ~ Exp(1 - q)`, `q = gamma/beta`;
  `E[W*^k] = k!/(1-q)^k` (this conditional form is the `w_moments` output).
- **SEIR** (2 types, E and I): `linear_terms = [[1,2,sigma]]` (E -> I),
  `quadratic_terms = [[2,1,2,beta]]` (I -> I + E), `lifetimes = [sigma, beta+gamma]`,
  `mean_matrix = [[-sigma, sigma],[beta, -gamma]]`.
- **3-type chain** (E1 -> E2 -> I, I -> I + E1): two linear terms, one quadratic
  term; strong type asymmetry via unequal lifetimes.

None of the public or hidden cases reuses a paper figure's parameter set verbatim.
SEIR uses `(R0, 1/sigma, 1/gamma)` triples distinct from the paper's fixed
`(1.7, 2.0, 3.0)`; the `cdf_grid` is curator-chosen; population size `N` never
enters (the branching process is the input, per the G2 design).

## Public (3) -- comfortable regime, one per model family

| # | Model | Parameters | `n` | `h` | `eps` | Grid | Purpose |
|---|---|---|---|---|---|---|---|
| 1 | SIR | `beta = 2.4, gamma = 1.0` (R0 = 2.4), `Z0 = [1]` | 21 | 0.1 | 1e-10 | 0..8 step 0.5 | analytic cross-check; single founder |
| 2 | SEIR | `R0 = 1.6, 1/sigma = 2.5, 1/gamma = 2.5`, `Z0 = [1, 0]` | 30 | 1.0 | 1e-6 | 0..12 step 0.5 | canonical 2-type, single founder |
| 3 | 3-type chain | rates below, `Z0 = [1, 0, 0]` | 25 | 1.0 | 1e-6 | 0..12 step 0.5 | multi-type moment aggregation |

3-type chain rates: `E1 -> E2` rate 0.5, `E2 -> I` rate 0.5, `I -> I + E1` rate 0.7,
`I` removal rate 0.35; `lifetimes = [0.5, 0.5, 1.05]`,
`mean_matrix = [[-0.5, 0.5, 0], [0, -0.5, 0.5], [0.7, 0, -0.35]]`.

## Hidden (8) -- each isolates one hazard

| # | Hazard | Case | Invariant checked | Shortcut it breaks |
|---|---|---|---|---|
| 1 | **SIR analytic, single founder** | SIR `beta = 3.0, gamma = 0.6` (R0 = 5), `Z0 = [1]`, `n = 21`, `h = 0.1`, grid 0..6 step 0.4 | exact match to `q + (1-q)(1-e^{-(1-q)w})`; `w_moments` = `k!/(1-q)^k` | any method that only moment-fits or drops the point mass |
| 2 | **Near-critical growth** | SEIR `R0 = 1.2`, `1/sigma = 2.0`, `1/gamma = 3.0`, `Z0 = [1, 0]`, `n = 30`, `h = 1.0` | `lambda` small -> `kappa` large in the recursion; CDF still monotone and `-> 1` | fixed / truncated `kappa`; skipping the recursion |
| 3 | **Genuine quadratic, high `q_star`** | SIR-type `beta = 1.3, gamma = 1.0` (R0 = 1.3), `Z0 = [1]`, `n = 25`, `h = 0.2`, grid 0..14 | extinction-heavy: `w_cdf(0) = q_star` (≈ 0.77); conditional exponential-type tail | omitting the point mass / renormalizing |
| 4 | **Strong type asymmetry** | 3-type chain, very unequal rates (`E1->E2` 0.15, `E2->I` 1.5, `I->I+E1` 0.9, removal 0.3), `Z0 = [2, 1, 0]`, `n = 25`, `h = 1.0` | multinomial moment aggregation over a mixed multi-type founder set | treating founders/types independently |
| 5 | **Low moment count** | SEIR `R0 = 1.7`, `1/sigma = 2.0`, `1/gamma = 3.0`, `Z0 = [1, 0]`, `n = 3`, `h = 1.0`, grid 0..7 | the 3-moment truncation shifts the CDF `~7e-3` from an `n = 30` computation; the gold is the correct `n = 3` result | hard-coding `n = 30` |
| 6 | **Low `n` + near-critical** | SEIR `R0 = 1.2`, `1/sigma = 2.0`, `1/gamma = 3.0`, `Z0 = [1, 0]`, `n = 4`, `h = 1.0` | small `n` and small `lambda` together: the `n = 4` truncation shifts the CDF `~4e-3` from `n = 30` and the recursion is long | hard-coding `n = 30`; fixed `kappa` |
| 7 | **Large embedding step** | SEIR `R0 = 1.7`, `1/sigma = 2.0`, `1/gamma = 3.0`, `Z0 = [1, 0]`, `n = 30`, `h = 5.0` | embedded GF `f~` over a long step; `mu = e^{lambda h}` large; result `h`-insensitive within tolerance | fixed `h`; ignoring the embedding entirely |
| 8 | **Multi-founder SEIR** | SEIR `R0 = 2.2`, `1/sigma = 1.8`, `1/gamma = 2.2`, `Z0 = [4, 3]`, `n = 25`, `h = 1.0` | product-over-`Z0` structure `phi_W = prod_i phi_{W_i}^{Z0_i}`; multinomial aggregation over 7 founders | assuming a single founder; wrong exponentiation |

## Shortcut programs (for `verify_0023_core_task.py`)

Each is a distinct wrong assumption; all must fail the hidden suite (score `< 1.0`).

1. `moments_only` -- return a generalized-gamma CDF fitted to the 5 moments instead
   of inverting the LST. (Reports the correct moments, fails the CDF cases.)
2. `mean_only_cdf` -- approximate `W` as a point mass at `E[W]` (step CDF).
3. `no_point_mass` -- omit the `q_star` atom at `w = 0` and renormalize by `1 - q*`.
4. `skip_recursion` -- use only the Taylor-series LST near 0; never apply the
   embedded-GF contraction for `|s| > L` (wrong for the large-`|s|` CME points).
5. `linear_only` -- ignore the quadratic progeny terms in the functional equation.
6. `independent_types` -- diagonalize `mean_matrix`, dropping the type coupling in
   the moment recursion.
7. `fixed_n` -- ignore the input `n_moments` and always use 30 (fails cases 5, 6).
8. `public_memorizer` -- hash-lookup of the 3 public outputs (hidden score 0).

## Deviation from the official Julia

`RandomTimeShifts.jl::error_bounds` computes the Taylor-region radius with `n!`;
the paper's Eq. 19 has `(n+1)!`. The oracle, the independent implementation, and
the curator reference all follow the **paper** (`(n+1)!`) so that a paper-only
blind implementation converges to the same gold. This is the only intentional
departure from the pinned Julia source.

## Tolerances

`build_0023_core_task.py` derives per-field tolerances from the maximum fieldwise
discrepancy between the oracle (Python port) and the independently written
`rts_core_scientific.py` across all 11 cases (`atol = max(floor, 8 * discrepancy)`):

- **`w_cdf`**: `atol` floor 1e-9, `rtol` 1e-8. Oracle and independent agree to
  ~1e-8 (they share no source).
- **`w_moments`**: `atol` 1e-8, `rtol` 1e-8 -- the moment recursion is exact
  arithmetic; agreement ~1e-11 relative.
- **`q_star`, `lambda`**: `atol` 1e-10, `rtol` 1e-9.

Build fails if `w_cdf` atol > 1e-6, `w_moments` atol > 1e-3, or `q_star`/`lambda`
atol > 1e-7.

The concentrated-matrix-exponential inversion after the `kappa`-fold contraction
has genuine implementation-choice sensitivity: a paper-only blind implementation
(G7) that chose a different `kappa` offset and ODE tolerance landed ~1e-4 from the
oracle on the mid-`n` cases. That is why **G7 is expected to be waived** (recorded
with the `[public, hidden]` score evidence, as with tasks 0011 and 0018) rather
than the tolerance being widened to ~1e-3, which would blunt every hidden case's
discriminating power against the audited shortcuts (whose errors are 1e-3 to 1e0).
