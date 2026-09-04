"""Shared case validation for the sketch-and-select Arnoldi (ssarnoldi)
curator implementation (task scibench_replication_0022).

A case specifies one condition-number-growth run of
`paper_ssa_final_test1a.m`/`test1b.m` (Guttel & Simunec, "A sketch-and-select
Arnoldi process", SIAM J. Sci. Comput. 2024) on one pinned SuiteSparse test
matrix. There is a single `case_type`: `arnoldi_cond_growth`.

DESIGN NOTE: the case's random inputs (`v0`, the SRHT Rademacher sign
pattern `D`, and the SRHT column-selection `perm`) are supplied EXPLICITLY
in the case JSON, not derived internally from a seed by each side. This is
necessary, not just convenient: `scientific.py`'s `solve(task_id, value)`
dispatcher (used by `reference_cli.py` at evaluation time) receives only
the raw case JSON and must reproduce the official adapter's exact answer
from that alone -- it has no access to a live Octave run's RNG state.
Requiring MATLAB/Octave's MT19937 stream to be bit-reproduced independently
in NumPy was considered and rejected as fragile and unnecessary (see
ssarnoldi_scientific.py's module docstring); baking the realized values
into the input instead makes both sides trivially agree on the same
random draws while still requiring a correct SRHT/Arnoldi implementation
to process them. The curator's build script (build_ssarnoldi_task.py)
populates these fields once per case via a real Octave RNG draw
(curation_tools/ssarnoldi_extract_randomness.m) before the case is ever
shipped in a task bundle -- an evaluated agent sees them as ordinary fixed
numeric inputs, the same way it sees the fixed sparse matrix `A` itself.
"""

from __future__ import annotations

from typing import Any

# The only three matrices with pinned local .mat files (see
# curation_tools/ssarnoldi_matrices/); ssget()'s live download path is
# avoided entirely, so only these identifiers are servable.
KNOWN_MATRICES = {"Norris/torso3", "Bai/cryg10000", "Norris/torso1"}
MATRIX_N = {"Norris/torso3": 259156, "Bai/cryg10000": 10000, "Norris/torso1": 116158}

SPEC_FIELDS = {"case_type", "matrix", "p", "s", "t", "condbound"}
REQUIRED_FIELDS = SPEC_FIELDS | {"v0", "D", "perm"}


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_positive_int(value: Any, lo: int, hi: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


def validate_spec(case: dict[str, Any]) -> dict[str, Any]:
    """Validates only the pre-randomness fields (case_type/matrix/p/s/t/
    condbound). Used by build_ssarnoldi_task.py / extract_randomness before
    v0/D/perm have been generated for a case; validate_case (below) is the
    full validator used everywhere else, including by the adapter/driver."""
    if not isinstance(case, dict) or "case_type" not in case:
        raise ValueError("case must be an object with a case_type field")
    if set(case) != SPEC_FIELDS:
        raise ValueError("arnoldi_cond_growth spec fields differ")
    if case["case_type"] != "arnoldi_cond_growth":
        raise ValueError("invalid case_type")

    matrix = case["matrix"]
    if not isinstance(matrix, str) or matrix not in KNOWN_MATRICES:
        raise ValueError("invalid matrix (no pinned .mat file for this identifier)")

    p = case["p"]
    if not _is_positive_int(p, 1, 300):
        raise ValueError("invalid p")

    s = case["s"]
    if not (_is_finite_number(s) and 1.0 <= s <= 10.0):
        raise ValueError("invalid s")

    t = case["t"]
    if not _is_positive_int(t, 1, 50):
        raise ValueError("invalid t")
    if t > p:
        raise ValueError("t must be <= p")

    condbound = case["condbound"]
    if isinstance(condbound, str):
        if condbound != "inf":
            raise ValueError("invalid condbound string (only 'inf' is accepted)")
        clean_condbound: Any = "inf"
    elif _is_finite_number(condbound) and condbound > 0:
        clean_condbound = float(condbound)
    else:
        raise ValueError("invalid condbound")

    return {
        "case_type": "arnoldi_cond_growth",
        "matrix": matrix,
        "p": p,
        "s": float(s),
        "t": t,
        "condbound": clean_condbound,
    }


def validate_case(case: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(case, dict) or set(case) != REQUIRED_FIELDS:
        raise ValueError("arnoldi_cond_growth case fields differ")
    spec = {key: case[key] for key in SPEC_FIELDS}
    clean = validate_spec(spec)

    n = MATRIX_N[clean["matrix"]]
    sketch_dim = round(clean["s"] * clean["p"])

    v0 = case["v0"]
    if not (isinstance(v0, list) and len(v0) == n and all(_is_finite_number(x) for x in v0)):
        raise ValueError("invalid v0 (must be a length-N list of finite numbers)")

    D = case["D"]
    if not (isinstance(D, list) and len(D) == n and all(x in (1, -1) for x in D)):
        raise ValueError("invalid D (must be a length-N list of +-1)")

    n2 = 1 << (n - 1).bit_length()  # next power of two >= n, matching srht.m's N=2^ceil(log2(n))
    perm = case["perm"]
    if not (
        isinstance(perm, list) and len(perm) == sketch_dim
        and all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= n2 for x in perm)
        and len(set(perm)) == len(perm)
    ):
        raise ValueError("invalid perm (must be a length-round(s*p) list of distinct 1-indexed ints in [1,N2])")

    clean["v0"] = [float(x) for x in v0]
    clean["D"] = [int(x) for x in D]
    clean["perm"] = [int(x) for x in perm]
    return clean
