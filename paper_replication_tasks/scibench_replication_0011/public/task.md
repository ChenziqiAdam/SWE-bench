# scibench_replication_0011

Implement the paper's core method as a general command-line program: generate seeded lattice random walks and estimate ensemble MSD and diffusion.

The runner invokes the declared entrypoint once per case as:

```text
<entrypoint> --input <case/input.json> --output <case-output-dir>
```

Write one finite JSON object to `<case-output-dir>/output.json`. Public cases and expected outputs are under `cases/`; five additional cases are hidden. Submit `submission.json` matching `interface.schema.json`. Random inputs explicitly declare their RNG and seed protocol.
