"""Curator-side isolated checker sensitivity (SANITIZER.md 8): each predicate must record its
expected alarm on a synthetic violating state, via fault injection or a modified observed state.
These tests are never benchmark witnesses.

Run:  SCIBENCH_PILOT=1 python -m pytest test_scientific_checkers.py -q  (instrumented sunpy on sys.path)
"""
import json
import os
import tempfile
import warnings

import numpy as np
import pytest

LOG = tempfile.mktemp(suffix=".jsonl")
os.environ["SCIBENCH_TRIGGER_LOG"] = LOG
warnings.simplefilter("ignore")

import astropy.units as u  # noqa: E402
from astropy.coordinates import SkyCoord  # noqa: E402
from astropy.time import Time  # noqa: E402

import sunpy._scientific_checkers as sc  # noqa: E402
import sunpy.map  # noqa: E402
from sunpy.coordinates import (Helioprojective, HeliographicStonyhurst, SphericalScreen,  # noqa: E402
                               get_earth, propagate_with_solar_surface, sun)
from sunpy.coordinates.ephemeris import get_body_heliographic_stonyhurst  # noqa: E402
from sunpy.sun import constants  # noqa: E402

T = Time("2020-04-08 12:00:00")


def run(fn, *args, **kwargs):
    """Return the set of IDs logged while calling ``fn``."""
    open(LOG, "w").close()
    fn(*args, **kwargs)
    return {json.loads(line)["checker_id"] for line in open(LOG) if line.strip()}


def make_map(n=64, scale=40.0, centre=(0, 0), date="2020-04-08", rotation=0.0):
    c = SkyCoord(centre[0] * u.arcsec, centre[1] * u.arcsec, obstime=date, observer="earth", frame=Helioprojective)
    hdr = sunpy.map.make_fitswcs_header(np.zeros((n, n)), c, scale=[scale, scale] * u.arcsec / u.pix,
                                        rotation_angle=rotation * u.deg)
    return sunpy.map.Map(np.random.default_rng(0).uniform(1, 10, (n, n)), hdr)


def shifted(smap, dx=1.0, dy=0.0):
    meta = smap.meta.copy()
    meta["crpix1"] = meta["crpix1"] + dx
    meta["crpix2"] = meta["crpix2"] + dy
    return sunpy.map.Map(smap.data, meta)


# ------------------------------------------------------------------ ephemeris
def test_eph_001():
    r, d = constants.radius, sun.earth_distance(T)
    th = sun.angular_radius(T)
    assert "SP-EPH-001" not in run(sc.check_angular_radius, r, d, th)
    assert "SP-EPH-001" in run(sc.check_angular_radius, r, d, th * 0.9)
    assert "SP-EPH-001" in run(sc.check_angular_radius, r, d, th * 1.5)


def test_eph_002_003():
    dist = sun.earth_distance(T)
    assert not run(sc.check_earth_distance, T, dist)
    assert "SP-EPH-002" in run(sc.check_earth_distance, T, dist * 0.9)
    f = run(sc.check_earth_distance, T, dist * (1 + 1e-6))
    assert "SP-EPH-003" in f and "SP-EPH-002" not in f


def test_eph_004():
    b0 = sun.B0(T)
    assert not run(sc.check_b0, T, b0)
    assert "SP-EPH-004" in run(sc.check_b0, T, b0 + 1e-6 * u.rad)


def test_eph_005():
    true = sun.true_obliquity_of_ecliptic(T)
    assert not run(sc.check_obliquity, T, true)
    assert "SP-EPH-005" in run(sc.check_obliquity, T, true + 20 * u.arcsec)


def test_eph_006():
    lon = sun.apparent_longitude(T)
    assert not run(sc.check_apparent_lon, T, lon)
    assert "SP-EPH-006" in run(sc.check_apparent_lon, T, lon - 60 * u.arcsec)


def test_eph_007():
    ra, dec = sun.apparent_rightascension(T), sun.apparent_declination(T)
    assert not run(sc.check_apparent_equatorial, T, ra, "ra")
    assert not run(sc.check_apparent_equatorial, T, dec, "dec")
    assert "SP-EPH-007" in run(sc.check_apparent_equatorial, T, ra + 1 * u.arcsec, "ra")
    assert "SP-EPH-007" in run(sc.check_apparent_equatorial, T, dec + 1 * u.arcsec, "dec")


