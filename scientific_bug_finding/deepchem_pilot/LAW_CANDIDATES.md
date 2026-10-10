# DeepChem scientific-sanitizer law candidates

Written from a static read only (SANITIZER.md Step 2-3), before any checker
code and before executing any input through the functions below. Each entry
states the law, not an outcome. Pinned base: upstream `455d07f3e17e880a4d980b5b0365e4a02b417e14`.

Fields: **Pre** input family where the law holds; **Law**; **Obs** observation
point; **Alarm** comparison of two quantities the law says agree; **Why**.
T/X/P/N = tolerance / transform neutrality / precondition / probe coverage
notes (SANITIZER.md 5.8) for re-call checkers.

Domain: chemistry/physics ML infrastructure (SO(3) representation theory,
variational Monte Carlo sampling, molecular and complex geometry, descriptors,
element constants, chemical splitting). Subsystems excluded by the engineering
gate: the libcint-backed DFT stack (`dqclibs` has no wheel for the pinned
interpreter), DGL graph networks, matminer wrappers.

## A. SO(3) representation theory -- `deepchem/utils/equivariance_utils.py`

**EQ-001 `wigner_D` is a proper rotation in every irrep.** Pre: integer degree
k >= 0, finite Euler angles. Law: D(a,b,g) is a real orthogonal matrix with
determinant +1 (a unitary representation of a rotation). Obs: `wigner_D`
return. Alarm: ||D D^T - I||_max or |det D - 1| above C*eps*(2k+1)*(k+1)
(matrix-exponential error grows with generator norm ~k). Family
`so3_irrep_rotation_matrix`. Why: a non-orthogonal "rotation" rescales
features and breaks equivariance.

**EQ-002 Same-axis angle additivity.** Pre: any a,g, b = 0 (rotations about
one fixed axis compose additively). Law: D(a,0,g) = D(a+g,0,0). Obs: `wigner_D`
return when the observed beta is 0 (mod 2*pi). Alarm: max |D(a,0,g) - D(a+g,0,0)|
> C*eps*(2k+1)*(k+1+|a|+|g|). Re-call forwards all arguments. Family
`so3_irrep_group_law`. Why: homomorphism property of the representation.

**EQ-003 Lie-algebra structure constants are degree independent.** Pre:
integer k >= 1. Law: the three real generators of degree k are skew-symmetric
and satisfy the same commutation relations as the degree-1 generators:
[G_a, G_b] = sum_c f_abc G_c with f_abc read off from degree 1. Obs:
`so3_generators(k)` return. Alarm: skew-symmetry or closure residual above
C*eps*k^2. Family `so3_lie_algebra`. Why: generators of different degrees
must be representations of one algebra.

**EQ-004 Angular-momentum Casimir.** Pre: integer k >= 0. Law: the sum of
squares of the three SU(2) generators is -k(k+1) times the identity (the
quadratic Casimir, J^2 = j(j+1)). Obs: `su2_generators(k)` return. Alarm:
||sum_a G_a^2 + k(k+1) I||_max > C*eps*k^2*(k+1). Family `su2_casimir`.
Why: the defining spectral invariant of angular momentum.

**EQ-005** (retired 2026-10-10; spherical-harmonic addition theorem, only float32 degree >= 29 overflow reachable).

**EQ-007 / EQ-008 `SO3.exp` is a rotation and `log` inverts it.** Pre: finite
axis-angle vectors w with |w| <= pi - 1e-2 (log is single valued and its
conditioning ~1/(pi-|w|) is bounded). Law: R = exp(w) is orthogonal with det +1
(EQ-007); log(R) = w (EQ-008). Obs: `SO3.exp` return; `SO3.log` return. Alarm:
orthogonality/det residual > C*eps_dtype; round-trip error > C*eps_dtype*
max(1,|w|)/(pi-|w|). Families `so3_exponential_map`, `so3_log_exp_inverse`.

