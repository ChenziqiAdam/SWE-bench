# SunPy scientific-sanitizer law candidates

Written from a static read only (SANITIZER.md Step 2-3), before any checker code and before
executing any input through the functions below. Pinned base: fork `ChenziqiAdam/sunpy`, branch
`scibench-scientific-checkers-pilot` built on upstream `sunpy/sunpy` main
`87d916c658045b3e5680aa58a130f9788ba618e4` (2026-10-06).

Fields: **Pre** input family where the law holds; **Law**; **Obs** observation point; **Alarm**
comparison of two quantities the law says agree; **Fam** root-cause family; **Why**. T/X/P/N =
tolerance / transform neutrality / precondition / probe coverage (SANITIZER.md 5.8).
`eps = 2.22e-16` (float64), `C = 64`. `T_EPH` = observation time inside `[1900-01-01, 2100-01-01]`
(validity span of the built-in ephemeris); outside it the ephemeris laws are not checked.

Domain: solar physics -- Sun-centred coordinate frames and their transformations, solar ephemeris and
Carrington rotation, solar differential rotation, solar-disk geometry, and map (image + FITS-WCS)
manipulation. Not covered by the existing banks (biology, astronomy/astropy, chemistry, materials,
quantum, fMRI). Astropy is covered, but SunPy's own frame graph, rotation models, screens and map
metadata handling are separate code with their own invariants.

Excluded by the engineering gate / SANITIZER.md 5.6: network clients (`net`), file I/O (`io`),
time-series containers, visualization, SPICE/Horizons wrappers, CDF/JSOC/VSO interfaces, and thin
wrappers over astropy/scipy kernels (`reproject_to`, `scipy.ndimage` calls themselves).

## Foreknowledge disclosure

The read covered `coordinates/{sun,ephemeris,_transformations,frames,utils,screens,wcs_utils}.py`,
`sun/{models,_constants}.py`, `physics/differential_rotation.py`, `map/{mapbase,maputils,header_helper}.py`,
`image/{resample,transform}.py`. While reading, the curator noticed (not executed):
`Map.resample` and `image.resample` use `fill_value=None` (extrapolation) so an upsampled grid samples
outside the input node range -- MAP-003's precondition therefore fences "no extrapolation";
`Map.resample/superpixel` rescale `pc*` keys but only when `pc1_1` is present; `differential_rotate`
pads by an integer pixel count; `L0` is called recursively by the HGS->HGC matrix builder (checkers
must be re-entrancy safe); `SphericalScreen.calculate_distance` iterates only under differential
rotation. No law below states a witness input and nothing was run. MAP-001/002/003/004, SCR-001
sit near the spots above and are flagged for an independent curator.

---

## A. Solar ephemeris -- `coordinates/sun.py`, `coordinates/ephemeris.py`

**EPH-001 Solar angular radius lies between the sine and tangent of the geometry.** Pre: `0 < R/D < 1`
for the physical radius `R` and distance `D` (any finite quantities). Law: with `x = R/D`, the
angular radius `theta` of a sphere seen from distance `D` satisfies `x <= theta <= x/sqrt(1-x^2)` (arc
vs chord vs tangent). Obs: return of `_angular_radius`. Alarm: `theta_rad < x*(1 - C*eps)` or
`theta_rad > x/sqrt(1-x^2) * (1 + C*eps)`; the slack is a few ulps of `theta` (arcsin plus two unit
conversions through arcsec). Fam `angular_radius_geometry`. Why: `sin(theta) = R/D` is the definition
of the Sun's semi-diameter and every disk-limb test downstream relies on it.

**EPH-002 Sun-Earth distance stays inside the orbital envelope.** Pre: `T_EPH`. Law: the distance lies
between perihelion and aphelion of Earth's orbit, `0.9825 AU <= r <= 1.0175 AU` (`a(1-e)`..`a(1+e)`
with `e = 0.0167`, `a = 1 AU`, margin 4e-4 AU for planetary perturbations and the Earth-Moon wobble).
Obs: return of `earth_distance`. Alarm: `r` outside that interval. Fam `earth_distance_orbit_envelope`.
Why: a unit or ephemeris-body slip produces distances outside any Keplerian envelope.

