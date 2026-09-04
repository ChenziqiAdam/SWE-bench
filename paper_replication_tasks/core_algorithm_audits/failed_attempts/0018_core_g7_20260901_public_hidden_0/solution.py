#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.optimize import linprog
from scipy.sparse import coo_matrix


EDGES = [(0, 1), (0, 4), (0, 5), (1, 2), (2, 3), (3, 4), (4, 5)]
GEN_REG = np.array([0, 2, 5, 0, 2, 5, 1, 4, 5])
GEN_KIND = np.array([0, 0, 0, 1, 1, 1, 2, 2, 2])  # base, peak, wind
STOR_REG = np.array([1, 4, 5])


def standardize(x):
    """Paper convention: each full hourly series has mean 0 and variance 1."""
    mu = x.mean(axis=(0, 1))
    sd = x.std(axis=(0, 1))
    sd = np.where(sd == 0, 1.0, sd)
    return (x - mu) / sd


def ward_groups(a, ids, count):
    ids = np.asarray(ids, dtype=int)
    if count >= len(ids):
        return [np.array([i], dtype=int) for i in ids]
    lab = fcluster(linkage(a[ids], method="ward"), count, criterion="maxclust")
    return [ids[lab == k] for k in range(1, lab.max() + 1)]


def aggregate(x, n, extreme=None, extra=None):
    a = standardize(x).reshape(len(x), -1)
    if extra is not None:
        e = np.asarray(extra, float)
        em, es = e.mean(axis=(0, 1)), e.std(axis=(0, 1))
        es = np.where(es == 0, 1.0, es)
        a = np.column_stack((a, ((e - em) / es).reshape(len(e), -1)))

    if extreme is None:
        groups = ward_groups(a, np.arange(len(x)), n)
    else:
        extreme = np.sort(np.asarray(extreme, dtype=int))
        regular = np.setdiff1d(np.arange(len(x)), extreme)
        if len(extreme) == 0:
            groups = ward_groups(a, regular, n)
            extreme = None
        else:
            ne = min(n // 2, len(extreme))
            nr = n - ne
            groups = ward_groups(a, regular, nr) + ward_groups(a, extreme, ne)

    # Stable public label convention: clusters are numbered at first occurrence.
    groups.sort(key=lambda g: g.min())
    z = np.empty(len(x), dtype=int)
    r = []
    for k, g in enumerate(groups):
        z[g] = k
        # A medoid is the real day nearest the cluster mean. Computing the
        # equivalent pairwise squared-distance sum makes two-point ties stable.
        d = ((a[g, None, :] - a[None, g, :]) ** 2).sum(axis=2).sum(axis=1)
        r.append(int(g[np.argmin(d)]))
    return np.asarray(r), np.bincount(z, minlength=len(groups)), z


class MatrixBuilder:
    def __init__(self, nv):
        self.nv = nv
        self.rr = []
        self.cc = []
        self.dd = []
        self.b = []

    def row(self, terms, rhs):
        row = len(self.b)
        for col, val in terms:
            if val:
                self.rr.append(row); self.cc.append(col); self.dd.append(val)
        self.b.append(rhs)

    def matrix(self):
        return coo_matrix((self.dd, (self.rr, self.cc)),
                          shape=(len(self.b), self.nv)).tocsr(), np.asarray(self.b)


def energy_lp(days, z, fixed_caps=None, want_operation=False, perturb=None):
    """Six-region model in Appendix B, with ordered representative days."""
    days = np.asarray(days, float)
    z = np.asarray(z, int)
    kdays, ndays = len(days), len(z)
    nh = ndays * 24
    weights = np.bincount(z, minlength=kdays)

    # cap: 3 base, 3 peak, 3 wind, 7 links, 3 stores
    off_cap = 0
    off_gen = 22
    off_flow = off_gen + kdays * 24 * 9
    off_cp = off_flow + kdays * 24 * 7
    off_cd = off_cp + kdays * 24 * 3
    off_s = off_cd + kdays * 24 * 3
    off_shed = off_s + nh * 3
    nshed = nh * 3 if fixed_caps is not None else 0
    nv = off_shed + nshed

    def gi(k, h, g): return off_gen + (k * 24 + h) * 9 + g
    def fi(k, h, e): return off_flow + (k * 24 + h) * 7 + e
    def cpi(k, h, s): return off_cp + (k * 24 + h) * 3 + s
    def cdi(k, h, s): return off_cd + (k * 24 + h) * 3 + s
    def si(t, s): return off_s + t * 3 + s
    def ui(t, s): return off_shed + t * 3 + s

    # Optional multiplier vectors are useful for faithfully representing the
    # paper's tiny regional tie-breaking perturbations.
    if perturb is None:
        pcap = np.ones(19); pgen = np.ones(9)
    else:
        pcap, pgen = perturb
    c = np.zeros(nv)
    if fixed_caps is None:
        annual = nh / 8760.0
        c[:9] = annual * np.r_[np.full(3, 300000.), np.full(3, 100000.), np.full(3, 100000.)] * pcap[:9]
        c[9:16] = annual * np.array([100000., 150000., 100000., 100000., 100000., 100000., 100000.]) * pcap[9:16]
        c[16:19] = annual * 1000. * pcap[16:19]
    for k in range(kdays):
        for h in range(24):
            c[[gi(k,h,g) for g in range(3)]] = 5 * weights[k] * pgen[:3]
            c[[gi(k,h,g) for g in range(3,6)]] = 35 * weights[k] * pgen[3:6]
    if fixed_caps is not None:
        c[off_shed:] = 6000.

    eq, ub = MatrixBuilder(nv), MatrixBuilder(nv)
    # Representative-hour regional balances.
    for k in range(kdays):
        for h in range(24):
            demand = np.zeros(6); demand[[1,3,4]] = days[k,h,:3]
            for reg in range(6):
                terms = []
                for g in np.flatnonzero(GEN_REG == reg): terms.append((gi(k,h,g), 1.))
                for e,(aa,bb) in enumerate(EDGES):
                    if reg == aa: terms.append((fi(k,h,e), -1.))
                    elif reg == bb: terms.append((fi(k,h,e), 1.))
                ss = np.flatnonzero(STOR_REG == reg)
                if len(ss):
                    s = int(ss[0]); terms += [(cpi(k,h,s), -1.), (cdi(k,h,s), 1.)]
                if fixed_caps is not None and reg in (1,3,4):
                    s = (1,3,4).index(reg); terms.append((ui(0,s),0.)) if False else None
                    # Every original occurrence has a separate shed variable.
                    # Balance below is duplicated through equality linking.
                eq.row(terms, demand[reg])

    # In operation mode the representative set is the original sequence, so
    # k==day and shed can be inserted directly into those balances. Rebuild
    # the affected coefficient positions compactly by adding equality rows is
    # not possible; operation calls always use identity z and we amend matrix.
    # Storage chronology, with representative charging repeated by mapping z.
    loss, eff = 1e-5, .95
    for t in range(nh):
        d, h = divmod(t, 24); k = z[d]
        for s in range(3):
            terms = [(si(t,s), 1.), (cpi(k,h,s), -eff), (cdi(k,h,s), 1./eff)]
            if t: terms.append((si(t-1,s), -(1-loss)))
            eq.row(terms, 0.)

    # Capacity upper bounds.
    for k in range(kdays):
        for h in range(24):
            for g in range(9):
                cf = days[k,h,3 + (g-6)] if g >= 6 else 1.
                ub.row([(gi(k,h,g),1.), (g,-cf)], 0.)
            for e in range(7):
                ub.row([(fi(k,h,e),1.), (9+e,-1.)],0.)
                ub.row([(fi(k,h,e),-1.), (9+e,-1.)],0.)
    for t in range(nh):
        for s in range(3): ub.row([(si(t,s),1.),(16+s,-1.)],0.)

    Aeq, beq = eq.matrix(); Aub, bub = ub.matrix()
    if fixed_caps is not None:
        # Add shed to region 2/4/5 balance rows. These are the first 6*k*24 rows.
        Aeq = Aeq.tolil()
        for d in range(ndays):
            k=d; assert z[d] == d
            for h in range(24):
                t=d*24+h
                for s,reg in enumerate((1,3,4)):
                    Aeq[(k*24+h)*6+reg, ui(t,s)] = 1.
        Aeq=Aeq.tocsr()

    bounds = [(0,None)] * nv
    for k in range(kdays):
        for h in range(24):
            for e in range(7): bounds[fi(k,h,e)] = (None,None)
    if fixed_caps is not None:
        fc=np.asarray(fixed_caps)
        for j in range(19): bounds[j]=(fc[j],fc[j])
    res=linprog(c,A_ub=Aub,b_ub=bub,A_eq=Aeq,b_eq=beq,bounds=bounds,
                method='highs',options={'dual_feasibility_tolerance':1e-7,
                                       'primal_feasibility_tolerance':1e-7})
    if not res.success: raise RuntimeError(res.message)
    caps=res.x[:19]
    if want_operation:
        gen=np.empty((ndays,24,9)); ch=np.empty((ndays,24,3)); shed=np.empty((ndays,24,3))
        for d in range(ndays):
            for h in range(24):
                gen[d,h]=[res.x[gi(d,h,g)] for g in range(9)]
                ch[d,h]=[res.x[cpi(d,h,s)]-res.x[cdi(d,h,s)] for s in range(3)]
                shed[d,h]=[res.x[ui(d*24+h,s)] for s in range(3)]
        return caps,gen,ch,shed
    return caps


def solve(inp):
    x=np.asarray(inp['x'],float); n=int(inp['n']); p=float(inp['p']); q=int(inp['q'])
    r0,w0,z0=aggregate(x,n)
    cap0=energy_lp(x[r0],z0)
    identity=np.arange(len(x))
    _,gen,ch,shed=energy_lp(x,identity,fixed_caps=cap0,want_operation=True)
    if q == 0:
        imp=shed.sum(axis=(1,2))
    else:
        imp=5*gen[:,:,:3].sum(axis=(1,2))+35*gen[:,:,3:6].sum(axis=(1,2))+6000*shed.sum(axis=(1,2))
    ne=int(round(p*len(x)))
    extreme=np.argsort(-imp,kind='stable')[:ne]
    r,w,z=aggregate(x,n,extreme,extra=ch if q==2 else None)
    caps=energy_lp(x[r],z)
    y=[caps[:3].sum(),caps[3:6].sum(),caps[6:9].sum(),caps[16:19].sum(),caps[9:16].sum()]
    return {'r':r.tolist(),'w':w.astype(int).tolist(),'y':[float(v) for v in y],'z':z.astype(int).tolist()}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--output',required=True)
    a=ap.parse_args()
    with open(a.input) as f: inp=json.load(f)
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    with open(out/'output.json','w') as f: json.dump(solve(inp),f,separators=(',',':'),allow_nan=False)


if __name__=='__main__': main()
