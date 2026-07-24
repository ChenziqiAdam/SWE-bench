# Storage-bounded test-generation evaluation

`test_generation` can retain large `sweb.eval.*` instance images. Pass
`--clean_images` to remove each instance image only after its `report.json` has
been written successfully. Shared `sweb.base.*` and `sweb.env.*` images remain
available for later instances.

Cleanup after evaluation does not lower the peak of a validation phase that
builds every selected image up front. On storage-constrained Podman hosts, run
small, sequential batches with one shared run ID, output directory, and log
tree:

```bash
python -m swebench.eval_pipeline.run_pipeline \
  --spreadsheet Issues.xlsx \
  --eval_mode test_generation \
  --run_id issues_testgen_001 \
  --output_dir outputs/issues_testgen_001 \
  --instance_ids id_1,id_2,id_3 \
  --skip_ingest \
  --skip_inference \
  --force_eval \
  --docker_workers 1 \
  --clean_images
```

Keep validation enabled for formal experiments, but omit `--revalidate` so its
spec-hash-aware cache is reused. The evaluation reuses any instance image built
by validation, saves the per-instance report, and then reclaims that image.
Targeted `--skip_inference --force_eval` runs rebuild the complete result CSV
from all cached per-instance reports, so subsequent batches accumulate into the
same experiment.

Use `--skip_validation` only for debugging with a trusted validation cache. A
full unbatched validation still requires enough space for all selected instance
images before evaluation begins.