def test_eph_008():
    hgs = get_body_heliographic_stonyhurst("earth", T)
    assert not run(sc.check_body_hgs, "earth", None, T, hgs)
    bad = HeliographicStonyhurst(hgs.lon + 1 * u.deg, hgs.lat, hgs.radius, obstime=T)
    assert "SP-EPH-008" in run(sc.check_body_hgs, "earth", None, T, bad)


def test_eph_009():
    from astropy.coordinates import get_body_barycentric
    from astropy.constants import c
    obs = get_body_barycentric("earth", T)
    em = T - (get_body_barycentric("venus", T) - obs).norm() / c
    ltt = (get_body_barycentric("venus", em) - obs).norm() / c
    assert not run(sc.check_light_time, "venus", obs, ltt, em, T)
    assert "SP-EPH-009" in run(sc.check_light_time, "venus", obs, ltt + 1e-3 * u.s, em, T)


def test_eph_010():
    s = np.array([0.0046]); m = np.array([0.0047]); d = np.array([0.0030])
    # planar reference overlap via the checker's own formula path: reuse by evaluating the true fraction
    r1, r2, dd = s[0], m[0], d[0]
    lens = (r1**2 * np.arccos((dd**2 + r1**2 - r2**2) / (2 * dd * r1))
            + r2**2 * np.arccos((dd**2 + r2**2 - r1**2) / (2 * dd * r2))
            - 0.5 * np.sqrt((-dd + r1 + r2) * (dd + r1 - r2) * (dd - r1 + r2) * (dd + r1 + r2)))
    frac = np.array([lens / (np.pi * r1**2)])
    assert not run(sc.check_eclipse, s, m, d, frac)
    assert "SP-EPH-010" in run(sc.check_eclipse, s, m, d, frac + 0.05)


# ------------------------------------------------------------------ Carrington
def test_car_001_003(monkeypatch):
    n = sun.carrington_rotation_number(T)
    assert not run(sc.check_carrington_number, T, n)
    assert "SP-CAR-001" in run(sc.check_carrington_number, T, n + 0.01)
    monkeypatch.setattr(constants, "mean_synodic_period", 27.0 * u.day)
    assert "SP-CAR-003" in run(sc.check_carrington_number, T, n)


def test_car_002():
    t = sun.carrington_rotation_time(2242)
    assert not run(sc.check_carrington_roundtrip, 2242 * u.one, t)
    assert "SP-CAR-002" in run(sc.check_carrington_roundtrip, 2242.001 * u.one, t)


def test_car_004():
    l0 = sun.L0(T)
    assert not run(sc.check_disk_center, T, l0, True, True, False)
    assert "SP-CAR-004" in run(sc.check_disk_center, T, l0 + 1 * u.deg, True, True, False)


# --------------------------------------------------------- differential rotation
def _dr(duration, lat, model="howard", frame_time="sidereal"):
    from sunpy.sun import models
    return models.differential_rotation(duration, lat, model=model, frame_time=frame_time)


def test_drm_clean():
    lat = np.array([-40, 10, 55]) * u.deg
    assert not run(sc.check_diffrot, 3 * u.day, lat, "howard", "sidereal", _dr(3 * u.day, lat))


@pytest.mark.parametrize("idx", ["SP-DRM-001", "SP-DRM-003"])
def test_drm_state_faults(idx):
    lat = np.array([-40, 10, 55]) * u.deg
    bad = _dr(3 * u.day, lat) + 2 * u.deg
    assert idx in run(sc.check_diffrot, 3 * u.day, lat, "howard", "sidereal", bad)