**EPH-003 `earth_distance` agrees with the radius of Earth in HGS.** Pre: `T_EPH`. Law: the Sun-Earth
distance from barycentric positions equals the radial coordinate of `get_earth` (two independent paths:
vector difference vs frame transformation). Obs: return of `earth_distance`. Alarm: relative difference
`> 1e-11` (both are float64 chains of about 10 operations on 1.5e11 m, `C*eps` = 1.4e-14, margin 700x).
Fam `earth_distance_cross_method`. Why: two public APIs report the same physical quantity.

**EPH-004 `B0` equals the tilt of the Sun's pole toward Earth.** Pre: `T_EPH`. Law:
`sin(B0) = p . e`, where `p` is the unit vector of the Sun's north pole in ICRS (constants `alpha_0`,
`delta_0`) and `e` is the unit Sun->Earth vector from barycentric positions (no frame transformation
involved). Obs: return of `B0`. Alarm: `|B0 - arcsin(p . e)| > 1e-11 rad` (B0 < 0.13 rad, so arcsin is well
conditioned; both paths are float64 with about 30 operations). Fam `b0_pole_tilt`. Why: B0 is by
definition the heliographic latitude of the sub-Earth point, the angle between the rotation axis and the
Sun-Earth line.

**EPH-005 Nutation in obliquity respects its amplitude.** Pre: any time. Law: true minus mean obliquity
is the nutation in obliquity, whose amplitude is 9.2 arcsec for the 18.6-year term and at most 10.5
arcsec in total. Obs: return of `true_obliquity_of_ecliptic`. Alarm: `|true - mean| > 10.5 arcsec`, with
`mean` from `mean_obliquity_of_ecliptic`. Fam `obliquity_nutation_amplitude`. Why: a wrong angle unit or
a nutation term applied twice changes every apparent coordinate.

**EPH-006 Apparent minus true solar longitude is aberration plus nutation.** Pre: `T_EPH`. Law: the
difference of the Sun's apparent longitude (true equinox of date, aberrated) and true longitude (mean
equinox of date, geometric) is the sum of the annual aberration (20.5 arcsec x 1 AU/r, at most 21.2) and
the nutation in longitude (at most 19.5 arcsec including the 1.3 arcsec semiannual term), so at most 42 arcsec in magnitude (revised from 40, see revision log). Obs: return of
`apparent_longitude`; the checker re-calls `true_longitude` at the same time. Alarm: wrapped
`|apparent - true| > 42 arcsec`. Fam `apparent_true_longitude_gap`. Why: catches precession/equinox
mismatches between the two definitions (X: the re-call is the identical time object).

**EPH-007 Apparent RA/Dec of the Sun agrees with the TETE frame.** Pre: `equinox_of_date=True`, `T_EPH`.
Law: the Sun's right ascension/declination referred to the true equinox of date equals its coordinates in
astropy's `TETE` frame obtained from HCRS (an independent transformation chain). Obs: return of
`apparent_rightascension` / `apparent_declination`. Alarm: angular difference `> 1e-3 arcsec` (both chains
use IAU 2006/2000A; rounding is below 1e-9 arcsec, the slack covers model-level differences far below any
use). Fam `apparent_equatorial_cross_frame`. Why: cross-method consistency of a published solar ephemeris
quantity.

**EPH-008 The Earth lies on the HGS prime meridian.** Pre: body `earth`, no observer (no light-time
shift), `T_EPH`. Law: in Heliographic Stonyhurst the Sun-Earth line projects onto zero longitude, so the
longitude of the Earth is 0. Obs: return of `get_body_heliographic_stonyhurst`. Alarm: wrapped
`|lon| > 1e-9 deg` (rounding of the HGS rotation is about 1e-14 deg). Fam `hgs_earth_meridian`. Why: the
definition of the Stonyhurst frame must hold for the ephemeris path that feeds it.

