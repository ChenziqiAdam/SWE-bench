# SciBench paper-replication functional tests (v4)

> Curation status: the active catalog contains eight validated functional tasks.
> Each is backed by pinned official reproduction and an independent scientific
> audit; task-specific provenance records the exact case count and environment.
> Task 0017 is the first R-based task, reproducing sobiEquity's balanced/
> conventional floating catchment area accessibility methods via a curator
> Rscript adapter; agents still submit pure Python solutions.

The 2026-08-15 fixed-sparsity and a posteriori TSA pilots were deferred before
ID assignment: their full official-plus-independent workflows exceeded the proposed
runtime budgets. Candidate reports preserve the measured evidence; no cached or
independent result was promoted as official gold.

The unified paper catalog is [`papers.json`](papers.json). It records paper
titles, canonical paper URLs, GitHub repositories, task IDs, and current build
statuses for validated tasks and candidates.

Each task is one paper-level functional replication. The public bundle contains
the complete paper, a JSON CLI schema, and every curated public input/output case.
Hidden-case counts are task-specific and validated against the registry.

## Contract

Submit `submission.json`:

```json
{"schema_version": 4, "task_id": "scibench_replication_0011", "entrypoint": ["python", "solution.py"]}
```

The trusted runner invokes a fresh process for every case:

```text
<entrypoint> --input <isolated-input.json> --output <new-output-directory>
```

The program must create `output.json`. Paths are checked for traversal and symlinks; JSON must be finite and shape-compatible. NPY/pickle output is not part of v4.

The comparator also supports explicit per-field mixed tolerances. This was added for
the deferred energy pilot (`0.05` capacity units and `max(1 MWh, 1%)` unserved energy)
without changing the comparator used by validated tasks.

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
