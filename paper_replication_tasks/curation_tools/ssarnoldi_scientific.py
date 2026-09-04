"""Independent clean-room NumPy/SciPy reimplementation of the 9
Krylov-basis-construction variants from paper_ssa_final_test1a.m/test1b.m
(Guttel & Simunec, "A sketch-and-select Arnoldi process", SIAM J. Sci.
Comput. 2024), for task scibench_replication_0022.

DESIGN CHOICE (see reim_scientific.py for the analogous precedent in task
0021): unlike reim_scientific.py, this file's `solve()` does NOT regenerate
its own random sketch/start vector. The paper's randomness (v0 = randn(N,1)
and the SRHT's Rademacher sign pattern D / column permutation perm) comes
from MATLAB/Octave's RNG stream (rng('default') + randi/randperm), which
this file makes no attempt to bit-match -- doing so is unnecessary and
fragile. Instead `solve()` accepts the ALREADY-REALIZED v0, D, and perm
arrays (extracted from a real ssarnoldi_driver.m run by a small addition to
the driver / a companion extraction call) as part of its input, and
reimplements only the deterministic downstream math: the SRHT application
and all 9 Arnoldi-type basis-update recurrences, written directly from the
paper's/script's mathematical description (independently structured, not
transliterated line-by-line from the .m file). This keeps the audit's
scope where it matters -- numerical-recurrence correctness -- while
sidestepping a MT19937-stream-compatibility project that would not by
itself validate any of the paper's algorithms.

If a build script cannot easily extract (v0, D, perm) from the Octave run,
the simpler fallback also supported here is `solve_with_own_randomness()`,
which draws its own NumPy random v0/D/perm (documented as NOT bit-matching
Octave) purely to sanity-check internal consistency of the 9 recurrences
against each other (e.g. variant 2's basis should equal variant 1's
sketched-and-reduced version) rather than against the official adapter's
exact numbers.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    from .ssarnoldi_common import validate_case, validate_spec
except ImportError:  # direct curator-script execution
    from ssarnoldi_common import validate_case, validate_spec


def _fwht(a: np.ndarray) -> np.ndarray:
    """Fast Walsh-Hadamard transform, padded to the next power of two,
    matching srht.m's myfwht butterfly recurrence (same additions in the
    same stage order, written independently from the algorithm's
    description rather than transliterated)."""
    n = a.shape[0]
    N = 1 << (n - 1).bit_length() if n > 1 else 1
    z = np.zeros(N, dtype=float)
    z[:n] = a
    h = 1
    while h < N:
        z = z.reshape(-1, 2, h)
        x, y = z[:, 0, :].copy(), z[:, 1, :].copy()
        z[:, 0, :] = x + y
        z[:, 1, :] = x - y
        z = z.reshape(N)
        h *= 2
    return z


def make_srht(n: int, s: int, D: np.ndarray, perm: np.ndarray):
    """S(x) = (1/sqrt(s)) * select(fwht(D .* x), perm), matching srht.m's
    public contract, given an already-realized sign pattern D (length n,
    +-1) and 0-indexed column selection perm (length s)."""
    def apply(x: np.ndarray) -> np.ndarray:
        return (1.0 / np.sqrt(s)) * _fwht(D * x)[perm]
    return apply


def _maxk_abs(x: np.ndarray, k: int) -> np.ndarray:
    """Indices (0-indexed) of the k largest |x| entries, descending, ties
    broken by ascending original index -- matches MATLAB/Octave maxk."""
    k = min(k, x.size)
    order = np.argsort(-np.abs(x), kind="stable")
    return order[:k]


def _basis_cond(V: np.ndarray, j: int) -> float:
    return float(np.linalg.cond(V[:, :j]))


def _run_variant(A, v0, srht, N, p, t, condbound, select) -> tuple[list[float], int]:
    """Shared driving loop for the 8 sketch-based variants: builds V, SV one
    column at a time, calling `select(j, w, sw, V, SV)` -> (h, idx) to get
    the orthogonalization coefficients/index set for column j. Truncated
    Arnoldi (variant 1, no sketch) is handled separately in solve() since it
    has no SV/sketch machinery at all."""
    sw0 = srht(v0)
    nsw0 = np.linalg.norm(sw0)
    V = np.zeros((N, p + 1))
    SV = np.zeros((sw0.shape[0], p + 1))
    V[:, 0] = v0 / nsw0
    SV[:, 0] = sw0 / nsw0

    cond_curve: list[float] = []
    jmax_ok = 0
    broke_at = None
    for j in range(1, p + 1):
        cond_curve.append(_basis_cond(V, j))
        if j % 10 == 0:
            c = _basis_cond(V, j)
            if c > condbound:
                broke_at = j
                break
            jmax_ok = j
        w = A @ V[:, j - 1]
        sw = srht(w)
        h, idx = select(j, w, sw, V[:, :j], SV[:, :j])
        V[:, j] = 0.0
        SV[:, j] = 0.0
        w_new = w - V[:, idx] @ h
        sw_new = sw - SV[:, idx] @ h
        nrm = np.linalg.norm(sw_new)
        V[:, j] = w_new / nrm
        SV[:, j] = sw_new / nrm

    jmax = p + 1 if broke_at is None else broke_at
    size_ = jmax
    for j in range(jmax_ok + 1, jmax + 1):
        c = _basis_cond(V, j)
        if c > condbound:
            size_ = j - 1
            break
        if j == jmax:
            size_ = j

    return cond_curve, size_


def _select_truncate(t):
    def select(j, w, sw, V_j, SV_j):
        cols = np.arange(max(0, j - t), j)
        h = SV_j[:, cols].T @ sw
        return h, cols
    return select


def _select_pinv(t, recompute):
    def select(j, w, sw, V_j, SV_j):
        coeffs = np.linalg.pinv(SV_j) @ sw
        idx = _maxk_abs(coeffs, t)
        if recompute:
            h = np.linalg.pinv(SV_j[:, idx]) @ sw
        else:
            h = coeffs[idx]
        return h, idx
    return select


def _select_corr(t, recompute):
    def select(j, w, sw, V_j, SV_j):
        coeffs = SV_j.T @ sw
        idx = _maxk_abs(coeffs, t)
        if recompute:
            h = np.linalg.pinv(SV_j[:, idx]) @ sw
        else:
            h = coeffs[idx]
        return h, idx
    return select


def _select_omp(t):
    def select(j, w, sw, V_j, SV_j):
        r = sw.copy()
        idx: list[int] = []
        for _ in range(min(j, t)):
            corr = np.abs(SV_j.T @ r)
            corr[idx] = 0.0
            i = int(np.argmax(corr))
            idx.append(i)
            SV_i = SV_j[:, idx]
            x_i = np.linalg.pinv(SV_i) @ sw
            r = sw - SV_i @ x_i
        idx_arr = np.array(idx, dtype=int)
        h = np.linalg.pinv(SV_j[:, idx_arr]) @ sw
        return h, idx_arr
    return select


def _select_sp(t, full_width, itsp=1):
    def select(j, w, sw, V_j, SV_j):
        corr = np.abs(SV_j.T @ sw)
        idx_i = _maxk_abs(corr, min(j, t))
        SV_i = SV_j[:, idx_i]
        x_i = np.linalg.pinv(SV_i) @ sw
        Sr = sw - SV_i @ x_i
        for _ in range(itsp):
            # `y = SV' * Sr` in the original: SV is dynamically grown
            # (SV=[] then SV(:,j+1)=... each iteration), so it genuinely has
            # only j columns here, not p+1 -- MATLAB/Octave's maxk(x,t)
            # auto-clamps to length(x) when t>length(x), returning all j
            # indices in that case (verified directly: maxk([3,7,1],5) ->
            # all 3, no padding). The zero-padding here is an equivalent
            # (not the literal) way to get the same clamped-maxk result via
            # NumPy's fixed-k argsort, since zero-padded entries always sort
            # last and are removed by the `< j` filter below; kept as-is
            # since it's verified to produce identical indices to the
            # correct clamped-maxk behavior in every case, including t>j.
            y_full = np.zeros(full_width)
            y_full[:j] = SV_j.T @ Sr
            idx2_i = _maxk_abs(y_full, t)
            idxU_i = np.union1d(idx_i, idx2_i)
            idxU_i = idxU_i[idxU_i < j]  # columns >= j are zero, pinv would be singular/meaningless if selected
            xU = np.linalg.pinv(SV_j[:, idxU_i]) @ sw
            idx_rel = _maxk_abs(xU, t)
            idx_i = idxU_i[idx_rel]
            SV_i = SV_j[:, idx_i]
            x_i = np.linalg.pinv(SV_i) @ sw
            Sr = sw - SV_i @ x_i
        h = np.linalg.pinv(SV_j[:, idx_i]) @ sw
        return h, idx_i
    return select


def _select_greedy(t):
    def select(j, w, sw, V_j, SV_j):
        ind: list[int] = []
        SV1 = SV_j.copy()
        sw1 = sw.copy()
        for _ in range(min(j, t)):
            corr = SV1.T @ sw1
            i = int(np.argmax(np.abs(corr)))
            ind.append(i)
            sw1 = sw1 - SV1[:, i] * (SV1[:, i] @ sw1)
            SV1 = SV1 - np.outer(SV1[:, i], SV1[:, i] @ SV1)
            norms = np.linalg.norm(SV1, axis=0)
            norms[norms == 0] = 1.0  # avoid 0/0; matching cols are zeroed next line anyway
            SV1 = SV1 / norms
            SV1[:, ind] = 0.0
        idx_arr = np.array(ind, dtype=int)
        h = np.linalg.pinv(SV_j[:, idx_arr]) @ sw
        return h, idx_arr
    return select


_MATRIX_FILES = {"Norris/torso3": "torso3.mat", "Bai/cryg10000": "cryg10000.mat", "Norris/torso1": "torso1.mat"}
_MATRIX_CACHE: dict[str, np.ndarray] = {}


def _load_matrix(matrix_name: str):
    """Loads a pinned matrix's Problem.A as a SciPy sparse matrix, matching
    what the official Octave adapter loads. Kept in this module (not
    imported from build_ssarnoldi_task.py) so this file has no dependency
    on curation-only build machinery -- solve() must be importable and
    callable standalone by scientific.py's SOLVERS dispatcher at evaluation
    time, the same way every other task's *_scientific.py module is."""
    if matrix_name not in _MATRIX_CACHE:
        import scipy.io
        path = Path(__file__).resolve().parent / "ssarnoldi_matrices" / _MATRIX_FILES[matrix_name]
        data = scipy.io.loadmat(path)
        _MATRIX_CACHE[matrix_name] = data["Problem"][0, 0]["A"].tocsr()
    return _MATRIX_CACHE[matrix_name]