**EPH-009 Light-travel-time iteration reaches its fixed point.** Pre: an observer is supplied, finite
positions. Law: the final light travel time equals the distance between the observer and the body at the
emission time, divided by `c`. Obs: after the iteration in `get_body_heliographic_stonyhurst`. Alarm:
`|ltt - |r_body(emitted) - r_obs|/c| > 1e-7 s` (the loop stops when successive estimates differ by 1e-8 s
and the map is a contraction with rate `v/c ~ 1e-4`). Fam `light_time_fixed_point`. Why: convergence of an
iterative scientific algorithm at its end state.

**EPH-010 Eclipse obscuration matches the planar overlap of two discs.** Pre: Sun and Moon angular radii
and separation all `< 0.02 rad`. Law: the obscured fraction of the spherical-cap overlap equals the planar
circle-lens-area fraction to within the curvature correction `O(theta^2)` (about 1e-4). Obs: before the
return of `eclipse_amount`, from its `s`, `m`, `d` and `fraction`. Alarm: absolute fraction difference
`> 2e-3`. Fam `eclipse_overlap_area`. Why: independent geometric model of the same physical quantity.

## B. Carrington rotation -- `coordinates/sun.py`

**CAR-001 The Carrington rotation number advances at the synodic rate.** Pre: `T_EPH`, finite times.
Law: the rotation number is monotonic in time and advances at `(Omega_sid - Omega_earth)/360 deg` per day
with `Omega_earth` between 0.9525 and 1.0187 deg/day, i.e. 13.16-13.23 deg/day. Obs: return of
`carrington_rotation_number`; the checker re-calls it at `t + 1 day` (exact two-double addition, X ok).
Alarm: `(n(t+1d) - n(t))*360` outside `[13.10, 13.30]`. Fam `carrington_rate`. Why: wrap-adjustment
mistakes shift the integer part by one rotation.

**CAR-002 Rotation number and rotation time are inverse.** Pre: `T_EPH`. Law:
`carrington_rotation_number(carrington_rotation_time(c)) = c` to the documented 0.11 s. Obs: return of
`carrington_rotation_time`. Alarm: `|n' - c| * 27.2753 d > 0.2 s`. Fam `carrington_roundtrip`. Why:
documented accuracy of a published conversion.

**CAR-003 Rotation constants are mutually consistent.** Pre: always. Law: the mean synodic period and the
sidereal rotation rate satisfy `1/P_syn = Omega_sid/360 deg - 1/P_orbit` with the sidereal year
`P_orbit = 365.256363 d`. Obs: in `carrington_rotation_number`. Alarm: relative difference of `P_syn`
`> 1e-4` (Julian vs sidereal year changes it by 1.3e-6). Fam `rotation_constants`. Why: physical-constant
consistency against an accepted value.

**CAR-004 The disk centre has Carrington longitude `L0`.** Pre: default `L0` options, scalar `T_EPH`.
Law: the Sun-disk centre seen from Earth (helioprojective `(0,0)`) lies at Carrington longitude `L0` (via
HPC -> HCC -> HGS -> HGC; independent of the formula in `L0`). Obs: return of `L0`. Alarm: wrapped
longitude difference `> 1e-9 deg`. Fam `disk_center_carrington`. Why: the definition of `L0`, exercised
through the frame graph (re-entrancy guarded).

## C. Differential rotation model -- `sun/models.py`

**DRM-001 Differential rotation is symmetric about the equator.** Pre: finite latitude. Law: rotation at
`-lat` equals rotation at `+lat` (the rate depends on `sin^2`). Obs: return of `differential_rotation`; re-call
with `-lat`. Alarm: wrapped difference `> C*eps*(|A|+|B|+|C|)*|dt|`. Fam `diffrot_hemisphere_symmetry`.
Why: the solar rotation profile is north-south symmetric.

