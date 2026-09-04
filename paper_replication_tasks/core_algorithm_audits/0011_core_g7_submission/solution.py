import json
import sys
import os
import numpy as np
from scipy.linalg import pinvh, pinv


def parse_args():
    args = sys.argv[1:]
    input_path = None
    output_dir = None
    i = 0
    while i < len(args):
        if args[i] == '--input':
            input_path = args[i + 1]
            i += 2
        elif args[i] == '--output':
            output_dir = args[i + 1]
            i += 2
        else:
            i += 1
    return input_path, output_dir


def recondition_covariance(sigma, max_condition):
    """Recondition a covariance matrix using the minimum eigenvalue method."""
    # Ensure sigma is symmetric
    sigma = (sigma + sigma.T) / 2.0
    # Eigen decomposition
    eigvals, eigvecs = np.linalg.eigh(sigma)
    # Find minimum eigenvalue
    min_eig = np.min(eigvals)
    if min_eig > 0:
        return sigma
    # Recondition
    max_eig = np.max(eigvals)
    target_min = max_eig / max_condition
    # Clip negative eigenvalues
    new_eigvals = np.maximum(eigvals, target_min)
    return eigvecs @ np.diag(new_eigvals) @ eigvecs.T


def log_likelihood(params, t, x, cov):
    """Log-likelihood of the multivariate normal model."""
    d, c = params
    m = d * t + c
    residual = x - m
    # Use Moore-Penrose pseudo-inverse for stability
    try:
        cov_inv = pinvh(cov)
    except Exception:
        cov_inv = pinv(cov)
    sign, logdet = np.linalg.slogdet(cov)
    if sign <= 0:
        return -np.inf
    ll = -0.5 * logdet - 0.5 * residual @ cov_inv @ residual
    return ll


def log_prior(d, c):
    """Improper prior: D* >= 0, c unrestricted."""
    if d < 0:
        return -np.inf
    return 0.0


def log_posterior(params, t, x, cov):
    """Log-posterior."""
    d, c = params
    lp = log_prior(d, c)
    if not np.isfinite(lp):
        return -np.inf
    return lp + log_likelihood(params, t, x, cov)


def find_initial_guess(t, x):
    """OLS initial guess for slope and intercept."""
    # Fit x = d*t + c using OLS
    A = np.column_stack([t, np.ones_like(t)])
    result = np.linalg.lstsq(A, x, rcond=None)
    params = result[0]
    return params[0], params[1]  # d, c


def find_map_estimate(d0, c0, t, x, cov):
    """Find MAP estimate using L-BFGS-B optimization."""
    from scipy.optimize import minimize

    def neg_log_post(params):
        d, c = params
        if d < 0:
            return 1e10
        val = -log_posterior([d, c], t, x, cov)
        return val

    result = minimize(
        neg_log_post,
        x0=[max(d0, 1e-6), c0],
        method='L-BFGS-B',
        bounds=[(1e-10, None), (None, None)]
    )
    if result.success:
        return result.x[0], result.x[1]
    return max(d0, 1e-6), c0


def mcmc_sample(d_map, c_map, t, x, cov, n_walkers=32, n_steps=1500, n_burn=500, thin=10, seed=11011):
    """Affine-invariant MCMC sampling."""
    rng = np.random.default_rng(seed)

    # Initialize walkers in a ball around MAP
    n_kept = (n_steps - n_burn) // thin
    total_samples = n_walkers * n_kept

    # We need to store samples
    samples = np.zeros((n_steps, n_walkers, 2))

    # Scale parameters for proposal
    # Initialize walkers near MAP with small perturbations
    for i in range(n_walkers):
        d_init = d_map * (1 + 0.01 * rng.standard_normal())
        c_init = c_map * (1 + 0.01 * rng.standard_normal())
        if d_init < 0:
            d_init = abs(d_init) * 0.1 + d_map * 0.1
        samples[0, i, 0] = d_init
        samples[0, i, 1] = c_init

    # Stretch move parameters
    a = 2.0
    p = 0.0  # Will compute below

    def log_prob(d, c):
        if d < 0:
            return -np.inf
        return log_posterior([d, c], t, x, cov)

    # Compute initial log-probs
    log_probs = np.zeros((n_steps, n_walkers))
    for i in range(n_walkers):
        log_probs[0, i] = log_prob(samples[0, i, 0], samples[0, i, 1])

    # MCMC loop
    for step in range(1, n_steps):
        # Split walkers into two halves
        split = n_walkers // 2
        order = rng.permutation(n_walkers)
        half1 = order[:split]
        half2 = order[split:]

        for i in range(split):
            j1 = half1[i]
            j2 = half2[i]

            # Propose new position
            current = samples[step - 1, j1].copy()
            other = samples[step - 1, j2].copy()

            # Stretch move
            z = ((a - 1) * rng.random() + 1) ** 2 / a
            proposed = other + z * (current - other)

            # Compute acceptance
            current_lp = log_probs[step - 1, j1]
            proposed_lp = log_prob(proposed[0], proposed[1])

            # Jacobian for stretch move
            log_accept = (proposed_lp - current_lp) + (2 * np.log(z) - np.log(a) - (a - 1) * np.log(z))

            if np.log(rng.random()) < log_accept:
                samples[step, j1] = proposed
                log_probs[step, j1] = proposed_lp
            else:
                samples[step, j1] = current
                log_probs[step, j1] = current_lp

        # Copy other half
        for i in half2:
            samples[step, i] = samples[step - 1, i]
            log_probs[step, i] = log_probs[step - 1, i]

    # Discard burn-in and thin
    kept_samples = samples[n_burn::thin, :, :]  # shape (n_kept, n_walkers, 2)
    flat_samples = kept_samples.reshape(-1, 2)

    return flat_samples


