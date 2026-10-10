"""Curator-side observation-reachability probe for the nilearn bank.

Calls the public API with valid inputs and records which checkers executed their
predicate (``SCIBENCH_CHECKER_DEBUG``). An alarm is not required: this only shows
that every checker is reached at its intended program point. Alarms seen here are
reported separately as "natural triggers on the probe inputs".

    python probe_reachability.py            # uses the active interpreter
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import warnings

import numpy as np

log = os.path.join(tempfile.mkdtemp(), "probe_log.jsonl")
os.environ["SCIBENCH_TRIGGER_LOG"] = log
os.environ["SCIBENCH_CHECKER_DEBUG"] = "1"
open(log, "w").close()

import nibabel as nib  # noqa: E402

from nilearn import _scientific_checkers as sc  # noqa: E402

warnings.simplefilter("ignore")
rng = np.random.default_rng(7)
AFF = np.diag([2.0, 2.0, 2.0, 1.0])
AFF[:3, 3] = [-10.0, -12.0, -8.0]


def img(shape, data=None, aff=AFF, dtype=np.float64):
    d = rng.standard_normal(shape) if data is None else data
    return nib.Nifti1Image(np.asarray(d).astype(dtype), aff)


def run():
    from scipy.stats import norm

    from nilearn import image, signal
    from nilearn.connectome import (
        ConnectivityMeasure,
        GroupSparseCovariance,
        group_sparse_covariance,
        sym_matrix_to_vec,
        vec_to_sym_matrix,
    )
    from nilearn.connectome.connectivity_matrices import _geometric_mean, cov_to_corr
    from nilearn.glm import OLSModel, compute_fixed_effects, threshold_stats_img
    from nilearn.glm.contrasts import Contrast, compute_contrast
    from nilearn.glm.first_level import compute_regressor, make_first_level_design_matrix
    from nilearn.glm.first_level.hemodynamic_models import (
        glover_time_derivative,
        orthogonalize,
        spm_time_derivative,
    )
    from nilearn.glm.regression import ARModel
    from nilearn.image import resample_img, smooth_img, threshold_img
    from nilearn.maskers import NiftiMasker
    from nilearn.mass_univariate import permuted_ols
    from nilearn.mass_univariate._utils import null_to_p
    from nilearn.regions import (
        img_to_signals_labels,
        signals_to_img_labels,
        signals_to_img_maps,
    )

    # ---- signal
    x = rng.standard_normal((120, 30)) + 5
    c = rng.standard_normal((120, 4))
    signal.clean(x, detrend=False, standardize="zscore_sample", confounds=c, filter=False)
    signal.clean(x, detrend=True, standardize="zscore_sample", t_r=2.0, high_pass=0.01, low_pass=0.1)
    signal.standardize_signal(x + 10, detrend=False, standardize="psc")
    signal.high_variance_confounds(x, n_confounds=3, percentile=50.0)
    signal.create_cosine_drift(0.02, np.arange(100) * 2.0)
    signal.clean(x, detrend=True, standardize="zscore_sample", t_r=2.0, high_pass=0.0213, filter="cosine")

    # ---- glm: OLS / AR, contrasts, z-scores
    n = 80
    design = np.column_stack([rng.standard_normal(n), rng.standard_normal(n), np.ones(n)])
    y = design @ rng.standard_normal((3, 40)) + rng.standard_normal((n, 40))
    res = OLSModel(design).fit(y)
    res.r_square  # noqa: B018
    ar = ARModel(design, 0.3).fit(y)
    labels = np.zeros(40, dtype=int)
    con = compute_contrast(labels, {0: res}, np.array([1.0, -1.0, 0.0]), "t")
    con.p_value()
    con.one_minus_pvalue()
    con.z_score()
    compute_contrast(labels, {0: res}, np.array([[1.0, 0, 0], [0, 1.0, 0]]), "F")
    compute_contrast(labels, {0: ar}, np.array([1.0, 0.0, 0.0]), "t")
    cons = [rng.standard_normal(60) for _ in range(3)]
    var_imgs = [np.abs(rng.standard_normal(60)) + 0.5 for _ in range(3)]
    mask = img((4, 5, 3), np.ones((4, 5, 3), dtype=np.int8), dtype=np.int8)
    ci = [nib.Nifti1Image(v.reshape(4, 5, 3), AFF) for v in cons]
    vi = [nib.Nifti1Image(v.reshape(4, 5, 3), AFF) for v in var_imgs]
    compute_fixed_effects(ci, vi, mask)
    compute_fixed_effects(ci, vi, mask, precision_weighted=True)

    # ---- hrf / design matrix
    ft = np.arange(100) * 2.0
    ev = (np.array([4.0, 30.0, 70.0, 110.0]), np.array([1.0, 2.0, 1.0, 3.0]), np.array([1.0, 2.0, 1.5, 1.0]))
    compute_regressor(ev, "glover", ft)
    compute_regressor(ev, "spm + derivative + dispersion", ft)
    compute_regressor(ev, "fir", ft, fir_delays=[0, 1, 2])
    orthogonalize(rng.standard_normal((50, 3)))
    spm_time_derivative(2.0)
    glover_time_derivative(2.0)
    import pandas as pd

    events = pd.DataFrame(
        {"onset": [4.0, 40.0, 90.0, 140.0], "duration": [2.0] * 4, "trial_type": list("abab")}
    )
    make_first_level_design_matrix(ft, events, hrf_model="spm + derivative", drift_model="polynomial", drift_order=2)

    # ---- thresholding
    stat = img((10, 11, 12), rng.standard_normal((10, 11, 12)) * 1.2)
    for hc in ("fpr", "fdr", "bonferroni"):
        threshold_stats_img(stat, alpha=0.05, height_control=hc, cluster_threshold=3)
    threshold_img(stat, threshold=1.0, cluster_threshold=4, two_sided=True)

    # ---- connectome
    ts = [rng.standard_normal((90, 6)) @ rng.standard_normal((6, 6)) for _ in range(5)]
    for kind in ("covariance", "correlation", "precision", "partial correlation", "tangent"):
        cm = ConnectivityMeasure(kind=kind, vectorize=True)
        cm.fit_transform(ts)
    cm = ConnectivityMeasure(kind="correlation", vectorize=True)
    cm.inverse_transform(cm.fit_transform(ts))
    cov = np.cov(ts[0].T)
    cov_to_corr(cov)
    sym_matrix_to_vec(cov)
    vec_to_sym_matrix(sym_matrix_to_vec(cov))
    mats = [np.cov(t.T) for t in ts]
    _geometric_mean(mats, max_iter=30, tol=1e-7)
    sub = [rng.standard_normal((70, 5)) for _ in range(3)]
    group_sparse_covariance(sub, alpha=0.05, max_iter=10)
    group_sparse_covariance(sub, alpha=5.0, max_iter=10)
    GroupSparseCovariance(alpha=0.1, max_iter=5).fit(sub)

    # ---- mass-univariate
    mimg = nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.int8), AFF)
    masker = NiftiMasker(mask_img=mimg).fit()
    tv = rng.standard_normal((20, 1))
    tgt = rng.standard_normal((20, 64))
    permuted_ols(tv, tgt, confounding_vars=rng.standard_normal((20, 2)), n_perm=20, random_state=0, masker=masker, tfce=True, threshold=0.05)
    permuted_ols(tv, tgt, n_perm=5, random_state=1, two_sided_test=False)
    null_to_p(np.array([0.5, 2.0, -3.0]), rng.standard_normal(500))
    null_to_p(rng.standard_normal(1500), rng.standard_normal(500), alternative="larger")

    # ---- images
    arr = img((12, 13, 14, 3))
    smooth_img(arr, fwhm=8)
    smooth_img(arr, fwhm=[8, 6, 8])
    smooth_img(arr, fwhm="fast")
    tgt_aff = np.diag([3.0, 3.0, 3.0, 1.0])
    tgt_aff[:3, 3] = [-12.0, -14.0, -10.0]
    resample_img(img((12, 13, 14)), target_affine=tgt_aff, target_shape=(10, 10, 10))
    resample_img(img((12, 13, 14)), target_affine=tgt_aff, interpolation="nearest")
    resample_img(img((12, 13, 14)), target_affine=np.diag([3.0, 3.0, 3.0]), interpolation="linear")
    lab = np.zeros((8, 8, 8), dtype=np.int32)
    lab[:4], lab[4:, :4], lab[4:, 4:] = 1, 2, 3
    lab_img = nib.Nifti1Image(lab, AFF)
    data4 = img((8, 8, 8, 25))
    sig, _l, _m = img_to_signals_labels(data4, lab_img)
    signals_to_img_labels(sig, lab_img)
    maps = np.abs(rng.standard_normal((8, 8, 8, 3)))
    maps_img = nib.Nifti1Image(maps, AFF)
    signals_to_img_maps(rng.standard_normal((25, 3)), maps_img)
    return norm


def main():
    run()
    retired = {"NL-SIG-002", "NL-SIG-005", "NL-MU-001"}
    ids = [f"NL-{a}-{i:03d}" for a, k in (("SIG", 8), ("GLM", 8), ("HRF", 4), ("THR", 3), ("CON", 9), ("MU", 5), ("IMG", 5)) for i in range(1, k + 1) if f"NL-{a}-{i:03d}" not in retired]
    reached = {i: sc.REACHED.get(i, 0) for i in ids}
    alarms = {}
    for line in open(log):
        cid = json.loads(line)["checker_id"]
        alarms[cid] = alarms.get(cid, 0) + 1
    out = {
        "reached": reached,
        "unreached": [i for i, v in reached.items() if v == 0],
        "alarms": alarms,
        "swallowed": sc.SWALLOWED,
    }
    print(json.dumps(out, indent=1))
    return 0 if not out["unreached"] and not out["swallowed"] else 1


if __name__ == "__main__":
    sys.exit(main())
