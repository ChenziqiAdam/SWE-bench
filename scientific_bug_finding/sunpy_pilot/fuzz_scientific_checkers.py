"""Curator-side false-positive fuzzing (SANITIZER.md 5.8, 8): random *valid* public-API inputs across
scale, conditioning and configuration. Any alarm is a candidate checker defect (or a real bug) and must
be adjudicated by reading the source; the revision log in LAW_CANDIDATES.md records the outcomes.

  python fuzz_scientific_checkers.py --seeds 0 1 2 [--n 40] [--stress 1.0]
Run with the instrumented sunpy on sys.path.
"""
import argparse
import json
import os
import sys
import tempfile
import warnings

LOG = tempfile.mktemp(suffix=".jsonl")
os.environ["SCIBENCH_TRIGGER_LOG"] = LOG
warnings.simplefilter("ignore")

import numpy as np  # noqa: E402
import astropy.units as u  # noqa: E402
from astropy.coordinates import SkyCoord  # noqa: E402
from astropy.time import Time  # noqa: E402

import sunpy._scientific_checkers as sc  # noqa: E402
import sunpy.map  # noqa: E402
from sunpy.coordinates import (Helioprojective, HeliographicCarrington, HeliographicStonyhurst,  # noqa: E402
                               SphericalScreen, get_earth, propagate_with_solar_surface, sun)
from sunpy.coordinates.ephemeris import get_body_heliographic_stonyhurst  # noqa: E402
from sunpy.coordinates.utils import GreatArc, get_heliocentric_angle, get_limb_coordinates  # noqa: E402
from sunpy.image.resample import resample  # noqa: E402
from sunpy.map.maputils import contains_limb, coordinate_is_on_solar_disk, is_all_off_disk, is_all_on_disk  # noqa: E402
from sunpy.physics.differential_rotation import differential_rotate, solar_rotate_coordinate  # noqa: E402
from sunpy.sun.models import differential_rotation  # noqa: E402

FAILS = []


def alarms():
    out = []
    if os.path.exists(LOG):
        out = [json.loads(line)["checker_id"] for line in open(LOG) if line.strip()]
        open(LOG, "w").close()
    return out


import time  # noqa: E402

SLOW = {}


def case(name, fn, desc):
    t0 = time.time()
    if os.environ.get("FUZZ_TRACE"):
        print("..", name, desc[:90], flush=True)
    try:
        fn()
        SLOW[name] = SLOW.get(name, 0.0) + (time.time() - t0)
    except Exception:  # invalid input for the production API: not a checker matter
        alarms()
        return
    a = alarms()
    if a:
        FAILS.append((name, sorted(set(a)), desc))


def rtime(rng, n=None):
    jd = rng.uniform(2415100, 2488000, size=n)
    return Time(jd, format="jd")


def log_uniform(rng, lo, hi):
    return 10 ** rng.uniform(np.log10(lo), np.log10(hi))


def rand_observer(rng, t):
    return HeliographicStonyhurst(rng.uniform(-180, 180) * u.deg, rng.uniform(-90, 90) * u.deg,
                                  log_uniform(rng, 1.2, 1e4) * u.R_sun if rng.random() < 0.5 else
                                  log_uniform(rng, 0.3, 5) * u.AU, obstime=t)


def rand_map(rng, stress):
    n = int(rng.integers(8, 70)); m = int(rng.integers(8, 70))
    scale = log_uniform(rng, 0.05, 400.0 * stress)
    t = rtime(rng)
    obs = rand_observer(rng, t) if rng.random() < 0.5 else get_earth(t)
    centre = rng.uniform(-1, 1, 2) * rng.choice([0, 100, 1000, 3000])
    c = SkyCoord(centre[0] * u.arcsec, centre[1] * u.arcsec, obstime=t, observer=obs, frame=Helioprojective)
    rot = rng.uniform(-180, 180) if rng.random() < 0.5 else 0.0
    ref = None if rng.random() < 0.5 else [rng.uniform(0, m - 1), rng.uniform(0, n - 1)] * u.pix
    hdr = sunpy.map.make_fitswcs_header(np.zeros((n, m)), c, reference_pixel=ref,
                                        scale=[scale, scale * rng.choice([1, 1, 1.3])] * u.arcsec / u.pix,
                                        rotation_angle=rot * u.deg)
    data = rng.uniform(1, 10, (n, m)) * log_uniform(rng, 1e-6, 1e6)
    if rng.random() < 0.3:
        data = data.astype(np.float32)
    return sunpy.map.Map(data, hdr), (n, m, scale, rot)


