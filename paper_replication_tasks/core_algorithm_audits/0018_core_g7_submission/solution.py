#!/usr/bin/env python3
import argparse
import json
import os

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.optimize import linprog
from scipy.sparse import coo_matrix


EDGES = ((0, 1), (0, 4), (0, 5), (1, 2), (2, 3), (3, 4), (4, 5))
GEN_REGIONS = (0, 2, 5, 0, 2, 5, 1, 4, 5)
STORAGE_REGIONS = (1, 4, 5)


def standardized_days(x):
    mean = x.mean(axis=(0, 1))
    sd = x.std(axis=(0, 1))
    sd[sd == 0] = 1.0
    return ((x - mean) / sd).reshape(len(x), -1)


def ward_groups(features, indices, count):
    indices = np.asarray(indices, dtype=int)
    count = min(count, len(indices))
    if count == len(indices):
        return [np.array([i], dtype=int) for i in indices]
    labels = fcluster(linkage(features[indices], method="ward"), count,
                      criterion="maxclust")
    return [indices[labels == label] for label in np.unique(labels)]


def aggregate(x, count, extreme=None, extra_features=None):
    features = standardized_days(x)
    if extra_features is not None:
        extra_features = np.asarray(extra_features, dtype=float)
        emean = extra_features.mean(axis=(0, 1))
        esd = extra_features.std(axis=(0, 1))
        esd[esd == 0] = 1.0
        e = ((extra_features - emean) / esd).reshape(len(x), -1)
        features = np.concatenate((features, e), axis=1)
    all_indices = np.arange(len(x))
    if extreme is None or len(extreme) == 0:
        groups = ward_groups(features, all_indices, count)
    else:
        extreme = np.asarray(extreme, dtype=int)
        regular = np.setdiff1d(all_indices, extreme)
        ne = min(count // 2, len(extreme))
        groups = ward_groups(features, regular, count - ne)
        groups += ward_groups(features, extreme, ne)
    groups.sort(key=lambda a: int(a.min()))
    labels = np.empty(len(x), dtype=int)
    representatives = []
    weights = []
    for k, ids in enumerate(groups):
        labels[ids] = k
        center = features[ids].mean(axis=0)
        representatives.append(int(ids[np.argmin(np.sum((features[ids] - center) ** 2,
                                                        axis=1))]))
        weights.append(int(len(ids)))
    return np.array(representatives), np.array(weights), labels


def planning_model(x, representatives, weights, labels, fixed_caps=None,
                   return_operation=False, cost_epsilon=0.0, cost_factors=None,
                   temporal_tiebreak=0.0, storage_loss=0.00001,
                   solver_method="highs"):
    """Chronology-preserving representative-day linear planning model."""
    n_days, hours, _ = x.shape
    n_rep = len(representatives)
    repx = x[representatives]
    n_rh = n_rep * hours
    n_full = n_days * hours

    # 19 capacities; per representative-hour: 9 generation, 7 line flows,
    # 3 charges, 3 discharges and 6 unserved-load variables; per original
    # hour: 3 storage levels.
    op0 = 19
    op_width = 28
    sto0 = op0 + op_width * n_rh
    nvar = sto0 + 3 * n_full

    objective = np.zeros(nvar)
    annual = np.array([300000.] * 3 + [100000.] * 3 + [100000.] * 3 +
                      [100000., 150000., 100000., 100000., 100000., 100000., 100000.] +
                      [1000.] * 3)
    # Region-dependent infinitesimal tie breaker used by the model.
    cost_regions = np.array([1, 3, 6, 1, 3, 6, 2, 5, 6,
                             1.5, 3., 3.5, 2.5, 3.5, 4.5, 5.5,
                             2, 5, 6], dtype=float)
    annual *= 1.0 + cost_epsilon * cost_regions
    if cost_factors is not None:
        annual *= np.asarray(cost_factors)
    if fixed_caps is None:
        objective[:19] = annual * (n_full / 8760.)
    for k in range(n_rep):
        for h in range(hours):
            base = op0 + op_width * (k * hours + h)
            gen_region_factor = 1.0 + cost_epsilon * np.array([1., 3., 6.])
            objective[base:base + 3] = 5. * weights[k] * gen_region_factor
            objective[base + 3:base + 6] = 35. * weights[k] * gen_region_factor
            objective[base + 22:base + 28] = (6000. * weights[k] *
                                               (1. + temporal_tiebreak * k))

    eq_i, eq_j, eq_v = [], [], []
    beq = []
    def eqrow(entries, rhs):
        row = len(beq)
        for col, value in entries:
            eq_i.append(row); eq_j.append(col); eq_v.append(value)
        beq.append(rhs)

    # Regional power balances for representative hours.
    for k in range(n_rep):
        for h in range(hours):
            base = op0 + op_width * (k * hours + h)
            demands = (0., repx[k, h, 0], 0., repx[k, h, 1], repx[k, h, 2], 0.)
            for region in range(6):
                entries = []
                entries += [(base + g, 1.) for g, rr in enumerate(GEN_REGIONS) if rr == region]
                for edge, (left, right) in enumerate(EDGES):
                    if region == left: entries.append((base + 9 + edge, -1.))
                    if region == right: entries.append((base + 9 + edge, 1.))
                for s, rr in enumerate(STORAGE_REGIONS):
                    if rr == region:
                        entries.append((base + 16 + s, -1.))
                        entries.append((base + 19 + s, 1.))
                entries.append((base + 22 + region, 1.))
                eqrow(entries, demands[region])

    # Actual storage chronology; representative-day charge patterns are reused.
    decay = 1. - storage_loss
    efficiency = 0.95
    for day in range(n_days):
        k = int(labels[day])
        for h in range(hours):
            obase = op0 + op_width * (k * hours + h)
            full_t = day * hours + h
            for s in range(3):
                entries = [(sto0 + 3 * full_t + s, 1.),
                           (obase + 16 + s, -efficiency),
                           (obase + 19 + s, 1. / efficiency)]
                if full_t > 0:
                    entries.append((sto0 + 3 * (full_t - 1) + s, -decay))
                eqrow(entries, 0.)

    ub_i, ub_j, ub_v = [], [], []
    bub = []
    def ubrow(entries, rhs=0.):
        row = len(bub)
        for col, value in entries:
            ub_i.append(row); ub_j.append(col); ub_v.append(value)
        bub.append(rhs)

    for k in range(n_rep):
        for h in range(hours):
            base = op0 + op_width * (k * hours + h)
            for g in range(6):
                ubrow(((base + g, 1.), (g, -1.)))
            for g in range(3):
                ubrow(((base + 6 + g, 1.), (6 + g, -repx[k, h, 3 + g])))
            for edge in range(7):
                ubrow(((base + 9 + edge, 1.), (9 + edge, -1.)))
                ubrow(((base + 9 + edge, -1.), (9 + edge, -1.)))
    for full_t in range(n_full):
        for s in range(3):
            ubrow(((sto0 + 3 * full_t + s, 1.), (16 + s, -1.)))

    Aeq = coo_matrix((eq_v, (eq_i, eq_j)), shape=(len(beq), nvar)).tocsr()
    Aub = coo_matrix((ub_v, (ub_i, ub_j)), shape=(len(bub), nvar)).tocsr()
    bounds = [(0., None)] * nvar
    for k in range(n_rep):
        for h in range(hours):
            base = op0 + op_width * (k * hours + h)
            for edge in range(7):
                bounds[base + 9 + edge] = (None, None)
            # Load shedding belongs to the diagnostic operation model.  The
            # capacity-planning model itself must meet every representative
            # hour, as in equations B.4--B.14.
            if fixed_caps is None:
                for region in range(6):
                    bounds[base + 22 + region] = (0., 0.)
    if fixed_caps is not None:
        for j, value in enumerate(fixed_caps):
            bounds[j] = (float(value), float(value))

    result = linprog(objective, A_ub=Aub, b_ub=np.asarray(bub),
                     A_eq=Aeq, b_eq=np.asarray(beq), bounds=bounds,
                     method=solver_method)
    if not result.success:
        raise RuntimeError(result.message)
    caps = result.x[:19]
    totals = np.array([caps[:3].sum(), caps[3:6].sum(), caps[6:9].sum(),
                       caps[16:19].sum(), caps[9:16].sum()])
    if not return_operation:
        return totals, caps
    generation = np.empty((n_rep, hours, 24))
    for k in range(n_rep):
        for h in range(hours):
            base = op0 + op_width * (k * hours + h)
            generation[k, h, :9] = result.x[base:base + 9]
            generation[k, h, 9:15] = result.x[base + 22:base + 28]
            generation[k, h, 15:18] = result.x[base + 16:base + 19]
            generation[k, h, 18:21] = result.x[base + 19:base + 22]
            # This is meaningful when each original day is a representative,
            # as in the full operation call below.
            full_t = k * hours + h
            if full_t < n_full:
                generation[k, h, 21:24] = result.x[sto0 + 3 * full_t:sto0 + 3 * full_t + 3]
    return totals, caps, generation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with open(args.input) as f:
        data = json.load(f)
    x = np.asarray(data["x"], dtype=float)
    n = int(data["n"])
    proportion = float(data["p"])
    method = int(data["q"])

    # First-stage, a-priori medoid aggregation and planning run.
    r0, w0, z0 = aggregate(x, n)
    _, preliminary_caps = planning_model(x, r0, w0, z0)

    # Operate the preliminary design on every original day.  Treating each
    # day as its own representative gives the unaggregated operation problem.
    days = np.arange(len(x), dtype=int)
    _, _, operation = planning_model(
        x, days, np.ones(len(x), dtype=int), days,
        fixed_caps=preliminary_caps, return_operation=True)
    unserved = operation[:, :, 9:15].sum(axis=(1, 2))
    generation_cost = ((5. * operation[:, :, :3]).sum(axis=(1, 2)) +
                       (35. * operation[:, :, 3:6]).sum(axis=(1, 2)) +
                       6000. * unserved)
    importance = unserved if method == 0 else generation_cost
    n_extreme = max(1, min(len(x), int(proportion * len(x))))
    # Stable sorting is material when several capacity-limited days have the
    # same cost: chronological order is the paper implementation's tie-break.
    extreme = np.sort(np.argsort(-importance, kind="stable")[:n_extreme])

    extra = None
    if method == 2:
        # Method F clusters on the signed storage (dis)charge decisions as
        # well as the demand/weather inputs.
        extra = operation[:, :, 15:18] - operation[:, :, 18:21]
    r, w, z = aggregate(x, n, extreme=extreme, extra_features=extra)
    y, _ = planning_model(x, r, w, z)
    answer = {"r": r.tolist(), "w": w.tolist(), "y": y.tolist(), "z": z.tolist()}
    os.makedirs(args.output, exist_ok=True)
    with open(os.path.join(args.output, "output.json"), "w") as f:
        json.dump(answer, f, allow_nan=False)


if __name__ == "__main__":
    main()
