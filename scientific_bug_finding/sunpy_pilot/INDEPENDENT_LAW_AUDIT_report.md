# Independent audit of seven SunPy laws

Repository: pristine upstream at `87d916c65` (nothing under `sunpy/` was modified).
Environment: Python from `sp_venv`, scipy 1.18.1, numpy 2.5.3, `PYTHONPATH=repo`.
All scripts are in `repo/audit_work/`. `mpmath` is not installed, so the high-precision references use
`decimal` at 60 digits (`hp.py`: Machin π, Taylor cos/sin, `Decimal.sqrt`). Each float64 input is converted exactly.

| Law | Is the law correct? | Does the library satisfy it? | Key number |
|---|---|---|---|
| FRM-001 `make_3d` near surface | Law correct | **Library bug**: look directions within the Sun's angular radius of the *anti*-Sun point get a negative distance, which puts the point on the far hemisphere | Earth observer, `(Tx,Ty)=(180°,0°)`: `distance = −1.0059 AU`, `D − d cosα = −rsun`. On-disk inputs: max `|r−rsun|/tol = 0.017` |
| FRM-002 on-disk ⇔ finite `make_3d` | Law correct (read "line of sight" as the forward ray) | **Library bug**, the same `make_3d` defect. `coordinate_is_on_solar_disk` itself is right | 99/4000 random all-sky directions disagree for Earth, 1922/4000 for an observer at 1.0001 R☉. 0 disagreements on about 30k on-disk and near-limb points |
| SCR-001 spherical screen, far root | Law correct; tolerance is achievable. The `tol` in `d ≥ C·u − tol` is never defined | **Library numerical defect** (catastrophic cancellation in the quadratic formula) | Screen of 1.5 R☉ centred on the Sun, observer at 160 AU: max dev 116 m = **83.5× tol**. A stable formula gives 4×10⁻⁴× tol |
| MAP-001 `resample` keeps the FOV | Law correct (add "integer dimensions" to Pre) | **Library bug** for some valid headers and source classes | GONG H-α/magnetogram: pixel scale not updated (FOV shrinks by the resample factor). PC without CDELT: 28 px. PC without PC1_1: 13 px. PC without PC1_2: `KeyError`. Standard headers: ≤1.6×10⁻¹² px |
| MAP-002 `superpixel` footprint | Law correct (state that dims/offset are `int()`-truncated; add "finite") | **Library bug**, same headers as MAP-001 | Same failures as MAP-001. Standard headers: ≤1.6×10⁻¹² px |
| MAP-003 no new extrema | Law correct (the Pre must count zero-weight cell corners as "used") | Library OK | 0 of 3014 in-range random cases (float64 and float32 input, magnitudes 10⁻³⁰…10³⁰) went outside [min,max], not even by 1 ulp |
| MAP-004 `rotate` keeps the array-centre coordinate | Law correct | **Library bug** for CD-only headers, and for GONG and CEA synoptic maps when `scale≠1` | CD-only header, `scale=1`: centre moves **14 px**. GONG H-α at `scale=1.5`: 674 px. HMI synoptic at `scale=1.5`: centre becomes NaN. Standard headers: ≤3.6×10⁻¹³ px |

---

## FRM-001 — `Helioprojective.make_3d`

**Derivation.** Take the observer O at the origin and Sun centre S with |S| = D. Along a ray with unit vector u (u·Ŝ = cosα), the point P = d·u satisfies |P − S|² = D² + d² − 2Dd cosα. Setting this equal to rsun² gives
d = D cosα ∓ √(rsun² − D² sin²α). The near root is the minus sign. P is on the hemisphere facing O when (P − S)·(O − S) ≥ 0, which simplifies to D − d cosα ≥ 0. The law is correct.

**Tolerance.** The discriminant D²cos²α − D² + rsun² cancels catastrophically. Its absolute error is about eps·D². That makes the error in d about eps·D²/(2√Δ), and the resulting error in r about eps·D²/(2 rsun), including exactly at the limb. So `1e-9 rsun + 64 eps D²/rsun` is a sound bound.

**Results on valid on-disk inputs** (`frm.py`, `frm_extra.py`). I used 4000–6000 directions per observer, half of them within 10⁻¹⁶…10⁻³ (relative) of the limb. Observers: Earth; a PSP-like observer at 9.86 R☉; 1.0001 R☉; 1+10⁻⁹ R☉; 160 AU; 10⁴ AU; a Carrington-frame observer at 0.3 AU. I also used `rsun` = 696342 km and 2×10⁶ km. The worst `|r − rsun|/tol` was **0.017**, and the hemisphere check always held.