**EQ-010 Spherical-coordinate map is a norm-preserving, scale-covariant
chart.** Pre: finite nonzero vectors, positive `divide_radius_by`. Law: the
radial output equals |v|/divide_radius_by; scaling v by s > 0 changes only
the radial output (by s) and leaves both angles unchanged. Obs:
`get_spherical_from_cartesian` return. Alarm: radial mismatch > C*eps*3 or
angle change > C*eps/min(1, sin(beta)) (chart conditioning at the poles).
Family `spherical_coordinate_chart`.

**EQ-011 Real-to-complex harmonic basis change is unitary.** Pre: integer
k >= 0. Law: Q^H Q = I. Obs: `change_basis_real_to_complex(k)` return. Alarm:
||Q^H Q - I||_max > C*eps*(2k+1). Family `harmonic_basis_change`. Why: a
non-unitary change of basis between orthonormal bases mixes norms.

**EQ-012 Basis tensors are rotation intertwiners.** Pre: integers 0 <= J,
|d_in-d_out| <= J <= d_in+d_out, d <= 4. Law: for rotation angles not used to
construct the basis, (D_out (x) D_in) Q_J = Q_J D_J and Q_J has orthonormal
columns (Clebsch-Gordan structure). Obs: `Q_J` as consumed in `get_basis`.
Alarm: intertwiner or orthonormality residual > C*eps_dtype*(2d+1)^2. Family
`clebsch_gordan_intertwiner`. Why: this is the property that makes the
SE(3)-equivariant convolution equivariant.

## B. Variational Monte Carlo sampler -- `deepchem/utils/electron_sampler.py`

**ES-001 Electron-count conservation at initialisation.** Pre: valid nucleus
array (n_nuc, 3), `no_sample` of integer counts per nucleus, finite stddev >= 0.
Law: x has shape (batch, sum_k n_k, 1, 3); the electrons in the k-th block
are those initialised around nucleus k, and the block mean lies within
6*stddev/sqrt(batch*n_k) of that nucleus (mean of Gaussian samples; false
alarm probability ~1e-9 per block). Obs: `gauss_initialize_position` end.
Alarm: shape/count mismatch or block mean outside bound. Family
`electron_initialisation`. Why: wrong electron counts change the system's
charge neutrality.

**ES-002 Harmonic-mean distance is a mean.** Pre: positions y with all
electron-nucleus distances > 0. Law: for each electron, min_k d_k <= H <= max_k d_k
(power-mean inequality for the harmonic mean over nuclei). Obs: `harmonic_mean`
return. Alarm: H outside [min d, max d] beyond C*eps*d. Family
`electron_nucleus_scale`. Why: the quantity scales the asymmetric proposal
width; a value outside the distance range is not a length scale of the system.

**ES-003 Flat target, symmetric proposal accepts everything.** Pre: symmetric
simultaneous moves, constant log-probability. Law: Metropolis acceptance for a
constant target and symmetric proposal is 1. Obs: `move` return in a sandboxed
re-run with the same configuration and a constant target (global RNG state
saved and restored). Alarm: accepted-move ratio != 1. Family
`metropolis_acceptance`. Why: detailed balance reduces to acceptance 1 here.

**ES-004 Gaussian log-density has the Gaussian dependence on sigma.** Pre: any
(y, mu, sigma) where sigma broadcasts to y and is positive. Law: with y = mu,
multiplying sigma by s changes the log-density by -N_coords*log(s), where
N_coords is the number of scalar coordinates of y per batch element; and
moving y away from mu lowers it by exactly 0.5*sum(((y-mu)/sigma)^2). Obs:
`log_prob_gaussian` return (re-calls with transformed sigma). Alarm: either
difference deviates beyond C*eps*scale. Family `gaussian_log_density`.
Why: the asymmetric Metropolis ratio is built from these densities.

## C. Rigid-body geometry -- `deepchem/utils/geometry_utils.py`

