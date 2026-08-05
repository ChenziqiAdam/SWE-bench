# scibench_replication_0012

Implement the paper's core method as a general command-line program: evaluate the exact anisotropic coherent-state effective Hamiltonian and field.

Use the following dimensionless convention:

- energies are measured in units of `A1`, with `A1 = 1`;
- `anisotropy_ratio = A2 / A1`;
- temperatures are measured in units of `A1 / kB`, hence `beta = 1 / T`;
- `g mu_B = 1`;
- `orientation_grid` contains `n_z` and every value must lie strictly in
  `(-1, 1)`.

Return `hamiltonian = H_eff / A1` and the corresponding dimensionless
longitudinal `effective_field`. Both arrays have shape
`len(temperature_grid) × len(orientation_grid)`. `spin` must be a positive
integer or half-integer; all temperatures must be positive.

The runner invokes the declared entrypoint once per case as:

```text
<entrypoint> --input <case/input.json> --output <case-output-dir>
```

Write one finite JSON object with exactly `temperature`, `orientation`,
`hamiltonian`, and `effective_field` to `<case-output-dir>/output.json`. Public
cases and expected outputs are under `cases/`; five additional cases are hidden.
Submit `submission.json` matching `interface.schema.json`.
