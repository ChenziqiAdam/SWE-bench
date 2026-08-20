"""Independent rational-empirical-interpolation-method (rEIM) implementation
for task 0021.

Clean-room reimplementation of Algorithm 2.1 (rEIM) from Li & Li, "A new
rational approximation algorithm via the empirical interpolation method"
(SISC), Section 2, plus the fractional-Laplacian P1-FEM application
(Section 3.1) and the adaptive-step BDF2 fractional-heat scheme
(Section 3.3). Used only to audit the pinned official Octave/MATLAB gold,
never to generate it.

The greedy recurrence follows Algorithm 2.1's mathematical statement
directly (select g_m maximizing the residual over the candidate pole set,
select x_m maximizing the pointwise residual, rebuild the Gram matrix), not
REIM.m's code structure -- xset/bset candidate-set constructions are taken
from the paper's own stated dictionary D(B) = {1/(x+b) : b in B} tuned
finer near the origin for singular target functions (Section 5.1), matching
what the officially published rEIM.m uses for these same four intervals.
"""

from __future__ import annotations

import numpy as np

try:
    from .reim_common import validate_case
except ImportError:  # direct curator-script execution
    from reim_common import validate_case


def _candidate_sets(a: float, b: float, family: str) -> tuple[np.ndarray, np.ndarray]:
    if a == 1e-6 and b == 1.0:
        xset = np.unique(np.concatenate([
            np.linspace(a, 0.001, 2001),
            np.linspace(0.001, 0.01, 2001),
            np.linspace(0.01, b, 4001),
        ]))
        if family == "power":
            bset = 10.0 ** np.linspace(-7, 1, 1000)
        elif family in ("time", "precon"):
            bset = 10.0 ** np.linspace(-6, 2, 1000)
        else:
            raise ValueError("unsupported family for interval [1e-6,1]")
    elif a == 1e-8 and b == 1.0 and family == "power":
        c, d = 1e-5, 1e-2
        xset = np.unique(np.concatenate([
            np.linspace(a, c, 3001), np.linspace(c, d, 3001), np.linspace(d, b, 3001),
        ]))
        bset = 10.0 ** np.linspace(-10, 1, 1000)
    elif a == 1.0 and b == 1e6 and family == "exp":
        c, d = b / 1e4, b / 1e2
        xset = np.unique(np.concatenate([
            np.linspace(a, c, 3001), np.linspace(c, d, 3001), np.linspace(d, b, 3001),
        ]))
        bset = 10.0 ** np.linspace(0, 3, 1000)
    else:
        raise ValueError("candidate set not defined for this (a,b,family)")
    return xset, bset


