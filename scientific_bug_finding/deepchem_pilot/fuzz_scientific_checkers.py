"""Checker-side false-positive hunt for the DeepChem bank (SANITIZER.md 5.8).

Sweeps valid public-API inputs over dtype, scale (1e-8..1e12), conditioning
and edge geometry. Any alarm is a *candidate*: it is either a checker defect
(tolerance / transform / precondition / probe, T-X-P-N) or a real library
finding, to be decided by reading the source (SANITIZER.md 8.1).

    PYTHONPATH=<deepchem checkout> python fuzz_scientific_checkers.py [--n 40] [--seed 0]
"""
import argparse
import json
import math
import os
import tempfile
import types
from collections import defaultdict

LOG = os.path.join(tempfile.gettempdir(), "dc_fuzz.jsonl")
os.environ["SCIBENCH_TRIGGER_LOG"] = LOG
os.environ["SCIBENCH_CHECKER_DEBUG"] = "1"

import numpy as np  # noqa: E402
import torch  # noqa: E402
from rdkit import Chem  # noqa: E402
from rdkit.Chem import AllChem  # noqa: E402
from rdkit.Geometry import Point3D  # noqa: E402

from deepchem import _scientific_checkers as sc  # noqa: E402

FOUND = defaultdict(list)  # id -> list of repro descriptions


def run_case(name, fn):
    """Run fn(); attribute any alarm written during it to `name`."""
    before = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    try:
        fn()
    except Exception as exc:  # library rejection of the input is not an alarm
        return f"exc:{type(exc).__name__}"
    with open(LOG) as fh:
        fh.seek(before)
        for line in fh:
            FOUND[json.loads(line)["checker_id"]].append(name)
    return "ok"


def conformer(mol, coords):
    conf = Chem.Conformer(mol.GetNumAtoms())
    for i, p in enumerate(coords):
        conf.SetAtomPosition(i, Point3D(*map(float, p)))
    mol.RemoveAllConformers()
    mol.AddConformer(conf)
    return mol


def rand_rot(rs):
    q = rs.randn(4)
    q /= np.linalg.norm(q)
    a, b, c, d = q
    return np.array([[a*a+b*b-c*c-d*d, 2*(b*c-a*d), 2*(b*d+a*c)],
                     [2*(b*c+a*d), a*a-b*b+c*c-d*d, 2*(c*d-a*b)],
                     [2*(b*d-a*c), 2*(c*d+a*b), a*a-b*b-c*c+d*d]])


