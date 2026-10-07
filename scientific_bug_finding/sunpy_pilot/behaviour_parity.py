"""Non-disruption evidence (SANITIZER.md 5.5): sha256 over deterministic public-API outputs and
the global NumPy RNG state must be identical on the pristine base, the instrumented tree with
the logger unset, and the instrumented tree with the logger on.

  python behaviour_parity.py --pristine <dir> --instrumented <dir> --python <abs python>
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import warnings

CHILD = r"""
import hashlib, json, sys, warnings
warnings.simplefilter("ignore")
import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
import sunpy.map
from sunpy.coordinates import (Helioprojective, HeliographicStonyhurst, SphericalScreen, get_earth,
                               propagate_with_solar_surface, sun)
from sunpy.coordinates.ephemeris import get_body_heliographic_stonyhurst
from sunpy.coordinates.utils import GreatArc, get_heliocentric_angle, get_limb_coordinates
from sunpy.image.resample import resample
from sunpy.map.maputils import contains_limb, coordinate_is_on_solar_disk, is_all_off_disk, is_all_on_disk
from sunpy.physics.differential_rotation import differential_rotate, solar_rotate_coordinate
from sunpy.sun.models import differential_rotation

np.random.seed(12345)  # global state must be deterministic so that its final value is comparable
h = hashlib.sha256()
n = 0
def feed(x):
    global n
    n += 1
    if hasattr(x, "jd1"):
        x = np.stack([x.jd1, x.jd2])
    elif hasattr(x, "cartesian"):
        x = x.cartesian.xyz.value
    elif hasattr(x, "data") and hasattr(x, "meta"):
        h.update(json.dumps({k: repr(v) for k, v in sorted(x.meta.items())}).encode())
        x = np.ma.getdata(x.data)
    elif hasattr(x, "value"):
        x = x.value
    a = np.ascontiguousarray(np.asarray(x, dtype=np.float64))
    h.update(a.tobytes())

t = Time("2020-04-08 12:00:00"); ts = Time(["2001-02-03", "2012-06-06", "2021-11-04"])
for f in (sun.angular_radius, sun.earth_distance, sun.B0, sun.P, sun.L0, sun.carrington_rotation_number,
          sun.true_obliquity_of_ecliptic, sun.apparent_longitude, sun.apparent_rightascension,
          sun.apparent_declination, sun.true_longitude, sun.true_latitude):
    feed(f(t)); feed(f(ts))
feed(sun.carrington_rotation_time(2242)); feed(sun.carrington_rotation_time(2000, 270 * u.deg))
feed(get_body_heliographic_stonyhurst("earth", t)); feed(get_body_heliographic_stonyhurst("venus", t, observer=get_earth(t)))
feed(sun.eclipse_amount(get_earth("2024-04-08 18:17:00")))
lat = np.linspace(-80, 80, 9) * u.deg
for model in ("howard", "snodgrass", "allen", "rigid"):
    for ft in ("sidereal", "synodic"):
        feed(differential_rotation(2 * u.day, lat, model=model, frame_time=ft))
pts = SkyCoord([0, 300, 600, 900, 1200] * u.arcsec, [0, 100, -200, 300, 0] * u.arcsec, frame=Helioprojective, observer="earth", obstime=t)
feed(pts.make_3d()); feed(coordinate_is_on_solar_disk(pts))
feed(pts.transform_to(Helioprojective(observer=get_body_heliographic_stonyhurst("mars", t), obstime=t)))
on = SkyCoord([0, 300] * u.arcsec, [0, 100] * u.arcsec, frame=Helioprojective, observer="earth", obstime=t)
feed(get_heliocentric_angle(on)); feed(get_limb_coordinates(get_earth(t)))
a = SkyCoord(100 * u.arcsec, 50 * u.arcsec, frame=Helioprojective, observer="earth", obstime=t)
b = SkyCoord(-400 * u.arcsec, 200 * u.arcsec, frame=Helioprojective, observer="earth", obstime=t)
feed(GreatArc(a, b).coordinates())
hp = Helioprojective(range(7) * u.arcsec * 319, [0] * 7 * u.arcsec, observer="earth", obstime="2020-04-08")
with SphericalScreen(hp.observer):
    feed(hp.make_3d())