def test_drm_faulty_model(monkeypatch):
    from sunpy.sun import models
    real = models.differential_rotation

    def cos2(duration, latitude, *, model="howard", frame_time="sidereal"):
        # rate increases toward the pole (cos^2 instead of sin^2)
        out = real(duration, 90 * u.deg - np.abs(latitude), model=model, frame_time=frame_time)
        return out
    lat = np.array([-40, 10, 55]) * u.deg
    res = real(3 * u.day, lat)
    monkeypatch.setattr(models, "differential_rotation", cos2)
    assert "SP-DRM-002" in run(sc.check_diffrot, 3 * u.day, lat, "howard", "sidereal", res)

    def scaled(duration, latitude, *, model="howard", frame_time="sidereal"):
        # unit slip in the coefficients: 10x too fast
        return real(duration * 10, latitude, model=model, frame_time=frame_time)
    monkeypatch.setattr(models, "differential_rotation", scaled)
    f = run(sc.check_diffrot, 3 * u.day, lat, "howard", "sidereal", res)
    assert "SP-DRM-004" in f

    def one_model(duration, latitude, *, model="howard", frame_time="sidereal"):
        return real(duration * (1.5 if model == "allen" else 1), latitude, model=model, frame_time=frame_time)
    monkeypatch.setattr(models, "differential_rotation", one_model)
    assert "SP-DRM-006" in run(sc.check_diffrot, 3 * u.day, lat, "howard", "sidereal", res)

    def bad_synodic(duration, latitude, *, model="howard", frame_time="sidereal"):
        out = real(duration, latitude, model=model, frame_time="sidereal")
        return out - (0.5 * u.deg / u.day * duration if frame_time == "synodic" else 0 * u.deg)
    monkeypatch.setattr(models, "differential_rotation", bad_synodic)
    assert "SP-DRM-005" in run(sc.check_diffrot, 3 * u.day, lat, "howard", "sidereal", res)


# --------------------------------------------------------------------- frames
def _hpc(tx=(300, 600, 900), ty=(100, -200, 300)):
    return SkyCoord(list(tx) * u.arcsec, list(ty) * u.arcsec, frame=Helioprojective, observer="earth", obstime=T)


def test_frm_001():
    c = _hpc()
    c3 = c.make_3d()
    f = c.frame
    args = (f, f.Tx, f.Ty, c3.distance)
    assert not run(sc.check_make3d, *args)
    assert "SP-FRM-001" in run(sc.check_make3d, f, f.Tx, f.Ty, c3.distance * 1.001)


def test_frm_002():
    c = _hpc((0, 300, 1500), (0, 100, 0))
    res = sunpy.map.coordinate_is_on_solar_disk(c)
    assert not run(sc.check_on_disk, c, res)
    assert "SP-FRM-002" in run(sc.check_on_disk, c, ~res)


def test_frm_003():
    c = _hpc((0, 300, 600), (0, 100, 0))
    other = get_body_heliographic_stonyhurst("mars", T)
    to = Helioprojective(observer=other, obstime=T)
    out = c.transform_to(to)
    assert not run(sc.check_observer_invariance, c.frame, to, out.frame)
    bad = to.realize_frame(out.data.__class__(out.spherical.lon, out.spherical.lat, out.spherical.distance * 1.001))
    assert "SP-FRM-003" in run(sc.check_observer_invariance, c.frame, to, bad)


def test_frm_004():
    from sunpy.coordinates.utils import get_heliocentric_angle
    c = _hpc((0, 300), (0, 100))
    ang = get_heliocentric_angle(c)
    assert not run(sc.check_helio_angle, c, ang)
    assert "SP-FRM-004" in run(sc.check_helio_angle, c, ang + 1 * u.deg)


def test_frm_005():
    from sunpy.coordinates.utils import get_limb_coordinates
    obs = get_earth(T)
    limb = get_limb_coordinates(obs)
    assert not run(sc.check_limb, limb, obs, constants.radius)
    assert "SP-FRM-005" in run(sc.check_limb, limb, obs, constants.radius * 1.01)


