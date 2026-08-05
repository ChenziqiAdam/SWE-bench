# SciBench paper-replication functional tests (v4)

> Curation status (2026-08-02): all five active tasks (0007, 0008, 0009, 0011,
> and 0012) are validated from two clean official runs and an independent
> scientific audit.

Each task is one paper-level functional replication. The public bundle contains the complete paper, a JSON CLI schema, and every curated public input/output case. Exactly five parameter-perturbed cases remain hidden.

## Contract

Submit `submission.json`:

```json
{"schema_version": 4, "task_id": "scibench_replication_0007", "entrypoint": ["python", "solution.py"]}
```

The trusted runner invokes a fresh process for every case:

```text
<entrypoint> --input <isolated-input.json> --output <new-output-directory>
```

The program must create `output.json`. Paths are checked for traversal and symlinks; JSON must be finite and shape-compatible. NPY/pickle output is not part of v4.

## Scoring

`score = 0.4 × public_score + 0.6 × hidden_score`. Scores within a split are the fraction of cases passing both maximum-absolute and RMSE tolerances. `full_success` requires every critical case and trusted execution check to pass. A program that only memorizes public outputs cannot exceed `0.4`.

## Layout

```text
scibench_replication_NNNN/
├── public/
│   ├── paper.pdf
│   ├── task.md
│   ├── interface.schema.json
│   └── cases/case_NN/{input.json,output.json}
└── hidden/
    ├── cases/case_NN/{input.json,output.json}
    ├── tolerances.json
    └── provenance.json
```

`build_tasks.py` is no longer permitted to generate gold through `scientific.py`.
Run `validate_tasks.py` for a structural candidate audit, or
`validate_tasks.py --reproduce-official --official-root <checkouts>` for the
fail-closed official gate. `reference_cli.py` and `scientific.py` are curator-only
independent implementations and can never be official gold generators.
