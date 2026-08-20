# scibench_replication_0020

Implement the paper's panel spatial Seemingly Unrelated Regression (SUR) model
with a spatial-lag-of-the-endogenous (SLM) structure, estimated by three-stage
least squares (3SLS), for daily COVID-19 incidence across 47 coterminous
Spanish provinces over a 30-day panel. The runner invokes
`<entrypoint> --input <input.json> --output <new-output-dir>`; write
`output.json`.

## Data

The dataset (population, GDP per capita, density, transit presence, daily
incidence, and lagged climatic variables for 47 provinces over 30 consecutive
days, plus a province adjacency table) is not shipped separately — you must
obtain it from the paper's own public data package
(`paezha/covid19-environmental-correlates` on GitHub, `covid19env` R data
package: `covid19_spain_1` and `provinces_spain`) or reconstruct an equivalent
panel from the paper's description. Two islands autonomous communities
(Baleares province, and the whole of Canarias) are excluded, leaving 47
coterminous provinces.

Each province-day observation has: `Incidence` (cases per 100,000), `GDPpc`
(GDP per capita, thousands of EUR), `Older` (percentage of population over
65), `Density` (population density), `Transit` (binary indicator for
presence of a mass transit system), and, for a given lag specification,
`Humidity`, `Mean_Temp`, and `Sunshine_Hours` computed as a moving average of
the preceding days (see "Lag specifications" below).

## Spatial weights

Build a 47x47 row-standardized ("W" style) queen-contiguity spatial weights
matrix `W` from the province polygons (two provinces are neighbors if they
share a boundary or touch at a vertex). Each row sums to 1; `W[i,j]` is
`1/(number of neighbors of i)` if `j` is a neighbor of `i`, else 0.

## Model

For each of the `G = 30` days (one day = one equation), the model is:

```
log(Incidence)_g = rho_g * W * log(Incidence)_g + X_g * beta_g + epsilon_g
```