**DRM-002 Rotation rate decreases toward the poles.** Pre: finite latitude. Law: the one-day rotation rate
is non-increasing in `|lat|`. Obs: return of `differential_rotation`; re-call with `|lat|+5 deg` (capped at 90),
duration 1 day. Alarm: rate at the higher latitude exceeds the lower by `> 1e-10 deg/day`. Fam
`diffrot_poleward_decrease`. Why: the equator rotates fastest for every published profile.

**DRM-003 Rotation is linear in elapsed time.** Pre: finite duration. Law: `rot(dt) = 2 rot(dt/2)` modulo
360 deg. Obs: return of `differential_rotation`; re-call with `dt/2`. Alarm: wrapped difference
`> C*eps*(|A|+|B|+|C|)*|dt|` in degrees. Fam `diffrot_linearity`. Why: a constant angular velocity at fixed
latitude.

**DRM-004 Equatorial rate agrees with the rigid sidereal rate.** Pre: any model. Law: the equatorial
one-day rotation of any model is within 5 percent of the sidereal rate `14.1844 deg/day`. Obs: return of
`differential_rotation`; re-call at latitude 0 and duration 1 day, sidereal. Alarm: relative deviation from
`sunpy.sun.constants.sidereal_rotation_rate` `> 0.05` (published equatorial rates span 14.1-14.7 deg/day).
Fam `diffrot_equatorial_rate`. Why: unit-conversion check of the model coefficients against the authoritative
constant.

**DRM-005 The synodic correction equals the Earth's mean motion.** Pre: `|dt| < 1e5 d`. Law: sidereal minus
synodic rotation equals `360 deg / 365.256363 d` times the elapsed time (mod 360). Obs: return of
`differential_rotation`; re-call with the other `frame_time`. Alarm: wrapped difference from the expected
shift `> 1e-4 * 0.9856 deg/d * |dt| + C*eps*scale`. Fam `diffrot_synodic_correction`. Why: hard-coded constant
checked against the orbital period.

**DRM-006 Published differential-rotation models agree.** Pre: model in `{howard, snodgrass, allen}`,
`|lat| <= 60 deg`. Law: the one-day rate agrees with the mean of the other two differential models within
10 percent (Beck 2000 compares them at the few-percent level). Obs: return of `differential_rotation`;
re-calls with the other models. Alarm: relative deviation `> 0.10`. Fam `diffrot_model_agreement`. Why:
cross-model consistency.

## D. Frames and geometry -- `coordinates/frames.py`, `_transformations.py`, `utils.py`, `maputils.py`

**FRM-003 Changing the observer moves the label, not the point.** Pre: same `obstime` for both frames,
observers defined. Law: after `Helioprojective -> Helioprojective` with a different observer, both
coordinates are the same Sun-centred point (compare in HGS). Obs: return of `hpc_to_hpc` when observers differ.
Alarm: HGS Cartesian difference `> 1e-3 m + 1e-12 L`, `L` = the largest of the point distances and the two observer distances (revised twice, see revision log). Fam `hpc_observer_invariance`. Why: a physical location
does not depend on who observes it.

**FRM-004 Heliocentric angle obeys the law of sines.** Pre: a 3-D coordinate with observer, radius `r > 0`, point
not on the Sun-observer line. Law: `sin(theta) = (D/r) sin(alpha)`, where `alpha` is the angle at the observer
between the disk centre and the point (triangle observer-Sun centre-point). Obs: return of
`get_heliocentric_angle`. Alarm: relative difference `> 1e-8` of `sin(theta)`. Fam `heliocentric_angle_sine_rule`.
Why: relates the limb-darkening angle `mu` to the observed disk position.

**FRM-005 Limb coordinates sit at the solar angular radius.** Pre: `D > rsun`. Law: every limb point seen from
the observer has angular distance `arcsin(rsun/D)` from the disk centre. Obs: return of `get_limb_coordinates`.
Alarm: any point's angular distance (via `atan2` of the HPC Cartesian vector, no cancellation) differs by
`> 1e-9 theta + C*eps`. Fam `limb_angular_radius`. Why: ties the limb construction to the angular-radius law.