**GU-001 Random rotation matrices are proper rotations.** Pre: none (no
arguments). Law: R^T R = I, det R = +1. Obs: `generate_random_rotation_matrix`
return. Alarm: orthogonality > 64*eps*3 or |det-1| > 64*eps*3. Family
`random_rotation_validity`.

**GU-002 `rotate_molecules` is an isometry.** Pre: finite coordinate arrays
(n,3). Law: all intra-molecule distances and each molecule's centroid norm are
unchanged. Obs: `rotate_molecules` return. Alarm: relative distance change
> C*eps*n (distance scale). Family `rigid_rotation_isometry`.

**GU-003 `angle_between` agrees with the two-argument arctangent form and is
symmetric and scale invariant.** Pre: finite nonzero vectors. Law:
angle(a,b) = atan2(|a x b|, a.b); angle(a,b) = angle(b,a); angle(sa,tb) =
angle(a,b) for s,t > 0. Obs: `angle_between` return. Alarm: difference above
64*eps/max(sin(theta), eps) (arccos conditioning). Family `vector_angle`.

**GU-004 Pairwise distances are rigid-motion invariant and transpose
symmetric.** Pre: finite (m,3), (n,3) arrays. Law: D(A,B) = D(RA+t, RB+t) and
D(A,B) = D(B,A)^T. Obs: `compute_pairwise_distances` return. Alarm: relative
difference > 64*eps*(1+|t|/scale) with t scaled to the cloud (X). Family
`pairwise_distance_invariance`.

