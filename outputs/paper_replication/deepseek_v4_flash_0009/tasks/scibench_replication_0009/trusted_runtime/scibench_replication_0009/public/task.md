# scibench_replication_0009

Implement the paper's generalized exact-DMD core method: fit a rank-truncated
model to one or more snapshot blocks and extrapolate from the final snapshot.

`snapshot_blocks` has shape `block × state_dimension × snapshots`. For every
block, pair adjacent columns and concatenate those pairs across blocks to form
`X1` and `X2`. Fit exact DMD at the requested `dmd_rank`. Return the projected
DMD eigenvalues as unordered `[real, imaginary]` pairs. Starting from the final
snapshot of the final block, return predictions at discrete times
`1..prediction_steps` as a finite real array of shape
`state_dimension × prediction_steps`.

The runner invokes the declared entrypoint once per case as:

```text
<entrypoint> --input <case/input.json> --output <case-output-dir>
```

Write one finite JSON object with exactly `eigenvalues` and `prediction` to
`<case-output-dir>/output.json`. Public cases and expected outputs are under
`cases/`; five additional cases are hidden. Submit `submission.json` matching
`interface.schema.json`.