**Library violation.** `cos_alpha = cos(Ty)·cos(Tx)` can be negative. For a back-facing direction within arcsin(rsun/D) of the anti-solar point, the discriminant is positive. The "near" formula then returns d = D cosα − √Δ < 0. A negative distance places the point behind the observer, on the Sun's far hemisphere: r = rsun is satisfied, but D − d cosα ≈ −rsun. `make_3d` should return NaN for any direction with cosα ≤ 0 (or whenever d < 0).

```python
import astropy.units as u
from astropy.coordinates import SkyCoord
from sunpy.coordinates import Helioprojective, HeliographicStonyhurst
c = SkyCoord(180*u.deg, 0*u.deg, frame=Helioprojective(observer='earth', obstime='2020-04-08'))
c3 = c.make_3d()
print(c3.distance.to(u.AU))                                        # -1.0059 AU (should be NaN)
print(c3.transform_to(HeliographicStonyhurst(obstime='2020-04-08')).radius)  # 695700 km: a far-side point
```

For observers near the Sun the affected cone is large. At 9.86 R☉ it covers |Tx| ≳ 174°. At 1.0001 R☉ almost the whole back hemisphere is affected.

**Wording / precondition.**
- Add "float64 (or wider) Tx/Ty" to Pre, or scale the tolerance with the input dtype. With float32 Tx/Ty, `make_3d` computes `cos_alpha` in float32. The worst residual was **1.6×10⁶ × tol** (about 2000 km off the surface). SunPy emits a warning for this input, so this is documented behaviour, not a bug.
- Optional: state explicitly that d ≥ 0.

## FRM-002 — `coordinate_is_on_solar_disk`

The predicate is `arccos(cos Tx cos Ty) ≤ arcsin(rsun/D)`. arcsin(rsun/D) is the correct tangent-line angular radius. The predicate is correct, and the law is correct if "intersects" means the forward ray.

**Is the 1e-6 rad limb margin enough?** Two error sources matter near the limb:
- Mis-classification in `make_3d` needs δ ≲ eps·D/rsun.
- The arccos error at the limb is about eps·D/rsun rad.

Both stay below 10⁻⁶ rad for every D at which the solar disk is wider than the margin, so the margin is sufficient.

**Results.** There were 0 disagreements away from the limb on every on-disk and near-limb set, for all observers above (including `rsun` = 2×10⁶ km and a Carrington observer). Every disagreement came from the FRM-001 back-facing defect: the predicate says False, while `make_3d` returns a finite negative distance. The reproduction is the snippet above plus `coordinate_is_on_solar_disk(c)` → `False`. **Classification:** library bug in `make_3d`, not in the predicate.

## SCR-001 — `SphericalScreen.calculate_distance`

**Derivation.** |d·u − C|² = R² gives d = C·u ± √((C·u)² − |C|² + R²). The far root (plus sign) gives d − C·u = √Δ ≥ 0, which matches the code and the law. The law is correct.

**Precision.** SunPy forms (C·u)² − |C|² + R². This cancels with absolute error about eps·|C|², so the error in |du − C| reaches about eps·|C|²/R near grazing incidence. The law's bound is 1e-9 R + 64 eps |C|. That bound is exceeded once |C|/R ≳ 10³:

| Case (`scr.py`) | |C|/R | max dev / tol |
|---|---|---|
| Screen centred on observer (default) | ~0 | 5×10⁻⁹ |
| Sun centre, R = 2 R☉, Earth observer | 108 | 0.0034 |
| Sun centre, R = 20 R☉, observer at 160 AU | 1.7×10³ | 0.68 |
| Sun centre, R = 0.05 R☉, Earth observer | 4.3×10³ | **4.6** |
| Sun centre, R = 1.5 R☉, observer at 160 AU | 2.3×10⁴ | **88.9** (116 m) |

`scr_stable.py` uses the cancellation-free form d = C·u + √(R² − |C×u|²) on the same inputs. Its worst residual is **4×10⁻⁴ × tol**. It also returns finite distances for 2850/3000 grazing rays, where SunPy returns 2063/3000; the other 787 are spurious NaNs. So the tolerance is achievable, and the excess is a (physically small) accuracy defect in the library.

Reproduction (public API):
```python
import astropy.units as u
from astropy.coordinates import SkyCoord
from sunpy.coordinates import HeliographicStonyhurst, Helioprojective, SphericalScreen
t = '2020-04-08'
obs = HeliographicStonyhurst(-40*u.deg, 30*u.deg, 160*u.AU, obstime=t)
scr = SphericalScreen(SkyCoord(HeliographicStonyhurst(0*u.deg, 0*u.deg, 0*u.km, obstime=t)),
                      radius=1.5*695700*u.km)
# distance = scr.calculate_distance(Helioprojective(Tx, Ty, observer=obs, obstime=t))
# For directions grazing the screen, |d u - C| - R reaches ~116 m (tol ~1.4 m); see scr_stable.py
```