def test_frm_006():
    from sunpy.coordinates.utils import GreatArc
    a = SkyCoord(100 * u.arcsec, 50 * u.arcsec, frame=Helioprojective, observer="earth", obstime=T)
    b = SkyCoord(-400 * u.arcsec, 200 * u.arcsec, frame=Helioprojective, observer="earth", obstime=T)
    arc = GreatArc(a, b)
    pts = arc._points_handler(None)
    # reconstruct the cartesian points
    ang = pts.reshape(-1, 1) * arc.inner_angle.value
    cart = arc.v1[None, :] * np.cos(ang) + arc.v3[None, :] * np.sin(ang) + arc.center_cartesian
    assert not run(sc.check_great_arc, arc, pts, cart)
    bad = cart.copy()
    bad[50] += 0.02 * arc._r  # off the geodesic
    assert "SP-FRM-006" in run(sc.check_great_arc, arc, pts, bad)


# -------------------------------------------------------------------- screens
def test_scr_001():
    from astropy.coordinates import CartesianRepresentation, UnitSphericalRepresentation
    centre = CartesianRepresentation([0.0, 0.0, 0.0] * u.m)
    centre = CartesianRepresentation(1.5e11 * u.m, 0 * u.m, 0 * u.m)
    rep = UnitSphericalRepresentation(np.array([0.001, 0.002]) * u.rad, np.array([0.0, 0.001]) * u.rad)
    radius = 1.5e11 * u.m
    cvec = np.array([1.5e11, 0, 0.0])
    uvec = rep.to_cartesian().xyz.value
    b = -2 * cvec @ uvec
    c = cvec @ cvec - radius.value**2
    d = (-b + np.sqrt(b**2 - 4 * c)) / 2 * u.m
    assert not run(sc.check_spherical_screen, centre, rep, d, radius)
    assert "SP-SCR-001" in run(sc.check_spherical_screen, centre, rep, d * 1.01, radius)
    near = (-b - np.sqrt(b**2 - 4 * c)) / 2 * u.m  # near root violates the far-root law
    assert "SP-SCR-001" in run(sc.check_spherical_screen, centre, rep, near, radius)


def test_scr_002(monkeypatch):
    hp = Helioprojective(range(3) * u.arcsec * 319, [0] * 3 * u.arcsec, observer="earth", obstime="2020-04-08")
    screen = SphericalScreen(hp.observer)
    screen_frame = Helioprojective(observer=hp.observer, obstime=hp.observer.obstime)
    dist = np.array([1.0, 1.0, 1.0]) * 1.496e11 * u.m
    monkeypatch.setattr(screen, "calculate_distance",
                        lambda f: np.full(f.shape, 1.2e11) * u.m)
    assert "SP-SCR-002" in run(sc.check_screen_iteration, screen, hp, dist, screen_frame)


# ---------------------------------------------------------- rotated coordinates
def test_drc():
    from sunpy.physics.differential_rotation import solar_rotate_coordinate
    c = SkyCoord(-570 * u.arcsec, 120 * u.arcsec, obstime=T, observer="earth", frame=Helioprojective)
    new_obs = get_body_heliographic_stonyhurst("earth", T + 6 * u.day)
    res = solar_rotate_coordinate(c, observer=new_obs)
    kw = {"frame_time": "sidereal"}
    assert not run(sc.check_solar_rotate, c, new_obs, new_obs, kw, res)
    # wrong-sign rotation: build the result with lon - drot
    from sunpy.coordinates import transform_with_sun_center
    from sunpy.sun.models import differential_rotation
    hgs = c.transform_to(HeliographicStonyhurst)
    drot = differential_rotation((new_obs.obstime - c.obstime).to(u.s), hgs.lat, frame_time="sidereal")
    rot = SkyCoord(hgs.lon - drot, hgs.lat, hgs.radius, obstime=c.obstime, frame=HeliographicStonyhurst)
    fr = c.frame.replicate_without_data(observer=new_obs, obstime=new_obs.obstime)
    with transform_with_sun_center():
        bad = rot.transform_to(fr)
    f = run(sc.check_solar_rotate, c, new_obs, new_obs, kw, bad)
    assert "SP-DRC-002" in f and "SP-DRC-001" in f


