# `compute_hydrogen_bonds` misses hydrogen bonds depending on fragment order / hydrogen order, and ignores the angle cutoff

### Setup

DeepChem master (`455d07f3e`, 2.8.1.dev), RDKit 2026.03, Python 3.12.

### Expected behaviour

`deepchem.utils.noncovalent_utils.compute_hydrogen_bonds` should report an
`X-H...Y` contact (N/O donor and acceptor) whenever the pair distance is in the
requested bin and the `X-H...Y` angle is within `hbond_angle_cutoffs[i]` of
linear. The result should not depend on which molecule is passed as `frag1`
or `frag2`, on the order in which a donor's hydrogens are stored, or be
insensitive to the angle cutoff the caller passes.

### Actual behaviour

A linear O-H...O water dimer (O...O 2.9 A), donor hydrogen pointing at the
acceptor:

```python
import numpy as np
from rdkit import Chem
from rdkit.Geometry import Point3D
from deepchem.utils.geometry_utils import compute_pairwise_distances
from deepchem.utils.noncovalent_utils import compute_hydrogen_bonds

def water(O, H1, H2):
    m = Chem.AddHs(Chem.MolFromSmiles("O"))          # atom order: O, H, H
    xyz = np.array([O, H1, H2], float)
    c = Chem.Conformer(3)
    for i, p in enumerate(xyz):
        c.SetAtomPosition(i, Point3D(*p))
    m.AddConformer(c)
    return xyz, m

def hbonds(f1, f2, angle=40.0):
    D = compute_pairwise_distances(f1[0], f2[0])
    return compute_hydrogen_bonds(f1, f2, D, [(2.5, 3.3)], [angle])[0]

acceptor = water((2.9, 0, 0), (3.4, 0.8, 0), (3.4, -0.8, 0))   # its H point away
bonding, other = (0.96, 0, 0), (-0.24, 0.93, 0)

for label, h1, h2 in [("bonding H first ", bonding, other),
                      ("bonding H second", other, bonding)]:
    donor = water((0, 0, 0), h1, h2)
    print(label, "donor=frag1:", hbonds(donor, acceptor),
          " donor=frag2:", hbonds(acceptor, donor))
```

```
bonding H first  donor=frag1: []  donor=frag2: [(np.int64(0), np.int64(0))]
bonding H second donor=frag1: []  donor=frag2: []
```

All four calls describe the same molecule pair and the same geometry; only one
reports the hydrogen bond. In the protein-ligand featurizers the protein is
`frag1`, so a protein donor is never found.

The angle cutoff is also ignored. Moving the donor hydrogen so that the
O-H...O angle deviates from linear by 11.9, 14.9 and 17.8 degrees, and asking for
`hbond_angle_cutoffs=[10]`, still returns the contact (as does 40):

```
bend  8 deg -> deviation 11.9 deg; cutoff 10: [(np.int64(0), np.int64(0))]  cutoff 40: [(np.int64(0), np.int64(0))]
bend 10 deg -> deviation 14.9 deg; cutoff 10: [(np.int64(0), np.int64(0))]  cutoff 40: [(np.int64(0), np.int64(0))]
bend 12 deg -> deviation 17.8 deg; cutoff 10: [(np.int64(0), np.int64(0))]  cutoff 40: [(np.int64(0), np.int64(0))]
```

`RdkitGridFeaturizer` defaults to `hbond_angle_cutoffs=[5, 50, 90]` and
`grid_featurizers.py` calls the same function, so the three distance bins all
effectively use the hard-coded 40 degrees.

### Cause

Three independent problems in `deepchem/utils/noncovalent_utils.py`:

1. `is_hydrogen_bond`, the loop over `frag1`'s atoms enumerates with `j` but
   reads the coordinates with the leftover index `i` from the previous loop
   over `frag2`:

   ```python
   for j, atom in enumerate(frag1_mol.GetAtoms()):
       if atom.GetAtomicNum() == 1:
           atom_xyz = frag1_xyz[i]          # should be frag1_xyz[j]
   ```

2. Further down, `return is_angle_within_cutoff(...)` is inside
   `for hydrogen_xyz in hydrogens:`, so only the first collected hydrogen is
   ever tested. A donor whose bonding hydrogen is not first is missed.
3. `compute_hbonds_in_range` calls
   `is_hydrogen_bond(frag1, frag2, contact, hbond_angle_cutoff)`. The fourth
   positional parameter is `hbond_distance_cutoff`, so the angle cutoff lands
   there and `hbond_angle_cutoff` always keeps its default of 40.

### Suggested fix

```python
        hydrogens = []
        for i, atom in enumerate(frag2_mol.GetAtoms()):
            if atom.GetAtomicNum() == 1 and \
               np.linalg.norm(frag2_xyz[i] - frag2_atom_xyz) < 1.3:
                hydrogens.append(frag2_xyz[i])
        for j, atom in enumerate(frag1_mol.GetAtoms()):
            if atom.GetAtomicNum() == 1 and \
               np.linalg.norm(frag1_xyz[j] - frag1_atom_xyz) < 1.3:
                hydrogens.append(frag1_xyz[j])
        return any(
            is_angle_within_cutoff(frag2_atom_xyz - h, frag1_atom_xyz - h,
                                   hbond_angle_cutoff) for h in hydrogens)
```

and in `compute_hbonds_in_range`:

```python
if is_hydrogen_bond(frag1, frag2, contact,
                    hbond_angle_cutoff=hbond_angle_cutoff):
```

With these changes the script above returns the contact `(0, 0)` for all four
fragment/hydrogen orderings, and `hbond_angle_cutoffs=[10]` rejects the three
bent geometries while `[40]` accepts them.
