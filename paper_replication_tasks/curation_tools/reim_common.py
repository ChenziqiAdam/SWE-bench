"""Shared case validation for the REIM (rational empirical interpolation
method) curator implementations.

A case specifies one deterministic evaluation drawn from the paper's seven
figures / Table 1. `case_type` selects which of six evaluations to run:

- `rational_approx`: rEIM approximation of x^-s on an interval (Fig 1,2,4-left).
- `time_family_approx`: rEIM approximation of (x^s+d/Lambda^s)^-1 (Fig 5-left).
- `exp_family_approx`: rEIM approximation of exp(-tau x) / varphi(-tau x) (Fig 7-right).
- `precon_family_approx`: rEIM approximation of (x^-0.5+K x^0.5)^-1 (Fig 7-left).
- `fractional_fem`: fractional-Laplacian P1-FEM solve using pinned rEIM
  residues/poles on uniform or graded meshes (Fig 3,4-right,Table 1).
- `bdf2_fractional_heat`: adaptive-step BDF2 solve of the fractional heat
  equation using rEIM-based resolvents (Fig 5-right,6).
"""

from __future__ import annotations

from typing import Any

_REIM_FAMILY_CASE_TYPES = {
    "rational_approx": "power",
    "time_family_approx": "time",
    "exp_family_approx": "exp",
    "precon_family_approx": "precon",
}

_REIM_FAMILY_INTERVALS = {
    "power": [(1e-6, 1.0), (1e-8, 1.0)],
    "time": [(1e-6, 1.0)],
    "exp": [(1.0, 1e6)],
    "precon": [(1e-6, 1.0)],
}


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_positive_int(value: Any, lo: int, hi: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


def _is_float_list(value: Any, length: int | None = None) -> bool:
    if not isinstance(value, list):
        return False
    if length is not None and len(value) != length:
        return False
    return all(_is_finite_number(x) for x in value)


def validate_case(case: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(case, dict) or "case_type" not in case:
        raise ValueError("case must be an object with a case_type field")
    case_type = case["case_type"]

    if case_type in _REIM_FAMILY_CASE_TYPES:
        return _validate_family_case(case, case_type)
    if case_type == "fractional_fem":
        return _validate_fractional_fem_case(case)
    if case_type == "bdf2_fractional_heat":
        return _validate_bdf2_case(case)
    raise ValueError("invalid case_type")


def _validate_family_case(case: dict[str, Any], case_type: str) -> dict[str, Any]:
    family = _REIM_FAMILY_CASE_TYPES[case_type]
    required = {"case_type", "a", "b", "M"}
    if family == "power":
        required |= {"s"}
    elif family == "time":
        required |= {"s", "d", "Lambda"}
    elif family == "exp":
        required |= {"tau"}
    elif family == "precon":
        required |= {"K"}
    if set(case) != required:
        raise ValueError(f"{case_type} case fields differ")

    a, b, M = case["a"], case["b"], case["M"]
    if not (_is_finite_number(a) and _is_finite_number(b) and a > 0 and b > a):
        raise ValueError("invalid interval")
    if not _is_positive_int(M, 1, 40):
        raise ValueError("invalid M")
    if (a, b) not in _REIM_FAMILY_INTERVALS[family]:
        raise ValueError("interval not supported for this family (REIM.m has no matching branch)")

    clean = {"case_type": case_type, "a": float(a), "b": float(b), "M": M}
    if family == "power":
        s = case["s"]
        if not (_is_finite_number(s) and 0.0 < s < 1.0):
            raise ValueError("invalid s")
        clean["s"] = float(s)
    elif family == "time":
        s, d, Lambda = case["s"], case["d"], case["Lambda"]
        if not (_is_finite_number(s) and 0.0 < s <= 1.0):
            raise ValueError("invalid s")
        if not (_is_finite_number(d) and d > 0):
            raise ValueError("invalid d")
        if not (_is_finite_number(Lambda) and Lambda > 0):
            raise ValueError("invalid Lambda")
        clean.update({"s": float(s), "d": float(d), "Lambda": float(Lambda)})
    elif family == "exp":
        tau = case["tau"]
        if not (_is_finite_number(tau) and tau > 0):
            raise ValueError("invalid tau")
        clean["tau"] = float(tau)
    elif family == "precon":
        K = case["K"]
        if not (_is_finite_number(K) and K > 0):
            raise ValueError("invalid K")
        clean["K"] = float(K)
    return clean


def _validate_fractional_fem_case(case: dict[str, Any]) -> dict[str, Any]:
    required = {"case_type", "s", "res", "pol", "mesh_type", "mesh_param"}
    if set(case) != required:
        raise ValueError("fractional_fem case fields differ")
    s = case["s"]
    if not (_is_finite_number(s) and 0.0 < s < 1.0):
        raise ValueError("invalid s")
    res, pol = case["res"], case["pol"]
    if not (_is_float_list(res) and _is_float_list(pol) and len(res) == len(pol) and len(res) > 0):
        raise ValueError("res/pol must be equal-length nonempty float lists")
    if any(p <= 0 for p in pol):
        raise ValueError("pol entries must be positive")
    mesh_type = case["mesh_type"]
    if mesh_type not in ("uniform", "graded"):
        raise ValueError("invalid mesh_type")
    mesh_param = case["mesh_param"]
    if mesh_type == "uniform":
        # number of uniformrefine calls after the fixed 2-refine base mesh
        # (base h=0.25, 2 refines -> h=2^-4; mesh_param additional refines
        # -> h=2^-(4+mesh_param), matching Table 1's h_i=2^-(i+3) family).
        if not _is_positive_int(mesh_param, 0, 6):
            raise ValueError("invalid mesh_param for uniform mesh")
    else:
        # target vertex count Nmax for the graded adaptive-refinement loop.
        if not _is_positive_int(mesh_param, 100, 100000):
            raise ValueError("invalid mesh_param for graded mesh")
    return {
        "case_type": "fractional_fem", "s": float(s), "res": [float(x) for x in res],
        "pol": [float(x) for x in pol], "mesh_type": mesh_type, "mesh_param": mesh_param,
    }


def _validate_bdf2_case(case: dict[str, Any]) -> dict[str, Any]:
    required = {"case_type", "s", "M", "Lambda", "tol", "tau0", "tend", "mesh_h_exponent"}
    if set(case) != required:
        raise ValueError("bdf2_fractional_heat case fields differ")
    s = case["s"]
    if not (_is_finite_number(s) and 0.0 < s <= 1.0):
        raise ValueError("invalid s")
    M = case["M"]
    if not _is_positive_int(M, 1, 40):
        raise ValueError("invalid M")
    Lambda = case["Lambda"]
    if not (_is_finite_number(Lambda) and Lambda > 0):
        raise ValueError("invalid Lambda")
    tol = case["tol"]
    if not (_is_finite_number(tol) and tol > 0):
        raise ValueError("invalid tol")
    tau0 = case["tau0"]
    if not (_is_finite_number(tau0) and tau0 > 0):
        raise ValueError("invalid tau0")
    tend = case["tend"]
    if not (_is_finite_number(tend) and tend > 0):
        raise ValueError("invalid tend")
    mesh_h_exponent = case["mesh_h_exponent"]
    if not _is_positive_int(mesh_h_exponent, 1, 10):
        raise ValueError("invalid mesh_h_exponent")
    return {
        "case_type": "bdf2_fractional_heat", "s": float(s), "M": M, "Lambda": float(Lambda),
        "tol": float(tol), "tau0": float(tau0), "tend": float(tend),
        "mesh_h_exponent": mesh_h_exponent,
    }