**GU-005 H-bond angle predicate is symmetric and monotone in the cutoff.**
Pre: finite nonzero vectors, cutoffs c in (0,180]. Law: P(a,b,c) = P(b,a,c)
and P(a,b,c) implies P(a,b,c') for c' >= c. Obs: `is_angle_within_cutoff`
return. Alarm: violation of either. Family `angle_cutoff_predicate`.

## D. Coordinate boxes -- `deepchem/utils/coordinate_box_utils.py`

**BX-001 Intersection lies inside both boxes.** Pre: boxes that overlap on
every axis (checked independently). Law: the result is contained in both
inputs and equals the per-axis [max of mins, min of maxes]. Obs: `intersection`
return. Alarm: containment fails. Family `box_set_algebra`.

**BX-003 Merging overlapping boxes never discards space.** Pre: any list of
boxes, threshold in [0,1]. Law: every input box is contained in at least one
output box, and no output exceeds the union hull of the inputs. Obs:
`merge_overlapping_boxes` return. Alarm: an input box not covered. Family
`box_coverage`. Why: a binding-site box silently dropped removes a region from
all downstream featurisation.

## E. Non-covalent interaction geometry -- `noncovalent_utils.py`, `rdkit_utils.py`

**NC-001 Ring normal is the ring-plane normal.** Pre: ring atoms planar to
1e-6 of the ring diameter (independent best-fit plane via SVD) and the first
three ring atoms not nearly collinear (sin of their angle >= 1e-3). Law: the
returned normal is parallel to the best-fit plane normal. Obs:
`compute_ring_normal` return. Alarm: sin(angle between them) >
64*eps/sin(angle at atom 0) + 1e-6. Family `ring_plane_normal`.

**NC-002 H-bond contacts are rigid-motion invariant.** Pre: fragments with
coordinates, distance bins and angle cutoffs; no interatomic distance used by
the predicate and no angle within 1e-6 relative of its threshold. Law:
contact set unchanged under a common rotation+translation. Obs:
`compute_hydrogen_bonds` return. Alarm: contact sets differ. All arguments
forwarded. Family `hbond_geometry_invariance`.

**NC-003 H-bond contacts are symmetric under exchange of the two fragments.**
Pre: NC-002 margins and identical bins for both roles. Law: swapping the
fragments and transposing the pairwise matrix returns the transposed contact
set. Obs: `compute_hydrogen_bonds` return. Alarm: transposed sets differ.
Family `hbond_role_symmetry`. Why: donor/acceptor roles are not fixed to the
protein or ligand side.

**NC-004 Salt-bridge partners carry opposite-sign charge.** Pre: contacts
returned by `compute_salt_bridges`. Law: for each contact the two atoms'
partial charges have strictly opposite signs. Obs: return of
`compute_salt_bridges`. Alarm: a contact with same-sign or zero charge on
either atom. Family `salt_bridge_electrostatics`. Why: a salt bridge is
attraction between opposite charges.

**NC-005 Cation-pi contact is rigid-motion invariant and normal-sign
invariant.** Pre: finite 3-vectors, positive cutoffs, no distance or angle
within 1e-6 relative of its threshold. Law: result unchanged under common
rotation+translation and under flipping the ring normal. Obs: `is_cation_pi`
return. Alarm: result differs. Family `cation_pi_geometry`.

## F. Molecular fragments -- `fragment_utils.py`

**FR-001 Contact-atom selection is invariant under rigid motion and fragment
order.** Pre: fragments with coordinates; no inter-fragment distance within
1e-6 relative of the cutoff. Law: moving the whole complex rigidly, or
permuting the fragment list, leaves the kept atoms unchanged (up to the
permutation). Obs: `get_contact_atom_indices` return. Alarm: sets differ.
Family `contact_region_invariance`.

**FR-002 Hydrogen stripping conserves heavy atoms.** Pre: coordinates matching
the molecule. Law: the output contains exactly the input's non-hydrogen atoms
(same element sequence, same coordinates, same order) and no hydrogen. Obs:
`strip_hydrogens` return. Alarm: element sequence or coordinates differ.
Family `fragment_atom_conservation`.

**FR-003 Fragment merging conserves atoms.** Pre: list of fragments. Law: the
merged fragment's atom sequence (element, charge, coordinates) is the
concatenation of the inputs'. Obs: `merge_molecular_fragments` return. Alarm:
sequence differs. Family `fragment_atom_conservation`.

## G. Coulomb-matrix descriptors -- `coulomb_matrices.py`

**CM-001 Coulomb matrix is rigid-motion invariant.** Pre: molecule with a
conformer, no atoms closer than 1e-3 angstrom. Law: moving every conformer
rigidly leaves the matrix unchanged. Obs: `coulomb_matrix` return (re-call on
a copied molecule). T/X: tolerance C*eps*max|M|; translation scaled to the
cloud. Family `coulomb_matrix_invariance`.

**CM-002 Off-diagonal entries obey Coulomb's law in atomic units.** Pre:
`remove_hydrogens`/padding accounted for; atoms at positive separation. Law:
M_ij * (r_ij / a0) = Z_i * Z_j with r_ij read from the conformer and a0 the
CODATA Bohr radius from `scipy.constants`. Obs: `coulomb_matrix` return.
Alarm: relative deviation > 1e-8 (CODATA revisions differ by 3e-11). Family
`coulomb_matrix_units`. Why: a unit/constant error rescales every descriptor.

**CM-003 Coulomb-matrix eigenvalue spectrum is permutation invariant and
sorted by magnitude.** Pre: finite matrices. Law: relabelling atoms leaves the
descriptor unchanged, and entries are ordered by |lambda| descending (padding
last). Obs: `CoulombMatrixEig._featurize` return (re-call on a renumbered
molecule). Alarm: spectra differ beyond C*eps*n*|M| or order violated. Family
`coulomb_spectrum_invariance`.

**CM-004 Randomised Coulomb matrices are simultaneous row/column
permutations.** Pre: symmetric input matrix. Law: every randomised matrix has
the input's sorted eigenvalues and sorted entries (permutation similarity).
Obs: `randomize_coulomb_matrix` return. Alarm: spectrum or entry multiset
differs. Family `coulomb_randomisation`.

## H. Periodic-table constants -- `periodic_table_utils.py`

**PT-001 Tabulated atomic mass is physically feasible.** Pre: Z in 1..86 with
a known isotope in RDKit's table. Law: mass(u) = get_atom_mass(Z) / (m_u/m_e,
CODATA from `scipy.constants`) lies within [lightest, heaviest] known isotope
mass of element Z. Obs: `get_atom_mass` return. Alarm: outside the range
(1e-6 relative slack). Family `element_mass_table`.

