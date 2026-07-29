# SciBench Paper Replication Tasks

This directory contains SciBench's paper-replication benchmark. Each task
corresponds to one paper-level scientific replication problem: an agent reads an
anonymized description of the paper, implements the core method from scratch,
and reproduces the required numerical results in an offline environment.

Official repositories are used only by curators to construct and verify hidden
references. They are not exposed to agents, and implementation similarity is not
part of the evaluation.

## Design principles

- One paper corresponds to one coherent task, not a collection of independent
  subtasks.
- The public bundle must contain enough scientific information for a clean-room
  implementation.
- Evaluation uses raw numerical artifacts rather than plots, PDFs, or
  self-reported metrics.
- Numerically equivalent implementations are accepted; official filenames,
  program structure, and eigensolver ordering are not required.
- Deterministic core experiments are preferred. Stochastic tasks require an
  explicit RNG protocol and independently justified tolerances.
- Hidden gold must be traceable, reproducible, and independently checked.
- A reference submission must obtain `score = 1.0` and
  `full_success = true`.

## Bundle structure

```text
paper_replication_tasks/
├── manifest.json
├── task_registry.py
├── run_submission.py
├── evaluation/
└── scibench_replication_NNNN/
    ├── public/
    │   ├── task.md
    │   ├── input.json
    │   ├── masked_paper.pdf
    │   └── submission_schema.json
    └── hidden/
        ├── evaluator.py
        ├── gold_output.json
        ├── provenance.json
        └── gold_artifacts/          # present when numerical arrays are needed
```

Only `public/` is visible to the agent:

- `task.md` defines the objective and required logical artifacts.
- `masked_paper.pdf` provides the equations, parameters, initial conditions,
  and experiment protocol.
- `input.json` declares public resources, artifact identities, media types, and
  any benchmark-only constraints.
- `submission_schema.json` defines the `results.json` interface.

Scientific parameters are intentionally not duplicated in `input.json`; the
masked paper is the authoritative scientific specification. `hidden/` is
trusted evaluator infrastructure and must remain inaccessible to the agent.

## Validated tasks

`task_registry.py` is the authoritative lifecycle registry. The current
validated tasks are:

| Task | Replication target | Required output |
|---|---|---|
| `0007` | OLS/WLS regression and uncertainty summaries | Six scalar text artifacts |
| `0008` | Finite-temperature spin analytical results | 23 deterministic TSV curves |
| `0009` | Floquet theory and exact DMD extrapolation | Eigenvalues, times, and prediction trajectory |
| `0011` | Fixed-seed random-walk MSD analysis | MSD, covariance, diffusion estimates, and summary |
| `0012` | Anisotropic single-spin core method | Effective Hamiltonian and field arrays |

Identifier `0010` is retired and must not be reused. Candidate repositories and
their `blocked` or `deferred` status are recorded in
[`CURATION_QUEUE.md`](CURATION_QUEUE.md) and `task_registry.py`; candidate status
does not imply benchmark acceptance.

## Submission workflow

An agent should:

1. Read only the selected task's `public/` directory.
2. Recover the complete scientific protocol from `masked_paper.pdf`.
3. Implement and run the method from scratch in the offline submission
   workspace.
4. Write the required raw artifacts and a `results.json` file at the submission
   root.

A submission index has the following form:

```json
{
  "schema_version": 1,
  "task_id": "scibench_replication_NNNN",
  "entrypoint": "python reproduce.py",
  "protocol": {},
  "checkpoints": {},
  "artifacts": [
    {
      "id": "artifact_id",
      "path": "artifacts/output.npy",
      "media_type": "application/x-npy"
    }
  ]
}
```

The exact artifact IDs and media types are task-specific. Paths must be relative
to the submission root and may not contain `..`, use absolute paths, or traverse
symlinks.

## Trusted execution and evaluation

`run_submission.py` records the command, exit code, runtime, resource use,
before/after file hashes, and final artifact hashes. It does not provide a
security sandbox, so it must run inside the benchmark's offline container or OS
sandbox and write its manifest outside the agent-writable directory.

```bash
python paper_replication_tasks/run_submission.py \
  --submission-dir /agent/workspace \
  --task-id scibench_replication_0007 \
  --output /trusted/execution_manifest.json \
  -- python reproduce.py
```

