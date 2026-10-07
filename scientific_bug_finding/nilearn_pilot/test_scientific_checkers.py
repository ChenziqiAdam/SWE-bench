"""Curator-side isolated-sensitivity tests for the nilearn scientific checkers.

Each ID gets (a) a synthetic *violating* observed state that must alarm the
expected ID and (b) a valid state that must stay silent. Where a checker re-calls
the public API, the violation is produced by fault injection into the function
the re-call uses. These tests are never benchmark witnesses (SANITIZER.md 8).

    pytest test_scientific_checkers.py -p no:randomly -q
"""

from __future__ import annotations

import json
import warnings

import nibabel as nib
import numpy as np
import pytest
from scipy import linalg
from scipy.signal import butter

from nilearn import _scientific_checkers as sc
from nilearn import signal

warnings.simplefilter("ignore")
RNG = np.random.default_rng(3)
AFF = np.diag([2.0, 2.0, 2.0, 1.0])


@pytest.fixture
def fired(tmp_path, monkeypatch):
    path = tmp_path / "log.jsonl"
    path.write_text("")
    monkeypatch.setenv("SCIBENCH_TRIGGER_LOG", str(path))
    monkeypatch.setenv("SCIBENCH_CHECKER_DEBUG", "1")
    sc._CALLS.clear()
    sc.SWALLOWED.clear()

    def ids():
        out = [json.loads(line)["checker_id"] for line in path.read_text().splitlines()]
        assert not sc.SWALLOWED, sc.SWALLOWED
        return out

    return ids


# --------------------------------------------------------------------- signal
def test_sig001(fired):
    x = RNG.standard_normal((50, 3)) + 3
    l1 = sc.l1_cols(x)
    good = signal._detrend(x.copy())
    assert fired() == []
    sc.check_detrend(good + 0.05, l1)
    assert fired() == ["NL-SIG-001"]


def test_sig002_003(fired):
    x = RNG.standard_normal((100, 4)) * 3 + 5
    z = (x - x.mean(0)) / x.std(0, ddof=1)
    sc.check_standardize(x, z, "zscore_sample", False)
    pm = x.mean(0)
    psc = (x - pm) / np.abs(pm) * 100
    sc.check_standardize(x, psc, "psc", False)
    assert fired() == []
    sc.check_standardize(x, z * 1.01, "zscore_sample", False)
    sc.check_standardize(x, psc * 1.05, "psc", False)
    assert fired() == ["NL-SIG-002", "NL-SIG-003"]


def test_sig004(fired):
    sc.check_butterworth_cutoff(butter(5, 0.1, "low", output="sos", fs=2.0), 0.1, 2.0, 5)
    assert fired() == []
    sc.check_butterworth_cutoff(butter(5, 0.1, "low", output="sos", fs=1.0), 0.1, 2.0, 5)
    assert fired() == ["NL-SIG-004"]


def test_sig005(fired):
    x = RNG.standard_normal((100, 6))
    c = RNG.standard_normal((100, 3))
    snap = sc.snap_clean(x, c, None, None, False, False, "zscore_sample", True)
    good = signal.clean(x, confounds=c, detrend=False, filter=False, standardize="zscore_sample")
    sc.check_clean_orthogonality(snap, good)
    assert fired() == []
    sc.check_clean_orthogonality(snap, good + 0.3 * (c[:, [0]] - c[:, 0].mean()))
    assert fired() == ["NL-SIG-005"]


def test_sig006_007(fired):
    ft = np.arange(100) * 2.0
    good = signal.create_cosine_drift(0.0213, ft)
    sc.check_cosine_drift(good, ft, 0.0213)
    assert fired() == []
    bad = good.copy()
    bad[:, 0] *= 1.01
    sc.check_cosine_drift(bad, ft, 0.0213)  # NL-SIG-006
    sc.check_cosine_drift(good, ft, 0.0113)  # drift reaches above the cut-off
    sc.check_cosine_drift(good, ft, 0.1)  # drift stops below the cut-off
    assert fired() == ["NL-SIG-006", "NL-SIG-007", "NL-SIG-007"]