**PT-002 Period equals the Madelung-rule row.** Pre: 1 <= Z <= 118. Law: the
period is the principal quantum number of the last shell filled in the
(n+l, n) Aufbau order. Obs: `get_period` return. Alarm: mismatch. Family
`element_period`.

**PT-003 Symbol-to-Z map agrees with an independent periodic table.** Pre:
symbols RDKit knows. Law: Z from `get_atomz(symbol)` equals RDKit's atomic
number for that symbol. Obs: `get_atomz` return for string input. Alarm:
mismatch. Family `element_symbol_table`.

## I. Chemical dataset splitting -- `splitters.py`

**SP-001 Scaffold split is scaffold-disjoint.** Pre: valid SMILES. Law: no
Bemis-Murcko scaffold (RDKit `MurckoScaffold`, generic=False) occurs in more
than one of train/valid/test. Obs: `ScaffoldSplitter.split` return. Alarm:
a scaffold shared across splits. Family `scaffold_split_leakage`.

**SP-002 Molecular-weight split is ordered by mass.** Pre: valid SMILES.
Law: max exact mass of train <= min of valid <= max of valid <= min of test
(independent RDKit exact mass). Obs: `MolecularWeightSplitter.split` return.
Alarm: ordering violated beyond 1e-9 relative. Family `mass_split_ordering`.

## Dropped before implementation (Step 5 review)

- Coulomb-matrix diagonal `0.5 Z^2.4`: would re-implement the formula.
- `FragmentUtils` partial-charge sum conservation: tests RDKit, not DeepChem.
- Box `get_face_boxes` vertex containment: local tautology.
- Spherical-harmonic Euler-frame equivariance (`precompute_sh`): the frame
  convention cannot be fixed without running code; recorded as a gap.
- Differentiation-utils solver residuals: tolerances are user-set, so a
  derived tolerance would be a guess; left for a later round.

## Step 5 review disposition (formulation text only)

38 laws were implemented; EQ-005 was later retired (37 remain). None was dropped at review: each compares a
quantity with its transform or with an independent path, none compares with a
literal, and no precondition names a single failing input. The five dropped
candidates above were rejected before implementation.

## Step 6 root-cause grouping

Laws whose violations plausibly share one defect are assigned one family so
redundant alarms do not inflate the primary score:

- `so3_irrep_representation`: EQ-001, EQ-002 (both observe `wigner_D`)
- `so3_exponential_map`: EQ-007, EQ-008 (`SO3.exp` / `SO3.log` inverse charts)
- `hbond_geometry_symmetry`: NC-002, NC-003 (both observe `compute_hydrogen_bonds`)
- `fragment_atom_conservation`: FR-002, FR-003

Result: 37 IDs in 33 families (manifest `sanitizers.json`).

## Disclosure on foreknowledge (SANITIZER.md 5.7.1)

The static read of `noncovalent_utils.py` and `electron_sampler.py` happened
before the laws for NC-002/003 and ES-004 were written, and the reader noticed
code that looked inconsistent at those spots. The laws were written as the
general laws one would state for those quantities regardless (rigid-motion and
role-exchange invariance of an interaction test; Gaussian normalisation), and
the wording above does not mention any mechanism. Because the independence
requirement cannot be proven by the same person, these two spots are the
priority for the fresh-context audit (SANITIZER.md 8.4, 10). Their later natural
triggers are recorded as audit data in `README.md` and never fed back into the
bank.
