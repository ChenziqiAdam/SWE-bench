# scibench_replication_0012

Reproduce the deterministic effective Hamiltonian and effective field used by the paper's anisotropic single-spin dynamics method.

Implement the scientific method from scratch in the offline workspace. Recover the scientific parameters and experiment definition from the anonymized replication dossier; they are intentionally not repeated in `input.json`. You may use equivalent numerical algorithms and locally available scientific libraries.

Run your implementation and write `results.json` at the submission root. Set `entrypoint` to the command used to run your implementation. The `protocol` and `checkpoints` objects may be empty; scientific values are read directly from the required artifacts. All artifact paths must be relative to that root and must not traverse through a symlink or `..`.

## Required logical artifacts

- `temperature` (`application/x-npy`)
- `orientation` (`application/x-npy`)
- `figure2_hamiltonian` (`application/x-npy`)
- `figure2_field` (`application/x-npy`)
- `figure3_hamiltonian` (`application/x-npy`)
- `figure3_field` (`application/x-npy`)
