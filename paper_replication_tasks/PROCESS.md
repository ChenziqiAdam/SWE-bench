# v4 curation process

## Task design

Agents implement a paper's core method from the paper alone — the public
bundle has the paper PDF, task description, I/O schema, and public cases;
no official source. Submissions are scored on hidden cases.

The official repository is curator-only, used solely to generate trustworthy
gold (the paper authors' own implementation, not our reading of the paper).
`scientific.py` (curator's clean-room implementation) may never generate
gold — only cross-check it — since gold from our own understanding couldn't
distinguish an agent's mistake from ours.

## Steps

1. Pin and check out the official repository in an isolated temporary directory.
2. Retain the complete public paper while excluding official source code from the agent bundle.
3. Define all paper/repository public cases and five scientifically valid hidden perturbations.
4. Adapt only parameter and JSON I/O boundaries; preserve the pinned scientific kernel.
5. Record repository, commit, environment, patch description, command, input/output hashes, independent discrepancy, and tolerance.
6. Regenerate every gold output twice from clean official checkouts, require identical hashes, then cross-check it with `scientific.py` and atomically rebuild `manifest.json`.
7. Require the clean-room reference to score `1.0`; require a public-only memorizer to score at most `0.4`.
8. Test malformed JSON, traversal, symlinks, hash mismatch, NaN/Inf, wrong shape, timeout, stale outputs, and partial failure.
9. Remove checkouts, execution directories, archives, bytecode, and deprecated v1-v3 files.

Random cases include RNG class and seed/range in the input. Tolerances are fixed per task from the official/independent audit, never inferred from a submission. No task enters `validated` until provenance records the adapter hash, exact command/environment versions, raw and normalized official hashes, per-field independent errors, derived tolerances, and two matching clean-checkout hashes.

## Scoped core-method tasks

`0009` and `0012` test only the deterministic mathematical core (exact-DMD
kernel; exact closed-form Hamiltonian/field functions) rather than the full
paper pipeline, because both papers' full pipelines are genuinely stochastic
(0009: Gaussian noise in QuTiP Example 2; 0012: LLG noise field averaged
over 20 realizations for Figures 2/3) — no single deterministic gold exists
for those. Confirmed against the source PDFs. `dmdlab==0.1.1` in 0009 is a
curator reproducibility pin, not an author environment artifact.

## Known issues / trail record

- `validate_tasks.py --reproduce-official` genuinely re-clones each repo
  twice, rebuilds a conda env per checkout, and reruns the adapter — verified
  end-to-end on 2026-08-04 (local arm64 Mac). `0008/0009/0011/0012` passed
  fully. `0007` failed the *local rerun only*: its `environment.yml` pins
  `matplotlib==3.4.3` via pip, which has no arm64 wheel and fails to build
  from source under modern Clang. The adapter never imports matplotlib —
  it's an unused transitive dep of the official repo's own plotting code —
  but `conda env create` installs the whole lock file regardless. 0007's
  existing provenance (two matching checkout hashes, passing audit) is
  unaffected; only re-verifying it *on arm64 right now* is blocked.
- No provenance record captures the OS/architecture the original curation
  ran on. Before rerunning `--reproduce-official` on the remote podman
  pipeline, confirm its architecture — if arm64, 0007 will likely hit the
  same matplotlib build failure.
- `--reproduce-official` deletes per-case output tempdirs itself but not the
  conda envs or `--official-root` checkout tree — caller must clean those up.