# ----------------------------------------------------------------------- maps
def test_map_001_002_004_005():
    m = make_map()
    assert not run(sc.check_resample_footprint, m, m.resample([32, 32] * u.pix))
    assert "SP-MAP-001" in run(sc.check_resample_footprint, m, shifted(m.resample([32, 32] * u.pix), 1.0))
    sp = m.superpixel([2, 2] * u.pix)
    assert not run(sc.check_superpixel_footprint, m, sp, [2, 2], [0, 0])
    assert "SP-MAP-002" in run(sc.check_superpixel_footprint, m, shifted(sp, 0.5), [2, 2], [0, 0])
    rot = m.rotate(20 * u.deg)
    assert not run(sc.check_rotate_center, m, rot, False)
    assert "SP-MAP-004" in run(sc.check_rotate_center, m, shifted(rot, 2.0, 1.0), False)
    sub = m.submap([10, 12] * u.pix, top_right=[40, 50] * u.pix)
    assert not run(sc.check_submap, m, sub)
    assert "SP-MAP-005" in run(sc.check_submap, m, shifted(sub, 0.5, 0.0))
    meta = sub.meta.copy()
    bad_data = sunpy.map.Map(sub.data + 1.0, meta)
    assert "SP-MAP-005" in run(sc.check_submap, m, bad_data)


def test_map_003():
    orig = np.random.default_rng(3).uniform(1, 10, (20, 30))
    dims = np.array([10.0, 15.0])
    m1 = np.array(0, dtype=np.int64)
    off = np.float64(0.5)
    from sunpy.image.resample import resample
    good = resample(orig, (10, 15), method="linear", center=True)
    assert not run(sc.check_resample_extrema, orig, dims, "linear", off, m1, good)
    assert "SP-MAP-003" in run(sc.check_resample_extrema, orig, dims, "linear", off, m1, good * 1.5)


def test_map_006_007_008():
    full = make_map(n=64, scale=100)       # contains limb (disk partly in 6400" field)
    on = make_map(n=40, scale=10)          # all on disk
    off = make_map(centre=(3000, 0))       # all off disk
    limb = bool(sunpy.map.contains_limb(full))
    assert not run(sc.check_disk_partition, full, limb)
    assert "SP-MAP-006" in run(sc.check_disk_partition, full, not limb)
    assert not run(sc.check_all_on_disk, on, True)
    part = make_map(n=40, scale=20, centre=(900, 0))  # straddles the limb
    assert "SP-MAP-007" in run(sc.check_all_on_disk, part, True)
    assert not run(sc.check_all_off_disk, off, True)
    assert "SP-MAP-008" in run(sc.check_all_off_disk, part, True)


# ------------------------------------------------------------ kernels, headers
def test_img_001(monkeypatch):
    import scipy.interpolate
    import sunpy.image.resample as rs
    shape, dims = (20, 30), np.array([10.0, 15.0])
    m1, off = np.array(0, dtype=np.int64), np.float64(0.5)
    assert not run(sc.check_resample_ramp, shape, dims, "linear", off, m1)
    real = rs._resample_nearest_linear

    def skewed(orig, dimensions, method, offset, m1):
        return real(orig, dimensions, method, offset + 0.01, m1)
    monkeypatch.setattr(rs, "_resample_nearest_linear", skewed)
    assert "SP-IMG-001" in run(sc.check_resample_ramp, shape, dims, "linear", off, m1)


def test_wcs_001(monkeypatch):
    import sunpy.coordinates.wcs_utils as wu
    from sunpy.coordinates.wcs_utils import solar_frame_to_wcs_mapping
    frame = Helioprojective(observer="earth", obstime=T)
    w = solar_frame_to_wcs_mapping(frame)
    assert not run(sc.check_frame_wcs, frame, w)
    real = wu.solar_wcs_frame_mapping
    monkeypatch.setattr(wu, "solar_wcs_frame_mapping",
                        lambda wcs: real(wcs).replicate_without_data(obstime=T + 5 * u.s))
    assert "SP-WCS-001" in run(sc.check_frame_wcs, frame, w)


