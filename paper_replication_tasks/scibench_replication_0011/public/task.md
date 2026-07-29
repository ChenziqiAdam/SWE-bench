# scibench_replication_0011

Reproduce the fixed-seed random-walk MSD ensemble and its OLS, WLS, and GLS diffusion estimates.

Implement the scientific method from scratch in the offline workspace. Recover the scientific parameters and experiment definition from the anonymized replication dossier; they are intentionally not repeated in `input.json`. You may use equivalent numerical algorithms and locally available scientific libraries.

Run your implementation and write `results.json` at the submission root. Set `entrypoint` to the command used to run your implementation. The `protocol` and `checkpoints` objects may be empty; scientific values are read directly from the required artifacts. All artifact paths must be relative to that root and must not traverse through a symlink or `..`.

## Required logical artifacts

- `msd` (`application/x-npy`)
- `covariance` (`application/x-npy`)
- `diffusion_estimates` (`application/x-npy`)
- `summary` (`application/json`)