**Wording.**
1. Define the `tol` in "d < C·u − tol". About 64 eps |C| is sufficient: the observed minimum of d − C·u was −2.4×10⁻⁸ km at |C| = 1 AU.
2. To keep the textbook quadratic formula (as FRM-001 implicitly does for `make_3d`), relax the bound to 1e-9 R + 64 eps max(|C|, |C|²/R). I recommend keeping the tight law and fixing the library instead.

## MAP-001 — `GenericMap.resample`

**Derivation.** The pixel→intermediate map is affine: x = diag(cdelt)·PC·(p − crpix). Resampling by s_i per axis maps old pixel p to new pixel q via p + ½ = s(q + ½). The FOV is preserved exactly when:
- cdelt_i → s_i·cdelt_i,
- PC_ij → PC_ij·s_j/s_i,
- CD_ij → CD_ij·s_j,
- crpix → (crpix₀ + ½)/s + ½.

The code implements these formulas, so the law is correct when n/s is an integer.

**Results.** Standard headers (CDELT+PC with unequal pixels, CROTA2 with unequal CDELT, CD-only, HGS-CAR, and all 2-D header-only test files shipped in `sunpy/data/test`, including HMI/MDI CEA synoptic): max corner move 1.6×10⁻¹² old px.

**Library violations** (`maps.py`, `headers.py`, `repro_map.py`):
1. **`GONGHalphaMap` and `GONGMagnetogramMap`.** Their `scale` property comes from `SOLAR-R`/`SEMIDIAM` and `FNDLMBMI`/`FNDLMBMA`, so updating `cdelt` has no effect. After `resample` to half size, `scale` is still 1.0795″/px, so the FOV halves (853 px corner move on the test map).
   ```python
   from sunpy.data.test import get_dummy_map_from_header
   g = get_dummy_map_from_header('gong_halpha.header')     # 2048x2048, 1.0795"/px
   print(g.resample([1024, 1024]*u.pix).scale)              # still 1.0795"/px (should be 2.159)
   ```
2. **PC header without CDELT** (FITS default CDELT = 1). Only the PC off-diagonal ratios are rescaled; the scale is left at 1. Corner move: 19–28 px.
3. **PC header with PC1_2/PC2_1 but no PC1_1** (FITS default 1). The code tests `'pc1_1' in meta`, so the off-diagonals are never rescaled. Corner move: 7.6–13 px when s_x ≠ s_y.
4. **PC header with PC1_1/PC2_2 but no off-diagonals.** `KeyError: 'pc1_2'`.

```python
import numpy as np, astropy.units as u, sunpy.map
from astropy.coordinates import SkyCoord
from sunpy.coordinates import frames
ref = SkyCoord(0*u.arcsec, 0*u.arcsec, obstime='2020-01-01', observer='earth', frame=frames.Helioprojective)
h = sunpy.map.make_fitswcs_header((50, 60), ref, reference_pixel=[0, 0]*u.pix, scale=[2, 2]*u.arcsec/u.pix)
for k in ['pc1_1', 'pc2_2']: h.pop(k)
h['pc1_2'], h['pc2_1'] = -0.2, 0.2
m = sunpy.map.Map(np.zeros((50, 60)), h)
r = m.resample([30, 10]*u.pix)
print(m.wcs.pixel_to_world(59.5, 49.5), r.wcs.pixel_to_world(29.5, 9.5))   # (99.2", 122.8") vs (111.1", 158.5")
```

**Wording.** Add "integer target dimensions" to Pre. Non-integer dimensions are accepted silently: the array gets `ceil(d)` pixels while the metadata uses the fractional ratio, so (30.5, 17.2) moves a corner by 2.25 px. Either reject them in the library or exclude them in the law.

## MAP-002 — `GenericMap.superpixel`

The derivation matches MAP-001 with p + ½ − offset = d(q + ½). The binned grid's edges are at old offset − ½ + d(edge + ½). The law is correct.

Standard headers, non-dividing dims (5,7) with offset (3,0), and non-integer dims/offset (int-truncated): ≤1.6×10⁻¹² px. The superpixel metadata code is the same as resample's, so it fails the same way:
- GONG maps: 853 px.
- PC without CDELT: 27.7 px.
- PC without PC1_1: 7.5 px.
- PC without PC1_2: `KeyError`.

