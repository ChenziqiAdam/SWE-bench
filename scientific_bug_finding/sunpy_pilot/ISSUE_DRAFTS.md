# SunPy issue drafts (not filed)

Tracker searched 2026-10-08 (`gh search issues --repo sunpy/sunpy`, terms: make_3d, coordinate_is_on_solar_disk, resample,
superpixel, GONG, rotate, eclipse_amount, propagate_with_solar_surface, screen). No open or closed issue covers these.
Related, different problem: #6570 (closed; `resample`/`superpixel` changed only `PCi_j`, not `CDELTi`). Both repros were
re-run on pristine upstream `87d916c65` (identical output to the instrumented tree).

## Draft 1: `Helioprojective.make_3d` returns a negative distance for look directions pointing away from the Sun

A 2D helioprojective coordinate whose line of sight points away from the Sun (|Tx| near 180 deg) gets a finite negative
distance from `make_3d()`: the ray's backward extension meets the Sun's far side. The point is behind the observer, on
the far hemisphere, and `coordinate_is_on_solar_disk` says False for the same coordinate, so the two disagree.

```python
import astropy.units as u
from astropy.coordinates import SkyCoord
from sunpy.coordinates import Helioprojective, HeliographicStonyhurst
from sunpy.map import coordinate_is_on_solar_disk
c = SkyCoord(180*u.deg, 0*u.deg, frame=Helioprojective(observer='earth', obstime='2020-04-08'))
c3 = c.make_3d()
print(c3.distance.to(u.AU))                                                  # -1.0059 AU
print(c3.transform_to(HeliographicStonyhurst(obstime='2020-04-08')).radius)  # 0.00465 AU = 1 R_sun
print(coordinate_is_on_solar_disk(c))                                        # False
```

Expected: NaN, as for any off-disk direction. Cause: `cos(Ty)cos(Tx) < 0` makes the discriminant positive and the "near"
root `d = D cos(alpha) - sqrt(...)` negative. Fix: return NaN when `d < 0` (equivalently `cos(alpha) <= 0`). Affected cone:
within arcsin(Rsun/D) of the anti-solar point (about 0.27 deg at 1 AU, |Tx| > 174 deg at 9.9 R_sun, most of the back
hemisphere at 1.0001 R_sun). Downstream: `solar_rotate_coordinate` of such a coordinate does not round-trip.

## Draft 2: `Map.resample`, `superpixel` and `rotate` do not keep the field of view when the map's scale is not stored in `CDELTi`/`PCi_j` as assumed

The three methods rescale only the `cdelt`/`cd`/`pc` keys of the metadata. That is wrong whenever the map's pixel scale
comes from elsewhere or the keys are partly absent:

1. `GONGHalphaMap` and `GONGMagnetogramMap` override `scale` (from `SOLAR-R`/`SEMIDIAM` and `FNDLMBMI/MA`). After `resample`
   the scale is unchanged while the pixel count changes, so the field of view shrinks by the resample factor.
   ```python
   from sunpy.data.test import get_dummy_map_from_header
   g = get_dummy_map_from_header('gong_halpha.header')      # 2048x2048
   r = g.resample([1024, 1024]*u.pix)
   print(g.scale.axis1, r.scale.axis1)                       # 1.0795 arcsec/pix both (expected 2.159 for r)
   print(g.wcs.pixel_to_world(2047.5, 2047.5).Tx, r.wcs.pixel_to_world(1023.5, 1023.5).Tx)   # 1105.9 vs 553.0 arcsec
   ```
   `superpixel` fails the same way; `rotate(scale=1.5)` also (centre moves hundreds of pixels). On HMI/MDI CEA synoptic maps
   (`CUNIT2='Sine Latitude'`) `rotate(scale!=1)` writes `cdelt2` in degrees that the `scale` property multiplies by 180/pi again.
2. A map with `CDi_j` only (no `CDELTi`): `rotate(angle=0)` deletes `CDi_j`, writes `PCi_j`, and writes `CDELTi` only when
   `scale != 1`, so the scale silently changes (2 -> 1 arcsec/pix in the reproduction; 14 pixel shift of the array centre).
3. `PCi_j` headers that omit `PC1_1` (FITS default 1): the off-diagonals are not rescaled (`'pc1_1' in meta` test); with
   `PC1_1`/`PC2_2` but no off-diagonals: `KeyError: 'pc1_2'`; without `CDELTi` (FITS default 1): the scale stays 1.

Reproduction of 2 on pristine upstream:
```python
import numpy as np, astropy.units as u, sunpy.map
from astropy.coordinates import SkyCoord
from sunpy.coordinates import frames
ref = SkyCoord(0*u.arcsec, 0*u.arcsec, obstime='2020-01-01', observer='earth', frame=frames.Helioprojective)
h = sunpy.map.make_fitswcs_header((50, 60), ref, reference_pixel=[0, 0]*u.pix, scale=[2, 2]*u.arcsec/u.pix)
for k in ['cdelt1', 'cdelt2', 'pc1_1', 'pc1_2', 'pc2_1', 'pc2_2']: h.pop(k)
h.update({'cd1_1': 2.0, 'cd1_2': 0.0, 'cd2_1': 0.0, 'cd2_2': 2.0})
m = sunpy.map.Map(np.zeros((50, 60)), h)
print(m.scale.axis1, m.rotate(angle=0*u.deg, missing=0).scale.axis1)    # 2 arcsec/pix -> 1 arcsec/pix
```
Suggested direction: derive the new scale from the map's own `scale`/`rotation_matrix` and write it back through one
helper (or let source classes override a hook), rather than editing individual keys.
