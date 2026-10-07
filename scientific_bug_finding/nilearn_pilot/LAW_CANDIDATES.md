# Nilearn scientific-sanitizer law candidates

Written from a static read only (SANITIZER.md Step 2-3), before any checker code and
before executing any input through the functions below. Pinned base: fork
`ChenziqiAdam/nilearn` main = upstream `nilearn/nilearn` `d6c09c9a4a30ec5f6d7b5211268e0163825a9f2e`
(2026-10-02).

Fields: **Pre** input family where the law holds; **Law**; **Obs** observation point;
**Alarm** comparison of two quantities the law says agree; **Fam** root-cause family;
**Why**. T/X/P/N = tolerance / transform neutrality / precondition / probe coverage
(SANITIZER.md 5.8). `eps_d` is the machine epsilon of the dtype the production code
actually rounds in; `C = 64`.

Magnitude domain: checkers that form squares or products of the data are skipped when a non-zero
magnitude lies outside `[1e-100, 1e100]` (float64 underflow/overflow of the checker's own arithmetic).

Domain: neuroimaging (fMRI) statistics -- time-series cleaning, general linear model,
hemodynamic regressors, multiple-comparison control, functional connectivity,
permutation inference, spatial smoothing and resampling. This is a domain the existing
banks (biology, astronomy, chemistry, materials, quantum) do not touch.

Excluded by the engineering gate / SANITIZER.md 5.6: file I/O, BIDS/fMRIPrep interfaces,
datasets, plotting and reporting, surface meshes (`vol_to_surf` etc.), thin wrappers over
scikit-learn (`Decoder`, `SpaceNet`, `SearchLight`, `ReNA`/hierarchical clustering,
`CanICA`/`DictLearning` internals) and over SciPy kernels; pure arithmetic identities
(e.g. an HRF that is divided by its own sum summing to 1).

## Foreknowledge disclosure

The static read was a single pass over `signal.py`, `glm/{regression,model,contrasts,_utils,
thresholding}.py`, `glm/first_level/{hemodynamic_models,design_matrix}.py`,
`connectome/{connectivity_matrices,group_sparse_cov}.py`, `mass_univariate/*`,
`image/{image,resampling}.py` (smoothing, thresholding, resampling), `masking.py` and
`regions/signal_extraction.py`. While reading, the curator noticed several spots that
looked unusual: the F-contrast branch of `compute_contrast` (re-assigning `con_val` in the
loop, reading the loop variable after it for the dof); the `[1e-300, 1-1e-16]` clipping
asymmetry in `z_score`; the `psc` branch of `standardize_signal`; the in-place division of
`n_samples` in `_group_sparse_covariance`; `fdr_threshold`'s `- 1e-12` shift; the
`dt`-from-end-points definition in `create_cosine_drift`; the missing `dh` factor in
`calculate_tfce`. The laws below were written as general laws over input families and none
states a witness input; nothing was executed. GLM-003/006/008, SIG-003/007, THR-001 and
CON-008 sit near those spots and are flagged for an independent curator in the audit round
(SANITIZER.md 5.7.1).

---

## A. Signal processing -- `signal.py`

**SIG-001 Detrending removes constant and linear components.** Pre: finite 2-D signals,
`n >= 2`, `type="linear"`. Law: every column of the detrended output is orthogonal to the
constant vector and to the centred linear ramp (projection onto the complement of
span{1, t}). Obs: return of `_detrend`. Alarm: for any column, `|sum(out)|` or
`|r . out|` (`r` = centred ramp normalised to unit L2, rebuilt in float64) exceeds
`C * eps_d * sum|x_in|` (each output element carries a few ulps of the *input* magnitude;
`|r_i| <= 1`; `eps_d` of the working dtype, float32 stays float32). Fam `detrend_orthogonality`.
Why: linear detrending is defined as projecting out the drift.

**SIG-002 Z-scoring yields zero mean and unit sample variance.** Pre:
`standardize="zscore_sample"`, `n >= 2`, finite; column spread (after detrending, if any)
`std >= 1e6 * eps_d * max|x_in|` with `x_in` the input before detrending (below that the column
is numerically constant and the law does not apply). Law: `mean(out) = 0`, `var(out, ddof=1) = 1`. Obs: return of
`standardize_signal`. Alarm: `|mean| > C * eps_d * q` or `|var - 1| > C * eps_d * q` with
`q = max|x_in| / std` (output error is `eps_d * q` per element). Fam `zscore_moments`.

**SIG-003 Percent signal change scales by the baseline.** Pre: `standardize="psc"`,
`detrend=False`, column `|mean| >= 1e6 * eps_d * std`. Law: output has zero mean and
`std(out, ddof=1) = 100 * std(in, ddof=1) / |mean(in)|` (the output spread is 100 times the
input coefficient of variation). Obs: return of `standardize_signal`. Alarm: either relation
violated by more than `C * eps_d * q`, `q = max|x| / std`. Fam `psc_scaling`.

**SIG-004 Butterworth cut-off is the half-power point.** Pre: `0 < f_c / nyq <= 1 - 1e-3`
(and `f_c / nyq >= 1e-3`), `order <= 10`, edges not coerced by the Nyquist/zero guard, and for a
band the edge separation is at least 0.1 % of the larger edge.
Law: the designed filter has `|H(f_c)| = 1/sqrt(2)` at each requested critical frequency
(Hz, with the stated `sampling_rate`), for `low`, `high` and `band` filters. Obs: after the
`sos` is built in `butterworth`. Alarm: `| |H(f_c)| - 1/sqrt(2) | > 1e-6` where `H` is
evaluated with `scipy.signal.sosfreqz(..., fs=sampling_rate)` (second-order sections in
float64: error `~ C * eps * order * (nyq/f_c)^order` stays below 1e-6 inside the
precondition). Fam `butterworth_cutoff_gain`. Why: a cut-off in Hz that is mapped through the
wrong sampling rate or the wrong band type changes which frequencies survive.

**SIG-005 Confound regression leaves the signal uncorrelated with the confounds.** Pre:
`confounds` finite, `detrend=False`, no low/high-pass filter, `sample_mask=None`,
`runs=None`, `standardize` not `psc`; if `standardize_confounds=False`, `standardize` in
`{False, None}`. Law: the cleaned column is orthogonal to every confound column (centred if
`standardize_confounds=True`, raw otherwise). Obs: return of `clean`. Alarm:
`|c . out| > C * eps * kappa * ||c||_2 * ||out||_2` for any column, where `kappa` is the
condition number of the retained confound subspace (singular values above `1e-8 s_max`);
skipped when a singular value lies in `[1e-14 s_max, 1e-8 s_max]` (rank ambiguity, P). Fam
`confound_regression_orthogonality`. Why: the purpose of `confounds=` is removing their linear
contribution.

**SIG-006 Cosine drift regressors form an orthonormal DCT-II basis.** Pre: any `n >= 2`
frames, `high_pass > 0` producing at least one non-constant column. Law: the non-constant
columns have unit norm, are mutually orthogonal and orthogonal to the constant column.
Obs: return of `create_cosine_drift`. Alarm: `max |B^T B - I| > C * eps * (2 pi k_max + 1)`
for the non-constant block `B` (angle error `eps * pi * k` accumulated over `n` terms of
weight `2/n`), or `|sum(B_k)| >` the same bound. Fam `cosine_drift_orthonormal`.

**SIG-007 Cosine drift contains exactly the frequencies below the high-pass cut-off.** Pre:
uniformly spaced frame times (`max|diff - mean diff| <= 1e-6 dt`), `high_pass > 0` (the
`1e-9` relative margins in the alarm absorb the `floor` boundary at integer `2 n dt high_pass`).
Law: regressor `k` has frequency `k / (2 n dt)` Hz (k half-cycles over the run); every
included frequency is `<= high_pass` and, unless the basis is full (`m = n - 1`), the next
frequency is `> high_pass`. Obs: return of `create_cosine_drift`. Alarm: `f_m > high_pass`
or `f_{m+1} <= high_pass` with `m` the number of non-constant columns. Fam
`cosine_drift_cutoff`. Why: a high-pass filter must remove the stated band, not more or less.

**SIG-008 CompCor components are free of constant and linear trend.** Pre: `detrend=True`,
`n_confounds <=` numerical rank (selected eigenvalue `>= 1e-8` of the largest) with
relative gap to the neighbouring eigenvalues `>= 1e-6` (eigenvector conditioning). Law: each
returned component is orthogonal to the constant and to the centred ramp (it lies in the span
of detrended series). Obs: `high_variance_confounds` after `eigh`. Alarm:
`|sum(u_j)|` or `|r . u_j| > C * eps * sqrt(n) * s_max / gap_j`. Fam `compcor_trend_free`.

---

## B. General linear model -- `glm/`

**GLM-001 Least-squares residuals satisfy the normal equations.** Pre: any finite design
`X` (n x p), data `Y`; effective condition number `kappa_eff <= 1e8` over singular values
above the pinv cut-off, with no singular value in `[1e-2, 1e2]` times that cut-off. Law:
`X_w^T r_w = 0` for the whitened design/residuals (OLS and AR alike). Obs: return of
`OLSModel.fit`. Alarm: `max|X_w^T r_w| > C * eps * (n + p) * kappa_eff * ||X||_F * ||Y_j||_2`.
Fam `ols_normal_equations`.

**GLM-002 R-squared obeys the variance decomposition.** Pre: OLS (`ARModel` with all
`rho = 0` counts), the constant vector lies in the column space of `X` (least-squares
residual of the ones vector `<= C eps n kappa`), `var(Y) > 0`. Law:
`R^2 = 1 - SSE / (n var(Y))` and `0 <= R^2 <= 1`. Obs: `RegressionResults.r_square`. Alarm:
`|R^2 - (1 - SSE/(n var Y))| > C * eps * (kappa_eff + mean(Y)^2 / var(Y))` or `R^2` outside
`[-tol, 1+tol]` (up to 50 columns sampled). Fam `r_square_decomposition`.

**GLM-003 z-scores invert both tail probabilities.** Pre: entries with
`1e-300 < p < 1 - 1e-16` and, when given, the same for `one_minus_p`. Law: the returned `z`
satisfies `sf(z) = p` and `cdf(z) = one_minus_p`. Obs: return of `glm._utils.z_score`. Alarm:
for `z >= 0` `|sf(z) - p| > C * eps * (1 + z^2) * p`; for `z < 0` (when `one_minus_p` was
supplied) `|cdf(z) - one_minus_p| > C * eps * (1 + z^2) * one_minus_p`; without
`one_minus_p`, `|sf(z) - p| > C * eps` absolute. Fam `zscore_tail_consistency`.

**GLM-004 A one-dimensional F contrast is the square of the t contrast.** Pre: t-type
contrast with `dim = 1`, finite statistic, `p > 1e-290`. Law: `F = t^2` and the F-test p-value
equals the two-sided t p-value `2 min(p_t, 1 - p_t)`. Obs: `Contrast.p_value`. Alarm: a
`Contrast(..., stat_type="F", dim=1)` built from the same effect/variance/dof (re-call)
gives `|p_F - 2 min(p_t, 1 - p_t)| > C * eps * (1 + t^2) * p_F + 2 eps` (F and t tails use different
incomplete-beta paths; relative error grows like `eps t^2` in the far tail). Entries with
`p_t > 0.5` and `1 - p_t < 1e-3` are excluded: the stored one-sided p is not resolved there. Fam
`t_f_equivalence`.

**GLM-005 The t statistic is invariant to the scale of the contrast vector.** Pre: 1-D
contrast vector, `regression_result` from OLS/AR. Law: `t(a c) = sign(a) t(c)`,
`effect(a c) = a effect(c)`, `var(a c) = a^2 var(c)` for `a != 0`. Obs: return of
`compute_contrast` with `stat_type="t"`. Alarm: re-calls with `a = 2` and `a = -1` (both
exact in floating point) disagree with the original by more than `8 * eps * max(|t|, 1)`
(X: power-of-two scaling and negation introduce no rounding). Fam `t_contrast_scale_invariance`.

**GLM-006 The F statistic depends only on the row space of the contrast matrix.** Pre: F
contrast with `q >= 2` rows, `cond(C V C^T) <= 1e8` for the first label. Law: permuting rows
and scaling a row by 2 leave `F` unchanged. Obs: return of `compute_contrast` with
`stat_type="F"`. Alarm: re-call with reversed rows and with row 0 doubled gives
`|F' - F| > C * eps * kappa * max(F, 1)` (X: permutation and power-of-two scaling are exact;
the matrix square root contributes `eps * kappa`). Fam `f_contrast_row_space_invariance`.

**GLM-007 Fixed-effects pooling stays inside the physical bounds.** Pre: finite effects and
variances over `N >= 1` runs (variances clipped at `1e-16` as in the function). Law: the pooled
effect lies in `[min_i c_i, max_i c_i]`; unweighted pooled variance `mean(v)/N` lies in
`[min v / N, max v / N]`; inverse-variance pooled variance `1/sum(1/v)` lies in
`[min v / N, min v]` (independent estimates cannot be combined into a larger variance than the
best one, nor a smaller one than `N` equal ones). Obs: return of `_compute_fixed_effects_params`.
Alarm: any bound violated by more than `C * eps * N` relative. Fam `fixed_effects_pooling`.

**GLM-008 The z-score of a t contrast is odd in the effect.** Pre: t-type `Contrast`, finite
statistic, `p` unclipped. Law: `z(-effect) = -z(effect)` (the null t distribution is symmetric).
Obs: `Contrast.z_score`. Alarm: a re-call on a `Contrast` with negated effect gives
`|z(e) + z(-e)| > 2^10 * eps * (1 + z^2)` (X: negation is exact). Fam `zscore_antisymmetry`.

---

## C. Hemodynamic regressors -- `glm/first_level/hemodynamic_models.py`

**HRF-001 Orthogonalised regressors are mutually orthogonal.** Pre: 2-D `X`, `>= 2` columns,
columns with norm `< 1e-12 max` ignored. Law: after `orthogonalize`, column `i` is orthogonal
to every earlier column. Obs: return of `orthogonalize` (input snapshotted at entry). Alarm:
`|x_i . x_j| > C * eps * n * ||x_i^orig|| * ||x_j|| * kappa_j` for `j < i`, `kappa_j` = ratio of
largest to smallest non-zero norm among the first `i` columns (already orthogonal). Fam
`regressor_orthogonalization`. Why: derivative regressors are orthogonalised so that shared
variance is attributed to the canonical response.

**HRF-002 BOLD responses superpose.** Pre: HRF model producing one column per kernel without
orthogonalisation (`glover`, `spm`, `None`, single callable, `fir`); `>= 2` events. Law:
`reg(A union B) = reg(A) + reg(B)` for any partition of the events. Obs: return of
`compute_regressor`. Alarm: re-calls on the even/odd-index halves of the events (X: exact
partition; same time grid) differ from the full result by more than
`C * eps * (n_hr + len_h) * sum|v| * sum|h|` (cumulative sum and convolution lengths). Fam
`bold_superposition`.

**HRF-003 BOLD amplitude is homogeneous.** Pre: any HRF model, `>= 1` event. Law:
`reg(a v) = a reg(v)`. Obs: return of `compute_regressor`. Alarm: re-calls with `a = 2` and
`a = -1` differ by more than `C * eps * max|reg|` (X: exact scalings; orthogonalisation is
scale-covariant). Fam `bold_homogeneity`.

**HRF-004 The time-derivative kernel crosses zero at the HRF peak.** Pre: `onset` arbitrary,
the kernel contains the whole response (`|h(end)|, |h(0)| <= 1e-2 max h`), grid spacing `Delta` and finite-difference step `delta = 0.1 s`. Law: the finite-difference
derivative `d = (h(t) - h(t - delta)) / delta` of the response changes sign from positive to
negative within `delta + 2 Delta` of the argmax of `h`. Obs: return of
`_generic_time_derivative` (both HRFs). Alarm: first `+ -> -` sign change of `d` after the
start is further than `delta + 2 Delta` from `argmax(h)`. Fam `hrf_derivative_peak`.

---

## D. Multiple-comparison control -- `glm/thresholding.py`, `image/image.py`

**THR-001 FDR thresholds control the estimated false discovery rate.** Pre:
`height_control="fdr"`, finite statistics, `n >= 1`, finite threshold `u`. Law: with `R` the
number of statistics at or above `u`, `f * n * sf(u) / R <= alpha` where `f = 2` for two-sided
tests (`f = 1` otherwise). Obs: `threshold_stats_img` after the threshold is computed (uses
the original `alpha`, not the internal `alpha/2`). Alarm: ratio exceeds `alpha * (1 + 1e-9)`
(the `- 1e-12` shift times `|u| <= 40` plus rounding). Fam `bh_fdr_control`.

**THR-002 Height-control methods are ordered by conservativeness.** Pre: finite statistics.
Law: number of discoveries `R_bonferroni <= R_fdr <= R_fpr` for the same data, alpha and
sidedness. Obs: `threshold_stats_img` (any of the three methods; re-calls for the other two
under a re-entrancy guard). Alarm: strict count of a more conservative method exceeds the
loose count of the less conservative one (margin `1e-9 (1 + |u|)` on each threshold). Fam
`multiple_comparison_ordering`.

**THR-003 Cluster-extent thresholding removes exactly the small clusters.** Pre: 3-D/4-D
volume, `cluster_threshold > 0`. Law: in the output, every 6-connected same-sign component has
size `>= cluster_threshold`, and every voxel of a pre-cluster component of size
`>= cluster_threshold` survives. Obs: return of `threshold_img` (pre-cluster data snapshotted).
Alarm: an independent `scipy.ndimage.label` finds an undersized surviving component or a
removed voxel in a large component. Fam `cluster_extent_semantics`.

---

## E. Functional connectivity -- `connectome/`

**CON-001 Correlation is invariant to rescaling variables.** Pre: symmetric covariance with
positive diagonal. Law: `corr(D S D) = corr(S)` for positive diagonal `D`. Obs: return of
`cov_to_corr`. Alarm: re-call with `D = diag(2^k_i)`, `k_i = (i mod 5) - 2` (X: exact) differs by
more than `C * eps`. Fam `correlation_scale_invariance`.

**CON-002 Connectivity matrices are valid covariance-type matrices.** Pre: finite output of
the estimator. Law: `covariance` and `correlation` outputs are symmetric positive
semi-definite (correlation with unit diagonal); `precision` outputs are symmetric positive
definite. Obs: end of `ConnectivityMeasure._fit_transform` (non-tangent). Alarm: asymmetry
`> C eps ||M||` or `lambda_min < -C eps p lambda_max` (`lambda_min <= 0` for precision, strictly
negative `lambda_min` for others beyond tolerance). Fam `connectivity_psd`.

**CON-003 Partial correlation equals the correlation of regression residuals.** Pre: covariance
with `cond <= 1e8`, `p >= 2`. Law: for any pair `(i, j)` the partial correlation given all other
variables equals `Sigma_{ij.rest} / sqrt(Sigma_{ii.rest} Sigma_{jj.rest})` with the Schur
complement `Sigma_ab - Sigma_{a,rest} Sigma_{rest,rest}^{-1} Sigma_{rest,b}`. Obs: partial
correlation branch of `ConnectivityMeasure._fit_transform` (up to 10 pairs, local RNG).
Alarm: difference `> C * eps * kappa * sqrt(p)`. Fam `partial_correlation_schur`.

**CON-004 / CON-005 Vectorisation is a scaled isometry.** Pre: symmetric matrices (batch
allowed). Law: `||vec(S)||^2 / ||S||_F^2` is the same constant for every symmetric `S`
(diagonal and off-diagonal entries are weighted consistently). Obs: return of
`sym_matrix_to_vec` (004) and `vec_to_sym_matrix` with `diagonal=None` (005). Alarm: the ratio
for the observed matrix differs from the ratio of the two probe matrices `E_00` and
`E_01 + E_10` passed through the same function, or the probes disagree, by more than
`C * eps * p^2` relative. Fam `symmetric_vectorization_isometry`.

**CON-006 The Frechet mean of SPD matrices is congruence-equivariant.** Pre: SPD inputs with
`kappa <= 1e6`, `_geometric_mean` converged. Law: `G(D S_k D) = D G(S_k) D`. Obs: return of
`_geometric_mean`. Alarm: re-call with `D = diag(2^k_i)` differs (after undoing `D`) by more
than `4 * tol_alg * size + C * eps * kappa * p * max_iter` relative to `||G||_F` (both runs stop
within the algorithm's own tolerance). Fam `frechet_mean_equivariance`.

**CON-007 The tangent-space embedding is centred at the mean.** Pre: `kind="tangent"`,
`fit_transform` on the training group, `n >= 2`, the Frechet-mean iteration converged (nilearn
warns when it stops at `max_iter`). Law: the mean over subjects of the embedded
matrices is zero (the reference point is the Frechet mean). Obs: end of
`ConnectivityMeasure._fit_transform`. Alarm: `||mean_k T_k||_F / p^2 > 1e-6` (ten times the
convergence tolerance of the fit). Fam `tangent_embedding_centering`.

**CON-008 Above `alpha_max` the group-sparse graph is empty.** Pre: `alpha >= 1.001 *
compute_alpha_max(emp_covs, n_samples)[0]` (n_samples normalised as the solver does),
default (diagonal) initialisation. Law: all off-diagonal precision entries are zero.
Obs: end of `_group_sparse_covariance`. Alarm: any `|Omega_ij,k| > C * eps * max diag`. Fam
`group_lasso_empty_graph`.

**CON-009 Estimated precision matrices are symmetric positive definite.** Pre: finite
output. Law: each `Omega[..., k]` is symmetric with `lambda_min > 0`. Obs: end of
`_group_sparse_covariance`. Alarm: asymmetry `> C eps ||Omega||` or
`lambda_min <= C * eps * p * lambda_max`. Fam `group_sparse_precision_spd`.

---

## F. Mass-univariate inference -- `mass_univariate/`

**MU-001 Permutation-test t scores equal GLM t scores.** Pre: finite data, `n > p + 2`,
design `kappa <= 1e8`; up to 5 descriptors and all tested regressors sampled. Law: the
original-data t score of regressor `r` equals the Wald t of column `r` of the OLS fit on
`[tested_r, confounds (+ intercept)]`. Obs: `permuted_ols`, right after the original scores.
Alarm: `|t_perm - t_glm| > C * eps * kappa * (1 + |t|) * (1 + t^2 / dof)`, where `1 + t^2/dof =
1/(1 - R^2)` is the conditioning of `t`; entries with `1 + t^2/dof > 1e8` (exact or numerically
exact fit: `t` infinite / rounding noise) are excluded. Fam `permuted_ols_vs_glm`.

**MU-002 Two-sided TFCE is odd in the statistic map.** Pre: `two_sided_test=True`. Law:
`tfce(-X) = -tfce(X)`. Obs: return of `calculate_tfce` (calls sampled: 1, 2, 4, 8, ...).
Alarm: re-call on `-X` differs by more than `C * eps * max|tfce|` (X: negation exact). Fam
`tfce_sign_symmetry`.

**MU-003 TFCE is homogeneous of degree H in the statistic.** Pre: `dh="auto"` (the step count
is data-independent), finite `X`. Law: `tfce(c X) = c^H tfce(X)` for `c > 0`. Obs: return of
`calculate_tfce`. Alarm: re-call on `2 X` differs from `2^H tfce(X)` by more than
`C * eps * max|tfce|` (X: power-of-two scaling is exact, `linspace` thresholds scale exactly).
Fam `tfce_homogeneity`.

**MU-004 Permutation p-values are non-increasing in the statistic.** Pre: any test values and
null sample. Law: larger evidence (larger `|t|`, or larger / smaller `t` for one-sided
alternatives) never has a larger p-value. Obs: return of `null_to_p`. Alarm: after sorting the
test values by evidence, some consecutive pair has `p_i < p_{i+1}`. Fam `permutation_p_monotone`.

**MU-005 Cluster-level measures are symmetric in the sign of a two-sided map.** Pre:
`two_sided_test=True`. Law: `(max size, max mass)(-X) = (max size, max mass)(X)`. Obs: return
of `calculate_cluster_measures` (calls sampled as MU-002). Alarm: re-call on `-X` differs in size
or by more than `C * eps * max mass` in mass. Fam `cluster_measure_sign_symmetry`.

---

## G. Images -- `image/`, `regions/`

**IMG-001 Gaussian smoothing conserves intensity and creates no new extrema.** Pre: numeric
FWHM (not `"fast"`: that kernel is documented as non-conservative on array edges), finite data
after the documented NaN replacement. Law: `sum(out) = sum(in)` (symmetric reflect boundary =>
doubly stochastic) and `min(in) <= out <= max(in)` (non-negative weights summing to one). Obs: return of `smooth_array`. Alarm: sum differs by more than
`C * eps_d * (sum_axes kernel_len + log2 N) * sum|x|` (`kernel_len = 2 int(4 sigma + 0.5) + 1`),
or extrema exceeded by more than `C eps_d (max - min)`. Fam `smoothing_conservation`.

**IMG-002 Smoothing kernels add in quadrature.** Pre: numeric FWHM with `sigma_vox / sqrt 2 >=
1` on every smoothed axis, `N <= 2e6` voxels. Law: smoothing with `f/sqrt(2)` twice equals
smoothing with `f`. Obs: return of `smooth_array`. Alarm: max difference `> 4 * 3 * 6.3e-5 *
(max - min) + C * eps_d * kernel_len * (max - min)` (kernel truncated at 4 sigma loses 6.3e-5
per pass; sampling aliasing `e^{-2 pi^2} < 3e-9`). Fam `smoothing_fwhm_quadrature`. Why: FWHM
in millimetres must combine like Gaussian widths.

**IMG-003 Resampling preserves world-space geometry.** Pre: resampling actually performed,
(integer outputs are quantised by the cast, one unit is allowed),
3-D (or first volume of 4-D), sampled interior output voxels whose source coordinate lies at
least one voxel inside the input (and `>= 1e-6` from a half-integer for `nearest`). Law:
the value of output voxel `v` equals the input interpolated (same order) at
`inv(A_in) A_out v` using the *returned* affine `A_out`. Obs: return of `resample_img`.
Alarm: difference `> C * eps_d * max|x| * 8` (cubic spline conditioning) from
`scipy.ndimage.map_coordinates`, with clipping and fill applied as documented. Fam
`resample_world_geometry`.

**IMG-004 Region signals expanded to an image average back to themselves.** Pre: 2-D signals,
every label survives the mask. Law: `img_to_signals_labels(signals_to_img_labels(S)) = S`.
Obs: return of `signals_to_img_labels`. Alarm: re-call difference `> C * eps * max|S|`. Fam
`label_signal_roundtrip_consistency`.

**IMG-005 Map-based region signals are recovered by least squares.** Pre: masked maps matrix
full column rank with `kappa <= 1e6`. Law: `img_to_signals_maps(signals_to_img_maps(S)) = S`.
Obs: return of `signals_to_img_maps`. Alarm: difference `> C * eps * kappa * ||S||_F`. Fam
`maps_signal_consistency`.

---

## Revision log (checker-side defects only; filled after audits)

Pre-implementation correction (law level, before any run): IMG-001 originally also claimed the
extrema bound for `fwhm="fast"`; that kernel is non-conservative at edges by design, so it was
restricted to numeric FWHM.

First reachability probe (2026-10-07), valid probe inputs only:
1. **GLM-004 (T, cancellation)**: the reference two-sided p `2 min(p_t, 1 - p_t)` uses the stored
   one-sided `p_t = sf(t)`, which rounds to 1 for strongly negative `t`, giving 0. Entries with
   `p_t > 0.5` and `1 - p_t < 1e-3` are now excluded. The tolerance factor `(1 + |t|)` was too
   tight for heavy tails (relative error 6e-10 at `t = 267`, dof 3), now `C eps (1 + t^2)`.
2. **SIG-007 (P)**: the extra exclusion of integer `2 n dt high_pass` was unnecessary (the 1e-9
   margins already cover it) and hid the checker on round parameters such as `n=100, TR=2,
   high_pass=0.02`; removed.

First upstream-suite run, checks on (2026-10-07; 1,708 tests in the instrumented modules, 20
baseline failures identical to the pristine tree, all in report rendering):
3. **SIG-002 (P/T, scale of the error)**: `test_standardize` and `test_clean_finite_no_inplace_mod`
   alarmed. After detrending a ramp / a two-sample column the column is rounding noise, so the
   library's constant-column guard (`std < eps -> 1`) correctly leaves it unscaled. The
   precondition and `q` were measured against the post-detrend magnitude; they must use the
   input magnitude (`mx_in`), which is what sets the rounding error.
4. **MU-001 (T, conditioning)**: `test_two_sided_recover_positive_and_negative_effects`,
   `test_tfce_smoke_legacy_smoke`, `test_tfce_no_masker_error` alarmed. Their target is exactly
   proportional to the tested variable (`1 - R^2 = 0`): `t` is infinite for the permutation
   path and rounding noise for the OLS path. The conditioning factor `1/(1 - R^2)` was missing
   from the tolerance and the exact-fit case from the precondition.

Adjudicated natural trigger, not a checker defect: after fix 3, `test_clean_finite_no_inplace_mod`
(`clean` on a 2-sample signal) still alarms SIG-002 on the *second*, internal `standardize_signal`
call, whose input is the rounding-noise column left by the first detrend (amplitude ~1e-17, spread
comparable to its magnitude). `standardize_signal` replaces `std < finfo(float64).eps` by 1, so such a
column is not scaled to unit variance, while the documented contract ("scaled to unit variance") has
no scale exception. The behaviour is scale-dependent (a genuine signal of amplitude < 2.2e-16, e.g.
femtotesla-scale data in SI units, is silently left unscaled). Recorded as audit data on the
`zscore_moments` family; whether it is a library defect is decided in the issue-drafting step.

Fuzz batch 1 (seeds 0-1, 14 case-sets x 8 areas each = 224 cases; alarms replayed from the saved seed):
5. **MU-001 (T, conditioning), 5 alarms**: values agreed to 1e-12 but the tolerance used the
   column-normalised `kappa` and the partial `1/(1 - R^2)`. `permuted_ols` forms
   `rss = 1 - a2 - beta^2` on unit-norm data, so the error follows `||y||^2 / ||residual||^2` of the
   *full* fit (large for data with an offset), and the OLS reference solves a `pinv` of the *raw*
   design, whose error follows the raw condition number. Both now used.
6. **SIG-008 (T, offset)**: the detrended series carry `eps * max|x_in|` of rounding noise per
   entry (here an offset 550x the spread), which leaks into the constant/ramp modes with weight
   `||E||_F / ||S||_F`. Added to the tolerance (`||S||_F^2 = n * sum(eigenvalues)`, needs no data).
7. **SIG-005 (X/T, units)**: tolerance was in input units, but a z-scored output is the residual
   divided by its own std, which scales the projection's rounding error by the same factor. The
   checker now recomputes the residual of the sampled columns independently and applies `1/std`.

Fuzz batch 2 (seeds 10-17, 100 case-sets x 8 areas = 6,400 cases; every ID reached >= 5 times):
8. **GLM-002 (T, conditioning), 3 alarms**: tolerance `eps (kappa + mean^2/var)` added the two
   amplifications; prediction error is `eps * kappa * ||y||`, i.e. `eps * kappa * sqrt(1 +
   mean^2/var)` relative to the spread, so they multiply. Now `4 C eps (1 + kappa sqrt(1 +
   mean^2/var))` with the data dtype's eps.

Fuzz batches 3-4 (seeds 20-27 clean; stress seeds 30-37 with scales to +-14 decades, 6,400 cases each):
9. **IMG-002 (T, offset), 3 alarms**: float32 volumes whose offset is far above their range
   (range 4e-3): rounding scales with `max|x|`, not `max - min`. Fixed.
10. **IMG-004 (T, accumulation), 2 alarms**: `ndimage.mean` sums a region sequentially, error
    `~ n_voxels * eps`; the tolerance had no region-size factor. Fixed.

First fresh-agent run (Sonnet 5.5, prompt-only isolation, 41 passing tests in one new file, 28 IDs scored;
`fresh_sonnet55/`). Every trigger was replayed and adjudicated; 23 IDs were checker-side defects, 5 real:
11. **Float32 data, tolerance in float64 eps (T)**: GLM-001/003/004/008, HRF-001, MU-001, IMG-005, CON-003
    used `eps` of float64 while the library rounds in the dtype of its inputs. Now the largest input eps.
12. **Underflow/overflow of the checker's own products (P)**: tests with amplitudes 1e-125..1e-320 made
    squares and products subnormal (tolerance 0, `-inf` ratios). GLM-001/002/007, HRF-001..003, IMG-001/002/005,
    CON-001/003/004/005, MU-001, SIG-001/005/008 and the SIG-002 upper range now skip magnitudes outside
    `[1e-100, 1e100]`. SIG-002 keeps firing below `2.2e-16` (library guard, see natural trigger above).
13. **CON-007 (P)**: the tangent embedding is centred only at a converged mean; nilearn warns
    ("Maximum number of iterations 30 reached") and the vectors average to 8e-5 per entry. Gated through a flag
    set at the warning.
14. **SIG-005 (T)**: float64 centring of the confounds leaves a mean `eps * offset`; the signal's own offset
    multiplies it. Verified against a 60-digit mpmath reference: library error `4e-5` at offset/std = 3e5,
    `3e-13` at 30, i.e. `eps (offset/std)^2`. Tolerance multiplied by `1 + max |mean|/std` of the confounds.
15. **SIG-007 (P)**: the library uses the mean frame step, the checker the median; a 1e-6 jitter moves the
    boundary by 2e-8 relative, but the margin was 1e-9. Margin now `1e-9 + 4 * jitter / dt`.
16. **HRF-004 (P)**: `time_length = 8` truncates the response; the sum-normalised shifted kernel is renormalised
    differently, so the zero crossing moves 0.4 s before the peak. Precondition `|h(end)| <= 1e-2 max h`.
17. **SIG-004 (P)**: band edges 1e-8 apart make an order-5 `sos` unable to resolve both edges (gain error 5e-6).
    Precondition: edge separation >= 0.1 % of the larger edge.
18. **IMG-003 (T)**: int16 output is quantised by the cast; one unit is allowed.
19. **GLM-002 (P), found by the next stress batch**: spread below the rounding of a 1e30 offset leaves R^2
    undetermined (tolerance > 1). Columns with tolerance >= 0.5 are skipped.

Real after adjudication (checker kept): SIG-002 (std < eps guard, above), THR-003 (below), SIG-001/003/008:
- **THR-003, library defect on valid input**: `_apply_cluster_size_threshold` takes `np.unique(label_map)[1:]`
  assuming label 0 exists; when the whole volume is one cluster there is no background, so the only cluster is
  never size-tested and survives (1x1x1 and 2x1x1 volumes with `cluster_threshold=5`). Contrived: needs a volume
  with fewer voxels than the cluster threshold.
- **SIG-001/003/008, float32 accumulation**: numpy sums float32 columns sequentially along axis 0, so detrend and
  percent signal change on float32 series lose accuracy with length and offset: mean of the detrended output 0.16
  (std 1) at n = 1e5, offset 1e4; `high_variance_confounds` returns the constant vector as first component at
  offset >= 1e5 (n = 2000) (cos with float64 result 0.02). Not seen at n <= 2000 with offset <= 1e4.

Verification after the fixes: isolated sensitivity 33/33, reachability 42/42, fuzz seeds 50-57 (896 cases) and
stress 60-67 (896 cases, scales to +-30 decades) show only SIG-002 alarms at extreme scales.

First fresh Opus 5.5 run (frozen commit `0b2557ea4`, 7 passing tests in 3 files, 8 IDs; `fresh_opus55/`). Scorer defect found
first: `scibench_pytest_plugin` flagged every test as tampered because `nilearn._utils.data_gen.get_legal_confound`
(upstream production code that re-exports a helper living in `fmriprep/tests/_testing.py`) matched the
"function defined under /tests/" rule. The rule now applies only to functions defined in files added by the submission
(`SCIBENCH_SUBMITTED`); the four demo submissions score as before.
20. **GLM-007 (T)**: float32 effect/variance maps; tolerance used float64 eps. Now the largest input eps.
21. **HRF-004 (P)**: negative onsets truncate the head of the response (`h(0) > 0`); same renormalisation artefact as
    item 16. Precondition extended to `|h(0)| <= 1e-2 max h`.
22. **CON-001 (P)**: float32 variances 1e-40 are subnormal in float32. `_scale_ok` now also skips magnitudes below
    `1e4 * tiny` of the data's own dtype.

Real after adjudication (checkers kept): SIG-001, SIG-002, and
- **GLM-003/GLM-008, stale cache (strong)**: `Contrast.z_score(baseline)` recomputes `p_value_` when the baseline
  changes but reuses the cached `one_minus_pvalue_` (`if self.one_minus_pvalue_ is None`), so `z_score()` followed by
  `z_score(baseline=3.0)` mixes tails of two different nulls. On the pristine tree the second call returns
  `[0.976, 1.886]` where a fresh object returns `[-1.886, -0.976]` (sign flipped).
- **SIG-005, absolute cutoff in the confound QR**: confounds of amplitude 1e-18 are dropped (cutoff `100 eps` on the
  unscaled columns, also with `standardize_confounds=True` because the z-scoring guard has the same absolute `eps`):
  the cleaned signal keeps 95 % of its norm in the span of the confounds (1e-15 at amplitude 1 and 1e-10).