def test_sig008(fired):
    x = RNG.standard_normal((80, 40)) + 4
    s_ = signal._detrend(x)
    s, u = linalg.eigh(s_.dot(s_.T) / s_.shape[0])
    ix = np.argsort(s)[::-1]
    good = u[:, ix[:3]].copy()
    sc.check_compcor(good, s, ix, 3, 80)
    assert fired() == []
    sc.check_compcor(good + 0.1, s, ix, 3, 80)
    assert fired() == ["NL-SIG-008"]


# ------------------------------------------------------------------------ GLM
def _ols(n=60, p=3, v=20):
    from nilearn.glm.regression import OLSModel

    X = np.column_stack([RNG.standard_normal((n, p - 1)), np.ones(n)])
    Y = X @ RNG.standard_normal((p, v)) + RNG.standard_normal((n, v))
    return X, Y, OLSModel(X).fit(Y)


def test_glm001_002(fired):
    X, Y, res = _ols()
    sc.check_ols_normal_equations(X, Y, res.whitened_residuals)
    r2 = np.var(res.predicted, 0) / np.var(Y, 0)
    sc.check_r_square(res.model, X, Y, res.whitened_residuals, r2)
    assert fired() == []
    sc.check_ols_normal_equations(X, Y, res.whitened_residuals + 0.1 * X[:, [0]])
    sc.check_r_square(res.model, X, Y, res.whitened_residuals, r2 * 0.9)
    assert fired() == ["NL-GLM-001", "NL-GLM-002"]


def test_glm003(fired):
    from scipy.stats import norm

    from nilearn.glm._utils import z_score

    p = np.array([1e-8, 0.01, 0.3, 0.7, 0.99])
    omp = 1 - p
    z = z_score(p, omp)
    sc.check_zscore_tails(p, omp, z)
    assert fired() == []
    sc.check_zscore_tails(p, omp, z + 0.05)
    assert fired() == ["NL-GLM-003"]
    del norm


def test_glm004(fired):
    from nilearn.glm.contrasts import Contrast

    c = Contrast(RNG.standard_normal(30) * 3, np.abs(RNG.standard_normal(30)) + 0.5, dof=40.0)
    pt = c.p_value()
    sc.check_t_f_equivalence(c, 0.0, pt)
    assert fired() == []
    sc.check_t_f_equivalence(c, 0.0, np.clip(pt * 1.5, 0, 0.5))
    assert fired() == ["NL-GLM-004"]


def test_glm005(fired, monkeypatch):
    from nilearn.glm import contrasts
    from nilearn.glm.model import LikelihoodModelResults

    X, Y, res = _ols()
    labels = np.zeros(20, dtype=int)
    cv = np.array([1.0, -1.0, 0.0])
    con = contrasts.compute_contrast(labels, {0: res}, cv, "t")  # silent: hook ran
    assert fired() == []
    orig = LikelihoodModelResults.vcov

    def bad_vcov(self, matrix=None, column=None, dispersion=None, other=None):
        out = orig(self, matrix=matrix, column=column, dispersion=dispersion, other=other)
        return out * (np.abs(matrix).sum() if matrix is not None else 1.0)

    monkeypatch.setattr(LikelihoodModelResults, "vcov", bad_vcov)
    sc.check_contrast_invariance(labels, {0: res}, cv, "t", con)
    assert fired() == ["NL-GLM-005"]


