# scibench_replication_0007

Reproduce the OLS and WLS regression summaries from scratch.

Implement the scientific method from scratch in the offline workspace. Recover the scientific parameters and experiment definition from the anonymized replication dossier; they are intentionally not repeated in `input.json`. You may use equivalent numerical algorithms and locally available scientific libraries.

Run your implementation and write `results.json` at the submission root. Set `entrypoint` to the command used to run your implementation. The `protocol` and `checkpoints` objects may be empty; scientific values are read directly from the required artifacts. All artifact paths must be relative to that root and must not traverse through a symlink or `..`.

## Required logical artifacts

- `metric_lin_mean_ols` (`text/plain`)
- `metric_non_mean_ols` (`text/plain`)
- `metric_lin_ci_ols` (`text/plain`)
- `metric_non_ci_ols` (`text/plain`)
- `metric_lin_mean_wls` (`text/plain`)
- `metric_non_mean_wls` (`text/plain`)
