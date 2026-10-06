"""Curator-side observation-reachability probe for the DeepChem bank.

Runs valid public-API calls for every checker ID and reports, per ID, how many
times its predicate was evaluated (reach) and how many times it alarmed. A
reach of 0 means a dead hook or an exception swallowed inside the checker.
Alarms here are audit data only (SANITIZER.md 8): they never change the bank.

    SCIBENCH_TRIGGER_LOG=/tmp/dc.jsonl SCIBENCH_CHECKER_DEBUG=1 \
        python probe_reachability.py [--json out.json]
"""
import json
import os
import sys
import tempfile
import types
from collections import Counter

LOG = os.environ.setdefault("SCIBENCH_TRIGGER_LOG",
                            os.path.join(tempfile.gettempdir(), "dc_probe.jsonl"))
os.environ.setdefault("SCIBENCH_CHECKER_DEBUG", "1")
open(LOG, "w").close()

import numpy as np  # noqa: E402
import torch  # noqa: E402
from rdkit import Chem  # noqa: E402
from rdkit.Chem import AllChem  # noqa: E402
from rdkit.Geometry import Point3D  # noqa: E402

from deepchem import _scientific_checkers as sc  # noqa: E402

REACH = sc.REACHED  # filled by the checkers when SCIBENCH_CHECKER_DEBUG is set


def with_conformer(mol, coords):
    conf = Chem.Conformer(mol.GetNumAtoms())
    for i, p in enumerate(coords):
        conf.SetAtomPosition(i, Point3D(*map(float, p)))
    mol.RemoveAllConformers()
    mol.AddConformer(conf)
    return mol


def water(offset=(0.0, 0.0, 0.0), flip=False):
    mol = Chem.AddHs(Chem.MolFromSmiles("O"))
    xyz = np.array([[0, 0, 0], [0.96, 0, 0], [-0.24, 0.93, 0]], float)
    if flip:
        xyz[:, 0] *= -1
    xyz = xyz + np.array(offset)
    return xyz, with_conformer(mol, xyz)


def embedded(smiles, seed=7, hs=True):
    mol = Chem.MolFromSmiles(smiles)
    if hs:
        mol = Chem.AddHs(mol)
    AllChem.EmbedMolecule(mol, randomSeed=seed)
    return mol