**Wording.**
- Say that `dims` and `offset` are the `int()`-truncated values (the code truncates them).
- Add "finite" to Pre. On full-Sun CEA synoptic maps the pixel-edge corners sit at sin(lat) = ±1, so world coordinates are NaN there. MAP-001 already has this precondition.

## MAP-003 — `sunpy.image.resample.resample`

Nearest returns input samples, and linear `interpn` forms convex combinations, so the law is correct.

`map003.py` ran 3014 random in-range cases (all centre/minusone combinations, float64 and float32 input, scales 10⁻³⁰…10³⁰). The output never left [min, max], not even by one ulp. Inputs of ±1.7×10³⁰⁸ do not overflow. int64 values near 2⁶³ show no excess after the cast to float64. **Library OK.**

**Wording / preconditions.**
- **"Finite samples used" must include zero-weight cell corners.** With a single NaN at `x[0,2]` in a 2×4 array, an identity-size linear resample makes `[[1,nan,nan,nan],[1,nan,nan,nan]]`. The NaN reaches nodes that should get it with weight 0, including the other row.
- The "inside the old node range" precondition is essential. Without it, upsampling extrapolates. For example, `Map.resample` (which uses `center=True`) turns the row [0, 1] into [−0.25, 0.25, 0.75, 1.25].
- Side issue outside the law: with `center=True, minusone=True` the sample grid is inconsistent (it gives [−0.33, 0, 0.33, 0.67]). The docstring says `minusone` "prevents extrapolation", which is not true in that combination.

## MAP-004 — `GenericMap.rotate(recenter=False)`

**Derivation.** The data are rotated about the padded array centre. The new CRPIX is c + sR(r − c), the new PC is PC·R⁻¹, and the new CDELT is cdelt/s. At the new array centre this gives intermediate coordinates cdelt·PC·(c_old − crpix_old), which is unchanged. Padding and cropping use the same amount on both sides. The law is correct.

**Results.** CDELT+PC, CROTA2, HGS-CAR, odd shapes, skew `rmatrix`, angles 0/45/90/179/−120, `scale=1.5`, and every shipped test header: ≤3.6×10⁻¹³ px (SOTMap: 1.3×10⁻⁹ px).

**Library violations:**
1. **CD-only header (no CDELT), `scale=1`.** `rotate` deletes CD1_1…CD2_2 and writes PC, but it writes CDELT only when `scale != 1`. The new map therefore defaults to CDELT = 1 (1″/px instead of 2″/px). The centre moves 14 px in my test, and the whole WCS is wrong.
   ```python
   h = sunpy.map.make_fitswcs_header((50, 60), ref, reference_pixel=[0, 0]*u.pix, scale=[2, 2]*u.arcsec/u.pix)
   for k in ['cdelt1', 'cdelt2', 'pc1_1', 'pc1_2', 'pc2_1', 'pc2_2']: h.pop(k)
   h.update(cd1_1=2.0, cd1_2=0.0, cd2_1=0.0, cd2_2=2.0)
   m = sunpy.map.Map(np.zeros((50, 60)), h)
   r = m.rotate(angle=0*u.deg, missing=0)
   print(m.scale, r.scale)   # 2"/px -> 1"/px; array-centre (59",49") -> (29.5",24.5")
   ```
2. **`scale ≠ 1` on maps whose `scale` property is not `cdelt`.** On GONG H-α and magnetogram maps, the new `cdelt` is ignored (674 px and 256 px shifts at `scale=1.5`). On HMI/MDI CEA synoptic maps (`CUNIT2='Sine Latitude'`), `rotate` writes `cdelt2 = scale[1]/s` in degrees and the `scale` property multiplies by 180/π again. The result is 12.16°/px instead of 0.212°/px. With CRPIX2 moved 60 rows off the centre, the centre's latitude goes from 19.47° to NaN (`synoptic_rot.py`).

**Cosmetic, not a law violation.** For `angle=90°` on a 64×48 map the output is 50×64, not 48×64. The reason: cos 90° ≠ 0 in floating point, so `ceil` rounds the size up by one pixel on each side. The centre is still preserved.

---

### Summary of recommended law edits
- **FRM-001:** add float64 input to Pre (or a dtype-dependent tolerance); optionally require d ≥ 0.
- **FRM-002:** say "forward line of sight".
- **SCR-001:** define `tol` for the far-root check.
- **MAP-001:** add integer target dimensions to Pre.
- **MAP-002:** use `int()`-truncated dims/offset; add "finite".
- **MAP-003:** count all interpolation-cell corners, including zero-weight ones, as "used".

No law is mathematically wrong.