def test_glm006(fired, monkeypatch):
    from nilearn.glm import contrasts
    from nilearn.glm.model import LikelihoodModelResults

    X, Y, res = _ols()
    labels = np.zeros(20, dtype=int)
    cm = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    con = contrasts.compute_contrast(labels, {0: res}, cm, "F")
    assert fired() == []
    orig = LikelihoodModelResults.vcov

    def bad_vcov(self, matrix=None, column=None, dispersion=None, other=None):
        out = orig(self, matrix=matrix, column=column, dispersion=dispersion, other=other)
        return out * (np.abs(matrix[0]).sum() if matrix is not None else 1.0)

    monkeypatch.setattr(LikelihoodModelResults, "vcov", bad_vcov)
    sc.check_contrast_invariance(labels, {0: res}, cm, "F", con)
    assert fired() == ["NL-GLM-006"]


def test_glm007(fired):
    c = RNG.standard_normal((4, 10))
    v = np.abs(RNG.standard_normal((4, 10))) + 0.5
    sc.check_fixed_effects(c, v, False, c.mean(0), v.mean(0) / 4)
    w = 1 / v
    sc.check_fixed_effects(c, v, True, (c * w).sum(0) / w.sum(0), 1 / w.sum(0))
    assert fired() == []
    sc.check_fixed_effects(c, v, False, c.mean(0), v.mean(0))  # forgot /N
    sc.check_fixed_effects(c, v, True, c.mean(0) + 100, 1 / w.sum(0))
    assert fired() == ["NL-GLM-007", "NL-GLM-007"]


def test_glm008(fired, monkeypatch):
    from nilearn.glm import contrasts

    c = contrasts.Contrast(RNG.standard_normal(30), np.abs(RNG.standard_normal(30)) + 0.5, dof=30.0)
    z = c.z_score()
    assert fired() == []
    monkeypatch.setattr(contrasts, "z_score", lambda p, one_minus_pvalue=None: contrasts.sps.norm.isf(p) + 0.1)
    sc.check_zscore_odd(c, 0.0, z)
    assert fired() == ["NL-GLM-008"]


# ------------------------------------------------------------------------ HRF
def test_hrf001(fired):
    from nilearn.glm.first_level.hemodynamic_models import orthogonalize

    x = RNG.standard_normal((50, 3))
    x0 = x.copy()
    out = orthogonalize(x)
    sc.check_orthogonalize(x0, out)
    assert fired() == []
    bad = out.copy()
    bad[:, 1] += 0.5 * bad[:, 0]
    sc.check_orthogonalize(x0, bad)
    assert fired() == ["NL-HRF-001"]


def test_hrf002_003(fired, monkeypatch):
    from nilearn.glm.first_level import hemodynamic_models as hm

    ft = np.arange(100) * 2.0
    ev = (np.array([4.0, 30.0, 70.0]), np.array([1.0, 2.0, 1.0]), np.array([1.0, 2.0, 1.5]))
    hm.compute_regressor(ev, "glover", ft)
    assert fired() == []
    orig = hm._resample_regressor
    monkeypatch.setattr(hm, "_resample_regressor", lambda h, a, b: np.tanh(orig(h, a, b)))
    reg, _ = hm.compute_regressor(ev, "glover", ft)  # hook runs on the faulty path too
    assert set(fired()) == {"NL-HRF-002", "NL-HRF-003"}
    del reg


def test_hrf004(fired, monkeypatch):
    from nilearn.glm.first_level import hemodynamic_models as hm

    hm.spm_time_derivative(2.0)
    assert fired() == []
    monkeypatch.setattr(hm, "_compute_derivative_from_values", lambda v, v2, dt=0.1: (v2 - v) / dt)
    hm.spm_time_derivative(2.0)
    assert fired() == ["NL-HRF-004"]


# ------------------------------------------------------------------------ THR
def _stat_img():
    d = RNG.standard_normal((10, 11, 12)) * 1.2
    d[2:5, 2:5, 2:5] += 4.0
    return nib.Nifti1Image(d, AFF)


def test_thr001(fired):
    from nilearn.glm.thresholding import fdr_threshold

    st = np.abs(RNG.standard_normal(500)) * 1.2
    st[:30] += 4.0
    sc.check_fdr_control(st, fdr_threshold(st, 0.05 / 2), 0.05, True)
    assert fired() == []
    sc.check_fdr_control(st, 0.0, 0.05, True)  # accepts everything
    assert fired() == ["NL-THR-001"]