def run():
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

    # --- A. SO(3) representation theory
    for k in (0, 1, 2, 3):
        eq.irr_repr(k, 0.3, 1.1, 2.0)
        eq.su2_generators(k)
        eq.so3_generators(k + 1)
        eq.change_basis_real_to_complex(k)
    th, ph = torch.tensor([0.3, 1.2, 2.5]), torch.tensor([0.1, 4.0, -2.0])
    for l in (0, 1, 2, 5):
        eq.SphericalHarmonics().get(l, th, ph)
    G = eq.SO3()
    w = torch.tensor([[0.3, -0.2, 0.5], [1.0, 0.0, 0.0]])
    G.log(G.exp(w))
    eq.get_spherical_from_cartesian(torch.randn(5, 3))
    eq.get_spherical_from_cartesian(torch.randn(5, 3), divide_radius_by=2.0)
    graph = types.SimpleNamespace(edata={"edge_attr": torch.randn(4, 3)})
    eq.get_basis(graph, max_degree=2)

    # --- B. VMC sampler
    s = ElectronSampler(central_value=np.array([[1, 1, 3], [3, 2, 3]]),
                        f=lambda x: 2 * np.log(np.random.uniform(
                            low=0, high=1.0, size=np.shape(x)[0])),
                        seed=0, batch_no=2, steps=20)
    s.gauss_initialize_position(np.array([[1], [2]]))
    s.harmonic_mean(s.x)
    s.move()
    sa = ElectronSampler(central_value=np.array([[0., 0, 0], [2., 0, 0]]),
                         f=lambda x: -np.sum(x**2, axis=(1, 2, 3)), seed=1,
                         batch_no=3, steps=10, symmetric=False)
    sa.gauss_initialize_position(np.array([[1], [1]]))
    sa.move(asymmetric_func=sa.harmonic_mean)

    # --- C. geometry
    gu.generate_random_rotation_matrix()
    pts = [np.random.RandomState(0).randn(6, 3), np.random.RandomState(1).randn(4, 3)]
    gu.rotate_molecules(pts)
    gu.angle_between(np.array([1.0, 0, 0]), np.array([1.0, 1.0, 0]))
    gu.compute_pairwise_distances(pts[0], pts[1])
    gu.is_angle_within_cutoff(np.array([1.0, 0, 0]), np.array([-1.0, 0.1, 0]), 30.0)

    # --- D. boxes
    b1, b2 = bx.CoordinateBox((0, 4), (0, 4), (0, 4)), bx.CoordinateBox((2, 6), (1, 5), (0, 3))
    bx.intersection(b1, b2)
    bx.merge_overlapping_boxes([b1, b2, bx.CoordinateBox((10, 12), (0, 1), (0, 1))])

    # --- E. non-covalent geometry
    xa, ma = water()
    xb, mb = water(offset=(2.85, 0.15, 0.0), flip=True)
    D = gu.compute_pairwise_distances(xa, xb)
    nc.compute_hydrogen_bonds((xa, ma), (xb, mb), D, [(2.5, 3.3)], [40.0])
    nc.is_cation_pi(np.array([0.0, 0, 3.5]), np.zeros(3), np.array([0.0, 0, 1.0]))
    benz = Chem.MolFromSmiles("c1ccccc1")
    ang = np.arange(6) * np.pi / 3
    with_conformer(benz, np.c_[1.4 * np.cos(ang), 1.4 * np.sin(ang), np.zeros(6)])
    ru.compute_ring_normal(benz, [0, 1, 2, 3, 4, 5])
    cat = Chem.MolFromSmiles("[NH4+]")
    an = Chem.MolFromSmiles("[O-]C")
    for m, q in ((cat, 1.0), (an, -1.0)):
        for a in m.GetAtoms():
            a.SetProp("_GasteigerCharge", str(q if a.GetAtomicNum() in (7, 8) else 0.0))
    nc.compute_salt_bridges(cat, an, np.array([[3.0] * an.GetNumAtoms()] * cat.GetNumAtoms()))

    # --- F. fragments
    wxyz, wmol = water()
    fr.strip_hydrogens(wxyz, wmol)
    f1 = fr.MolecularFragment(list(wmol.GetAtoms()), wxyz)
    f2 = fr.MolecularFragment(list(mb.GetAtoms()), xb)
    fr.merge_molecular_fragments([f1, f2])
    fr.get_contact_atom_indices([(xa, ma), (xb, mb)], cutoff=3.2)

    # --- G. Coulomb matrices
    mol = embedded("CCO")
    CoulombMatrix(max_atoms=12).featurize([mol])
    CoulombMatrix(max_atoms=12, remove_hydrogens=True).featurize([mol])
    CoulombMatrixEig(max_atoms=12).featurize([mol])
    CoulombMatrix(max_atoms=12, randomize=True, n_samples=2, seed=3).featurize([mol])

    # --- H. element constants
    for z in (1, 6, 8, 13, 26, 46, 57, 79):
        for fn in (pt.get_atom_mass, pt.get_period):
            try:
                fn(z)
            except KeyError:  # documented: element not tabulated
                pass
    for sym in ("H", "C", "Al", "Fe"):
        pt.get_atomz(sym)

    # --- I. splitters
    smiles = ["c1ccccc1C", "c1ccccc1CC", "CCO", "CCCO", "C1CCCCC1", "C1CCCCC1C",
              "c1ccncc1", "CC(C)Cl", "CCN", "CCCCCCCC"]
    ds = dc.data.NumpyDataset(X=np.zeros(len(smiles)), ids=np.array(smiles))
    dc.splits.ScaffoldSplitter().split(ds, frac_train=0.6, frac_valid=0.2, frac_test=0.2)
    dc.splits.MolecularWeightSplitter().split(ds, frac_train=0.6, frac_valid=0.2, frac_test=0.2)


def main():
    run()
    ids = sorted(json.load(open(os.path.join(os.path.dirname(__file__),
                                             "sanitizers.json")))["ids"]) \
        if os.path.exists(os.path.join(os.path.dirname(__file__), "sanitizers.json")) \
        else sorted(REACH)
    alarms = Counter()
    for line in open(LOG):
        alarms[json.loads(line)["checker_id"]] += 1
    report = {i: {"reached": REACH.get(i, 0), "alarms": alarms[i]} for i in sorted(set(ids) | set(REACH) | set(alarms))}
    for i, r in report.items():
        print(f"{i:12s} reached={r['reached']:3d} alarms={r['alarms']:3d}")
    print("never reached:", [i for i, r in report.items() if r["reached"] == 0])
    print("swallowed exceptions:", len(sc.SWALLOWED))
    for tb in sc.SWALLOWED[:8]:
        print(tb)
    if "--json" in sys.argv:
        json.dump(report, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)


if __name__ == "__main__":
    main()