def sweep(n, seed):
    from deepchem.utils import equivariance_utils as eq
    from deepchem.utils.electron_sampler import ElectronSampler
    from deepchem.utils import geometry_utils as gu
    from deepchem.utils import coordinate_box_utils as bx
    from deepchem.utils import noncovalent_utils as nc
    from deepchem.utils import fragment_utils as fr
    from deepchem.utils import rdkit_utils as ru
    from deepchem.utils import periodic_table_utils as pt
    from deepchem.feat import CoulombMatrix, CoulombMatrixEig
    import deepchem as dc

    rs = np.random.RandomState(seed)
    scales = [1e-8, 1e-4, 1.0, 1e3, 1e8, 1e12]
    wide = scales + [1e-25, 1e-30, 1e25, 1e30]  # dtype-range adversaries
    dtypes = [torch.float32, torch.float64]

    # ---- A. SO(3)
    for t in range(n):
        for dt in dtypes:
            k = int(rs.randint(0, 7))
            ang = [float(rs.uniform(-10, 10)) * (1000 if t % 7 == 0 else 1) for _ in range(3)]
            run_case(f"wigner k={k} ang={ang} {dt}",
                     lambda: eq.wigner_D(k, *[torch.tensor(a, dtype=dt) for a in ang]))
        k = int(rs.randint(1, 13))
        run_case(f"so3gen k={k}", lambda: eq.so3_generators(k))
        run_case(f"su2gen k={k}", lambda: eq.su2_generators(k))
        run_case(f"basischange k={k}", lambda: eq.change_basis_real_to_complex(k))
        for dt in dtypes:
            l = int(rs.randint(0, 31))
            th = torch.tensor(rs.uniform(-4, 7, 8), dtype=dt)
            th[0], th[1] = 0.0, math.pi
            ph = torch.tensor(rs.uniform(-20, 20, 8), dtype=dt)
            run_case(f"sh l={l} {dt} th={th.tolist()} ph={ph.tolist()}",
                     lambda: eq.SphericalHarmonics().get(l, th, ph))
            r = float(rs.choice([1e-3, 0.5, 1.0, 3.0, 3.09, 3.13, 3.1415, 20.0, 50.0, 1e4]))
            ax = rs.randn(3)
            w = torch.tensor(ax / np.linalg.norm(ax) * r, dtype=dt)
            G = eq.SO3()
            run_case(f"so3 r={r} w={w.tolist()} {dt}", lambda: G.log(G.exp(w)))
            s = float(rs.choice(wide))
            v = torch.tensor(rs.randn(6, 3) * s, dtype=dt)
            if t % 3 == 0:
                v[0] = torch.tensor([0.0, s, 0.0], dtype=dt)  # polar axis
                v[1] = torch.tensor([0.0, -s, 1e-6 * s], dtype=dt)
            c = float(rs.choice([0.5, 1.0, 7.0]))
            run_case(f"chart s={s} c={c} {dt} v={v.tolist()}",
                     lambda: eq.get_spherical_from_cartesian(v, c))
    gdict = types.SimpleNamespace
    old = os.getcwd()
    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, "cache", "trans_Q"))
    os.chdir(tmp)
    try:
        for md in (1, 2, 3):
            run_case(f"get_basis md={md}",
                     lambda: eq.get_basis(gdict(edata={"edge_attr": torch.randn(5, 3)}), md))
    finally:
        os.chdir(old)

    # ---- B. sampler
    for t in range(n):
        nn = int(rs.randint(1, 4))
        cen = rs.randn(nn, 3) * float(rs.choice([0.1, 1.0, 10.0]))
        counts = rs.randint(1, 4, size=(nn, 1))
        b = int(rs.randint(1, 6))
        sd = float(rs.choice([0.0, 0.02, 0.5]))
        s = ElectronSampler(cen, lambda x: -np.sum(x**2, axis=(1, 2, 3)), batch_no=b,
                            steps=int(rs.randint(1, 15)), seed=t)
        run_case(f"es init cen={cen.tolist()} counts={counts.ravel().tolist()} b={b} sd={sd}",
                 lambda: s.gauss_initialize_position(counts, sd))
        run_case(f"es hm t={t}", lambda: s.harmonic_mean(s.x))
        run_case(f"es move t={t}", lambda: s.move(stddev=0.1))
        shapes = [(b, s.x.shape[1], 1, 1), (b, 1, 1, 1), (1, 1, 1, 1), ()]
        for shp in shapes:
            sig = rs.uniform(0.05, 3.0, shp) if shp else np.float64(rs.uniform(0.05, 3.0))
            run_case(f"es logprob broadcast sigma shape={shp}",
                     lambda: s.log_prob_gaussian(s.x, s.x * 0.9, sig))

    # ---- C. geometry
    for t in range(n):
        for s in scales:
            A = rs.randn(int(rs.randint(1, 8)), 3) * s + s * float(rs.choice([0, 1, 100]))
            B = rs.randn(int(rs.randint(1, 8)), 3) * s
            run_case(f"gu dist s={s}", lambda: gu.compute_pairwise_distances(A, B))
            run_case(f"gu rotate s={s}", lambda: gu.rotate_molecules([A, B]))
            run_case(f"gu rot", lambda: gu.generate_random_rotation_matrix())
            u = rs.randn(3) * s
            for eps in (1.0, 1e-3, 1e-6, 1e-9, 1e-12, 0.0):
                for flip in (1.0, -1.0):
                    v = flip * (u + eps * rs.randn(3) * s)
                    if np.linalg.norm(v) == 0:
                        continue
                    run_case(f"gu angle s={s} eps={eps} flip={flip} u={u.tolist()} v={v.tolist()}",
                             lambda: gu.angle_between(u, v))
                    for cut in (5.0, 40.0, 120.0, 180.0):
                        run_case(f"gu cutoff cut={cut}", lambda: gu.is_angle_within_cutoff(u, v, cut))
            for deg, cut in ((140.0, 40.0), (150.0, 30.0), (100.0, 80.0), (179.0, 1.0)):
                th = math.radians(deg)
                a_ = np.array([1.0, 0, 0]) * s
                b_ = np.array([math.cos(th), math.sin(th), 0]) * s * float(rs.choice([1.0, 3.0, 0.1]))
                run_case(f"gu on-edge deg={deg} cut={cut} s={s}",
                         lambda: gu.is_angle_within_cutoff(a_, b_, cut))

    # ---- D. boxes
    for t in range(n):
        def box():
            lo = rs.uniform(-10, 10, 3)
            ext = rs.choice([0.0, 0.5, 3.0, 20.0], 3)
            return bx.CoordinateBox(*[(float(a), float(a + e)) for a, e in zip(lo, ext)])
        boxes = [box() for _ in range(int(rs.randint(1, 6)))]
        run_case(f"bx inter {boxes[0]} {boxes[-1]}", lambda: bx.intersection(boxes[0], boxes[-1]))
        th = float(rs.choice([0.0, 0.5, 0.8, 1.0]))
        run_case(f"bx merge th={th} {[str(b) for b in boxes]}",
                 lambda: bx.merge_overlapping_boxes(boxes, th))

    # ---- E. non-covalent / F. fragments
    def water(R, off, scale):
        mol = Chem.AddHs(Chem.MolFromSmiles("O"))
        xyz = np.array([[0, 0, 0], [0.96, 0, 0], [-0.24, 0.93, 0]], float) * scale
        return (xyz @ R.T + off), conformer(mol, xyz @ R.T + off)

    for t in range(n):
        for scale in (1.0, 1.0, 1e-3, 1e3):
            R1, R2 = rand_rot(rs), rand_rot(rs)
            off = rs.uniform(-1, 1, 3) * scale + rs.choice([0, 1e3, 1e8]) * scale
            d = float(rs.uniform(2.4, 3.4)) * scale
            dirn = rs.randn(3)
            dirn /= np.linalg.norm(dirn)
            x1, m1 = water(R1, off, scale)
            x2, m2 = water(R2, off + d * dirn, scale)
            D = gu.compute_pairwise_distances(x1, x2)
            run_case(f"nc hbond scale={scale} R1={R1.tolist()} R2={R2.tolist()} off={off.tolist()} d={d}",
                     lambda: nc.compute_hydrogen_bonds((x1, m1), (x2, m2), D,
                                                       [(2.5 * scale, 3.3 * scale)], [40.0]))
            run_case(f"fr contacts scale={scale}",
                     lambda: fr.get_contact_atom_indices([(x1, m1), (x2, m2)], 3.0 * scale))
            run_case("fr strip", lambda: fr.strip_hydrogens(x1, m1))
            f1 = fr.MolecularFragment(list(m1.GetAtoms()), x1)
            f2 = fr.MolecularFragment(list(m2.GetAtoms()), x2)
            run_case("fr merge", lambda: fr.merge_molecular_fragments([f1, f2]))
        for s in scales:
            big = float(rs.choice([0.0, 1e6, 1e9])) * s
            c = rs.randn(3) * s + big
            o = rs.randn(3) * s + big
            n_ = rs.randn(3)
            run_case(f"nc cation-pi s={s}",
                     lambda: nc.is_cation_pi(c, o, n_, 6.5 * s, 30.0))
            ring = Chem.MolFromSmiles("c1ccccc1")
            ang = np.arange(6) * np.pi / 3 + rs.uniform(0, 1)
            P = np.c_[1.4 * s * np.cos(ang), 1.4 * s * np.sin(ang), np.zeros(6)]
            P = P @ rand_rot(rs).T + rs.randn(3) * s
            conformer(ring, P)
            run_case(f"nc ringnormal s={s} P={P.tolist()}",
                     lambda: ru.compute_ring_normal(ring, [0, 1, 2, 3, 4, 5]))
    for s in range(3):
        cat, an = Chem.MolFromSmiles("[NH4+]"), Chem.MolFromSmiles("[O-]C")
        for m, q in ((cat, 1.0), (an, -1.0)):
            for a in m.GetAtoms():
                a.SetProp("_GasteigerCharge", str(q if a.GetAtomicNum() in (7, 8) else 0.0))
        run_case("nc salt", lambda: nc.compute_salt_bridges(cat, an, np.full((1, 2), 3.0)))
    for smi in ("CCO", "c1ccccc1", "CC(=O)Nc1ccc(O)cc1", "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"):
        mol = Chem.AddHs(Chem.MolFromSmiles(smi))
        for seed in range(3):
            AllChem.EmbedMolecule(mol, randomSeed=seed + 1)
            xyz0 = np.array(mol.GetConformer().GetPositions())
            na = mol.GetNumAtoms()
            for scale in (1.0, 1e-2, 1e2):
                for shift in (0.0, 1e3, 1e6):
                    m2 = Chem.Mol(mol)
                    conformer(m2, xyz0 * scale + shift)
                    for hs in (False, True):
                        run_case(f"cm {smi} seed={seed} scale={scale} shift={shift} rh={hs}",
                                 lambda: CoulombMatrix(max_atoms=na + 2, remove_hydrogens=hs).featurize([m2]))
                        run_case(f"cmeig {smi} seed={seed} scale={scale} shift={shift} rh={hs}",
                                 lambda: CoulombMatrixEig(max_atoms=na + 2, remove_hydrogens=hs).featurize([m2]))
            run_case(f"cm rand {smi}",
                     lambda: CoulombMatrix(max_atoms=na, randomize=True, n_samples=3, seed=seed).featurize([mol]))

    # ---- H. constants
    for z in range(1, 119):
        for fn in (pt.get_atom_mass, pt.get_period):
            run_case(f"pt {fn.__name__} z={z}", lambda: fn(z))
    for sym in list(pt.periodic_table_atomz):
        run_case(f"pt atomz {sym}", lambda: pt.get_atomz(sym))

    # ---- I. splitters
    pool = ["c1ccccc1", "c1ccccc1C", "c1ccccc1CC", "CCO", "CCCO", "C1CCCCC1", "C1CCCCC1C", "c1ccncc1",
            "CC(C)Cl", "CCN", "CCCCCCCC", "c1ccc2ccccc2c1", "C1CCC2CCCCC2C1", "CC(=O)O", "O=C1CCCCC1",
            "c1ccc(cc1)c1ccccc1", "C1CC1", "N#CC", "CCOC(=O)C", "c1ccoc1"]
    for t in range(n):
        smi = list(rs.choice(pool, size=int(rs.randint(6, 20))))
        ds = dc.data.NumpyDataset(X=np.zeros(len(smi)), ids=np.array(smi))
        run_case(f"sp scaffold {smi}", lambda: dc.splits.ScaffoldSplitter().split(ds))
        run_case(f"sp mw {smi}", lambda: dc.splits.MolecularWeightSplitter().split(ds))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json")
    a = ap.parse_args()
    open(LOG, "w").close()
    sweep(a.n, a.seed)
    print("== alarms by checker (candidates) ==")
    for cid in sorted(FOUND):
        print(f"{cid}: {len(FOUND[cid])} cases; first: {FOUND[cid][0][:300]}")
    if not FOUND:
        print("none")
    print("swallowed exceptions:", len(sc.SWALLOWED))
    for tb in sc.SWALLOWED[:5]:
        print(tb)
    if a.json:
        json.dump({k: v[:20] for k, v in FOUND.items()}, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
