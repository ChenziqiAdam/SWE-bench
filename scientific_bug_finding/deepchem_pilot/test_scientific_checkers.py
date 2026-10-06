"""Isolated checker-sensitivity tests (SANITIZER.md 8) for the DeepChem bank.

Each test hands a checker a synthetic observed state that violates its law (or
fault-injects the re-called API) and asserts the expected alarm; a matching
valid state is the negative control. These tests are curator-side only: they
are never benchmark witnesses and say nothing about the repository's
correctness.

    cd <deepchem checkout> && PYTHONPATH=. pytest -q \
        <this dir>/test_scientific_checkers.py
"""
import json
import os
import types

import numpy as np
import pytest
import torch
from rdkit import Chem
from rdkit.Geometry import Point3D

from deepchem import _scientific_checkers as sc


@pytest.fixture(autouse=True)
def log(tmp_path, monkeypatch):
    path = tmp_path / "trig.jsonl"
    path.write_text("")
    monkeypatch.setenv("SCIBENCH_TRIGGER_LOG", str(path))
    monkeypatch.setenv("SCIBENCH_CHECKER_DEBUG", "1")
    monkeypatch.chdir(tmp_path)  # basis_transformation_Q_J writes ./cache
    (tmp_path / "cache" / "trans_Q").mkdir(parents=True)
    sc.SWALLOWED.clear()
    sc._CG_SEEN.clear()
    yield path
    assert not sc.SWALLOWED, sc.SWALLOWED


def fired(path):
    return {json.loads(l)["checker_id"] for l in path.read_text().splitlines()}


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


# --------------------------------------------------------------- A. SO(3)
def test_eq001_eq002_wigner(log):
    from deepchem.utils import equivariance_utils as eq
    a, b, g = torch.tensor(0.3), torch.tensor(1.1), torch.tensor(2.0)
    good = eq.wigner_D(2, a, b, g)
    log.write_text("")
    sc.check_wigner_d(2, a, b, g, good)
    assert fired(log) == set()
    sc.check_wigner_d(2, a, b, g, 1.01 * good)
    assert "DC-EQ-001" in fired(log)
    log.write_text("")
    other = eq.wigner_D(2, a + 0.4, b, g)  # orthogonal but not D(a,b,g)
    sc.check_wigner_d(2, a, b, g, other)
    assert fired(log) == {"DC-EQ-002"}


def test_eq003_generators(log):
    from deepchem.utils import equivariance_utils as eq
    G = eq.so3_generators(2)
    sc.check_so3_generators(2, G)
    assert fired(log) == set()
    bad = G.clone()
    bad[0] = 1.1 * bad[0]
    sc.check_so3_generators(2, bad)
    assert fired(log) == {"DC-EQ-003"}
    log.write_text("")
    sym = G.clone()
    sym[1] = sym[1] + torch.eye(5) * 0.01  # not skew-symmetric
    sc.check_so3_generators(2, sym)
    assert fired(log) == {"DC-EQ-003"}


def test_eq004_casimir(log):
    from deepchem.utils import equivariance_utils as eq
    G = eq.su2_generators(2)
    sc.check_su2_generators(2, G)
    assert fired(log) == set()
    sc.check_su2_generators(2, 1.01 * G)
    assert fired(log) == {"DC-EQ-004"}


def test_eq005_shell(log):
    from deepchem.utils import equivariance_utils as eq
    th, ph = torch.tensor([0.4, 1.9]), torch.tensor([0.2, 3.3])
    Y = eq.SphericalHarmonics().get(3, th, ph)
    sc.check_spherical_harmonics(3, th, ph, Y)
    assert fired(log) == set()
    sc.check_spherical_harmonics(3, th, ph, 1.05 * Y)
    assert fired(log) == {"DC-EQ-005"}


def test_eq007_eq008_exp_log(log):
    from deepchem.utils import equivariance_utils as eq
    G = eq.SO3()
    w = torch.tensor([[0.3, -0.2, 0.5]])
    R = G.exp(w)
    log.write_text("")
    sc.check_so3_exp(w, R)
    sc.check_so3_log(R, G.log(R))
    assert fired(log) == set()
    sc.check_so3_exp(w, 1.01 * R)
    assert fired(log) == {"DC-EQ-007"}
    log.write_text("")
    sc.check_so3_log(R, 1.1 * G.log(R))
    assert fired(log) == {"DC-EQ-008"}


