"""Regression tests for the 2026-09-14 Astropy checker repairs."""

import os

import numpy as np

from astropy import _scientific_checkers as checkers


def _capture(monkeypatch):
    seen = []
    monkeypatch.setattr(
        checkers,
        "trigger_if",
        lambda condition, checker_id: seen.append(checker_id) if condition else None,
    )
    return seen


def test_coord001_binds_alarm_to_requested_offset(monkeypatch):
    seen = _capture(monkeypatch)
    checkers.check_offset_roundtrip(0.0, 0.0, 0.2, 0.3, 1.0, 0.4)
    assert seen == ["AP-COORD-001"]


def test_coord001_valid_public_call_does_not_alarm(monkeypatch):
    from astropy import units as u
    from astropy.coordinates import SkyCoord

    seen = _capture(monkeypatch)
    monkeypatch.setenv("SCIBENCH_TRIGGER_LOG", os.devnull)
    SkyCoord(10 * u.deg, 20 * u.deg).directional_offset_by(
        30 * u.deg, 2 * u.deg
    )
    assert seen == []


def test_nddata001_observes_propagated_result_and_is_sensitive(monkeypatch):
    from astropy.nddata import NDDataArray, StdDevUncertainty

    seen = _capture(monkeypatch)
    a = NDDataArray([2.0, 3.0], uncertainty=StdDevUncertainty([0.2, 0.3]))
    b = NDDataArray([4.0, 5.0], uncertainty=StdDevUncertainty([0.4, 0.5]))
    good = a.add(b)
    assert seen == []

    checkers.check_uncertainty_cross_representation(
        a.uncertainty,
        np.add,
        b,
        good.data,
        0,
        StdDevUncertainty([9.0, 9.0]),
    )
    assert seen == ["AP-NDDATA-001"]


def test_high_condition_signed_kernel_is_outside_comparison_domain(monkeypatch):
    from astropy.convolution import CustomKernel, convolve

    seen = _capture(monkeypatch)
    monkeypatch.setenv("SCIBENCH_TRIGGER_LOG", os.devnull)
    rng = np.random.default_rng(20260914)
    array = rng.normal(size=101)
    kernel = CustomKernel(np.array([1e12, -1e12, 1.0]))
    result = convolve(array, kernel, boundary="wrap", normalize_kernel=True)
    assert np.all(np.isfinite(result))
    assert seen == []


def test_signed_doppler_probes_do_not_false_alarm(monkeypatch):
    from astropy import units as u
    from astropy.units.equivalencies import doppler_optical, doppler_radio

    seen = _capture(monkeypatch)
    monkeypatch.setenv("SCIBENCH_TRIGGER_LOG", os.devnull)
    doppler_radio(1 * u.GHz)
    doppler_optical(1 * u.GHz)
    assert seen == []


def test_model001_uses_more_than_the_stationary_first_probe(monkeypatch):
    class HiddenDependence:
        n_inputs = 1
        n_outputs = 1

        def __call__(self, x):
            return ((x - 0.7) ** 2,)

    seen = _capture(monkeypatch)
    checkers.check_separability_soundness(
        HiddenDependence(), np.array([[False]], dtype=bool)
    )
    assert "AP-MODEL-001" in seen


def test_stats003_honors_ignore_nan_domain(monkeypatch):
    from astropy.stats import biweight_midvariance

    data = np.array([1.0, 2.0, 3.0, 4.0, 6.0, np.nan])
    result = biweight_midvariance(data, ignore_nan=True)
    seen = _capture(monkeypatch)
    checkers.check_biweight_midvariance_equivariance(
        data, 9.0, None, False, True, result
    )
    assert seen == []


def test_stats003_does_not_false_alarm_on_small_c_large_offset(monkeypatch):
    """Regression for the 2026-09-18 false positive: the gate compared
    `|median|/MAD` to a fixed threshold, but the estimator normalizes by
    `c * MAD`, not `MAD` alone. A non-default small `c` (1.635, vs. the
    default 9.0) narrowed the outlier-rejection window enough that this
    16-point array -- large common offset, small scatter -- tripped the
    equivariance check (relerr 2.83e-9 > tol 1e-9) even though astropy's
    `biweight_midvariance` has no logic bug here (verified against exact
    rational arithmetic): the error is ordinary float64 rounding on an
    input whose true `c`-scaled condition number is ~5.9e5, past this
    checker's own domain of applicability.
    """
    from astropy.stats import biweight_midvariance

    arr = np.array(
        [
            -783161.534172163,
            -783150.1681280751,
            -783151.1712676457,
            -783150.3240702435,
            -783149.6016685006,
            -783151.2339116425,
            -783149.4110833952,
            -783151.5565275266,
            -783150.1572755894,
            -783149.5619023215,
            -783150.5133361227,
            -783151.7201092979,
            -783150.8919657138,
            -783150.690095443,
            -783149.2541900594,
            -783148.7953265094,
        ]
    )
    c = 1.6349759216748132
    result = biweight_midvariance(arr, c=c)

    seen = _capture(monkeypatch)
    checkers.check_biweight_midvariance_equivariance(arr, c, None, False, False, result)
    assert seen == []


def test_quarantined_checkers_are_inert(monkeypatch):
    seen = _capture(monkeypatch)
    checkers.check_asinh_stretch_inverse_roundtrip(
        1e-308, np.array([0.5]), np.array([0.0])
    )
    checkers.check_frame_roundtrip_3d((1.0, 0.0, 0.0), (2.0, 0.0, 0.0))
    assert seen == []


def test_quarantine_set_matches_review_decisions():
    assert checkers._QUARANTINED_CHECKERS == {
        "frame_transform_roundtrip",
        "frame_transform_roundtrip_3d",
        "time_scale_roundtrip",
        "circstd_circvar_consistency",
        "kernel_normalization_exactness",
        "lombscargle_cross_implementation",
        "log_stretch_inverse_roundtrip",
        "asinh_stretch_inverse_roundtrip",
        "power_dist_stretch_inverse_roundtrip",
    }