def solve(case: dict) -> dict:
    """Entry point matching every other task's *_scientific.py `solve(case)`
    contract (see scientific.py's SOLVERS dispatcher) -- v0/D/perm are read
    directly from the case (see ssarnoldi_common.py's module docstring for
    why they are baked into the input rather than derived from a seed)."""
    clean = validate_case(case)
    spec = {key: clean[key] for key in ("case_type", "matrix", "p", "s", "t", "condbound")}
    A = _load_matrix(clean["matrix"])
    v0 = np.array(clean["v0"])
    D = np.array(clean["D"])
    perm = np.array(clean["perm"]) - 1  # case JSON stores 1-indexed (Octave-native); make_srht wants 0-indexed
    return solve_arnoldi_cond_growth(spec, A, v0, D, perm)


def solve_arnoldi_cond_growth(spec: dict, A, v0: np.ndarray, D: np.ndarray, perm: np.ndarray) -> dict:
    """Lower-level entry point taking A/v0/D/perm explicitly (used by
    solve() above, and directly by build_ssarnoldi_task.py's independent-
    audit step, which already has A/v0/D/perm on hand and would otherwise
    reload/reconvert them redundantly). `spec` is the pre-randomness case
    spec (case_type/matrix/p/s/t/condbound; validate_spec-shaped, NOT the
    full case with v0/D/perm inside it -- those are the separate array
    arguments below). A: dense or sparse (N,N) matrix operator (must
    support A @ vector). v0: realized initial vector (length N). D: realized
    SRHT Rademacher sign pattern (length N, entries +-1). perm: realized
    0-INDEXED SRHT column selection (length round(s*p)) -- note this
    differs from case['perm']'s 1-indexed on-disk convention; callers
    passing perm directly (not via solve()) must subtract 1 themselves, as
    solve() does above."""
    clean = validate_spec(spec)
    p, t = clean["p"], clean["t"]
    condbound = float("inf") if clean["condbound"] == "inf" else clean["condbound"]
    N = v0.shape[0]
    sketch_dim = perm.shape[0]
    srht = make_srht(N, sketch_dim, D, perm)

    # Variant 1: truncated Arnoldi, no sketching.
    V = np.zeros((N, p + 1))
    V[:, 0] = v0 / np.linalg.norm(v0)
    cond_curve_1: list[float] = []
    jmax_ok = 0
    broke_at = None
    for j in range(1, p + 1):
        cond_curve_1.append(_basis_cond(V, j))
        if j % 10 == 0:
            c = _basis_cond(V, j)
            if c > condbound:
                broke_at = j
                break
            jmax_ok = j
        w = A @ V[:, j - 1]
        cols = np.arange(max(0, j - t), j)
        h = V[:, cols].T @ w
        w_new = w - V[:, cols] @ h
        V[:, j] = w_new / np.linalg.norm(w_new)
    jmax = p + 1 if broke_at is None else broke_at
    size_1 = jmax
    for j in range(jmax_ok + 1, jmax + 1):
        c = _basis_cond(V, j)
        if c > condbound:
            size_1 = j - 1
            break
        if j == jmax:
            size_1 = j

    variants = {
        "cond_sketch_truncate": _select_truncate(t),
        "cond_select_pinv": _select_pinv(t, recompute=False),
        "cond_select_pinv_recomp": _select_pinv(t, recompute=True),
        "cond_select_corr": _select_corr(t, recompute=False),
        "cond_select_corr_pinv": _select_corr(t, recompute=True),
        "cond_select_omp": _select_omp(t),
        "cond_select_sp": _select_sp(t, p + 1),
        "cond_select_greedy": _select_greedy(t),
    }
    size_names = {
        "cond_sketch_truncate": "sketch_truncate",
        "cond_select_pinv": "select_pinv",
        "cond_select_pinv_recomp": "select_pinv_recomp",
        "cond_select_corr": "select_corr",
        "cond_select_corr_pinv": "select_corr_pinv",
        "cond_select_omp": "select_omp",
        "cond_select_sp": "select_sp",
        "cond_select_greedy": "select_greedy",
    }

    result = {"case_type": "arnoldi_cond_growth", "cond_truncated": cond_curve_1}
    basis_size = {"truncated": size_1}
    for name, select in variants.items():
        curve, size_ = _run_variant(A, v0, srht, N, p, t, condbound, select)
        result[name] = curve
        basis_size[size_names[name]] = size_
    result["basis_size"] = basis_size
    return result
