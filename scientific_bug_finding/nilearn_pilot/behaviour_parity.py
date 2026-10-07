"""Non-disruption check: sha256 of deterministic public-API outputs.

Run the same script against (a) the pristine upstream tree, (b) the instrumented
tree with the logger unset and (c) the instrumented tree with the logger on; the
three hash maps must be identical (SANITIZER.md 5.5). It also hashes the global
NumPy RNG state, which a checker must never touch.

    PYTHONPATH=<tree> python behaviour_parity.py [--log <file>] > hashes.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import warnings

import numpy as np

warnings.simplefilter("ignore")


def h(x):
    a = np.ascontiguousarray(np.asarray(x))
    return hashlib.sha256(a.tobytes() + str(a.dtype).encode() + str(a.shape).encode()).hexdigest()[:16]


def outputs():
    import nibabel as nib
    import pandas as pd

    from nilearn import image, signal
    from nilearn.connectome import (
        ConnectivityMeasure,
        group_sparse_covariance,
        sym_matrix_to_vec,
        vec_to_sym_matrix,
    )
    from nilearn.connectome.connectivity_matrices import _geometric_mean, cov_to_corr
    from nilearn.glm import OLSModel, compute_fixed_effects, threshold_stats_img
    from nilearn.glm.contrasts import Contrast, compute_contrast
    from nilearn.glm.first_level import compute_regressor, make_first_level_design_matrix
    from nilearn.glm.first_level.hemodynamic_models import glover_time_derivative, spm_time_derivative
    from nilearn.glm.regression import ARModel
    from nilearn.maskers import NiftiMasker
    from nilearn.mass_univariate import permuted_ols
    from nilearn.mass_univariate._utils import null_to_p
    from nilearn.regions import img_to_signals_labels, signals_to_img_labels, signals_to_img_maps

    np.random.seed(0)
    rng = np.random.default_rng(11)
    aff = np.diag([2.0, 2.0, 2.0, 1.0])
    out = {}

    x = rng.standard_normal((120, 30)) + 5
    c = rng.standard_normal((120, 4))
    out["clean_conf"] = signal.clean(x, detrend=False, standardize="zscore_sample", confounds=c, filter=False)
    out["clean_bw"] = signal.clean(x, detrend=True, standardize="psc", t_r=2.0, high_pass=0.01, low_pass=0.1)
    out["clean_cos"] = signal.clean(x, detrend=True, standardize="zscore_sample", t_r=2.0, high_pass=0.0213, filter="cosine", confounds=c)
    out["psc"] = signal.standardize_signal(x + 10, detrend=False, standardize="psc")
    out["compcor"] = signal.high_variance_confounds(x, n_confounds=3, percentile=50.0)
    out["cosdrift"] = signal.create_cosine_drift(0.0213, np.arange(100) * 2.0)
    out["x32"] = signal.clean(x.astype(np.float32), detrend=True, standardize="zscore_sample", filter=False)

    n = 80
    design = np.column_stack([rng.standard_normal(n), rng.standard_normal(n), np.ones(n)])
    y = design @ rng.standard_normal((3, 40)) + rng.standard_normal((n, 40))
    res = OLSModel(design).fit(y)
    out["ols_theta"], out["ols_disp"], out["ols_r2"] = res.theta, res.dispersion, res.r_square
    ar = ARModel(design, 0.3).fit(y)
    out["ar_theta"] = ar.theta
    labels = np.zeros(40, dtype=int)
    ct = compute_contrast(labels, {0: res}, np.array([1.0, -1.0, 0.0]), "t")
    out["t_stat"], out["t_p"], out["t_z"] = ct.stat(), ct.p_value(), ct.z_score()
    cf = compute_contrast(labels, {0: res}, np.array([[1.0, 0, 0], [0, 1.0, 0]]), "F")
    out["F_stat"], out["F_z"] = cf.stat(), cf.z_score()
    mask = nib.Nifti1Image(np.ones((4, 5, 3), dtype=np.int8), aff)
    ci = [nib.Nifti1Image(rng.standard_normal((4, 5, 3)), aff) for _ in range(3)]
    vi = [nib.Nifti1Image(np.abs(rng.standard_normal((4, 5, 3))) + 0.5, aff) for _ in range(3)]
    for k, r in enumerate(compute_fixed_effects(ci, vi, mask, precision_weighted=True)):
        out[f"fixed{k}"] = r.get_fdata()

    ft = np.arange(100) * 2.0
    ev = (np.array([4.0, 30.0, 70.0, 110.0]), np.array([1.0, 2.0, 1.0, 3.0]), np.array([1.0, 2.0, 1.5, 1.0]))
    out["reg_glover"] = compute_regressor(ev, "glover", ft)[0]
    out["reg_spm3"] = compute_regressor(ev, "spm + derivative + dispersion", ft)[0]
    out["reg_fir"] = compute_regressor(ev, "fir", ft, fir_delays=[0, 1, 2])[0]
    out["d_spm"], out["d_glover"] = spm_time_derivative(2.0), glover_time_derivative(2.0)
    events = pd.DataFrame({"onset": [4.0, 40.0, 90.0, 140.0], "duration": [2.0] * 4, "trial_type": list("abab")})
    out["dm"] = make_first_level_design_matrix(ft, events, hrf_model="spm + derivative", drift_model="polynomial", drift_order=2).to_numpy()

    d = rng.standard_normal((10, 11, 12)) * 1.2
    d[2:5, 2:5, 2:5] += 4.0
    stat = nib.Nifti1Image(d, aff)
    for hc in ("fpr", "fdr", "bonferroni"):
        im, thr = threshold_stats_img(stat, alpha=0.05, height_control=hc, cluster_threshold=3)
        out[f"thr_{hc}"], out[f"thr_{hc}_v"] = im.get_fdata(), np.array(thr)
    out["thr_img"] = image.threshold_img(stat, threshold=1.0, cluster_threshold=4).get_fdata()

    ts = [rng.standard_normal((90, 6)) @ rng.standard_normal((6, 6)) for _ in range(5)]
    for kind in ("covariance", "correlation", "precision", "partial correlation", "tangent"):
        out[f"cm_{kind}"] = ConnectivityMeasure(kind=kind, vectorize=True).fit_transform(ts)
    cov = np.cov(ts[0].T)
    out["c2c"] = cov_to_corr(cov)
    out["s2v"] = sym_matrix_to_vec(cov)
    out["v2s"] = vec_to_sym_matrix(sym_matrix_to_vec(cov))
    out["gmean"] = _geometric_mean([np.cov(t.T) for t in ts], max_iter=30, tol=1e-7)
    sub = [rng.standard_normal((70, 5)) for _ in range(3)]
    out["gsc_lo"] = group_sparse_covariance(sub, alpha=0.05, max_iter=10)[1]
    out["gsc_hi"] = group_sparse_covariance(sub, alpha=5.0, max_iter=10)[1]

    masker = NiftiMasker(mask_img=nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.int8), aff)).fit()
    tv, tg = rng.standard_normal((20, 1)), rng.standard_normal((20, 64))
    po = permuted_ols(tv, tg, confounding_vars=rng.standard_normal((20, 2)), n_perm=20, random_state=0, masker=masker, tfce=True, threshold=0.05)
    for k in sorted(po):
        out[f"pols_{k}"] = po[k]
    out["n2p"] = null_to_p(rng.standard_normal(1500), rng.standard_normal(500), alternative="larger")

    arr = nib.Nifti1Image(rng.standard_normal((12, 13, 14, 3)), aff)
    out["smooth8"] = image.smooth_img(arr, fwhm=8).get_fdata()
    out["smooth_fast"] = image.smooth_img(arr, fwhm="fast").get_fdata()
    tgt = np.diag([3.0, 3.0, 3.0, 1.0])
    tgt[:3, 3] = [-12.0, -14.0, -10.0]
    src = nib.Nifti1Image(rng.standard_normal((12, 13, 14)), aff)
    out["rs_cubic"] = image.resample_img(src, target_affine=tgt, target_shape=(10, 10, 10)).get_fdata()
    out["rs_near"] = image.resample_img(src, target_affine=tgt, interpolation="nearest").get_fdata()
    lab = np.zeros((8, 8, 8), dtype=np.int32)
    lab[:4], lab[4:, :4], lab[4:, 4:] = 1, 2, 3
    lab_img = nib.Nifti1Image(lab, aff)
    sig, _l, _m = img_to_signals_labels(nib.Nifti1Image(rng.standard_normal((8, 8, 8, 25)), aff), lab_img)
    out["i2s"] = sig
    out["s2i"] = signals_to_img_labels(sig, lab_img).get_fdata()
    maps = nib.Nifti1Image(np.abs(rng.standard_normal((8, 8, 8, 3))), aff)
    out["s2m"] = signals_to_img_maps(rng.standard_normal((25, 3)), maps).get_fdata()
    out["np_rng_state"] = np.random.get_state()[1]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=None)
    args = ap.parse_args()
    if args.log:
        os.environ["SCIBENCH_TRIGGER_LOG"] = args.log
        open(args.log, "w").close()
    o = outputs()
    hashes = {k: h(v) for k, v in sorted(o.items())}
    import nilearn

    print(json.dumps({"nilearn_file": nilearn.__file__, "hashes": hashes}, indent=0))


if __name__ == "__main__":
    main()