def test_eq010_chart(log, monkeypatch):
    from deepchem.utils import equivariance_utils as eq
    v = torch.randn(4, 3) + 0.5
    s = eq.get_spherical_from_cartesian(v)
    log.write_text("")
    sc.check_spherical_chart(v, 1.0, s)
    assert fired(log) == set()
    bad = s.clone()
    bad[..., 0] *= 1.1
    sc.check_spherical_chart(v, 1.0, bad)
    assert fired(log) == {"DC-EQ-010"}
    log.write_text("")
    real = eq.get_spherical_from_cartesian

    def scale_dependent(c, divide_radius_by=1.0):  # fault: angle depends on |v|
        out = real(c, divide_radius_by)
        out[..., 1] = out[..., 1] + 0.01 * torch.linalg.norm(c, dim=-1)
        return out

    monkeypatch.setattr(eq, "get_spherical_from_cartesian", scale_dependent)
    sc.check_spherical_chart(v, 1.0, real(v))
    assert fired(log) == {"DC-EQ-010"}


def test_eq011_basis_change(log):
    from deepchem.utils import equivariance_utils as eq
    Q = eq.change_basis_real_to_complex(2)
    sc.check_basis_change(2, Q)
    assert fired(log) == set()
    sc.check_basis_change(2, 1.01 * Q)
    assert fired(log) == {"DC-EQ-011"}
    log.write_text("")
    # real output dtype is outside the domain (imaginary part is discarded)
    sc.check_basis_change(2, eq.change_basis_real_to_complex(2, dtype=torch.float64))
    assert fired(log) == set()


def test_eq012_intertwiner(log):
    from deepchem.utils import equivariance_utils as eq
    Q = eq.basis_transformation_Q_J(1, 1, 1)
    sc.check_cg_intertwiner(1, 1, 1, Q)
    assert fired(log) == set()
    rng = np.random.RandomState(0)
    bad = Q + 1e-2 * torch.tensor(rng.randn(*Q.shape), dtype=Q.dtype)
    sc.check_cg_intertwiner(1, 1, 1, bad)
    assert fired(log) == {"DC-EQ-012"}


# --------------------------------------------------------------- B. VMC
def sampler(**kw):
    from deepchem.utils.electron_sampler import ElectronSampler
    s = ElectronSampler(central_value=np.array([[0.0, 0, 0], [2.0, 0, 0]]),
                        f=lambda x: -np.sum(x**2, axis=(1, 2, 3)), seed=0,
                        batch_no=4, steps=5, **kw)
    s.gauss_initialize_position(np.array([[2], [1]]))
    return s


def test_es001_init(log):
    s = sampler()
    sc.check_electron_init(s, np.array([[2], [1]]), 0.02)
    assert fired(log) == set()
    s.x = s.x + 1.0  # electrons displaced far from their nuclei
    sc.check_electron_init(s, np.array([[2], [1]]), 0.02)
    assert fired(log) == {"DC-ES-001"}
    log.write_text("")
    s = sampler()
    s.x = s.x[:, :2]  # an electron is lost
    sc.check_electron_init(s, np.array([[2], [1]]), 0.02)
    assert fired(log) == {"DC-ES-001"}


def test_es002_harmonic_mean(log):
    s = sampler()
    good = s.harmonic_mean(s.x)
    log.write_text("")
    sc.check_harmonic_mean(s, s.x, good)
    assert fired(log) == set()
    d = np.linalg.norm(s.x - s.central_value, axis=-1, keepdims=True)
    above = 3 * d.max(axis=-2, keepdims=True)  # outside [min d, max d]
    below = 0.1 * d.min(axis=-2, keepdims=True)
    sc.check_harmonic_mean(s, s.x, above)
    assert fired(log) == {"DC-ES-002"}
    log.write_text("")
    sc.check_harmonic_mean(s, s.x, below)
    assert fired(log) == {"DC-ES-002"}


def test_es003_flat_target(log, monkeypatch):
    from deepchem.utils import electron_sampler as es
    s = sampler()
    sc.check_flat_target_acceptance(s, 0.02)
    assert fired(log) == set()
    monkeypatch.setattr(es.ElectronSampler, "move", lambda self, **k: 0.5)
    sc.check_flat_target_acceptance(s, 0.02)
    assert fired(log) == {"DC-ES-003"}


