# Issues-No-Tests offline Codex pilot

This pilot is frozen to `openmm__openmm-4161`, `openmm__openmm-5302`, and
`rdkit__rdkit-7990`. It cross-checks those rows against
`Issues_No_Tests_split.xlsx`, then locates their exact instances in an existing
pipeline `instances.jsonl`.

Validate the selection without network access:

```bash
python -m swebench.issue_pipeline.offline_codex_pilot \
  --instances outputs/issues_testgenwo_001/instances.jsonl \
  --output-dir outputs/issues_no_tests_codex_pilot_001 \
  --dry-run
```

Run the pilot (the prefetch phase needs GitHub access; agent shell tools do not):

```bash
python -m swebench.issue_pipeline.offline_codex_pilot \
  --instances outputs/issues_testgenwo_001/instances.jsonl \
  --output-dir outputs/issues_no_tests_codex_pilot_001
```

The runner shallow-fetches all three exact base commits before inference,
removes remotes and extra reachable history, and then launches three independent
`gpt-5.6-sol` Codex processes. Each has a 900-second limit, a workspace-write
sandbox with network disabled, no personal config/MCP, and disabled web,
browser, app, plugin, computer-use, and multi-agent features.

Review `offline_audit.json`, then manually inspect every file under
`trajectories/`. A detected network attempt or non-test patch produces an empty
`model_patch` and `error: attempted_network` or
`error: disallowed_patch_scope`; it is never retried. Record manual review
outside the immutable trajectory before evaluation.

Upload `instances.jsonl` and `agent_predictions.jsonl` to the evaluation server,
place them in the chosen pipeline output directory, and evaluate the same three
IDs with the normal pipeline arguments plus:

```text
--eval_mode test_generation --agent_backend codex --codex_model gpt-5.6-sol \
--instance_ids openmm__openmm-4161,openmm__openmm-5302,rdkit__rdkit-7990 \
--skip_ingest --skip_inference --force_eval
```

## GPU configuration (remote eval host)

The remote eval host has 3x NVIDIA L40S GPUs (podman + CDI). Before running
OpenMM test-generation eval, export:

```bash
export SWEBENCH_GPU_COUNT=3
```

Without this, `_next_gpu_index` in `swebench/harness/docker_build.py`
defaults to a divisor of 1 and every GPU-requesting container is assigned
GPU index 0, serializing all CUDA/OpenCL OpenMM eval onto a single card
regardless of how many are physically available.