**FRM-006 Great-arc points advance uniformly along the geodesic.** Pre: `sin(inner angle) >= 1e-6`. Law: the point
at parameter `p` makes angle `p*Theta` with the start vector and `(1-p)*Theta` with the end vector (angles
measured from the arc centre), independent of radius. Obs: before the return of `GreatArc.coordinates`. Alarm: any
angle error `> 64 eps / sin(Theta)`. Fam `great_arc_uniform_angle`. Why: a great-circle path is a constant-speed
geodesic.

## E. Screens -- `coordinates/screens.py`

**SCR-001 Spherical-screen points lie on the sphere (far root).** Pre: no differential rotation, finite
discriminant. Law: the promoted point `d u` is at distance `R` from the sphere centre and `d >= C.u` (the far
intersection). Obs: before the differential-rotation branch of `SphericalScreen.calculate_distance`. Alarm:
`| |d u - C| - R | > 1e-9 R + C*eps*|C|` or `d < C.u - tol`. Fam `spherical_screen_surface`. Why: the defining
geometry of the screen assumption.

**SCR-002 Screen-distance iteration converges.** Pre: differential-rotation branch, finite starting distance.
Law: at the returned distance the 3D->2D->3D shift is below the solver tolerance (documented 1e-11, accepted
1e-9). Obs: return of `_iterate_calculate_distance`. Alarm: residual `|delta/distance| > 1e-9` for any element.
Fam `screen_iteration_convergence`. Why: convergence of the numerical solve at its end state.

## F. Differential rotation of coordinates -- `physics/differential_rotation.py`

**DRC-001 Solar rotation is reversible.** Pre: coordinate with an HGS observer at its own `obstime`, on-disk
(finite HGS), `observer` supplied. Law: rotating to a new observer/time and back to the original observer/time
recovers the 3-D input. Obs: return of `solar_rotate_coordinate`; the checker rotates back. Alarm: `|dTx|,|dTy|`
`> 1e-6 arcsec` or `|d distance| > 1e-12 D`. Fam `solar_rotate_reversible`. Why: differential rotation changes
longitude as a function of latitude only. N: blind to a global sign error, hence DRC-002.

**DRC-002 Solar rotation is prograde in an inertial frame.** Pre: on-disk input, sidereal frame. Law: about the
Sun's rotation axis, in an inertial (ICRS-oriented, Sun-centred) frame, a point's longitude advances by
`differential_rotation(dt, lat)`. Obs: return of `solar_rotate_coordinate`. Alarm: wrapped change of the longitude of
the HCRS Cartesian vector in the de-tilted frame (axis = solar north) differs from `drot` by `> 1e-8 deg`. Fam
`solar_rotate_prograde`. Why: fixes the direction the reversibility law cannot see.

## G. Maps -- `map/mapbase.py`, `map/maputils.py`, `image/resample.py`

**MAP-001 Resampling preserves the field of view.** Pre: celestial 2-D WCS, finite. Law: the world coordinates of
the four outer corners of the pixel grid (edges at `-0.5` and `n-0.5`) are unchanged by `resample`. Obs: return
of `GenericMap.resample`. Alarm: any corner moves by `> 1e-6` old pixel scales. Fam `map_resample_footprint`.
Why: resampling changes sampling, not the sky covered.

**MAP-002 Superpixel binning preserves the covered footprint.** Pre: celestial 2-D WCS. Law: the outer corners
of the binned grid coincide with the old pixel-edge corners at `offset - 0.5 + dims*(edge + 0.5)`. Obs: return of
`GenericMap.superpixel`. Alarm: any corner differs by `> 1e-6` old pixel scales. Fam `map_superpixel_footprint`.
Why: binning keeps the sky area of the kept pixels.