def test_es004_log_density(log):
    s = sampler()
    y = s.x
    mu = np.zeros_like(y)
    # one width per electron (broadcast over the 3 coordinates)
    sig = np.random.RandomState(0).uniform(0.2, 0.5, (4, y.shape[1], 1, 1))
    good = s.log_prob_gaussian(y, mu, sig)
    log.write_text("")
    sc.check_log_prob_gaussian(s, y, mu, sig, good)
    assert fired(log) == set()
    sc.check_log_prob_gaussian(s, y, mu, sig, good + 0.5)  # wrong quadratic term
    assert fired(log) == {"DC-ES-004"}
    log.write_text("")
    wrong_norm = types.SimpleNamespace(
        log_prob_gaussian=lambda a, b, c: s.log_prob_gaussian(a, b, c) -
        np.sum(np.log(np.broadcast_to(c, a.shape)), axis=(1, 2, 3)))
    sc.check_log_prob_gaussian(wrong_norm, y, mu, sig, good)
    assert fired(log) == {"DC-ES-004"}


# ------------------------------------------------------------- C. geometry
def test_gu001_rotation(log):
    sc.check_random_rotation(np.eye(3))
    assert fired(log) == set()
    sc.check_random_rotation(1.01 * np.eye(3))
    assert fired(log) == {"DC-GU-001"}
    log.write_text("")
    sc.check_random_rotation(np.diag([1.0, 1.0, -1.0]))  # improper
    assert fired(log) == {"DC-GU-001"}


def test_gu002_isometry(log):
    pts = [np.random.RandomState(0).randn(6, 3)]
    th = 0.7
    Rz = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
    sc.check_rotate_molecules(pts, [pts[0] @ Rz.T])
    assert fired(log) == set()
    sc.check_rotate_molecules(pts, [1.01 * pts[0]])
    assert fired(log) == {"DC-GU-002"}


def test_gu003_angle(log, monkeypatch):
    from deepchem.utils import geometry_utils as gu
    a, b = np.array([1.0, 0, 0]), np.array([1.0, 1.0, 0])
    sc.check_angle_between(a, b, np.pi / 4)
    assert fired(log) == set()
    sc.check_angle_between(a, b, np.pi / 4 + 1e-3)
    assert fired(log) == {"DC-GU-003"}
    log.write_text("")
    monkeypatch.setattr(gu, "angle_between",
                        lambda x, y: np.pi / 4 + 1e-3 * np.linalg.norm(x))
    sc.check_angle_between(a, b, np.pi / 4)
    assert fired(log) == {"DC-GU-003"}


def test_gu004_distances(log):
    from deepchem.utils import geometry_utils as gu
    A, B = np.random.RandomState(1).randn(5, 3), np.random.RandomState(2).randn(4, 3)
    D = gu.compute_pairwise_distances(A, B)
    log.write_text("")
    sc.check_pairwise_distances(A, B, D)
    assert fired(log) == set()
    sc.check_pairwise_distances(A, B, 1.01 * D)
    assert fired(log) == {"DC-GU-004"}


def test_gu005_angle_cutoff(log):
    a, b = np.array([1.0, 0, 0]), np.array([1.0, 0.0, 0])  # parallel
    sc.check_angle_cutoff(a, b, 30.0, False)
    assert fired(log) == set()
    sc.check_angle_cutoff(a, b, 30.0, True)  # parallel flagged as antiparallel
    assert fired(log) == {"DC-GU-005"}
    log.write_text("")
    sc.check_angle_cutoff(a, -b, 30.0, True)
    assert fired(log) == set()
    sc.check_angle_cutoff(a, -b, 30.0, False)
    assert fired(log) == {"DC-GU-005"}


# --------------------------------------------------------------- D. boxes
def test_bx001_bx003(log):
    from deepchem.utils.coordinate_box_utils import CoordinateBox as B
    b1, b2 = B((0, 4), (0, 4), (0, 4)), B((2, 6), (1, 5), (0, 3))
    good = B((2, 4), (1, 4), (0, 3))
    sc.check_box_intersection(b1, b2, good)
    assert fired(log) == set()
    sc.check_box_intersection(b1, b2, B((2, 5), (1, 4), (0, 3)))  # leaks out of b1
    assert fired(log) == {"DC-BX-001"}
    log.write_text("")
    sc.check_box_merge([b1, b2], [B((0, 6), (0, 5), (0, 4))])
    assert fired(log) == set()
    sc.check_box_merge([b1, b2], [b1])  # b2 dropped
    assert fired(log) == {"DC-BX-003"}
    log.write_text("")
    sc.check_box_merge([b1, b2], [B((0, 9), (0, 5), (0, 4))])  # exceeds hull
    assert fired(log) == {"DC-BX-003"}


# ------------------------------------------------------- E. non-covalent
def hbond_inputs():
    from deepchem.utils import geometry_utils as gu
    xa, ma = water()
    xb, mb = water(offset=(2.85, 0.15, 0.0), flip=True)
    return (xa, ma), (xb, mb), gu.compute_pairwise_distances(xa, xb)