where `X_g` (47 x 8) has columns, in this exact order: intercept,
`log(GDPpc)`, `log(Older)`, `log(Density)`, `Transit`,
`log(Humidity)`, `log(Mean_Temp)`, `log(Sunshine_Hours + 0.1)` (using that
day's lag-specification climatic values). `rho_g` is a per-equation spatial
autoregressive coefficient.

### Equality restrictions (`restricted` case)

When `restricted` is `true`, the `log(GDPpc)` and `log(Older)` coefficients
are constrained equal across all 30 equations (i.e. `beta_{GDPpc,g}` is the
same value for every `g`, likewise for `Older`); this reduces the regressor
matrix from 30 separate `log(GDPpc)`/`log(Older)` columns to one shared
column each, obtained by summing that regressor's per-equation columns into
a single pooled column (all other regressors, including the intercept and
`rho_g`, remain per-equation). When `restricted` is `false`, no restriction
is applied and every equation has its own full 8-coefficient block.

### 3-stage least squares (3SLS) estimation

Let `Z` be the (47*30 x (30 + p)) stacked regressor matrix, where `p` is the
number of `beta` columns (240 unrestricted, 182 restricted): column block `g`
of `Z`'s first 30 columns holds `W * log(Incidence)_g` in rows
`[(g-1)*47+1, g*47]` and zero elsewhere; the remaining columns are `X_g`
placed block-diagonally in the same row ranges (or the pooled columns from
the restriction step, contributing to every equation's row range).

Let `Y` be the stacked `(47*30 x 1)` vector of `log(Incidence)_g` values,
same row ordering as `Z`.

**Instruments.** Build `H = [W^2 * X_noIntercept, W * X_noIntercept, X]`,
where `X` is the same regressor matrix used for `Z` (with intercept
columns), `X_noIntercept` drops every intercept column, and `W^k` means `W`
applied `k` times via the same block-equation-wise spatial-lag operator
(`(I_G kron W)` applied to the full stacked vector, since there is one time
period). This gives instruments for the 30 `Wy_g` endogenous regressors.

**Stage 1.** OLS-fit each column of `Z` on `H` (no intercept), producing
fitted values `Z_hat` (first-stage predicted regressors).

**Stage 2.** OLS-fit `Y` on `Z_hat` (no intercept) to get residuals
`e`. Reshape `e` into a `(47 x 30)` matrix (47 provinces x 30 equations,
same row/column layout as `Z`'s blocks) and compute its `30 x 30` sample
covariance matrix `Sigma` (columns = equations, `ddof=1` / divide by `N-1`).

**Stage 3.** Feasible GLS: with `Omega_inv = Sigma^-1 kron I_47`,

```
beta_3sls = (Z_hat' * Omega_inv * Z_hat)^-1 * (Z_hat' * Omega_inv * Y)
```

The first 30 entries of `beta_3sls` are the `rho_g` (spatial autoregressive
coefficients, one per equation, in day order); the rest are the `beta`
coefficients, ordered to match `Z`'s regressor-column order. Standard errors
are `sqrt(diag((Z_hat' * Omega_inv * Z_hat)^-1))`, same ordering.

Fitted values use the **original** (non-instrumented) regressors:
`Y_hat = Z * beta_3sls`.

### R-squared

`pooled_r2` is the squared Pearson correlation between `Y` and `Y_hat` over
all `47*30` observations. `r2_by_equation` is, for each of the 30 equations
(in day order), the squared Pearson correlation between that equation's 47
observed and fitted values.

## Direct, indirect, and total effects

Because of the spatial lag term `rho_g * W * log(Incidence)_g`, an ordinary
`beta` coefficient is **not** the marginal effect of its regressor: a change
to `X_k` in one province also changes `log(Incidence)` in neighboring
provinces via `W`, which then feeds back through further neighbors. Following
LeSage and Pace (2009), decompose the `N x N` matrix of partial derivatives
`d log(Incidence)_g / d X_{k,g}` for each equation `g` and non-intercept
regressor `k` into:

- **Direct effect**: the mean of the diagonal elements (a province's own
  regressor affecting its own outcome).
- **Indirect effect**: the mean of the off-diagonal elements (spillover from
  other provinces' regressor values via contagion).
- **Total effect**: direct + indirect.

For the SLM specification used here, with `S_g(rho_g) = (I - rho_g * W)^-1`,
the exact partial-derivatives matrix for regressor `k` in equation `g` is
`S_g(rho_g) * beta_{k,g}`. Using the trace-based approximation of LeSage and
Pace (equivalent to expanding `S_g(rho_g) = sum_{q=0}^{Q-1} rho_g^q * W^q`
with `Q = 30` terms, i.e. `spatialreg::trW(..., type = "mult")`'s default
`m = 30`):

```
direct_{k,g}   = beta_{k,g} * (1/N) * sum_{q=0}^{Q-1} rho_g^q * tr(W^q)
total_{k,g}    = beta_{k,g} * (1/N) * sum_i sum_j S_g(rho_g)_{ij}
               = beta_{k,g} * sum_{q=0}^{Q-1} rho_g^q * (row-sums of W^q averaged)
indirect_{k,g} = total_{k,g} - direct_{k,g}
```

Equivalently and more directly: let `S_g = (I_47 - rho_g * W)^-1` (computed
exactly, not via the trace series) for each equation `g`. Then
`direct_{k,g} = beta_{k,g} * mean(diag(S_g))`, and
`total_{k,g} = beta_{k,g} * mean(rowSums(S_g))` (equivalently
`beta_{k,g} * (sum of all entries of S_g) / N`, since `W`, and hence `S_g`,
is row-standardized this equals `beta_{k,g} * mean(rowSums(S_g))`). Use the
exact `S_g` matrix inverse form (not a truncated series) for full precision;
this is algebraically identical to the trace series in the limit and matches
it to numerical precision for this well-conditioned `W`.

This decomposition applies to every non-intercept regressor in every
equation, using that equation's `rho_g` and `beta_{k,g}` (for the restricted
case, `log(GDPpc)` and `log(Older)` use the single pooled coefficient in
every equation's decomposition, each equation still using its own `rho_g`).
It does not apply to the intercept.

## Lag specifications

`input.json`'s `lag_spec` selects which moving average of the climatic
variables (`Humidity`, `Mean_Temp`, `Sunshine_Hours`) is used in `X_g`:

- `"lag8"`: an 8-day trailing moving average.
- `"lag11"`: an 11-day trailing moving average.
- `"lag11w"`: an 11-day trailing *weighted* moving average (more recent days
  weighted more heavily).

These pre-computed lagged series are part of the source dataset; you do not
need to re-derive the moving-average weighting scheme, only select the
correct pre-computed column set for the requested `lag_spec`.

## Input

```json
{"lag_spec": "lag8", "restricted": true}
```

`lag_spec` is one of `"lag8"`, `"lag11"`, `"lag11w"`. `restricted` is a
boolean.

## Output

Write JSON with these exact keys:

- `coefficients`: object mapping each `beta` coefficient's name to its
  estimated value. Name each per-equation coefficient
  `"<regressor>_<equation_number>"` (equation numbers 1-30, in day order,
  earliest day first), e.g. `"(Intercept)_1"`, `"log(Density)_7"`. For a
  restricted case, name the two pooled coefficients `"log(GDPpc)_1"` and
  `"log(Older)_1"` (they have no per-equation suffix beyond `_1`, since they
  are shared across all equations).
- `std_errors`: object with the same keys as `coefficients`, holding each
  coefficient's 3SLS standard error.
- `rho`: array of the 30 `rho_g` spatial autoregressive coefficients, in day
  order (earliest day first).
- `r2_by_equation`: array of the 30 per-equation R-squared values, in day
  order.
- `pooled_r2`: the single pooled R-squared value.
- `direct_effects`, `indirect_effects`, `total_effects`: objects with the
  same per-equation naming scheme as `coefficients` (`"<regressor>_<equation_number>"`,
  and the two pooled `"_1"`-suffixed names for a restricted case), but
  covering only the non-intercept regressors (no `"(Intercept)_g"` keys), each
  holding that regressor/equation's direct, indirect, or total effect as
  defined above.

Use float64 arithmetic throughout.