Then run the task evaluator:

```bash
python paper_replication_tasks/scibench_replication_0007/hidden/evaluator.py \
  --submission-dir /agent/workspace \
  --gold paper_replication_tasks/scibench_replication_0007/hidden/gold_output.json \
  --run-manifest /trusted/execution_manifest.json \
  --output /trusted/evaluation.json
```

Candidate scientific failures produce an evaluation with `score < 1` and exit
code `0`. Invalid evaluator invocations return exit code `2`; evaluator defects
return exit code `3`.

The score consists of:

- 90% scientific correctness;
- 10% artifact completeness.

`full_success = true` additionally requires every critical check to pass. A
trusted execution failure forces the total score to zero.

Evaluators verify artifact freshness and hashes before comparing scientific
values. They also enforce safe paths, expected media types, shapes, dtypes,
finite values, and task-specific numerical tolerances. NPY files are loaded with
`allow_pickle=False`. Exact file hashes are diagnostic only when numerical
equivalence is the intended criterion.

## Formal evaluation pipeline

`run_pipeline.py` runs one Codex or Claude Code backend/model over validated
tasks. Formal runs require:

- rootless Podman with its Docker-compatible API socket enabled;
- `DOCKER_HOST` pointing to that Podman socket;
- a local, prebuilt container image containing the selected `codex` or `claude`
  CLI and all scientific dependencies;
- a Responses-compatible gateway for Codex or an Anthropic Messages-compatible
  gateway for Claude Code;
- that gateway bound to a loopback address.

Inference, trusted execution, and hidden evaluation run in separate ephemeral,
rootless Podman containers with a read-only root filesystem, all Linux
capabilities dropped, `no-new-privileges`, and PID/CPU/memory limits. The agent
and execution containers never mount the repository or hidden task tree. Only
the trusted evaluator container receives a read-only copy of its selected
hidden evaluator and gold data; it receives the executed submission read-only.

The container uses `network=none`. During inference, a mounted Unix socket
relays only the host's loopback model gateway to `127.0.0.1` inside the
container. Trusted submission reruns receive no relay and therefore have no
network path. The pipeline never pulls an image during a formal run; it records
the local image ID/digest and includes that digest in resume matching.

Build the supplied baseline image once:

```bash
podman build \
  --tag scibench-paper-agent:py310 \
  --file paper_replication_tasks/Containerfile \
  paper_replication_tasks
```

For stronger reproducibility, set `CODEX_VERSION` and `CLAUDE_CODE_VERSION`
build arguments rather than accepting their default `latest` values.

Run Codex on every validated task:

```bash
DOCKER_HOST=unix:///run/user/$(id -u)/podman/podman.sock \
python -m paper_replication_tasks.run_pipeline \
  --backend codex \
  --model MODEL_ID \
  --endpoint http://127.0.0.1:4000 \
  --container-image scibench-paper-agent:py310 \
  --run-id codex-model-id-01
```

Run Claude Code on selected tasks:

```bash
DOCKER_HOST=unix:///run/user/$(id -u)/podman/podman.sock \
python -m paper_replication_tasks.run_pipeline \
  --backend claude_code \
  --model MODEL_ID \
  --endpoint http://127.0.0.1:4000 \
  --container-image scibench-paper-agent:py310 \
  --task-id scibench_replication_0007 \
  --task-id scibench_replication_0009 \
  --run-id claude-model-id-01
```

Claude Code containers do not mount the host's `~/.claude` login state. Supply
authentication with `--api-key`, `ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN`, `--claude-oauth-token`, or
`CLAUDE_CODE_OAUTH_TOKEN`. Environment variables are resolved by the host
pipeline and only the selected credential is injected into the container. Keys
and tokens are redacted from persisted commands, errors, runtime state, and
logs; only the credential source name is recorded in `run_config.json`.

Outputs are stored under `outputs/paper_replication/<run_id>/`:

- `run_config.json`: credential-free run configuration;
- `tasks/<task_id>/agent/`: raw JSONL streams, stderr, attempts, and usage;
- `tasks/<task_id>/raw_submission/`: the agent workspace, with any literal API
  credential scrubbed before persistence;