def test_thr002(fired, monkeypatch):
    from nilearn.glm import thresholding

    img = _stat_img()
    thresholding.threshold_stats_img(img, alpha=0.05, height_control="fdr")
    assert fired() == []
    monkeypatch.setattr(thresholding, "fdr_threshold", lambda z, a: 0.0)  # accepts everything
    thresholding.threshold_stats_img(img, alpha=0.05, height_control="fdr")
    assert "NL-THR-002" in fired()


def test_thr003(fired, monkeypatch):
    from nilearn.image import image as nimage

    img = _stat_img()
    nimage.threshold_img(img, threshold=1.0, cluster_threshold=20)
    assert fired() == []
    monkeypatch.setattr(nimage, "_apply_cluster_size_threshold", lambda arr, k, copy=True: arr.copy())
    nimage.threshold_img(img, threshold=1.0, cluster_threshold=20)
    assert fired() == ["NL-THR-003"]


# ------------------------------------------------------------------------ CON
def test_con001(fired, monkeypatch):
    from nilearn.connectome import connectivity_matrices as cm

    cov = np.cov(RNG.standard_normal((60, 5)).T)
    corr = cm.cov_to_corr(cov)
    assert fired() == []
    monkeypatch.setattr(cm, "cov_to_corr", lambda c: c / np.sqrt(np.outer(np.diag(c), np.diag(c)) + 0.1))
    sc.check_corr_scale_invariance(cov, corr)
    assert fired() == ["NL-CON-001"]


def test_con002(fired):
    good = np.array([np.cov(RNG.standard_normal((60, 5)).T) for _ in range(2)])
    sc.check_connectivity_psd(good, "covariance")
    assert fired() == []
    bad = good.copy()
    bad[0] -= 2 * np.eye(5) * np.linalg.eigvalsh(bad[0])[-1]
    sc.check_connectivity_psd(bad, "covariance")
    assert fired() == ["NL-CON-002"]


def test_con003(fired):
    from nilearn.connectome.connectivity_matrices import prec_to_partial

    s = np.cov(RNG.standard_normal((80, 6)).T)
    good = prec_to_partial(linalg.inv(s))
    sc.check_partial_correlation([s], [good])
    assert fired() == []
    sc.check_partial_correlation([s], [prec_to_partial(linalg.inv(s)) * 0.9 + np.eye(6) * 0.1])
    assert fired() == ["NL-CON-003"]


def test_con004_005(fired):
    from nilearn.connectome import connectivity_matrices as cm

    s = np.cov(RNG.standard_normal((60, 5)).T)
    v = cm.sym_matrix_to_vec(s)
    sc.check_vec_isometry_to_vec(s, v, cm.sym_matrix_to_vec)
    sym = cm.vec_to_sym_matrix(v)
    sc.check_vec_isometry_to_sym(v, sym, cm.vec_to_sym_matrix)
    assert fired() == []

    def bad_to_vec(m):
        return m[..., np.tril(np.ones(m.shape[-2:])).astype(bool)]  # forgot sqrt(2)

    def bad_to_sym(vec):
        out = cm.vec_to_sym_matrix(vec)
        i = np.arange(out.shape[-1])
        out[..., i, i] /= 2.0
        return out

    sc.check_vec_isometry_to_vec(s, bad_to_vec(s), bad_to_vec)
    sc.check_vec_isometry_to_sym(v, bad_to_sym(v), bad_to_sym)
    assert fired() == ["NL-CON-004", "NL-CON-005"]