**MAP-003 Interpolation does not create new extrema.** Pre: method `nearest` or `linear`, every new sample
coordinate inside the old node range (no extrapolation), finite samples used. Law: output values lie within
`[min, max]` of the input (maximum principle). Obs: return of `image.resample.resample`. Alarm: output beyond
the range by `> C*eps*max|x|`. Fam `resample_maximum_principle`. Why: linear interpolation is a convex
combination.

**MAP-004 Rotation about the array centre keeps the centre coordinate.** Pre: `recenter=False`, celestial WCS.
Law: the array-centre pixel has the same world coordinate before and after `rotate` (padding and cropping are
symmetric). Obs: return of `GenericMap.rotate`. Alarm: centre moves by `> 1e-6` old pixel scales. Fam
`map_rotate_center`. Why: rotation about the centre must not shift the image.

**MAP-005 A submap keeps the pixel grid and the data.** Pre: finite WCS conversion. Law: the submap's pixel
`(0,0)` corresponds to an integer pixel `(x0,y0)` of the parent, the scale is unchanged, and the data equal
`parent[y0:y0+ny, x0:x0+nx]`. Obs: return of `GenericMap.submap`. Alarm: non-integer offset `> 1e-6`, scale
change `> 1e-12` relative, or data mismatch. Fam `map_submap_grid`. Why: cropping must not resample.

**MAP-006 Disk-coverage classes partition all maps.** Pre: helioprojective map. Law: exactly one of
`is_all_on_disk`, `is_all_off_disk`, `contains_limb` is true. Obs: return of `contains_limb`. Alarm: zero or more
than one true. Fam `disk_coverage_partition`. Why: the three classes are the possible relations between a
rectangle and a disk.

**MAP-007 "All on disk" holds for every pixel.** Pre: map with at most 262144 pixels, field of view `<= 5 deg`.
Law: when the edge test says all on disk, every pixel centre is on the disk (convexity). Obs: return of
`is_all_on_disk`. Alarm: result true but some pixel centre is off disk. Fam `disk_edge_vs_exhaustive_on`. Why:
shortcut vs exhaustive cross-check.

**MAP-008 "All off disk" holds for every pixel.** Pre: as MAP-007 and disk angular radius `>= 2` pixels. Law: when
the edge test says all off disk, no pixel centre is on the disk. Obs: return of `is_all_off_disk`. Alarm: result
true but some pixel centre is on disk. Fam `disk_edge_vs_exhaustive_off`. Why: shortcut vs exhaustive cross-check.

## H. Resampling kernels and metadata -- `image/resample.py`, `coordinates/wcs_utils.py`, `map/header_helper.py`

**IMG-001 Linear resampling reproduces an affine ramp exactly.** Pre: method `linear`, `size <= 4e6`. Law:
resampling the ramp `a i + b j + c` (fixed float64, independent of the user data) returns the ramp evaluated at
the physical sample positions `(i + o) s - o`. Obs: return of `image.resample.resample`; re-run on the ramp.
Alarm: `> C*eps*(|a| n1 + |b| n2 + |c|)*10`. Fam `resample_affine_exactness`. Why: coordinate mapping check with a
data-independent probe.

**WCS-001 Frame -> WCS -> frame preserves the observer.** Pre: Sun-fixed frame with an HGS/HGC observer frame.
Law: converting a frame to a WCS and back recovers frame class, `obstime` (to 1 ms, FITS precision), `rsun` and
observer lon/lat/radius. Obs: return of `solar_frame_to_wcs_mapping`. Alarm: any differs by `> 1e-12` relative
(`1 ms` for time). Fam `frame_wcs_roundtrip`. Why: serialization must be lossless.

**WCS-002 `make_fitswcs_header` places the reference coordinate at the reference pixel.** Pre: coordinate frame
with lon/lat, `rotation_matrix` not given. Law: evaluating the header's WCS at the zero-based reference pixel gives
the input coordinate, and one pixel along an axis moves the coordinate by the requested scale. Obs: return of
`make_fitswcs_header`. Alarm: coordinate error `> 1e-9 + C eps 360 deg / scale` pixels, or step differs by `> 1e-9 + x^2/2 + C eps 360 deg / |scale|` relative (`x` = the step in radians; a zenithal pixel step of plane size `x` spans `atan(x)`; the last term is the rounding of two O(360 deg) coordinates differenced over one step). Fam
`fits_header_reference`. Why: FITS 1-based vs 0-based pixel conventions and units.

