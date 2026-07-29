"""Manually rewritten public method dossiers.

These texts intentionally omit paper identity, bibliographic metadata, verbatim
abstracts/introduction, result values, and implementation references. Equations
and experimental settings required for scientific replication are retained.
"""

from __future__ import annotations


DOSSIERS = {
    "0007": r"""
# Anonymous replication dossier: transformed regression

## Scientific objective

Quantify the bias introduced when noisy exponential-decay observations are
log-transformed before regression. Compare fitting in the original observation
space with ordinary and weighted least squares in transformed space.

## Model and estimators

Use the first-order decay model

[EQUATION]

    y(t) = y_0 exp(-k t).

The transformed relation is

[EQUATION]

    log(y(t)) = -k t + log(y_0).

For every simulated data set, estimate k in two ways:

1. Fit y(t) directly to the exponential model by nonlinear least squares,
   treating both k and y_0 as free parameters.
2. Fit log(y(t)) against t by linear least squares and negate the fitted slope.

The unweighted comparison assumes constant additive uncertainty in the original
observation space. For the weighted comparison, propagate a common observation
standard deviation through the logarithm. The transformed uncertainty for an
observation y_i is sigma_log,i = sigma_y / y_i, so the corresponding WLS weight
used by the reference experiment is proportional to 1 / sigma_log,i. This is
the historical weighting convention evaluated by this replication task. Use
the same generated observations for the paired nonlinear and transformed fits.

## Monte Carlo protocol

Set k = 0.15 s^-1 and y_0 = 7.5 mol m^-3. Generate 2^15 independent noisy data
sets using NumPy's default random generator initialized with seed 1, at
t={2,4,6,8,10,12,14,16,18,20} seconds. Use additive Gaussian measurement
noise with standard deviation
0.3 mol m^-3 for the uncertainty-aware comparison. Reject or otherwise handle
non-positive noisy concentrations consistently before taking a logarithm; do
not silently replace the requested number of successful replicates.

For every fitted rate constant, form the dimensionless normalized estimate
r = k_hat / k, where the denominator is the true rate constant k = 0.15 s^-1.
Compute the requested means and the 2.5th and 97.5th percentiles from the
empirical distribution of r, not from the raw fitted k_hat values. The six
artifacts correspond to the transformed and direct-fit normalized summaries for
the OLS and WLS comparisons. Write each requested artifact separately.

[MASKED: all reference estimates and interval endpoints are withheld.]
""",
    "0008": r"""
# Anonymous replication dossier: finite-temperature single-spin curves

## Scientific objective

For one spin in a constant field along z, reproduce five families of thermal
expectation-value curves. Compare the exact discrete quantum calculation,
continuous coherent-state approximations, and classical limits. This task
evaluates only the finite deterministic curves; stochastic spin-dynamics
estimates and graphics are outside its scope.

## Definitions

Let s be the spin quantum number, beta = 1/(k_B T), and use the Zeeman
Hamiltonian H = -g mu_B B_z S_z / hbar. In the discrete basis,
S_z |s,m> = hbar m |s,m>, with m = -s,...,s. The exact reference expectation is

[EQUATION]

    <S_z>_q =
      sum_{m=-s}^{s} hbar m exp(beta g mu_B m B_z)
      / sum_{m=-s}^{s} exp(beta g mu_B m B_z).

Introduce coherent states indexed by complex z:

[EQUATION]

    |z> = (1+|z|^2)^(-s)
          sum_{p=0}^{2s} binom(2s,p)^(1/2) z^p |p>,
    dmu(z) = (2s+1)/pi * dz/(1+|z|^2)^2.

Map z to the unit-vector component

[EQUATION]

    n_z = (1-|z|^2)/(1+|z|^2).

The leading moments needed by the expansion are

[EQUATION]

    <z|S_z|z> = hbar s n_z,
    <z|S_z^2|z> = (hbar s n_z)^2
                  + 2 hbar^2 s |z|^2/(1+|z|^2)^2.

Higher powers contain the classical term (hbar s n_z)^k plus corrections of
higher order in 1/s. Generate the coherent-state approximation by expanding the
operator exponential in beta and retaining the requested number of correction
orders for each logical curve.

## Classical and coherent-state expectations

The classical-limit expectation can be evaluated as

[EQUATION]

    <n_z>_cl =
      integral_{-1}^{1} n_z exp(beta g mu_B s B_z n_z) dn_z
      / integral_{-1}^{1} exp(beta g mu_B s B_z n_z) dn_z.

For a coherent-state effective Hamiltonian H_eff, use

[EQUATION]

    <S_z>_eff =
      integral dmu(z) hbar s n_z exp(-beta H_eff)
      / integral dmu(z) exp(-beta H_eff).

A coarse low-temperature correction is

[EQUATION]

    H_eff_low =
      -g mu_B B_z s n_z
      + (1/2) g mu_B B_z sqrt(2s) sqrt(1-n_z^2).

For the high-temperature construction, start from the exact coherent-state
integrand

[EQUATION]

    F(beta,z) = exp(-beta g mu_B s B_z)
      ((exp(beta g mu_B B_z)+|z|^2)/(1+|z|^2))^(2s).

Expanding log(F) through third order in beta gives the effective Hamiltonian

[EQUATION]

    H_eff_high =
      -g mu_B s B_z n_z
      -(1/4) beta (g mu_B)^2 s B_z^2 (1-n_z^2)
      +(1/12) beta^2 (g mu_B)^3 s B_z^3 n_z(1-n_z^2).

When the approximate coherent-state observable is used, apply the normalization
required by its beta -> infinity limit, which is s^2/(s+1), so the saturated
observable has the correct scale.

## Curve groups

Use the following fixed curve ordering:

- Group 1 (`curve_01`--`curve_05`, s=0.5): classical limit; coherent-state
  series with one, two, and three retained correction orders; exact quantum.
  Use 500 uniformly spaced temperatures from 0.02 K to 5 K.
- Group 2 (`curve_06`--`curve_14`): classical curves for s={0.5,2,5};
  low-temperature curves for s={0.5,2,5}; exact quantum curves for s={0.5,2,5}.
  Use 100 uniformly spaced temperatures from 0.02 K to 5 K.
- Group 3 (`curve_15`--`curve_18`, s=2): classical, first-order
  high-temperature, second-order high-temperature, and exact quantum curves.
  Use 100 uniformly spaced temperatures from 0.07 K to 5 K.
- Group 4 (`curve_19`--`curve_21`, s=2): normalized coherent-state,
  unnormalized coherent-state, and exact quantum curves.
  Use 50 uniformly spaced temperatures from 0.07 K to 5 K.
- Group 5 (`curve_22`--`curve_23`, s=2): classical and exact quantum curves.
  Use 500 uniformly spaced temperatures from 0.02 K to 5 K. The divergent
  high-order curve with non-finite low-temperature values is intentionally
  excluded.

[MASKED: all reference curves and numerical comparisons are withheld.]
""",
    "0009": r"""
# Anonymous replication dossier: deterministic Floquet system identification

## Scientific objective

Reproduce a deterministic stroboscopic Floquet-DMD experiment for a driven
two-level quantum system. Learn a one-drive-period propagator from four
training periods and extrapolate the Pauli-vector trajectory. No measurement
noise or random sampling is used.

## State dynamics

Use the Hamiltonian

[EQUATION]

    H(t) = pi sigma_3 + cos(2 pi omega_D t) sigma_1,
    omega_D = 1.1.

The intrinsic period is 1 and the drive period is T=1/omega_D. Start in the
lower sigma_3 eigenstate and record

[EQUATION]

    x(t) = (<sigma_1>, <sigma_2>, <sigma_3>)^T.

Equivalently, evolve the density matrix with the von Neumann equation or the
real Bloch vector with

[EQUATION]

    dx_1/dt = -2 pi x_2,
    dx_2/dt = 2 pi x_1 - 2 cos(2 pi omega_D t) x_3,
    dx_3/dt = 2 cos(2 pi omega_D t) x_2.

## Floquet snapshots

Sample four equally spaced phases per drive period. Arrange one period in each
column:

[EQUATION]

    z_n = [x(nT); x(nT+T/4); x(nT+T/2); x(nT+3T/4)].

The one-period propagator exists because

[EQUATION]

    P_T(t_0) = exp(-i T H_F(t_0)).

Use z_0,z_1,z_2,z_3 as the four training columns. Apply rank-three exact DMD to
the three offset pairs:

[EQUATION]

    X  = [z_0,z_1,z_2],
    X' = [z_1,z_2,z_3].

If X=U Sigma V^dagger, diagonalize

[EQUATION]

    A_tilde = U^dagger X' V Sigma^(-1).

Return its three eigenvalues. Use the full fifth-period column z_4 as the
initial condition and extrapolate eight subsequent periods. Submit the 32
predicted phase samples for periods beginning at 5T through 13T (endpoint
excluded); do not include z_4 itself in the submitted prediction.

## Output requirements

Save the eigenvalues as `floquet_eigenvalues`, a float array of shape (3,2)
whose columns are real and imaginary parts. Save the 32 sample times as
`prediction_times` and the three Pauli components as
`prediction_trajectory` with shape (3,32). Eigenvalue order is arbitrary.

[MASKED: all eigenvalues, extrapolated values, comparisons, and original
graphics are withheld.]
""",
    "0011": r"""
# Anonymous replication dossier: correlated displacement regression

## Scientific objective

Reproduce a complete stochastic experiment comparing ordinary, weighted, and
generalized least-squares estimates of a diffusion coefficient from correlated
mean-squared-displacement (MSD) observations. Generate every trajectory from
the prescribed seeds; do not substitute a published MSD curve or sample from a
fitted distribution.

## Random-walk experiment

For each integer seed from 0 through 4095, initialize an independent legacy
MT19937 random-number generator using the semantics of
`numpy.random.RandomState(seed)`. Simulate 128 particles, each taking 128 steps
on a three-dimensional cubic lattice. Draw all direction indices in one call
equivalent to `rng.choice(6, size=(128,128))`: rows index particles and columns
index consecutive timesteps. Map choices, in order, to displacement vectors

[EQUATION]

    (+j,0,0), (-j,0,0), (0,+j,0), (0,-j,0), (0,0,+j), (0,0,-j),
    where j = 2.4494897428.

This decimal step length is part of the fixed workflow and makes the true
diffusion coefficient numerically equal to one in the dimensionless timestep
convention because <|Delta r|^2> = 6 D Delta t.

For a lag k in {1,...,128}, include the implicit position at time zero and
calculate all valid time-origin displacements for each particle:

[EQUATION]

    MSD_s(k) = 1 / [128(129-k)]
               sum_{p=1}^{128} sum_{t=0}^{128-k}
               |r_{s,p}(t+k)-r_{s,p}(t)|^2.

The submitted `msd` array contains lags k=2,...,128 in increasing order and has
one row per seed, producing shape (4096,127). Lag one is excluded from the
regression experiment.

## Covariance and regressions

Compute the unbiased sample covariance across the 4096 MSD curves, using the
4095 denominator. Submit this 127 by 127 matrix as `covariance`. Let the time
vector be t=(1,2,...,127), matching the historical index convention for the
selected MSD columns, and use a design matrix with columns [t,1]. Thus every
fit includes an intercept. For a response vector y, calculate

[EQUATION]

    beta_hat = (A^T W A)^(-1) A^T W y,
    D_hat = beta_hat[0] / 6.

Use W=I for OLS, `numpy.linalg.pinv` with `rcond=1e-15` on the diagonal
covariance for WLS, and the same pseudoinverse convention on the full covariance
for GLS. Apply each fixed weight matrix to all 4096 response curves. Submit
`diffusion_estimates` with rows ordered OLS, WLS, GLS and shape (3,4096).

## Summary statistics

Submit a JSON object named `summary`, keyed exactly by `OLS`, `WLS`, and `GLS`.
For every method provide `population_mean` and
`population_standard_deviation`; the latter uses the population convention
with denominator 4096. Also provide `analytical_uncertainty`. For WLS and GLS,
this is sqrt([(A^T W A)^(-1)]_00)/6. For OLS, calculate the conventional
intercept-inclusive slope standard error separately for each response curve,
divide each by six, and report their arithmetic mean.

All arrays must be finite, numeric, non-pickle NPY files. The covariance must
be symmetric and positive semidefinite up to ordinary floating-point roundoff.

[MASKED: all generated arrays, estimator means, estimator spreads, analytical
uncertainties, and numerical comparisons are withheld.]
""",
    "0012": r"""
# Anonymous replication dossier: logarithmic spin effective Hamiltonian

## Scope

Reproduce the deterministic core calculation that supplies an effective field
to a finite-temperature spin-dynamics simulation. This task does not run the
subsequent stochastic dynamics and does not claim to reproduce its sampled
magnetization curves.

Consider one spin with dimensionless S_z eigenvalues m=-s,...,s and

[EQUATION]

    H = -(A_0 I + A_1 S_z + A_2 S_z^2),
    A_0 = lambda sigma,
    A_1 = g mu_B mu_0 H_z,
    A_2 = K-lambda sigma.

Use lambda sigma=0 and mu_0 H_z=1 tesla. Obtain the absolute electron Landé
factor, Bohr magneton, and Boltzmann constant from a standard CODATA constants
library. Let beta=1/(k_B T).

## Coherent-state construction

For p=0,...,2s, define |p>=|s,s-p> and

[EQUATION]

    |z> = (1+|z|^2)^(-s)
          sum_p binom(2s,p)^(1/2) z^p |p>.

Map the stereographic radius to the unit-spin orientation by

[EQUATION]

    u_z = (1-|z|^2)/(1+|z|^2),
    |z|^2 = (1-u_z)/(1+u_z).

The polynomial entering the coherent-state partition integrand is

[EQUATION]

    L = sum_p binom(2s,p) |z|^(2p)
        exp(beta A_2 p^2)
        exp[-beta(2s A_2+A_1)p].

After factoring out the energy of the m=s state, define

[EQUATION]

    W(beta,u_z) = L/(1+|z|^2)^(2s),
    H_eff(beta,u_z) = -beta^(-1) log W(beta,u_z).

This factorization fixes the otherwise arbitrary additive constant:
H_eff(beta,1)=0. Submit the dimensionless gauge-fixed Hamiltonian

[EQUATION]

    h(beta,u_z) = H_eff(beta,u_z)/A_1.

Evaluate logarithms and exponential sums stably. In particular, do not form
large low-temperature exponentials before applying the logarithm.

The longitudinal effective field supplied to spin dynamics is

[EQUATION]

    B_eff,z = -(g mu_B s)^(-1) partial H_eff/partial u_z.

Because A_1=g mu_B mu_0 H_z, submit the dimensionless field

[EQUATION]

    b(beta,u_z) = B_eff,z/(mu_0 H_z)
                = -(1/s) partial h/partial u_z.

The field should be obtained analytically or to equivalent numerical accuracy.
It is not a thermal average and cannot be replaced by a partition-function
magnetization.

## Parameter groups and artifacts

Submit `temperature` as float64 `linspace(0.02,10.0,200)` in kelvin, shape
`(200,)`. Submit `orientation` as float64
`linspace(-0.98,0.98,201)`, shape `(201,)`. Array axes are always parameter
row, increasing temperature, increasing orientation.

For the Figure 2 parameter group, use K/A_1=-2 and rows ordered by
s={0.5,1.0,1.5,2.0}. Submit `figure2_hamiltonian` and `figure2_field`, each
with shape `(4,200,201)`.

For the Figure 3 parameter group, fix s=1 and order rows by
K/A_1={10,0,-1,-10}. Submit `figure3_hamiltonian` and `figure3_field`, each
with shape `(4,200,201)`.

All six artifacts must be finite, numeric, non-pickle float64 NPY files.
Graphics, stochastic trajectories, magnetization averages, and self-reported
checkpoints are not scored.

[MASKED: all effective-Hamiltonian values, effective-field values, comparisons,
and original graphics are withheld.]
""",
}
