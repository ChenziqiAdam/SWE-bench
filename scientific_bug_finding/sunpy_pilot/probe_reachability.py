"""Curator-side observation-reachability probe (SANITIZER.md 8): every checker must be
*evaluated* (predicate executed) by at least one valid public-API call. No alarm is required.

Usage: python probe_reachability.py [--ids]   (run with the instrumented sunpy on sys.path)
"""
import json
import os
import sys
import tempfile
import warnings

LOG = tempfile.mktemp(suffix=".jsonl")
os.environ["SCIBENCH_TRIGGER_LOG"] = LOG
os.environ["SCIBENCH_CHECKER_DEBUG"] = "1"
warnings.simplefilter("ignore")

import numpy as np  # noqa: E402
import astropy.units as u  # noqa: E402
from astropy.coordinates import SkyCoord  # noqa: E402
from astropy.time import Time  # noqa: E402

import sunpy._scientific_checkers as sc  # noqa: E402
import sunpy.map  # noqa: E402
from sunpy.coordinates import (Helioprojective, HeliographicStonyhurst, SphericalScreen,  # noqa: E402
                               get_earth, propagate_with_solar_surface, sun)
from sunpy.coordinates.ephemeris import get_body_heliographic_stonyhurst  # noqa: E402
from sunpy.coordinates.utils import GreatArc, get_heliocentric_angle, get_limb_coordinates  # noqa: E402
from sunpy.image.resample import resample  # noqa: E402
from sunpy.map.maputils import (contains_limb, coordinate_is_on_solar_disk, is_all_off_disk,  # noqa: E402
                                is_all_on_disk)
from sunpy.physics.differential_rotation import differential_rotate, solar_rotate_coordinate  # noqa: E402
from sunpy.sun.models import differential_rotation  # noqa: E402


def make_map(n=64, scale=40.0, centre=(0, 0), date="2020-04-08", rotation=0.0, observer="earth"):
    c = SkyCoord(centre[0] * u.arcsec, centre[1] * u.arcsec, obstime=date, observer=observer,
                 frame=Helioprojective)
    hdr = sunpy.map.make_fitswcs_header(np.zeros((n, n)), c, scale=[scale, scale] * u.arcsec / u.pix,
                                        rotation_angle=rotation * u.deg)
    rng = np.random.default_rng(0)
    data = rng.uniform(1, 10, (n, n))
    return sunpy.map.Map(data, hdr)


def run():
    t = Time("2020-04-08 12:00:00")
    ts = Time(["2001-02-03", "2012-06-06", "2021-11-04"])
    # ephemeris
    sun.angular_radius(t); sun.earth_distance(ts); sun.B0(ts); sun.P(t); sun.L0(t)
    sun.carrington_rotation_number(ts); sun.carrington_rotation_time(2242)
    sun.carrington_rotation_time(2000, 270 * u.deg)
    sun.true_obliquity_of_ecliptic(t); sun.apparent_longitude(t)
    sun.apparent_rightascension(t); sun.apparent_declination(ts)
    get_body_heliographic_stonyhurst("earth", t)
    get_body_heliographic_stonyhurst("venus", t, observer=get_earth(t))
    sun.eclipse_amount(get_earth("2024-04-08 18:17:00"))
    # differential rotation (model)
    lat = np.linspace(-60, 60, 7) * u.deg
    for model in ("howard", "snodgrass", "allen", "rigid"):
        for ft in ("sidereal", "synodic"):
            differential_rotation(2 * u.day, lat, model=model, frame_time=ft)
    # frames
    pts = SkyCoord([0, 300, 600, 900, 1200] * u.arcsec, [0, 100, -200, 300, 0] * u.arcsec,
                   frame=Helioprojective, observer="earth", obstime=t)
    pts.make_3d(); coordinate_is_on_solar_disk(pts)
    other = get_body_heliographic_stonyhurst("mars", t)
    pts.transform_to(Helioprojective(observer=other, obstime=t))
    on = SkyCoord([0, 300] * u.arcsec, [0, 100] * u.arcsec, frame=Helioprojective, observer="earth", obstime=t)
    get_heliocentric_angle(on)
    get_limb_coordinates(get_earth(t))
    a = SkyCoord(100 * u.arcsec, 50 * u.arcsec, frame=Helioprojective, observer="earth", obstime=t)
    b = SkyCoord(-400 * u.arcsec, 200 * u.arcsec, frame=Helioprojective, observer="earth", obstime=t)
    GreatArc(a, b).coordinates()
    # screens
    hp = Helioprojective(range(7) * u.arcsec * 319, [0] * 7 * u.arcsec, observer="earth", obstime="2020-04-08")
    with SphericalScreen(hp.observer):
        hp.make_3d()
    with SphericalScreen(hp.observer), propagate_with_solar_surface():
        later = Helioprojective(hp.Tx, hp.Ty, observer="earth", obstime="2020-04-10")
        later.transform_to(hp)
    # rotated coordinates
    c = SkyCoord(-570 * u.arcsec, 120 * u.arcsec, obstime=t, observer="earth", frame=Helioprojective)
    solar_rotate_coordinate(c, observer=get_body_heliographic_stonyhurst("earth", t + 6 * u.day))
    solar_rotate_coordinate(c, time=t + 25 * u.hr)
    # maps
    m = make_map()
    m.resample([32, 32] * u.pix); m.resample([100, 80] * u.pix, method="nearest")
    m.superpixel([2, 2] * u.pix); m.superpixel([3, 2] * u.pix, offset=[1, 1] * u.pix)
    m.rotate(20 * u.deg); m.rotate(30 * u.deg, scale=1.2, order=1)
    m.submap([10, 12] * u.pix, top_right=[40, 50] * u.pix)
    is_all_on_disk(make_map(n=40, scale=10)); is_all_off_disk(make_map(centre=(3000, 0)))
    contains_limb(m); contains_limb(make_map(n=64, scale=100))
    contains_limb(make_map(n=40, scale=10)); contains_limb(make_map(n=30, scale=120))
    contains_limb(make_map(centre=(3000, 0)))
    is_all_off_disk(make_map(n=64, scale=100, centre=(0, 0)))
    # kernels
    img = np.random.default_rng(1).uniform(size=(20, 30))
    resample(img, (10, 15), method="linear", center=True)
    resample(img, (10, 15), method="nearest")
    resample(img, (40, 60), method="linear", minusone=True)
    # wcs frame mapping
    m.wcs
    differential_rotate(m, time=2 * u.day)


def main():
    run()
    from sunpy.sun import constants  # noqa: F401
    ids = sorted(json.load(open(os.path.join(os.path.dirname(__file__), "sanitizers.json")))["sanitizers"][i]["id"]
                 for i in range(0)) if False else None
    reached = dict(sc.REACHED)
    fired = {}
    if os.path.exists(LOG):
        for line in open(LOG):
            k = json.loads(line)["checker_id"]
            fired[k] = fired.get(k, 0) + 1
    print("REACHED", json.dumps(reached, indent=0, sort_keys=True))
    print("FIRED (natural, audit data)", json.dumps(fired, sort_keys=True))
    print("SWALLOWED", len(sc.SWALLOWED))
    for tb in sc.SWALLOWED[:6]:
        print(tb)
    print("n_reached", len(reached))


if __name__ == "__main__":
    main()