---

## Revision log (checker-side defects and adjudicated triggers)

Recorded after the checkers existed, from review, isolated tests and fuzzing. None of these feeds back into
which laws are kept (SANITIZER.md 5.4); they correct tolerance, precondition, transform neutrality and
re-entrancy of an already-stated law.

1. **EPH-006 bound 40 -> 42 arcsec (P/T).** The first sensitivity test showed apparent-true = -38.5 arcsec at
   2020-04-08, only 1.5 arcsec below the bound. Re-deriving the error model: aberration reaches 21.2 arcsec at
   perihelion and nutation in longitude 19.5 arcsec including the 1.3 arcsec semiannual term, so the maximum is
   about 40.8 arcsec. The bound was too tight and would false-alarm at winter perihelion with large nutation.
2. **Map checkers filled the production map's property caches (side effect).** Upstream
   `test_rotate_assumed_obstime` failed only with checking on: the checker read `new_map.wcs`, which emits a
   metadata warning on first access and then caches, so the user's first access no longer warned. All map checkers
   now work on shallow clones (`_clone`).
3. **EPH-004 / EPH-007 re-parsed `'now'` (X).** `parse_time('now')` yields a different instant each time, so the
   re-computation used a later time (`print_params()` fired SP-EPH-004 with a 1 ms offset, B0 changes 6e-9 rad/s).
   Checkers skip a literal `'now'`.
4. **FRM-003 tolerance scaled with the observer distance (T).** `test_hpc_hpc_spherical_screen` places the point on
   a screen 1e9 light-years away; float64 error on a 1e25 m position is 2e9 m. The tolerance is now relative to the
   point's own distance (`1e-12 |point|`).
5. **DRC-002 reference frame (T).** The first version compared against the longitude in
   `HeliocentricInertial`. Fuzzing alarmed in about a quarter of the cases at an epoch-dependent 4e-7 deg while the
   HCRS-oriented transport agreed to 1e-12 deg. Cause: `_rotation_matrix_hgs_to_hci` builds the ecliptic pole from a
   1 m vector (`z_axis = CartesianRepresentation(0, 0, 1) * u.m`) that is shifted by the Sun's ~1e9 m barycentric
   offset in the HME -> HGS chain, so the HCI orientation matrix carries ~1e-7 relative rounding noise (the same
   inertial vector has HCI longitude varying by up to 2.5e-5 deg between 1900 and 2099). That is a
   conditioning limitation of the frame under test, not a violation of the rotation law, so the reference is now the
   longitude of the HCRS Cartesian vector in the de-tilted frame (axis = solar north, the library's own
   `_SUN_DETILT_MATRIX`).
6. **FRM-003 tolerance scale (T, second revision).** Fuzzing with an observer at about 7000 R_sun (3e12 m) and a point
   near the Sun alarmed (2 of 96 cases): the HPC -> HGS conversion cancels terms of the observer distance, so the
   float64 error is `C eps D_obs ~ 4e-2 m`, above `1e-3 m + 1e-12 |point|`. The scale `L` now includes both observer
   distances.
7. **WCS-002 step tolerance (T).** A fuzzed header with a 0.0996 deg pixel scale alarmed (1 of 96 cases):
   for a TAN projection the great-circle separation of one pixel step is `atan(x)`, a relative `x^2/3 = 1.0e-6`
   below the plane step `x`, which exceeded the flat `1e-6`. The tolerance now includes the projection term.
8. **WCS-002 coordinate tolerance (T).** A header with a 1.6e-5 deg pixel scale alarmed (1 of 96 cases): world
   coordinates are O(100 deg) float64 numbers whose absolute rounding (`C eps 360 deg = 5e-12 deg`) is 3e-7 pixel at
   that scale, above the flat `1e-9` pixel. The tolerance now carries the `C eps 360 deg / scale` term.