def test_con006(fired, monkeypatch):
    from nilearn.connectome import connectivity_matrices as cm

    mats = np.array([np.cov(RNG.standard_normal((80, 4)).T) for _ in range(3)])
    g = cm._geometric_mean(mats, max_iter=30, tol=1e-7)
    sc.check_frechet_equivariance(mats, None, 30, 1e-7, g, True)
    assert fired() == []
    monkeypatch.setattr(cm, "_geometric_mean", lambda m, init=None, max_iter=10, tol=1e-7: np.mean(m, 0) + 0.01 * np.eye(4))
    sc.check_frechet_equivariance(mats, None, 30, 1e-7, np.mean(mats, 0) + 0.01 * np.eye(4), True)
    assert fired() == ["NL-CON-006"]


def test_con007(fired):
    from nilearn.connectome import ConnectivityMeasure

    ts = [RNG.standard_normal((80, 4)) @ RNG.standard_normal((4, 4)) for _ in range(4)]
    out = ConnectivityMeasure(kind="tangent").fit_transform(ts)
    sc.check_tangent_centering(out)
    assert fired() == []
    sc.check_tangent_centering(out + 0.05)
    assert fired() == ["NL-CON-007"]


def test_con008_009(fired):
    from nilearn.connectome.group_sparse_cov import _group_sparse_covariance, empirical_covariances

    sub = [RNG.standard_normal((60, 4)) for _ in range(3)]
    emp, n = empirical_covariances(sub)
    omega = _group_sparse_covariance(emp, n.copy(), 10.0, max_iter=5)
    assert fired() == []
    om = omega.copy()
    om[0, 1, :] = om[1, 0, :] = 0.3
    sc.check_group_sparse(om, emp, n.copy(), 10.0, None)
    assert fired() == ["NL-CON-008"]
    om2 = omega.copy()
    om2[2, 2, 0] = -1.0
    sc.check_group_sparse(om2, emp, n.copy(), 10.0, None)
    assert "NL-CON-009" in fired()


# ------------------------------------------------------------------------- MU
def test_mu001(fired):
    from nilearn.mass_univariate._utils import t_score_with_covars_and_normalized_design  # noqa: F401

    x = RNG.standard_normal((30, 1))
    y = RNG.standard_normal((30, 12))
    cv = np.hstack([RNG.standard_normal((30, 1)), np.ones((30, 1))])
    from nilearn.glm.regression import OLSModel

    design = np.hstack([x, cv])
    ref = np.atleast_1d(OLSModel(design).fit(y).Tcontrast(np.array([1.0, 0, 0])).t)
    sc.check_permuted_ols_vs_glm(x, y, cv, ref[:, None])
    assert fired() == []
    sc.check_permuted_ols_vs_glm(x, y, cv, ref[:, None] * 1.05)
    assert fired() == ["NL-MU-001"]


def test_mu002_003_005(fired, monkeypatch):
    from nilearn.mass_univariate import _utils as mu
    from scipy.ndimage import generate_binary_structure

    arr = RNG.standard_normal((6, 6, 6, 2)) * 2
    bs = generate_binary_structure(3, 1)
    out = mu.calculate_tfce(arr, bs, two_sided_test=True)
    sc.check_tfce(arr, bs, 0.5, 2, "auto", True, out)
    sizes, masses = mu.calculate_cluster_measures(arr, 1.0, bs, two_sided_test=True)
    sc._CALLS.clear()
    sc.check_cluster_measures(arr, 1.0, bs, True, sizes, masses)
    assert fired() == []
    sc._CALLS.clear()
    bad = lambda a, b, E=0.5, H=2, dh="auto", two_sided_test=True: np.abs(a) ** 1.5  # noqa: E731
    monkeypatch.setattr(mu, "calculate_tfce", bad)
    sc.check_tfce(arr, bs, 0.5, 2, "auto", True, bad(arr, bs))
    monkeypatch.setattr(mu, "calculate_cluster_measures", lambda a, t, b, two_sided_test=False: (np.array([1, 1]), np.array([5.0, 5.0])))
    sc.check_cluster_measures(arr, 1.0, bs, True, sizes + 3, masses)
    assert set(fired()) == {"NL-MU-002", "NL-MU-003", "NL-MU-005"}