def test_nc002_nc003_hbonds(log):
    from deepchem.utils import noncovalent_utils as nc
    f1, f2, D = hbond_inputs()
    truth = nc.compute_hydrogen_bonds(f1, f2, D, [(2.5, 3.3)], [40.0])
    assert truth[0], "fixture must contain an H-bond"
    log.write_text("")
    sc.check_hydrogen_bonds(f1, f2, D, [(2.5, 3.3)], [40.0], truth)
    assert fired(log) == set()
    sc.check_hydrogen_bonds(f1, f2, D, [(2.5, 3.3)], [40.0], [[]])
    assert fired(log) == {"DC-NC-002", "DC-NC-003"}


def test_nc004_salt_bridge(log):
    def mol(smiles, q):
        m = Chem.MolFromSmiles(smiles)
        for a in m.GetAtoms():
            a.SetProp("_GasteigerCharge", str(q if a.GetAtomicNum() in (7, 8) else 0.0))
        return m

    cat, an, cat2 = mol("[NH4+]", 1.0), mol("[O-]C", -1.0), mol("[NH4+]", 1.0)
    sc.check_salt_bridges(cat, an, [(0, 0)])
    assert fired(log) == set()
    sc.check_salt_bridges(cat, cat2, [(0, 0)])  # like charges
    assert fired(log) == {"DC-NC-004"}


def test_nc005_cation_pi(log):
    c, o, n = np.array([0.0, 0, 3.5]), np.zeros(3), np.array([0.0, 0, 1.0])
    sc.check_cation_pi(c, o, n, 6.5, 30.0, True)
    assert fired(log) == set()
    sc.check_cation_pi(c, o, n, 6.5, 30.0, False)
    assert fired(log) == {"DC-NC-005"}


def test_nc001_ring_normal(log):
    benz = Chem.MolFromSmiles("c1ccccc1")
    ang = np.arange(6) * np.pi / 3
    with_conformer(benz, np.c_[1.4 * np.cos(ang), 1.4 * np.sin(ang), np.zeros(6)])
    ring = [0, 1, 2, 3, 4, 5]
    sc.check_ring_normal(benz, ring, np.array([0.0, 0.0, -3.0]))
    assert fired(log) == set()
    sc.check_ring_normal(benz, ring, np.array([1.0, 0.0, 0.0]))
    assert fired(log) == {"DC-NC-001"}


# ------------------------------------------------------------ F. fragments
def test_fr001_contacts(log):
    from deepchem.utils import fragment_utils as fr
    f1, f2, _ = hbond_inputs()
    truth = fr.get_contact_atom_indices([f1, f2], cutoff=3.2)
    assert any(truth)
    log.write_text("")
    sc.check_contact_atoms([f1, f2], 3.2, truth)
    assert fired(log) == set()
    sc.check_contact_atoms([f1, f2], 3.2, [[0], [0]])
    assert fired(log) == {"DC-FR-001"}


def test_fr002_strip(log):
    from deepchem.utils import fragment_utils as fr
    xyz, mol = water()
    good = fr.strip_hydrogens(xyz, mol)
    log.write_text("")
    sc.check_strip_hydrogens(xyz, mol, good)
    assert fired(log) == set()
    full = fr.MolecularFragment(list(mol.GetAtoms()), xyz)
    sc.check_strip_hydrogens(xyz, mol, (xyz, full))  # hydrogens kept
    assert fired(log) == {"DC-FR-002"}


def test_fr003_merge(log):
    from deepchem.utils import fragment_utils as fr
    f1, f2, _ = hbond_inputs()
    a = fr.MolecularFragment(list(f1[1].GetAtoms()), f1[0])
    b = fr.MolecularFragment(list(f2[1].GetAtoms()), f2[0])
    good = fr.merge_molecular_fragments([a, b])
    log.write_text("")
    sc.check_merge_fragments([a, b], good)
    assert fired(log) == set()
    sc.check_merge_fragments([a, b], a)  # b lost
    assert fired(log) == {"DC-FR-003"}


# ------------------------------------------------------------ G. Coulomb
def ethanol():
    from rdkit.Chem import AllChem
    m = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    AllChem.EmbedMolecule(m, randomSeed=7)
    return m


def test_cm001_cm002(log):
    from deepchem.feat import CoulombMatrix
    f = CoulombMatrix(max_atoms=12)
    mol = ethanol()
    M = np.asarray(f.coulomb_matrix(mol))
    log.write_text("")
    sc.check_coulomb_matrix(f, mol, M)
    assert fired(log) == set()
    bad = M.copy()
    bad[0, 0, 1] *= 1.01
    bad[0, 1, 0] *= 1.01
    sc.check_coulomb_matrix(f, mol, bad)
    assert fired(log) == {"DC-CM-001", "DC-CM-002"}
    log.write_text("")
    # a conversion-constant error (Angstrom treated as Bohr) breaks the unit law
    sc.check_coulomb_matrix(f, mol, M * 0.529177)
    assert "DC-CM-002" in fired(log)