def main():
    input_path, output_dir = parse_args()
    with open(input_path, 'r') as f:
        data = json.load(f)

    condition_limit = data['condition_limit']
    dimension = data['dimension']
    fit_start = data['fit_start']
    independent_sample_counts = np.array(data['independent_sample_counts'])
    lag_times = np.array(data['lag_times'])
    mcmc_seed = data['mcmc_seed']
    squared_displacement_samples = data['squared_displacement_samples']

    # Compute MSD and estimated variance for each lag time
    n_lags = len(lag_times)
    msd = np.zeros(n_lags)
    var_est = np.zeros(n_lags)

    for i in range(n_lags):
        samples = np.array(squared_displacement_samples[i])
        msd[i] = np.mean(samples)
        # Variance of squared displacements
        var_sq = np.var(samples, ddof=1)
        # Rescaled variance: var(x_i) = var(Δr²_i) / N_i'
        var_est[i] = var_sq / independent_sample_counts[i]

    # Build covariance matrix using analytical form
    # Sigma'[xi, xj] = sigma²[xi] * Ni'/Nj' for i <= j
    Ni_prime = independent_sample_counts.astype(float)
    cov = np.zeros((n_lags, n_lags))
    for i in range(n_lags):
        for j in range(n_lags):
            if i <= j:
                cov[i, j] = var_est[i] * (Ni_prime[i] / Ni_prime[j])
            else:
                cov[i, j] = var_est[j] * (Ni_prime[j] / Ni_prime[i])

    # Make symmetric
    cov = (cov + cov.T) / 2.0

    # Recondition covariance matrix
    cov = recondition_covariance(cov, condition_limit)

    # Find fitting region (t >= fit_start)
    if fit_start is not None and fit_start > 0:
        # Convert fit_start to time value
        # fit_start could be an index (integer) or a time value
        # Looking at case_03: fit_start=3.4, lag_times=[0.2, 0.6, 1.3, 2.1, 3.4, 5.5, 8.9, 14.4, 22.0]
        # 3.4 matches lag_times[4], so fit_start is a time value
        # For case_01: fit_start=1, lag_times=[0.5, 1, 2, 3, 5, 8, 12, 17]
        # 1 matches lag_times[1], so fit_start is a time value
        # For case_02: fit_start=1, lag_times=[1, 2, 4, 7, 11, 16, 23]
        # 1 matches lag_times[0], so fit_start is a time value
        mask = lag_times >= fit_start
    else:
        mask = np.ones(n_lags, dtype=bool)

    t_fit = lag_times[mask]
    x_fit = msd[mask]
    cov_fit = cov[np.ix_(mask, mask)]

    # Find initial OLS guess
    d_ols, c_ols = find_initial_guess(t_fit, x_fit)

    # Find MAP estimate
    d_map, c_map = find_map_estimate(d_ols, c_ols, t_fit, x_fit, cov_fit)

    # MCMC sampling
    samples = mcmc_sample(
        d_map, c_map, t_fit, x_fit, cov_fit,
        n_walkers=32, n_steps=1500, n_burn=500, thin=10, seed=mcmc_seed
    )

    # Extract D* samples (slope)
    d_samples = samples[:, 0]

    # Compute statistics
    mean_d = np.mean(d_samples)
    var_d = np.var(d_samples, ddof=1)
    quantiles = np.percentile(d_samples, [16, 50, 84])

    output = {
        'mean': float(mean_d),
        'quantiles': [float(q) for q in quantiles],
        'variance': float(var_d)
    }

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'output.json')
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)


if __name__ == '__main__':
    main()