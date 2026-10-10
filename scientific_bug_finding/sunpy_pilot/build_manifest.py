"""Build sanitizers.json from LAW_CANDIDATES.md (single source of truth for the laws)."""
import json
import re
import sys

doc = open("LAW_CANDIDATES.md").read()
SRC = {  # id -> (source, symbol, quantity)
 "EPH-001": ("sunpy/coordinates/sun.py", "_angular_radius", "solar angular radius"),
 "EPH-002": ("sunpy/coordinates/sun.py", "earth_distance", "Sun-Earth distance"),
 "EPH-003": ("sunpy/coordinates/sun.py", "earth_distance", "Sun-Earth distance"),
 "EPH-004": ("sunpy/coordinates/sun.py", "B0", "heliographic latitude of the sub-Earth point"),
 "EPH-005": ("sunpy/coordinates/sun.py", "true_obliquity_of_ecliptic", "true obliquity of the ecliptic"),
 "EPH-006": ("sunpy/coordinates/sun.py", "apparent_longitude", "apparent ecliptic longitude of the Sun"),
 "EPH-007": ("sunpy/coordinates/sun.py", "apparent_rightascension/apparent_declination", "apparent equatorial position of the Sun"),
 "EPH-008": ("sunpy/coordinates/ephemeris.py", "get_body_heliographic_stonyhurst", "Earth longitude in HGS"),
 "EPH-009": ("sunpy/coordinates/ephemeris.py", "get_body_heliographic_stonyhurst", "light travel time"),
 "EPH-010": ("sunpy/coordinates/sun.py", "eclipse_amount", "solar eclipse obscuration"),
 "CAR-001": ("sunpy/coordinates/sun.py", "carrington_rotation_number", "Carrington rotation number"),
 "CAR-002": ("sunpy/coordinates/sun.py", "carrington_rotation_time", "Carrington rotation time"),
 "CAR-003": ("sunpy/coordinates/sun.py", "carrington_rotation_number", "mean synodic rotation period"),
 "CAR-004": ("sunpy/coordinates/sun.py", "L0", "Carrington longitude of the disk centre"),
 "DRM-001": ("sunpy/sun/models.py", "differential_rotation", "differential rotation angle"),
 "DRM-002": ("sunpy/sun/models.py", "differential_rotation", "differential rotation rate"),
 "DRM-003": ("sunpy/sun/models.py", "differential_rotation", "differential rotation angle"),
 "DRM-004": ("sunpy/sun/models.py", "differential_rotation", "equatorial rotation rate"),
 "DRM-005": ("sunpy/sun/models.py", "differential_rotation", "synodic correction"),
 "DRM-006": ("sunpy/sun/models.py", "differential_rotation", "differential rotation rate"),
 "FRM-003": ("sunpy/coordinates/_transformations.py", "hpc_to_hpc", "helioprojective coordinates"),
 "FRM-004": ("sunpy/coordinates/utils.py", "get_heliocentric_angle", "heliocentric angle"),
 "FRM-005": ("sunpy/coordinates/utils.py", "get_limb_coordinates", "solar limb"),
 "FRM-006": ("sunpy/coordinates/utils.py", "GreatArc.coordinates", "great-arc points"),
 "SCR-001": ("sunpy/coordinates/screens.py", "SphericalScreen.calculate_distance", "distance to a spherical screen"),
 "SCR-002": ("sunpy/coordinates/screens.py", "BaseScreen._iterate_calculate_distance", "distance to a rotated screen"),
 "DRC-001": ("sunpy/physics/differential_rotation.py", "solar_rotate_coordinate", "differentially rotated coordinate"),
 "DRC-002": ("sunpy/physics/differential_rotation.py", "solar_rotate_coordinate", "differentially rotated coordinate"),
 "MAP-001": ("sunpy/map/mapbase.py", "GenericMap.resample", "map footprint"),
 "MAP-002": ("sunpy/map/mapbase.py", "GenericMap.superpixel", "map footprint"),
 "MAP-003": ("sunpy/image/resample.py", "resample", "resampled image intensity"),
 "MAP-004": ("sunpy/map/mapbase.py", "GenericMap.rotate", "rotated map centre"),
 "MAP-005": ("sunpy/map/mapbase.py", "GenericMap.submap", "submap pixel grid"),
 "MAP-006": ("sunpy/map/maputils.py", "contains_limb", "disk-coverage class"),
 "MAP-007": ("sunpy/map/maputils.py", "is_all_on_disk", "disk-coverage class"),
 "MAP-008": ("sunpy/map/maputils.py", "is_all_off_disk", "disk-coverage class"),
 "IMG-001": ("sunpy/image/resample.py", "resample", "resampling sample positions"),
 "WCS-001": ("sunpy/coordinates/wcs_utils.py", "solar_frame_to_wcs_mapping", "WCS observer metadata"),
 "WCS-002": ("sunpy/map/header_helper.py", "make_fitswcs_header", "FITS-WCS reference coordinate"),
}


def clean(t):
    return re.sub(r"\s+", " ", t).strip()


out = []
blocks = re.findall(r"^\*\*([A-Z]+-\d{3}) ([^*]+?)\.\*\*(.*?)(?=\n\n\*\*|\n\n## |\n\n---|\Z)", doc, re.S | re.M)
for ident, title, body in blocks:
    m = re.search(r"Pre: (.*?)\. ?Law: (.*?)\. ?Obs: (.*?)\. ?Alarm: (.*?)\. ?Fam `(\w+)`\.? ?(?:Why: (.*))?$", clean(body))
    if not m:
        sys.exit(f"parse failure: {ident}")
    pre, law, obs, alarm, fam, why = m.groups()
    src, sym, qty = SRC[ident]
    out.append({"id": "SP-" + ident, "category": "scientific", "family": fam, "source": src,
                "symbol": sym, "scientific_quantity": qty, "precondition": pre, "invariant": law,
                "observation_point": obs, "alarm": alarm,
                "rationale": (why or title).rstrip(".") + "."})
ids = [s["id"] for s in out]
assert len(ids) == len(set(ids)) == len(SRC), (len(ids), len(set(ids)), len(SRC))
import os
meta = {}
if os.path.exists("sanitizers.json"):
    meta = {k: v for k, v in json.load(open("sanitizers.json")).items() if k != "sanitizers"}
meta.setdefault("schema_version", 3)
meta.setdefault("repository", "https://github.com/sunpy/sunpy")
meta.setdefault("base_commit", "87d916c658045b3e5680aa58a130f9788ba618e4")
meta.setdefault("base_tag", None)
meta.setdefault("fork_repository", "https://github.com/ChenziqiAdam/sunpy")
meta.setdefault("fork_branch", "scibench-scientific-checkers-pilot")
meta.setdefault("note", "Scientific bank only (traditional reference bank not built). Laws were written before any "
                "checker code or execution (LAW_CANDIDATES.md) and frozen before triggerability analysis.")
json.dump({**meta, "sanitizers": out}, open("sanitizers.json", "w"), indent=1)
print(len(out), "sanitizers;", len({s["family"] for s in out}), "families")