def test_cm003_spectrum(log):
    from deepchem.feat import CoulombMatrixEig
    f = CoulombMatrixEig(max_atoms=12)
    mol = ethanol()
    good = f._featurize(mol)
    log.write_text("")
    sc.check_coulomb_eig(f, mol, good)
    assert fired(log) == set()
    sc.check_coulomb_eig(f, mol, good[::-1].copy())  # not |lambda|-sorted
    assert fired(log) == {"DC-CM-003"}
    log.write_text("")
    sc.check_coulomb_eig(f, mol, 1.01 * good)  # wrong spectrum
    assert fired(log) == {"DC-CM-003"}


def test_cm004_randomize(log):
    from deepchem.feat import CoulombMatrix
    f = CoulombMatrix(max_atoms=12)
    M = np.asarray(f.coulomb_matrix(ethanol()))[0][:9, :9]
    p = np.random.RandomState(0).permutation(9)
    sc.check_randomize_coulomb(M, [M[p][:, p]])
    assert fired(log) == set()
    sc.check_randomize_coulomb(M, [M[p]])  # rows only
    assert fired(log) == {"DC-CM-004"}


# ------------------------------------------------------------ H. elements
def test_pt001_mass(log):
    from deepchem.utils import periodic_table_utils as pt
    good = pt.get_atom_mass(6)
    sc.check_atom_mass(6, good)
    assert fired(log) == set()
    sc.check_atom_mass(6, 10 * good)
    assert fired(log) == {"DC-PT-001"}
    log.write_text("")
    sc.check_atom_mass(6, good / 1822.888486209)  # unit forgotten
    assert fired(log) == {"DC-PT-001"}


def test_pt002_period(log):
    sc.check_period(26, 4)
    sc.check_period(57, 6)
    sc.check_period(46, 5)
    assert fired(log) == set()
    sc.check_period(26, 3)
    assert fired(log) == {"DC-PT-002"}


def test_pt003_atomz(log):
    sc.check_atomz("Al", 13)
    assert fired(log) == set()
    sc.check_atomz("Al", 14)
    assert fired(log) == {"DC-PT-003"}


# ------------------------------------------------------------ I. splitters
def test_sp001_scaffold(log):
    ids = ["c1ccccc1C", "c1ccccc1CC", "CCO", "C1CCCCC1"]
    sc.check_scaffold_split(ids, [0, 1], [2], [3])
    assert fired(log) == set()
    sc.check_scaffold_split(ids, [0], [1], [2, 3])  # same scaffold split apart
    assert fired(log) == {"DC-SP-001"}


def test_sp002_mass(log):
    ids = ["C", "CC", "CCC", "CCCC"]
    sc.check_mass_split(ids, [0, 1], [2], [3])
    assert fired(log) == set()
    sc.check_mass_split(ids, [3, 1], [2], [0])
    assert fired(log) == {"DC-SP-002"}


# ------------------------------------------------- module-wide discipline
def test_disabled_is_inert(monkeypatch, tmp_path):
    path = tmp_path / "must_stay_empty.jsonl"
    path.write_text("")
    monkeypatch.delenv("SCIBENCH_TRIGGER_LOG", raising=False)
    assert not sc.enabled()
    sc.trigger("DC-X")
    sc.trigger_if(True, "DC-X")
    assert path.read_text() == ""


def test_checker_never_raises_on_garbage():
    import inspect
    for name in dir(sc):
        if name.startswith("check_"):
            fn = getattr(sc, name)
            fn(*([None] * len(inspect.signature(fn).parameters)))
    assert sc.SWALLOWED  # garbage was caught inside the checkers, not raised
    sc.SWALLOWED.clear()


def test_global_rng_untouched(log):
    s = sampler()
    np.random.seed(5)
    state = np.random.get_state()
    sc.check_flat_target_acceptance(s, 0.02)
    after = np.random.get_state()
    assert state[0] == after[0] and np.array_equal(state[1], after[1]) and state[2:] == after[2:]
    t = torch.get_default_dtype()
    from deepchem.utils import equivariance_utils as eq
    sc.check_cg_intertwiner(1, 1, 1, eq.basis_transformation_Q_J(1, 1, 1))
    assert torch.get_default_dtype() == t
