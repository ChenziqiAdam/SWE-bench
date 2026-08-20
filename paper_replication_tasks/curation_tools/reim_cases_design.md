# Task 0021 (REIM) case design

3 public + 5 hidden cases, spanning all 6 case_types. Public cases mirror the
paper's own figure/table configurations. Hidden cases were redesigned on
2026-08-20 (superseding an earlier coverage-only draft) to each isolate one
directly-measured numerical hazard, per the 0019 redesign lesson in
PROGRESS.md ("coverage design rather than difficulty design").

## Public (3)

1. **rational_approx**, Fig 2 config: `a=1e-6, b=1, M=40, s=0.5`.
2. **fractional_fem**, Table 1-inspired uniform-grid config:
   `s=0.5, mesh_type=uniform, mesh_param=0` (h=2^-4), `res`/`pol` from a
   live `REIM(30,1e-6,1,'power')` call.
3. **bdf2_fractional_heat**, Fig 6 config: `s=0.5, M=30, Lambda=1e6,
   tol=1e-4, tau0=1e-3, tend=1.0, mesh_h_exponent=8`.

## Hidden (5) — each isolates a measured numerical hazard

1. **rational_approx**, `a=1e-6, b=1, M=40, s=0.05`: the rEIM Gram matrix
   `G` is a Cauchy matrix whose condition number grows exponentially with
   `M` (directly measured: `cond(G)` ~2.0e5 at M=10, ~2.9e10 at M=30,
   ~2.6e13 at M=40 — near the double-precision limit). `s=0.05` (close to
   the *non*-singular end of `x^-s`) combines this near-limit conditioning
   with the empirically worst-observed `s` value: measured `Linf_error`
   ~7x larger than at `s=0.5`, which is non-obvious since `s=0.05` is
   naively "less singular."
2. **exp_family_approx**, `a=1, b=1e6, M=30, tau=0.002`: the paper's own
   lower sampled `tau` bound (Fig 7-right), the slowest-decaying
   `exp(-tau x)` regime across `[1,1e6]`.
3. **precon_family_approx**, `a=1e-6, b=1, M=40, K=1e-6`: the paper's own
   lower sampled `K` bound (Fig 7-left) combined with max (`M=40`)
   conditioning. Measured `Linf_error` ~120x larger than at `K=1`: the
   target `(x^-0.5+K x^0.5)^-1` degenerates toward pure `x^0.5` growth as
   `K->0`.
4. **fractional_fem**, graded mesh, `s=0.75`, repository literal `res`/`pol`
   (from `FEM2D_factional_demo.m`'s pinned ad hoc dictionary tuning, NOT
   regenerable from a live REIM call): `mesh_type=graded, mesh_param=16000`
   (reaches N=19585, matching Fig 3's T2). Tests a distinct
   input-handling regime from the public case's live-generated resolvent —
   an agent must treat `res`/`pol` as opaque pinned data here, not
   re-derive them.
5. **bdf2_fractional_heat**, `s=0.5, M=30, Lambda=1e6, tol=1e-6, tau0=0.05,
   tend=1.0, mesh_h_exponent=8`: a much tighter `tol` (1e-6 vs. the public
   case's 1e-4) combined with an oversized initial `tau0` (0.05 vs. 1e-3)
   forces an immediate rejected step, then a rapid step-size collapse
   toward the `tau0<=1e-4` early-termination floor. Measured: the
   trajectory terminates at `T~0.051`, far short of `tend=1.0` — a
   qualitatively different trajectory *shape* (the early-exit code path)
   than every other case, which all reach `tend` normally. This exercises
   both the reject-branch coefficient computation and the early-stop
   condition, code paths the public case never reaches.

### Rejected candidates from the initial coverage-only draft

The first draft (superseded) used `time_family_approx(s=0.95,d=900)`,
`exp_family_approx(tau=0.002)`, `precon_family_approx(K=1e-6,M=30)`,
`fractional_fem(s=0.75,graded,literal)`, and `bdf2(s=1.0)` — parameter
values near the paper's own sampled boundaries, but without measuring
whether they actually triggered a *harder* code path or larger
implementation-error sensitivity than the public cases. A user audit
flagged this as coverage-oriented rather than hazard-oriented (matching the
0019 lesson). Each surviving/replaced case above was kept or swapped only
after directly measuring its `Linf_error`/`L2_error`/trajectory shape
against a neighboring easy case to confirm a real, quantified difficulty
gap exists.

## Runtime summary (measured, Octave, this machine)

- All `*_family_approx` cases (M<=40): ~5-10s each.
- `fractional_fem` uniform/graded at the case's own `mesh_param`: ~2-3s each.
- `bdf2_fractional_heat` full trajectory: under 1 minute (both the
  tend-reaching public case and the early-terminating hidden case).

Total build/verify runtime for all 8 cases is on the order of 5-10 minutes.