9. **Dtype awareness (P/T).** Quantity inputs keep float32. DRM-001..003/005 and DRM-002 now use the input dtype's
   epsilon.
10. **SCR-002 natural trigger (adjudicated as real, not a defect).** Fuzz found one case (observer 0.48 AU, screen centre
    4.8 R_sun, `propagate_with_solar_surface`) where the iteration stops after 20 steps: the library warns
    "Failed to solve for the differentially rotated screen after 20 iterations. Using the best guess." and the returned
    distances carry residuals of 5e-4 to 1.2e-1 relative. The law (returned distance is a fixed point) is violated by
    the library at valid input; the warning confirms the library knows.
11. **WCS-002 step tolerance, rounding term (T, second revision).** After item 8 two fuzz cases (scales 0.058 and 0.12
    arcsec/pixel) still alarmed: the step is the difference of two O(100 deg) coordinates 1.6e-5 deg apart, so the
    rounding `C eps 360 deg` is 3e-7 of the step. The step tolerance now includes `C eps 360 deg / |scale|`.

12. **Fresh-agent audit (Sonnet 5.5, 30 tests, 11 IDs triggered); adjudication: 5 checker defects fixed, 6 IDs real.**
13. **DRC-002 near the pole (T).** The heliographic longitude is conditioned as 1/cos(lat); the measured residual times
    cos(lat) is constant (about 6e-12 deg from 60 deg to 89.9999999 deg). The tolerance now adds `1e3 eps / cos(lat)`.
14. **DRC-001 observer distance (T).** With a 50 AU observer the positions are O(7.5e12 m) floats; the round trip from a
    1.5 R_sun observer differs by 2e-12 relative, 3e-7 arcsec. The tolerances now carry `C eps L / d`, L the largest
    observer distance.
15. **FRM-006 small arc far from the origin (T).** A 30 km arc on the surface, seen from 1 AU, has points of magnitude
    `|center|`; rounding is `C eps |center| / radius` as an angle (5e-12 rad here, measured 8e-13). The tolerance now
    carries that term.
16. **SCR-001 small screen (T).** The quadratic root carries `eps |c|^2` of cancellation: `eps |c|^2 / r` metres along
    the ray (0.12 m for a 10,000 km sphere at 0.5 AU, measured 0.07 m). The far-root check allows `sqrt(C eps) |c|` at
    tangency.
17. **WCS-002 non-zenithal projections (N).** `cdelt` is a native-plane step; it equals the sky step only where the
    projection has unit local scale (zenithal, CAR, MER, CEA, SFL). For MOL, PAR, HPX, TSC, CSC, QSC the step test is
    now skipped; the reference-coordinate test still runs for all.
18. **Real, kept:** MAP-001/002/004 (maps whose `scale` is overridden from
    non-CDELT keys, e.g. GONG magnetogram `SEMIDIAM/FNDLMB*`: `resample`, `superpixel`, `rotate(scale)` only rescale
    `cdelt`/`cd` keys in the meta, so the scale is unchanged while the pixel count changes and the footprint shrinks 4x);
    SCR-002 (natural, see item 10).
19. **Fresh-agent audit (Opus 5.5, 8 tests, 8 IDs triggered, run at 74b7f5fb8); adjudication: 0 checker defects, 8 real.**
    New real IDs beyond item 18: EPH-010 (`eclipse_amount` within about 2 km of the umbral apex, Sun and Moon nearly equal
    and concentric: the library returns 99.87% where the planar two-disc overlap, accurate there, gives 99.998%, up to
    0.5% difference measured; the agent saw about 97% at other points) and DRC-001 (a look direction pointing away from the
    Sun is promoted to a negative distance by `make_3d`, and the rotate-out/rotate-back round trip does not
    return it). The agent's claim that WCS-002 "can never fire" was checked and is wrong: the checker fires on a shifted
    reference pixel for TAN and MOL headers.