def fuzz(seed, n, stress):
    rng = np.random.default_rng(seed)
    for k in range(n):
        s = rng.integers(0, 10**9)
        r = np.random.default_rng(s)
        tag = f"seed={seed} case={k} s={s}"
        # ---- ephemeris
        for arr in (False, True):
            t = rtime(r, 4 if arr else None)
            for f in (sun.angular_radius, sun.earth_distance, sun.B0, sun.L0, sun.carrington_rotation_number,
                      sun.true_obliquity_of_ecliptic, sun.apparent_longitude, sun.apparent_rightascension,
                      sun.apparent_declination, sun.P):
                case(f.__name__, lambda f=f, t=t: f(t), f"{tag} t={t.iso if t.isscalar else t.iso[:2]}")
        case("crot_time", lambda: sun.carrington_rotation_time(float(r.uniform(700, 2500))), tag)
        case("crot_time_lon", lambda: sun.carrington_rotation_time(int(r.integers(700, 2500)), float(r.uniform(1, 360)) * u.deg), tag)
        t = rtime(r)
        for body in ("venus", "mars", "earth", "jupiter"):
            obs = get_earth(t) if r.random() < 0.6 else None
            case("hgs_body", lambda body=body, obs=obs: get_body_heliographic_stonyhurst(body, t, observer=obs), f"{tag} {body}")
        case("eclipse", lambda: sun.eclipse_amount(get_earth(t)), tag)
        te = Time(str(r.choice(["2024-04-08 18:17", "2017-08-21 18:26", "2023-10-14 17:59", "2015-03-20 09:46",
                                "2019-07-02 19:22", "2010-07-11 19:34"]))) + float(r.uniform(-4, 4)) * u.hr
        case("eclipse_near", lambda: sun.eclipse_amount(get_earth(te), moon_radius=str(r.choice(["IAU", "minimum"]))), f"{tag} {te.iso}")
        # ---- differential rotation model
        lat = r.uniform(-90, 90, size=int(r.integers(1, 6))) * u.deg
        dur = (log_uniform(r, 1e-4, 4000) * r.choice([-1, 1])) * u.day
        for model in ("howard", "snodgrass", "allen", "rigid"):
            for ft in ("sidereal", "synodic"):
                case("diffrot", lambda: differential_rotation(dur, lat, model=model, frame_time=ft), f"{tag} {model} {ft} dur={dur} lat={lat}")
        # ---- frames
        obs = rand_observer(r, t)
        m = int(r.integers(1, 6))
        tx = r.uniform(-1, 1, m) * log_uniform(r, 10, 3e4) * u.arcsec
        ty = r.uniform(-1, 1, m) * log_uniform(r, 10, 3e4) * u.arcsec
        pts = SkyCoord(tx, ty, frame=Helioprojective, observer=obs, obstime=t)
        case("make_3d", lambda: pts.make_3d(), f"{tag} obs={obs.radius} tx={tx} ty={ty}")
        case("on_disk", lambda: coordinate_is_on_solar_disk(pts), f"{tag} obs={obs.radius} tx={tx} ty={ty}")
        obs2 = rand_observer(r, t)
        case("hpc_hpc", lambda: pts.make_3d().transform_to(Helioprojective(observer=obs2, obstime=t)), f"{tag} o1={obs.radius} o2={obs2.radius}")
        case("hpc_hpc_2d", lambda: pts.transform_to(Helioprojective(observer=obs2, obstime=t)), f"{tag} o1={obs.radius} o2={obs2.radius}")
        case("helio_angle", lambda: get_heliocentric_angle(pts), f"{tag}")
        case("limb", lambda: get_limb_coordinates(obs, rsun=log_uniform(r, 1e4, 7e8) * u.km if r.random() < 0.3 else None) if False else get_limb_coordinates(obs, resolution=int(r.integers(4, 200))), f"{tag} obs={obs.radius}")
        p1 = SkyCoord(*(r.uniform(-900, 900, 2) * u.arcsec), frame=Helioprojective, observer=obs, obstime=t)
        p2 = SkyCoord(*(r.uniform(-900, 900, 2) * u.arcsec), frame=Helioprojective, observer=obs, obstime=t)
        case("great_arc", lambda: GreatArc(p1, p2, points=int(r.integers(3, 50))).coordinates(), f"{tag}")
        # ---- screens
        center = rand_observer(r, t) if r.random() < 0.5 else obs
        def screen():
            with SphericalScreen(center):
                pts.make_3d()
        case("spherical_screen", screen, f"{tag} obs={obs.radius} center={center.radius}")

        def screen_rot():
            with SphericalScreen(center), propagate_with_solar_surface():
                later = Helioprojective(pts.Tx, pts.Ty, observer=obs, obstime=t + float(r.uniform(-10, 10)) * u.day)
                later.transform_to(Helioprojective(observer=obs, obstime=t))
        case("screen_diffrot", screen_rot, f"{tag} obs={obs.radius} center={center.radius}")
        # ---- rotated coordinates
        on = SkyCoord(*(r.uniform(-900, 900, 2) * u.arcsec), frame=Helioprojective, observer="earth", obstime=t)
        dt = r.uniform(-30, 30) * u.day
        case("solar_rotate", lambda: solar_rotate_coordinate(on, observer=get_body_heliographic_stonyhurst("earth", t + dt)), f"{tag} dt={dt}")
        case("solar_rotate_t", lambda: solar_rotate_coordinate(on, time=t + dt), f"{tag} dt={dt}")
        # ---- maps
        smap, mdesc = rand_map(r, stress)
        d = f"{tag} map={mdesc}"
        ny, nx = smap.data.shape
        case("resample", lambda: smap.resample([int(r.integers(2, 120)), int(r.integers(2, 120))] * u.pix, method=str(r.choice(["linear", "nearest"]))), d)
        dims = [int(r.integers(1, 5)), int(r.integers(1, 5))]
        off = [int(r.integers(0, 3)), int(r.integers(0, 3))]
        case("superpixel", lambda: smap.superpixel(dims * u.pix, offset=off * u.pix), f"{d} dims={dims} off={off}")
        ang = r.uniform(-180, 180)
        sc_ = float(r.choice([1.0, 1.0, 0.7, 1.5]))
        case("rotate", lambda: smap.rotate(ang * u.deg, scale=sc_, order=int(r.choice([0, 1, 3]))), f"{d} ang={ang} scale={sc_}")
        x0, y0 = int(r.integers(0, nx - 2)), int(r.integers(0, ny - 2))
        case("submap", lambda: smap.submap([x0, y0] * u.pix, top_right=[int(r.integers(x0 + 1, nx)), int(r.integers(y0 + 1, ny))] * u.pix), d)
        for fn in (is_all_on_disk, is_all_off_disk, contains_limb):
            case(fn.__name__, lambda fn=fn: fn(smap), d)
        if mdesc[2] >= 10.0 and max(smap.data.shape) <= 48:  # padding grows with (shift / pixel scale)
            case("differential_rotate", lambda: differential_rotate(smap, time=float(r.uniform(-1, 1)) * u.day), d)
        smap.wcs
        # ---- kernels
        shape = (int(r.integers(2, 60)), int(r.integers(2, 60)))
        img = r.uniform(-1, 1, shape) * log_uniform(r, 1e-8, 1e8)
        newd = (int(r.integers(1, 100)), int(r.integers(1, 100)))
        for meth in ("linear", "nearest", "spline"):
            case("image_resample", lambda meth=meth: resample(img, newd, method=meth, center=bool(r.integers(0, 2)), minusone=bool(r.integers(0, 2))), f"{tag} {shape}->{newd} {meth}")
        # ---- header / WCS
        for fcls in (Helioprojective, HeliographicStonyhurst):
            c = SkyCoord(r.uniform(-3000, 3000) * u.arcsec if fcls is Helioprojective else r.uniform(-180, 180) * u.deg,
                         r.uniform(-1000, 1000) * u.arcsec if fcls is Helioprojective else r.uniform(-80, 80) * u.deg,
                         obstime=t, observer="earth", frame=fcls) if fcls is Helioprojective else \
                SkyCoord(r.uniform(-180, 180) * u.deg, r.uniform(-80, 80) * u.deg, obstime=t, frame=fcls)
            sc_pix = log_uniform(r, 0.01, 300) * u.arcsec / u.pix
            case("fits_header", lambda: sunpy.map.make_fitswcs_header((int(r.integers(5, 300)), int(r.integers(5, 300))), c,
                                                                       reference_pixel=r.uniform(0, 100, 2) * u.pix,
                                                                       scale=[sc_.value, sc_.value] * sc_.unit,
                                                                       projection_code=str(r.choice(["TAN", "CAR", "ARC"]))) if fcls is Helioprojective else
                 sunpy.map.make_fitswcs_header((100, 100), c, scale=[sc_.value / 3600] * 2 * u.deg / u.pix, projection_code="CAR"), f"{tag} {fcls.__name__}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--stress", type=float, default=1.0)
    a = ap.parse_args()
    for sd in a.seeds:
        fuzz(sd, a.n, a.stress)
    print(f"{len(a.seeds)} seeds x {a.n} cases: {len(FAILS)} alarming calls")
    byid = {}
    for name, ids, desc in FAILS:
        for i in ids:
            byid.setdefault(i, []).append((name, desc))
    for i, v in sorted(byid.items()):
        print(i, len(v))
        for name, desc in v[:3]:
            print("   ", name, desc[:300])
    print("SWALLOWED", len(sc.SWALLOWED))
    print("seconds by call:", {k: round(v, 1) for k, v in sorted(SLOW.items(), key=lambda kv: -kv[1])[:8]})
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