def test_mu004(fired):
    from nilearn.mass_univariate._utils import null_to_p

    t = np.array([0.1, 1.0, 2.0, 3.0])
    p = null_to_p(t, RNG.standard_normal(500))
    sc.check_null_to_p(t, p, "two-sided")
    assert fired() == []
    sc.check_null_to_p(t, p[::-1], "two-sided")
    assert fired() == ["NL-MU-004"]


# ----------------------------------------------------------------------- image
def test_img001_002(fired):
    from nilearn.image.image import smooth_array

    x = RNG.standard_normal((16, 16, 16))
    good = smooth_array(x, AFF, fwhm=10.0)
    sc.check_smoothing(x, good, AFF, 10.0, smooth_array, True)
    assert fired() == []
    # a tampered output violates both laws (the quadrature probe compares to it)
    sc.check_smoothing(x, good + 0.01, AFF, 10.0, smooth_array, True)
    assert fired() == ["NL-IMG-001", "NL-IMG-002"]

    def bad_smooth(a, aff, f, ensure_finite=True, copy=True):
        return smooth_array(a, aff, np.asarray(f) * 2.0, ensure_finite=ensure_finite, copy=copy)

    # a smoother whose widths do not add in quadrature alarms only NL-IMG-002
    sc.check_smoothing(x, good, AFF, 10.0, bad_smooth, True)
    assert fired()[2:] == ["NL-IMG-002"]


def test_img003(fired):
    from nilearn.image import resample_img

    data = RNG.standard_normal((12, 13, 14))
    img = nib.Nifti1Image(data, AFF)
    tgt = np.diag([3.0, 3.0, 3.0, 1.0])
    tgt[:3, 3] = [-1.0, -2.0, -3.0]
    out = resample_img(img, target_affine=tgt, target_shape=(9, 9, 9))
    assert fired() == []
    shifted = np.roll(out.get_fdata(), 1, axis=0)
    sc.check_resample_geometry(data, AFF, shifted, out.affine, "continuous", 0.0, True)
    assert fired() == ["NL-IMG-003"]


def test_img004_005(fired, monkeypatch):
    from nilearn.regions import img_to_signals_labels, signals_to_img_labels, signals_to_img_maps
    from nilearn.regions import signal_extraction as se

    lab = np.zeros((8, 8, 8), dtype=np.int32)
    lab[:4], lab[4:, :4], lab[4:, 4:] = 1, 2, 3
    lab_img = nib.Nifti1Image(lab, AFF)
    sig = RNG.standard_normal((20, 3))
    res = signals_to_img_labels(sig, lab_img)
    maps_img = nib.Nifti1Image(np.abs(RNG.standard_normal((8, 8, 8, 3))), AFF)
    signals_to_img_maps(sig, maps_img)
    assert fired() == []
    orig = se.img_to_signals_labels
    monkeypatch.setattr(se, "img_to_signals_labels", lambda *a, **k: (orig(*a, **k)[0] + 1.0, [1, 2, 3], None))
    sc.check_labels_signal_roundtrip(sig, res, lab_img, None, 0)
    orig2 = se.img_to_signals_maps
    monkeypatch.setattr(se, "img_to_signals_maps", lambda *a, **k: (orig2(*a, **k)[0] + 1.0, [0, 1, 2]))
    sc.check_maps_signal_consistency(sig, res, maps_img, None)
    assert fired() == ["NL-IMG-004", "NL-IMG-005"]
    del img_to_signals_labels


# ------------------------------------------------------------------ disabled
def test_inert_without_env(monkeypatch, tmp_path):
    monkeypatch.delenv("SCIBENCH_TRIGGER_LOG", raising=False)
    assert not sc.enabled()
    sc.trigger_if(True, "NL-SIG-001")  # no log configured: no-op
    assert not list(tmp_path.iterdir())