- `tasks/<task_id>/executed_submission/`: the separate trusted-rerun copy;
- `execution_manifest.json` and `evaluation.json`: trusted execution and full
  evaluator results;
- `task_results.jsonl`: complete per-task backend, usage, execution, and
  evaluator records;
- `results.csv`: task-level score, success, completeness, token/cost/time, CPU,
  and peak-memory fields;
- `difference_metrics.csv`: one row per evaluator check with full diagnostics
  plus common numerical difference and tolerance columns; and
- `summary.json`: cohort score/success statistics, failure classes, and total
  agent usage.

Standard output emits timestamped per-task stage transitions, inference
tokens/cost/time, trusted-execution resources, final score and success state,
and one compact diagnostic line for every failed evaluator check. This output
is suitable for `nohup` log monitoring and is flushed after every line.

Agent inference metrics describe model usage and generation resources: tokens,
cost, turns, and wall time. Scientific difference metrics come exclusively from
the hidden task evaluators and describe agreement between generated artifacts
and trusted scientific references. They are intentionally not combined into a
new cross-task normalized error.

Resume is enabled by default. A task record is reused only when task ID,
backend, model, public-bundle fingerprint, and container-image digest all match.
`--force-inference` reruns the agent and all downstream stages;
`--force-evaluation` reuses the raw submission but rebuilds and reruns the
trusted execution and evaluation stages. Other run IDs and task records are not
deleted.

## Anonymous replication dossiers

The public PDF is a manually rewritten anonymous replication dossier, not a
redacted excerpt of the original paper. It retains the scientific definitions
needed to solve the task while removing:

- titles, authors, affiliations, and contact information;
- abstracts, introductions, citations, and acknowledgements;
- paper, repository, commit, and implementation identifiers;
- reported results, figures, tables, and result-derived discussion.

Source, dossier, and PDF hashes are pinned. Automated leakage checks cover
identity terms, result values, links, commit hashes, and long verbatim overlap,
but they supplement rather than replace scientific review. This process reduces
memorization leakage; it cannot formally eliminate semantic re-identification.

## Curation and acceptance

A candidate advances in this order:

1. Select one paper-level core experiment and assess determinism, dependencies,
   compute budget, source availability, and public-only solvability.
2. Pin the paper version, official source revision, environment, and entrypoint;
   reproduce the paper-aligned result.
3. Extract only compact evaluator-relevant gold, remove non-core or non-finite
   outputs, independently cross-check it, and justify tolerances.
4. Rewrite and review the anonymous dossier for both leakage and completeness.
5. Implement a small evaluator that checks scientific invariants and raw
   artifacts directly.
6. Test malformed submissions, path attacks, stale artifacts, hash mismatches,
   non-finite data, incorrect shapes, and numerical tolerance boundaries.
7. Require an independent clean-room implementation using only `public/` and a
   trusted reference evaluation with full success.

The lifecycle states are:

- `validated`: all reproduction, audit, masking, evaluator, and clean-room gates
  passed;
- `blocked`: a concrete missing dependency or paper input prevents credible
  paper-level gold;
- `deferred`: prerequisites or scientific scope remain unresolved;
- `retired`: the identifier is permanently unavailable.

A repository demonstration using different data from the paper is not valid
paper-level gold. Removing an unsuitable task is expected quality control.

## Curator commands

After obtaining the reviewed and pinned paper sources:

```bash
python paper_replication_tasks/prepare_masked_papers.py \
  --source-root /trusted/paper-sources
python paper_replication_tasks/generate_reference_0009.py
python paper_replication_tasks/generate_reference_0011.py
python paper_replication_tasks/generate_reference_0012.py
python paper_replication_tasks/build_tasks.py
python paper_replication_tasks/validate_tasks.py
python -m unittest test_replication_evaluators.py
```

The builder, masker, and validator derive formal task selection from
`task_registry.py`. Where supported, a curator can target a validated task with
the repeatable option:

```bash
python paper_replication_tasks/build_tasks.py \
  --task scibench_replication_0011
```

See [`PROCESS.md`](PROCESS.md) for the concise curation policy and
[`../PROCESS.md`](../PROCESS.md) for the research decisions, evaluator
simplifications, and historical audit trail.
