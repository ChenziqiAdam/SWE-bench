"""Adversarial false-positive fuzzing of the nilearn bank (T/X/P/N classes).

Random *valid* inputs (dtype, scale, offset, conditioning, geometry) are pushed
through the public API with the logger on. Every alarm is recorded with the case
descriptor so it can be replayed (``--seed S --only CASE``) and adjudicated: either a
checker-side defect (fix and log in LAW_CANDIDATES.md) or a library behaviour.

    python fuzz_scientific_checkers.py --seeds 0 1 2 3 --out fuzz.json
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import traceback
import warnings

import numpy as np

warnings.simplefilter("ignore")
_LOG = os.path.join(tempfile.mkdtemp(), "fuzz_log.jsonl")
os.environ["SCIBENCH_TRIGGER_LOG"] = _LOG
os.environ["SCIBENCH_CHECKER_DEBUG"] = "1"
open(_LOG, "w").close()

import nibabel as nib  # noqa: E402

from nilearn import _scientific_checkers as sc  # noqa: E402


def rand_affine(rng, kind):
    a = np.eye(4)
    vox = 10 ** rng.uniform(-0.3, 0.7, size=3)
    if kind == "diag":
        a[:3, :3] = np.diag(vox)
    else:
        q, _ = np.linalg.qr(rng.standard_normal((3, 3)))
        a[:3, :3] = q * vox
        if kind == "sheared":
            a[:3, :3] += 0.15 * rng.standard_normal((3, 3)) * vox.mean()
    a[:3, 3] = rng.uniform(-20, 20, 3)
    return a


STRESS = float(os.environ.get("FUZZ_STRESS", "1"))


def log_scale(rng, lo=-8, hi=8):
    return 10 ** rng.uniform(lo * STRESS, hi * STRESS)


# ------------------------------------------------------------------ cases
def case_signal(rng):
    from nilearn import signal

    n = int(rng.integers(3, 300))
    p = int(rng.integers(1, 30))
    dt = np.float32 if rng.random() < 0.3 else np.float64
    scale = log_scale(rng, -6, 6)
    off = scale * log_scale(rng, -3, 3) * rng.choice([0, 1, -1])
    x = (rng.standard_normal((n, p)) * scale + off).astype(dt)
    if rng.random() < 0.3:
        x += (np.arange(n)[:, None] * scale * rng.standard_normal(p) * 0.1).astype(dt)
    desc = dict(n=n, p=p, dtype=str(np.dtype(dt)), scale=scale, off=off)
    r = rng.random()
    if r < 0.25:
        std = rng.choice(["zscore_sample", "psc"])
        signal.standardize_signal(x, detrend=bool(rng.random() < 0.5 and std != "psc"), standardize=str(std))
        desc["op"] = f"standardize {std}"
    elif r < 0.5:
        k = int(rng.integers(1, max(2, min(8, n - 1))))
        c = rng.standard_normal((n, k))
        if rng.random() < 0.4 and k > 1:
            c[:, -1] = c[:, 0] * rng.choice([1.0, 1e-6, 1e6]) + 1e-9 * rng.standard_normal(n)
        if rng.random() < 0.3:
            c *= log_scale(rng, -4, 4)
        sc_conf = bool(rng.random() < 0.7)
        signal.clean(x, confounds=c, detrend=False, filter=False, standardize=("zscore_sample" if rng.random() < 0.6 else None), standardize_confounds=sc_conf)
        desc["op"] = f"clean confounds k={k} std_conf={sc_conf}"
    elif r < 0.7:
        t_r = float(10 ** rng.uniform(-0.5, 0.8))
        nyq = 0.5 / t_r
        lo = float(nyq * rng.uniform(0.05, 0.9))
        hi = float(lo * rng.uniform(0.05, 0.9))
        filt = rng.choice(["butterworth", "cosine"])
        kw = dict(t_r=t_r, high_pass=hi, low_pass=lo if filt == "butterworth" else None)
        signal.clean(x, detrend=bool(rng.random() < 0.5), standardize=str(rng.choice(["zscore_sample", "psc"])), filter=str(filt), **kw)
        desc["op"] = f"clean {filt} {kw}"
    elif r < 0.85:
        t_r = float(10 ** rng.uniform(-0.5, 0.8))
        nn = int(rng.integers(5, 400))
        hp = float(10 ** rng.uniform(-3, 0) / (2 * t_r))
        signal.create_cosine_drift(hp, np.arange(nn) * t_r)
        desc["op"] = f"cosine n={nn} t_r={t_r} hp={hp}"
    else:
        nc = int(rng.integers(1, 5))
        if n > 12 and p >= 8:
            signal.high_variance_confounds(x.astype(np.float64), n_confounds=nc, percentile=float(rng.uniform(20, 100)), detrend=bool(rng.random() < 0.7))
        desc["op"] = f"compcor nc={nc}"
    return desc


def case_glm(rng):
    from nilearn.glm.contrasts import Contrast, compute_contrast
    from nilearn.glm.regression import ARModel, OLSModel

    n = int(rng.integers(12, 200))
    p = int(rng.integers(1, min(8, n - 4)))
    scale = log_scale(rng, -3, 3)
    X = rng.standard_normal((n, p)) * log_scale(rng, -2, 2)
    if rng.random() < 0.7:
        X[:, -1] = 1.0
    if rng.random() < 0.2 and p > 2:
        X[:, 0] = X[:, 1] * (1 + 10 ** rng.uniform(-9, -3) * rng.standard_normal(n))
    v = int(rng.integers(1, 60))
    Y = X @ rng.standard_normal((p, v)) * scale + rng.standard_normal((n, v)) * scale * rng.choice([1e-3, 1.0])
    Y = Y + scale * log_scale(rng, -2, 4) * rng.choice([0, 1])
    desc = dict(n=n, p=p, v=v, scale=scale)
    rho = rng.choice([0.0, 0.0, 0.4])
    res = (OLSModel(X) if rho == 0 else ARModel(X, float(rho))).fit(Y)
    res.r_square  # noqa: B018
    labels = np.zeros(v, dtype=int)
    cv = rng.standard_normal(p)
    r = rng.random()
    if r < 0.4:
        c = compute_contrast(labels, {0: res}, cv, "t")
        c.p_value(), c.one_minus_pvalue(), c.z_score()
        desc["op"] = "t contrast"
    elif r < 0.7 and p >= 2:
        q = int(rng.integers(2, p + 1))
        cm = rng.standard_normal((q, p))
        c = compute_contrast(labels, {0: res}, cm, "F")
        c.z_score()
        desc["op"] = f"F contrast q={q}"
    else:
        e = rng.standard_normal(v) * log_scale(rng, -2, 3)
        var = np.abs(rng.standard_normal(v)) * log_scale(rng, -4, 2) + 1e-12
        dof = float(10 ** rng.uniform(0, 12))
        c = Contrast(e, var, dof=dof)
        c.p_value(), c.z_score()
        desc["op"] = f"direct Contrast dof={dof:.3g}"
    return desc


def case_fixed(rng):
    import nibabel as nib

    from nilearn.glm import compute_fixed_effects

    aff = np.eye(4)
    shape = (4, 4, 3)
    nr = int(rng.integers(1, 6))
    mask = nib.Nifti1Image(np.ones(shape, dtype=np.int8), aff)
    s = log_scale(rng, -3, 3)
    ci = [nib.Nifti1Image(rng.standard_normal(shape) * s, aff) for _ in range(nr)]
    vi = [nib.Nifti1Image(np.abs(rng.standard_normal(shape)) * s * s * log_scale(rng, -2, 2) + 1e-14, aff) for _ in range(nr)]
    compute_fixed_effects(ci, vi, mask, precision_weighted=bool(rng.random() < 0.5))
    return dict(nr=nr, s=s, op="fixed effects")


def case_hrf(rng):
    from nilearn.glm.first_level import compute_regressor
    from nilearn.glm.first_level.hemodynamic_models import (
        glover_time_derivative,
        orthogonalize,
        spm_time_derivative,
    )

    t_r = float(10 ** rng.uniform(-0.3, 0.7))
    n = int(rng.integers(10, 200))
    ft = np.arange(n) * t_r
    ne = int(rng.integers(1, 12))
    on = rng.uniform(-10, ft[-1] + 5, ne)
    du = rng.choice([0.0, t_r, 3 * t_r, 10.0], size=ne)
    va = rng.standard_normal(ne) * log_scale(rng, -2, 2)
    model = str(rng.choice(["glover", "spm", "glover + derivative", "spm + derivative + dispersion", "fir"]))
    ov = int(rng.integers(5, 60))
    kw = dict(fir_delays=[0, 1, 2]) if model == "fir" else {}
    compute_regressor((on, du, va), model, ft, oversampling=ov, **kw)
    if rng.random() < 0.5:
        (spm_time_derivative if rng.random() < 0.5 else glover_time_derivative)(t_r, oversampling=ov)
    orthogonalize(rng.standard_normal((int(rng.integers(5, 80)), int(rng.integers(2, 6)))) * log_scale(rng, -2, 2))
    return dict(t_r=t_r, n=n, ne=ne, model=model, ov=ov, op="hrf")


def case_thr(rng):
    from nilearn.glm.thresholding import threshold_stats_img
    from nilearn.image import threshold_img

    shape = tuple(int(s) for s in rng.integers(5, 14, 3))
    d = rng.standard_normal(shape) * float(rng.choice([1.0, 1.0, 5.0]))
    if rng.random() < 0.7:
        a, b, c = (int(rng.integers(0, s - 2)) for s in shape)
        d[a : a + 3, b : b + 3, c : c + 3] += rng.uniform(2, 8) * rng.choice([1, -1])
    img = nib.Nifti1Image(d, np.eye(4))
    hc = str(rng.choice(["fpr", "fdr", "bonferroni"]))
    ts = bool(rng.random() < 0.6)
    al = float(10 ** rng.uniform(-4, -0.5))
    ct = int(rng.choice([0, 0, 2, 5, 12]))
    threshold_stats_img(img, alpha=al, height_control=hc, two_sided=ts, cluster_threshold=ct)
    threshold_img(img, threshold=float(rng.uniform(0, 3)), cluster_threshold=ct, two_sided=ts)
    return dict(shape=shape, hc=hc, ts=ts, alpha=al, ct=ct, op="thresholds")


def case_con(rng):
    from nilearn.connectome import (
        ConnectivityMeasure,
        group_sparse_covariance,
        sym_matrix_to_vec,
        vec_to_sym_matrix,
    )
    from nilearn.connectome.connectivity_matrices import _geometric_mean, cov_to_corr

    p = int(rng.integers(2, 12))
    ns = int(rng.integers(2, 7))
    T = int(rng.integers(p + 5, 200))
    mix = rng.standard_normal((p, p)) * 10 ** rng.uniform(-1, 1, p)
    ts = [rng.standard_normal((T, p)) @ mix for _ in range(ns)]
    desc = dict(p=p, ns=ns, T=T)
    r = rng.random()
    if r < 0.4:
        kind = str(rng.choice(["covariance", "correlation", "precision", "partial correlation", "tangent"]))
        if kind == "tangent" and ns < 2:
            kind = "covariance"
        ConnectivityMeasure(kind=kind, vectorize=bool(rng.random() < 0.5)).fit_transform(ts)
        desc["op"] = kind
    elif r < 0.6:
        cov = np.cov(ts[0].T)
        cov_to_corr(cov)
        v = sym_matrix_to_vec(cov, discard_diagonal=False)
        vec_to_sym_matrix(v)
        desc["op"] = "vec"
    elif r < 0.8:
        mats = [np.cov(t.T) for t in ts]
        _geometric_mean(mats, max_iter=int(rng.choice([10, 30])), tol=float(rng.choice([1e-7, 1e-5])))
        desc["op"] = "gmean"
    else:
        sub = [rng.standard_normal((T, min(p, 6))) for _ in range(min(ns, 4))]
        group_sparse_covariance(sub, alpha=float(10 ** rng.uniform(-2, 1.2)), max_iter=8)
        desc["op"] = "gsc"
    return desc


def case_mu(rng):
    from nilearn.mass_univariate import permuted_ols
    from nilearn.mass_univariate._utils import null_to_p
    from nilearn.maskers import NiftiMasker

    n = int(rng.integers(12, 60))
    nr = int(rng.integers(1, 3))
    nv = int(rng.integers(4, 40))
    tv = rng.standard_normal((n, nr)) * log_scale(rng, -2, 2)
    tg = rng.standard_normal((n, nv)) * log_scale(rng, -2, 2) + log_scale(rng, -2, 2) * rng.choice([0, 1])
    cv = rng.standard_normal((n, int(rng.integers(1, 3)))) if rng.random() < 0.6 else None
    if rng.random() < 0.3:
        tg[:, 0] = tv[:, 0] * 2.0 + 0.1 * rng.standard_normal(n)
    permuted_ols(tv, tg, confounding_vars=cv, model_intercept=bool(rng.random() < 0.7), n_perm=0, random_state=0)
    if rng.random() < 0.4:
        mask = nib.Nifti1Image(np.ones((3, 3, 3), dtype=np.int8), np.eye(4))
        masker = NiftiMasker(mask_img=mask).fit()
        tg2 = rng.standard_normal((n, 27))
        permuted_ols(tv[:, :1], tg2, n_perm=int(rng.choice([3, 8])), random_state=1, masker=masker, tfce=True, threshold=0.1, two_sided_test=bool(rng.random() < 0.5))
    null_to_p(rng.standard_normal(int(rng.integers(2, 1300))), rng.standard_normal(int(rng.integers(5, 300))), alternative=str(rng.choice(["two-sided", "larger", "smaller"])))
    return dict(n=n, nr=nr, nv=nv, op="mass-univariate")


def case_img(rng):
    from nilearn.image import resample_img, smooth_img
    from nilearn.regions import img_to_signals_labels, signals_to_img_labels, signals_to_img_maps

    shape = tuple(int(s) for s in rng.integers(6, 16, 3))
    kind = str(rng.choice(["diag", "rot", "sheared"]))
    aff = rand_affine(rng, kind)
    dt = np.float32 if rng.random() < 0.3 else np.float64
    d = (rng.standard_normal(shape) * log_scale(rng, -3, 3) + log_scale(rng, -3, 3) * rng.choice([0, 1])).astype(dt)
    img = nib.Nifti1Image(d, aff)
    desc = dict(shape=shape, aff=kind, dtype=str(np.dtype(dt)))
    r = rng.random()
    if r < 0.35:
        fw = float(10 ** rng.uniform(0, 1.4))
        smooth_img(img, fwhm=fw if rng.random() < 0.7 else [fw, fw * 1.5, fw * 0.7])
        desc["op"] = f"smooth {fw}"
    elif r < 0.75:
        tgt = rand_affine(rng, str(rng.choice(["diag", "rot", "sheared"])))
        interp = str(rng.choice(["continuous", "linear", "nearest"]))
        tshape = tuple(int(s) for s in rng.integers(6, 16, 3))
        try:
            resample_img(img, target_affine=tgt, target_shape=tshape, interpolation=interp, clip=bool(rng.random() < 0.7))
        except Exception:
            pass
        desc["op"] = f"resample {interp}"
    elif r < 0.9:
        lab = rng.integers(0, 4, shape).astype(np.int32)
        li = nib.Nifti1Image(lab, aff)
        sig = rng.standard_normal((int(rng.integers(3, 20)), len(np.unique(lab)) - 1))
        signals_to_img_labels(sig, li)
        desc["op"] = "labels"
    else:
        m = np.abs(rng.standard_normal((*shape, 3))) + 0.1 * rng.random()
        signals_to_img_maps(rng.standard_normal((10, 3)), nib.Nifti1Image(m, aff))
        desc["op"] = "maps"
    return desc


CASES = [case_signal, case_glm, case_fixed, case_hrf, case_thr, case_con, case_mu, case_img]


STATS = {"cases": 0, "errors": 0, "error_kinds": {}, "reached": {}}


def run(seed, n_sets, only=None):
    out = []
    for k in range(n_sets):
        for fn in CASES:
            name = f"{fn.__name__}#{k}"
            if only and name != only:
                continue
            rng = np.random.default_rng([seed, k, CASES.index(fn)])
            before = os.path.getsize(_LOG)
            try:
                desc = fn(rng)
            except Exception as exc:  # invalid combination for the library itself
                desc = {"error": f"{type(exc).__name__}: {str(exc)[:80]}"}
                STATS["errors"] += 1
                key = f"{fn.__name__}: {desc['error']}"
                STATS["error_kinds"][key] = STATS["error_kinds"].get(key, 0) + 1
            STATS["cases"] += 1
            if os.path.getsize(_LOG) > before:
                with open(_LOG) as fh:
                    fh.seek(before)
                    ids = [json.loads(line)["checker_id"] for line in fh.read().splitlines()]
                out.append({"seed": seed, "case": name, "ids": ids, "desc": desc})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--sets", type=int, default=14)
    ap.add_argument("--only", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    allr = []
    for s in a.seeds:
        allr += run(s, a.sets, a.only)
    STATS["reached"] = dict(sorted(sc.REACHED.items()))
    res = {"alarms": allr, "swallowed": sc.SWALLOWED[:5], "n_swallowed": len(sc.SWALLOWED), "stats": STATS}
    txt = json.dumps(res, indent=1, default=str)
    if a.out:
        open(a.out, "w").write(txt)
    print(txt)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