def test_wcs_002():
    c = SkyCoord(100 * u.arcsec, -50 * u.arcsec, obstime=T, observer="earth", frame=Helioprojective)
    scale = [2.0, 2.0] * u.arcsec / u.pix
    ref = [10.0, 20.0] * u.pix
    meta = sunpy.map.make_fitswcs_header((64, 64), c, reference_pixel=ref, scale=scale)
    assert not run(sc.check_fits_header, c, ref, scale, None, (64, 64), meta)
    bad = dict(meta)
    bad["crpix1"] = bad["crpix1"] + 1.0
    assert "SP-WCS-002" in run(sc.check_fits_header, c, ref, scale, None, (64, 64), bad)
    bad = dict(meta)
    bad["cdelt1"] = bad["cdelt1"] * 1.001
    assert "SP-WCS-002" in run(sc.check_fits_header, c, ref, scale, None, (64, 64), bad)


def test_map_checkers_do_not_fill_production_caches():
    """Non-disruption: checkers work on clones, so the property caches (a cached ``wcs`` would swallow the
    user's first-access metadata warning) of the production maps stay untouched."""
    m = make_map()
    new = m.resample([32, 32] * u.pix)
    for obj in (m, new):
        obj.__dict__.pop("wcs", None)
    before = (set(m.__dict__), set(new.__dict__))
    run(sc.check_resample_footprint, m, new)
    run(sc.check_rotate_center, m, new, False)
    run(sc.check_submap, m, new)
    run(sc.check_disk_partition, m, True)
    run(sc.check_all_on_disk, m, True)
    run(sc.check_all_off_disk, m, True)
    assert (set(m.__dict__), set(new.__dict__)) == before


def test_fresh_agent_false_alarm_regressions():
    """Conditioning cases found by the fresh Sonnet 5.5 audit: valid inputs that must not alarm."""
    from sunpy.coordinates.utils import GreatArc
    from sunpy.physics.differential_rotation import solar_rotate_coordinate

    R = 695700 * u.km
    ob = get_earth("2020-01-01")
    hgs, hpc = HeliographicStonyhurst(obstime=ob.obstime), Helioprojective(observer=ob, obstime=ob.obstime)

    def point(lon, lat):
        return SkyCoord(lon * u.deg, lat * u.deg, R, frame=hgs).transform_to(hpc)

    step = (30 * u.km / R).to_value(u.one) * 57.29577951  # 30 km arc on the solar surface
    arc = GreatArc(point(20 + step, 10), point(20, 10 + step), center=point(20, 10))
    assert not run(arc.coordinates, np.linspace(0, 1, 11))

    t = Time("2020-08-01")
    near = SkyCoord(20 * u.deg, 3 * u.deg, 1.5 * R, frame=HeliographicStonyhurst, obstime=t)
    far = SkyCoord(100 * u.deg, -5 * u.deg, 50 * u.AU, frame=HeliographicStonyhurst, obstime=t + 1 * u.day)
    p = SkyCoord(80 * u.deg, 30 * u.deg, R, frame=HeliographicStonyhurst, obstime=t)
    assert not run(solar_rotate_coordinate, p.transform_to(Helioprojective(observer=near, obstime=t)), observer=far)

    pole = SkyCoord(10 * u.deg, 89.99999 * u.deg, R, frame=HeliographicStonyhurst, obstime=t)
    assert not run(solar_rotate_coordinate, pole.transform_to(Helioprojective(observer=get_earth(t), obstime=t)),
                   time=t + 5 * u.day)

    cen = SkyCoord(ob.lon, ob.lat, 0.5 * u.AU, frame=HeliographicStonyhurst, obstime=ob.obstime)
    coo = SkyCoord(np.linspace(-60, 60, 41) * u.arcsec, np.linspace(-40, 50, 41) * u.arcsec,
                   frame=Helioprojective, observer=ob, obstime=ob.obstime)

    def small_screen():
        with SphericalScreen(cen, radius=10000 * u.km):
            coo.make_3d()
    assert not run(small_screen)

    c = SkyCoord(100 * u.arcsec, 200 * u.arcsec, frame=Helioprojective, observer=ob, obstime=ob.obstime)
    for proj in ("MOL", "PAR", "HPX", "TSC", "CSC", "QSC"):
        assert not run(sunpy.map.make_fitswcs_header, (100, 100), c, scale=[2, 2] * u.arcsec / u.pix,
                       projection_code=proj)