with SphericalScreen(hp.observer), propagate_with_solar_surface():
    feed(Helioprojective(hp.Tx, hp.Ty, observer="earth", obstime="2020-04-10").transform_to(hp))
c = SkyCoord(-570 * u.arcsec, 120 * u.arcsec, obstime=t, observer="earth", frame=Helioprojective)
feed(solar_rotate_coordinate(c, observer=get_body_heliographic_stonyhurst("earth", t + 6 * u.day)))
feed(solar_rotate_coordinate(c, time=t + 25 * u.hr))
def mk(n=64, scale=40.0, centre=(0, 0), rot=0.0):
    cc = SkyCoord(centre[0] * u.arcsec, centre[1] * u.arcsec, obstime="2020-04-08", observer="earth", frame=Helioprojective)
    hdr = sunpy.map.make_fitswcs_header(np.zeros((n, n)), cc, scale=[scale, scale] * u.arcsec / u.pix, rotation_angle=rot * u.deg)
    return sunpy.map.Map(np.random.default_rng(0).uniform(1, 10, (n, n)), hdr)
m = mk()
feed(m); feed(m.resample([32, 32] * u.pix)); feed(m.resample([100, 80] * u.pix, method="nearest"))
feed(m.superpixel([2, 2] * u.pix)); feed(m.superpixel([3, 2] * u.pix, offset=[1, 1] * u.pix))
feed(m.rotate(20 * u.deg)); feed(m.rotate(30 * u.deg, scale=1.2, order=1))
feed(m.submap([10, 12] * u.pix, top_right=[40, 50] * u.pix))
feed(differential_rotate(m, time=2 * u.day))
for mm in (m, mk(n=40, scale=10), mk(centre=(3000, 0)), mk(n=64, scale=100)):
    feed(np.array([bool(is_all_on_disk(mm)), bool(is_all_off_disk(mm)), bool(contains_limb(mm))]))
img = np.random.default_rng(1).uniform(size=(20, 30))
for kw in (dict(method="linear", center=True), dict(method="nearest"), dict(method="spline")):
    feed(resample(img, (10, 15), **kw))
feed(resample(img, (40, 60), method="linear", minusone=True))
st = np.random.get_state()
h.update(st[1].tobytes()); h.update(str(st[2:]).encode())
print(h.hexdigest(), n)
"""


def child(pythonpath, python, log=None):
    env = dict(os.environ, PYTHONPATH=pythonpath)
    env.pop("SCIBENCH_TRIGGER_LOG", None)
    if log:
        env["SCIBENCH_TRIGGER_LOG"] = log
    out = subprocess.run([python, "-c", CHILD], env=env, capture_output=True, text=True, cwd=tempfile.gettempdir())
    if out.returncode:
        sys.exit(out.stderr[-3000:])
    return out.stdout.strip().split()[-2:]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pristine", required=True)
    p.add_argument("--instrumented", required=True)
    p.add_argument("--python", required=True)
    a = p.parse_args()
    log = tempfile.mktemp(suffix=".jsonl")
    res = {"pristine": child(a.pristine, a.python),
           "instrumented_off": child(a.instrumented, a.python),
           "instrumented_on": child(a.instrumented, a.python, log)}
    for k, v in res.items():
        print(f"{k:18s} {v[0]}  ({v[1]} outputs)")
    alarms = [json.loads(line)["checker_id"] for line in open(log)] if os.path.exists(log) else []
    print("alarms in the 'on' run:", sorted(set(alarms)) or "none")
    same = len({v[0] for v in res.values()}) == 1
    print("IDENTICAL" if same else "DIFFERENT")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