def reim(M: int, a: float, b: float, family: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Algorithm 2.1: greedy rational empirical interpolation. Returns
    (xm, bm, G) -- interpolation points, poles, and the m-by-m Gram matrix
    G[i,j] = 1/(xm[i]+bm[j])."""
    xset, bset = _candidate_sets(a, b, family)
    gset_all = 1.0 / (xset[:, None] + bset[None, :])  # dictionary evaluated on xset for every candidate pole

    bm = np.zeros(M)
    xm = np.zeros(M)
    gm = np.zeros((len(xset), M))

    bm[0] = bset[0]
    gm[:, 0] = gset_all[:, 0]
    xm[0] = xset[np.argmax(np.abs(gm[:, 0]))]
    G = np.array([[1.0 / (xm[0] + bm[0])]])

    for m in range(1, M):
        rhs_all = 1.0 / (xm[:m, None] + bset[None, :])
        coef_all = np.linalg.solve(G, rhs_all)
        residual_all = gset_all - gm[:, :m] @ coef_all
        L = np.max(np.abs(residual_all), axis=0)
        idb = np.argmax(L)
        bm[m] = bset[idb]
        gm[:, m] = gset_all[:, idb]

        rhs = 1.0 / (xm[:m] + bm[m])
        coef = np.linalg.solve(G, rhs)
        rm = gm[:, m] - gm[:, :m] @ coef
        xm[m] = xset[np.argmax(np.abs(rm))]

        pts, poles = xm[: m + 1], bm[: m + 1]
        G = 1.0 / (pts[:, None] + poles[None, :])

    return xm, bm, G


def _linf_error(xtest: np.ndarray, ftest: np.ndarray, xm: np.ndarray, bm: np.ndarray,
                 G: np.ndarray, fxm: np.ndarray) -> float:
    gtest = 1.0 / (xtest[:, None] + bm[None, :])
    coef = np.linalg.solve(G, fxm)
    return float(np.max(np.abs(ftest - gtest @ coef)))


def _solve_family(case: dict) -> dict:
    case_type = case["case_type"]
    a, b, M = case["a"], case["b"], case["M"]
    family = {"rational_approx": "power", "time_family_approx": "time",
              "exp_family_approx": "exp", "precon_family_approx": "precon"}[case_type]
    xm, bm, G = reim(M, a, b, family)

    xtest = np.linspace(a, b, int(5e5))
    if family == "power":
        s = case["s"]
        ftest = xtest ** (-s)
        fxm = xm ** (-s)
    elif family == "time":
        s, d, Lambda = case["s"], case["d"], case["Lambda"]
        ftest = 1.0 / (xtest ** s + d / Lambda ** s)
        fxm = 1.0 / (xm ** s + d / Lambda ** s)
    elif family == "exp":
        tau = case["tau"]
        ftest = np.exp(-tau * xtest)
        fxm = np.exp(-tau * xm)
    else:
        K = case["K"]
        ftest = 1.0 / (xtest ** (-0.5) + K * xtest ** 0.5)
        fxm = 1.0 / (xm ** (-0.5) + K * xm ** 0.5)

    linf_error = _linf_error(xtest, ftest, xm, bm, G, fxm)
    return {
        "case_type": case_type, "xm": xm.tolist(), "bm": bm.tolist(),
        "G": G.tolist(), "Linf_error": linf_error,
    }


# --- Fractional-Laplacian P1-FEM application (Section 3.1) ------------------

def _square_mesh(x0, x1, y0, y1, h):
    xs = np.arange(x0, x1 + h / 2, h)
    ys = np.arange(y0, y1 + h / 2, h)
    X, Y = np.meshgrid(xs, ys)
    node = np.column_stack([X.ravel(order="F"), Y.ravel(order="F")])
    ni = len(ys)
    N = node.shape[0]
    t2n = np.arange(1, N - ni + 1)
    top = np.arange(ni, N - ni + 1, ni)
    t2n = np.setdiff1d(t2n, top, assume_unique=False)
    k = t2n
    elem = np.vstack([
        np.column_stack([k + ni, k + ni + 1, k]),
        np.column_stack([k + 1, k, k + ni + 1]),
    ]) - 1  # to 0-indexed
    return node, elem.astype(int)


def _uniform_refine(node, elem):
    edges = np.vstack([elem[:, [1, 2]], elem[:, [2, 0]], elem[:, [0, 1]]])
    edges_sorted = np.sort(edges, axis=1)
    uniq, inverse = np.unique(edges_sorted, axis=0, return_inverse=True)
    NT = elem.shape[0]
    elem2edge = inverse.reshape(3, NT).T
    N = node.shape[0]
    NE = uniq.shape[0]
    new_node = (node[uniq[:, 0]] + node[uniq[:, 1]]) / 2
    node2 = np.vstack([node, new_node])
    e2n = N + np.arange(NE)

    p1, p2, p3 = elem[:, 0], elem[:, 1], elem[:, 2]
    p4, p5, p6 = e2n[elem2edge[:, 0]], e2n[elem2edge[:, 1]], e2n[elem2edge[:, 2]]
    elem2 = np.vstack([
        np.column_stack([p1, p6, p5]),
        np.column_stack([p6, p2, p4]),
        np.column_stack([p5, p4, p3]),
        np.column_stack([p4, p5, p6]),
    ])
    return node2, elem2.astype(int)


def _boundary_free_dofs(node, elem):
    edges = np.vstack([elem[:, [1, 2]], elem[:, [2, 0]], elem[:, [0, 1]]])
    edges_sorted = np.sort(edges, axis=1)
    uniq, counts = np.unique(edges_sorted, axis=0, return_counts=True)
    boundary_edges = uniq[counts == 1]
    boundary_nodes = np.unique(boundary_edges)
    all_nodes = np.arange(node.shape[0])
    return np.setdiff1d(all_nodes, boundary_nodes)


def _p1_assemble(node, elem):
    from scipy.sparse import coo_matrix

    NT = elem.shape[0]
    p = node[elem]  # NT x 3 x 2
    ve = np.stack([p[:, 2] - p[:, 1], p[:, 0] - p[:, 2], p[:, 1] - p[:, 0]], axis=1)
    area = 0.5 * (-ve[:, 2, 0] * ve[:, 1, 1] + ve[:, 2, 1] * ve[:, 1, 0])
    Dl = np.zeros((NT, 3, 2))
    Dl[:, 2] = np.column_stack([-ve[:, 2, 1] / (2 * area), ve[:, 2, 0] / (2 * area)])
    Dl[:, 0] = np.column_stack([-ve[:, 0, 1] / (2 * area), ve[:, 0, 0] / (2 * area)])
    Dl[:, 1] = np.column_stack([-ve[:, 1, 1] / (2 * area), ve[:, 1, 0] / (2 * area)])

    ii = elem[:, [0, 1, 2, 0, 0, 1, 1, 2, 2]]
    jj = elem[:, [0, 1, 2, 1, 2, 2, 0, 0, 1]]
    Mvals = np.column_stack([
        np.repeat(area / 6, 3).reshape(3, NT).T if False else np.tile(area / 6, (3, 1)).T,
        np.tile(area / 12, (6, 1)).T,
    ])
    d12 = area * np.sum(Dl[:, 0] * Dl[:, 1], axis=1)
    d13 = area * np.sum(Dl[:, 0] * Dl[:, 2], axis=1)
    d23 = area * np.sum(Dl[:, 1] * Dl[:, 2], axis=1)
    Avals = np.column_stack([
        area * np.sum(Dl[:, 0] * Dl[:, 0], axis=1),
        area * np.sum(Dl[:, 1] * Dl[:, 1], axis=1),
        area * np.sum(Dl[:, 2] * Dl[:, 2], axis=1),
        d12, d13, d23, d12, d13, d23,
    ])
    NV = node.shape[0]
    M = coo_matrix((Mvals.ravel(), (ii.ravel(), jj.ravel())), shape=(NV, NV)).tocsr()
    A = coo_matrix((Avals.ravel(), (ii.ravel(), jj.ravel())), shape=(NV, NV)).tocsr()
    return A, M, area


def _p1_rhs(node, elem, area, f):
    centroid = (node[elem[:, 0]] + node[elem[:, 1]] + node[elem[:, 2]]) / 3
    fpxy = f(centroid)
    bt = np.tile((fpxy * area / 3)[:, None], (1, 3))
    NV = node.shape[0]
    rhs = np.zeros(NV)
    np.add.at(rhs, elem.ravel(order="F"), bt.ravel(order="F"))
    return rhs


def _u_exact_fractional(p, s, m=2000):
    z = np.zeros(p.shape[0])
    for i in range(1, m + 1, 2):
        sinpix = np.sin(i * np.pi * 0.5 * (p[:, 0] + 1))
        for j in range(1, m + 1, 2):
            z = z + (0.25 * (i ** 2 + j ** 2) * np.pi ** 2) ** (-s) * 16 / i / j / np.pi ** 2 * sinpix * np.sin(j * np.pi * 0.5 * (p[:, 1] + 1))
    return z


def _graded_refine(node, elem, Nmax, theta=6, maxit=30):
    for _ in range(maxit):
        NV = node.shape[0]
        if NV >= Nmax:
            break
        _, _, area = _p1_assemble(node, elem)
        mid = (node[elem[:, 0]] + node[elem[:, 1]] + node[elem[:, 2]]) / 3
        dist = np.minimum(np.minimum(np.minimum(np.abs(mid[:, 0] - 1), np.abs(mid[:, 0] + 1)),
                                      np.abs(mid[:, 1] - 1)), np.abs(mid[:, 1] + 1))
        marker = area > (theta / NV * np.log10(NV) * dist)
        node, elem = _bisect(node, elem, marker)
    return node, elem


def _auxstructure_neighbor1(elem):
    """Port of auxstructure.m/myauxstructure.m restricted to what bisect.m
    uses: elem2edge (edge index opposite vertex i, i.e. edge (i+1,i+2)) and
    neighbor(:,1) (element sharing elem2edge(:,1))."""
    NT = elem.shape[0]
    total_edge = np.vstack([elem[:, [1, 2]], elem[:, [2, 0]], elem[:, [0, 1]]])
    total_edge_sorted = np.sort(total_edge, axis=1)
    edge, j = np.unique(total_edge_sorted, axis=0, return_inverse=True)
    elem2edge = j.reshape(3, NT).T

    edge0_to_elems: dict[int, list[int]] = {}
    for t in range(NT):
        edge0_to_elems.setdefault(int(elem2edge[t, 0]), []).append(t)
    neighbor0 = np.full(NT, -1, dtype=int)
    for _, ts in edge0_to_elems.items():
        if len(ts) == 2:
            neighbor0[ts[0]] = ts[1]
            neighbor0[ts[1]] = ts[0]
    return edge, elem2edge, neighbor0


def _bisect(node, elem, marked):
    """Newest-vertex bisection, ported directly from bisect.m's algorithm
    (no bdFlag/tree/HB outputs, which the graded-mesh refinement loop here
    does not consume). edge2newNode is computed once from the pre-bisection
    elem2edge numbering and elem2edge(:,1) is updated in place across the
    two-pass loop exactly as bisect.m does -- NOT recomputed from a fresh
    unique() on the growing element list, which would desynchronize the
    edge2newNode indexing (this was a real bug caught by testing against the
    official adapter's mesh vertex counts)."""
    edge, elem2edge, neighbor0 = _auxstructure_neighbor1(elem)
    N = node.shape[0]
    NT = elem.shape[0]
    NE = edge.shape[0]

    marked_idx = np.nonzero(marked)[0].tolist()
    is_cut = np.zeros(NE, dtype=bool)
    queue = list(marked_idx)
    while queue:
        next_queue: list[int] = []
        for t in queue:
            e0 = int(elem2edge[t, 0])
            is_cut[e0] = True
        for t in queue:
            nb = neighbor0[t]
            if nb >= 0 and not is_cut[int(elem2edge[nb, 0])]:
                next_queue.append(nb)
        queue = next_queue

    edge2new = np.zeros(NE, dtype=int) - 1
    cut_edges = np.nonzero(is_cut)[0]
    edge2new[cut_edges] = N + np.arange(len(cut_edges))
    new_node = (node[edge[cut_edges, 0]] + node[edge[cut_edges, 1]]) / 2
    node2 = np.vstack([node, new_node]) if len(new_node) else node.copy()

    elem_list = elem.copy()
    e2e = elem2edge.copy()
    cur_NT = NT
    for _ in range(2):
        t = np.nonzero(edge2new[e2e[:, 0]] >= 0)[0]
        new_NT = len(t)
        if new_NT == 0:
            break
        L = t
        R = np.arange(cur_NT, cur_NT + new_NT)
        p1, p2, p3 = elem_list[t, 0], elem_list[t, 1], elem_list[t, 2]
        p4 = edge2new[e2e[t, 0]]

        new_size = cur_NT + new_NT
        elem_grown = np.zeros((new_size, 3), dtype=int)
        elem_grown[:cur_NT] = elem_list
        elem_grown[L] = np.column_stack([p4, p1, p2])
        elem_grown[R] = np.column_stack([p4, p3, p1])

        e2e_grown = np.zeros((new_size, 3), dtype=int)
        e2e_grown[:cur_NT] = e2e
        e2e_grown[R] = e2e[t]  # placeholder rows for the new elements' other 2 edge slots (unused below)
        e2e_grown[L, 0] = e2e[t, 2]
        e2e_grown[R, 0] = e2e[t, 1]

        elem_list = elem_grown
        e2e = e2e_grown
        cur_NT = new_size

    return node2, elem_list.astype(int)


def _solve_fractional_fem(case: dict) -> dict:
    s, res, pol = case["s"], np.asarray(case["res"]), np.asarray(case["pol"])
    mesh_type, mesh_param = case["mesh_type"], case["mesh_param"]

    node, elem = _square_mesh(-1, 1, -1, 1, 0.25)
    for _ in range(2):
        node, elem = _uniform_refine(node, elem)

    if mesh_type == "uniform":
        for _ in range(mesh_param):
            node, elem = _uniform_refine(node, elem)
        Lambda = 1e6
    else:
        node, elem = _graded_refine(node, elem, mesh_param)
        Lambda = 1e8

    A, M, area = _p1_assemble(node, elem)
    b_rhs = _p1_rhs(node, elem, area, lambda p: np.ones(p.shape[0]))
    fv = _boundary_free_dofs(node, elem)
    AA = A[fv][:, fv]
    MM = M[fv][:, fv]
    rhs = b_rhs[fv] / Lambda ** s

    from scipy.sparse import identity
    from scipy.sparse.linalg import spsolve

    x = np.zeros(len(fv))
    for j in range(len(pol)):
        Kmat = (AA / Lambda + pol[j] * MM).tocsc()
        x = x + res[j] * spsolve(Kmat, rhs)

    uh = np.zeros(node.shape[0])
    uh[fv] = x
    uexact = _u_exact_fractional(node, s)
    e = uh - uexact
    l2_error = float(np.sqrt(e @ (M @ e)))

    return {"case_type": "fractional_fem", "s": s, "mesh_type": mesh_type,
            "N": int(node.shape[0]), "L2_error": l2_error}


# --- Adaptive BDF2 fractional heat equation (Section 3.3) -------------------

def _u_bdf2(t, p):
    return np.exp(-t / 20) * np.cos(2 * np.pi * t) * np.sin(np.pi * p[:, 0]) * np.sin(np.pi * p[:, 1])


def _f_bdf2(t, p, s):
    return (-1 / 20 + (2 * np.pi ** 2) ** s) * _u_bdf2(t, p) - 2 * np.pi * np.exp(-t / 20) * np.sin(2 * np.pi * t) * np.sin(np.pi * p[:, 0]) * np.sin(np.pi * p[:, 1])


def _solve_bdf2(case: dict) -> dict:
    from scipy.sparse.linalg import splu

    s, M, Lambda = case["s"], case["M"], case["Lambda"]
    tol, tau0_init, tend, h_exp = case["tol"], case["tau0"], case["tend"], case["mesh_h_exponent"]

    Xm, Bm, _ = reim(M, 1e-6, 1.0, "time")
    gx = 1.0 / (Xm[:, None] + Bm[None, :])

    node, elem = _square_mesh(0, 1, 0, 1, 0.125)
    for _ in range(h_exp - 3):
        node, elem = _uniform_refine(node, elem)
    S, Mass, _ = _p1_assemble(node, elem)
    fv = _boundary_free_dofs(node, elem)
    Sf = (S[fv][:, fv]).tocsc()
    Mf = (Mass[fv][:, fv]).tocsc()

    lu_factors = [splu((Sf / Lambda + Bm[i] * Mf).tocsc()) for i in range(len(Bm))]

    tau = [tau0_init]
    T = [0.0]
    tau0 = tau0_init
    err: list[float] = []
    errest: list[float] = []
    Tdel: list[float] = []
    taudel: list[float] = []
    Uarray = [_u_bdf2(0.0, node[fv])]
    _, area = None, None
    _, _, area = _p1_assemble(node, elem)

    while T[-1] <= tend:
        j = len(T)  # 0-indexed len(T) == MATLAB's j (1-indexed) - 1 offset absorbed below
        t_next = T[-1] + tau0
        uexact_j = _u_bdf2(t_next, node[fv])
        rhs_full = _p1_rhs(node, elem, area, lambda p: _f_bdf2(t_next, p, s))
        fn_j = rhs_full[fv]

        fx = 1.0 / (Xm ** s + 1 / (tau0 * Lambda ** s))
        res_c = np.linalg.solve(gx, fx)
        Uj = Uarray[-1]
        F = ((Mf @ Uj) / tau0 + fn_j) / Lambda ** s

        a_step = tau[-1]
        k0 = (a_step + 2 * tau0) / (tau0 * (a_step + tau0))
        k1 = -(a_step + tau0) / (a_step * tau0)
        k2 = tau0 / (a_step * (a_step + tau0))
        if len(T) > 1:
            Ui = Uarray[-2]
            G_rhs = (-k1 * (Mf @ Uj) - k2 * (Mf @ Ui) + fn_j) / Lambda ** s
        else:
            G_rhs = F
        hx = 1.0 / (Xm ** s + k0 / Lambda ** s)
        res2_c = np.linalg.solve(gx, hx)

        U1 = np.zeros(len(fv))
        U2 = np.zeros(len(fv))
        for i in range(len(Bm)):
            solved = lu_factors[i].solve(np.column_stack([F, G_rhs]))
            U1 = U1 + res_c[i] * solved[:, 0]
            U2 = U2 + res2_c[i] * solved[:, 1]
        if len(T) == 1:
            U2 = U1.copy()
        cur_errest = float(np.sqrt((U1 - U2) @ (Mf @ (U1 - U2))))
        errest.append(cur_errest)

        if cur_errest <= tol:
            # bisect.m/BDF2_FEM.m's `tau(j-1) = tau0` OVERWRITES tau(1) on the
            # very first accepted step (tau starts as the scalar tau0_init,
            # a placeholder only used for a_step in that first iteration),
            # then appends from the second accept onward. Appending
            # unconditionally here would leave an extra stale tau0_init
            # entry, shifting every subsequent a_step = tau[-1] read by one
            # step relative to the official code (caught by cross-checking
            # against the official adapter's exact T/tau/err arrays).
            if len(T) == 1:
                tau[0] = tau0
            else:
                tau.append(tau0)
            T.append(T[-1] + tau0)
            Uarray.append(U1)
            cur_err = float(np.sqrt((U1 - uexact_j) @ (Mf @ (U1 - uexact_j))))
            err.append(cur_err)
            tau0 = 0.8 * tau0 * (tol / max(cur_errest, 1e-6)) ** 0.5
            if T[-1] + tau0 > tend:
                if T[-2] >= tend:
                    break
                tau0 = tend - T[-1]
        else:
            Tdel.append(T[-1] + tau0)
            taudel.append(tau0)
            tau0 = 0.8 * tau0 * (tol / cur_errest) ** 0.5
        if tau0 <= 1e-4:
            break

    return {"case_type": "bdf2_fractional_heat", "s": s, "T": T, "err": [0.0] + err,
            "tau": tau, "Tdel": Tdel, "taudel": taudel}


def solve(case: dict) -> dict:
    clean = validate_case(case)
    case_type = clean["case_type"]
    if case_type in ("rational_approx", "time_family_approx", "exp_family_approx", "precon_family_approx"):
        return _solve_family(clean)
    if case_type == "fractional_fem":
        return _solve_fractional_fem(clean)
    if case_type == "bdf2_fractional_heat":
        return _solve_bdf2(clean)
    raise ValueError(f"unsupported case_type: {case_type}")
