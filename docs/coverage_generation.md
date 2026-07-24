# Coverage-generation pipeline

`coverage_generation` is a standalone repository experiment. It asks an agent
to add meaningful tests, then independently evaluates the patch at a fixed
commit. No issue, PR, spreadsheet, gold patch, or SWE-bench instance is needed.
It first measures whole-repository branch coverage, gives the per-file report to
the agent, and lets the agent choose poorly tested modules. It then measures
whole-repository coverage again. An optional Pynguin control receives the same
commit and baseline. Mutation testing then uses the union of production modules
whose coverage increased in either generated-test arm, making mutation targets
identical for the original, Pynguin, and agent rows.

```bash
python -m swebench.eval_pipeline.run_pipeline \
  --eval_mode coverage_generation \
  --repo_url https://github.com/owner/repository.git \
  --base_commit <full-commit-sha> \
  --agent_backend claude_code \
  --comparison_protocol agent_led_shared_targets \
  --run_id coverage_001
```

Enable the Python-first conventional baseline with:

```bash
  --traditional_test_generator pynguin
```

The defaults pin Pynguin `0.45.0`, seed `0`, `PYTHONHASHSEED=0`, DynaMOSA,
`SIMPLE` assertions, a 900-second end-to-end budget, and sequential 60-second
module slices. Override them with `--pynguin_version`, `--pynguin_seed`,
`--pynguin_total_budget`, `--pynguin_module_slice`, and
`--pynguin_assertion_mode`. Repeat `--pynguin_module` to restrict eligible
import names or source paths. Otherwise every uncovered, importable production
module is eligible and is prioritized by uncovered branches, then lines.
`--skip_inference` skips only the coding-agent call: Pynguin is generated when
its matching cached prediction is absent, so an existing agent patch can be
compared without paying for agent inference again.
Use `--skip_pynguin` to make the Pynguin arm cache-only as well. A matching
`pynguin_predictions.jsonl` row is reused; if it is absent, the comparison row
reports `missing_cached_prediction` instead of running Pynguin.

Formal Agent/Pynguin comparisons should pass
`--comparison_protocol agent_led_shared_targets`. The pipeline validates the
agent patch, freezes its positive-gain production targets under the statement
budget, then gives the same target manifest and generation-only budget to a
fresh Pynguin checkout. The default `independent` mode is retained for legacy
result reproduction and should not be mixed with shared-target v8 results.

`--coverage_target` is optional. Without it, modules whose covered lines or
branches increase after the agent patch become the mutation targets. Repeat the
flag only when an experiment needs fixed mutation targets; coverage remains
repository-wide.

The default commands are:

```text
setup:             python -m pip install -e . pytest
tests:             python -m pytest
coverage:          python -m coverage run --branch --source=. -m pytest
coverage results:  python -m coverage json -o <phase-output>
mutation:          mutmut run --paths-to-mutate=<agent-selected-targets>
mutation results:  mutmut results
tools:             pytest, coverage, and a Python-compatible mutmut version
```

Override repository-specific behavior with `--coverage_setup_command`,
`--coverage_test_command`, `--coverage_command`,
`--coverage_results_command`, `--mutation_command`,
`--mutation_results_command`, or `--coverage_tool_install_command`. Run the
pipeline in a dedicated Python/Conda environment because setup and tests execute
trusted repository code on the host. Claude Code/Codex also work in their own
clean clone; the evaluator never trusts agent-reported metrics.

The editable default is important for scientific packages with compiled
extensions: tests launched from the checkout import the checkout's package,
not a separately installed wheel. The editable build makes those extensions
available to source-tree imports. Projects with additional build or test
dependencies should override the setup command.

Biopython, GeoPandas, and Astropy have built-in standalone profiles. For their
GitHub URLs, default CLI values select the repository's editable installation,
offline/package test suite, coverage source package, and generated-test
mutation layout. Explicit command overrides still take precedence.

The GeoPandas and Astropy experiments can be launched on the remote server with
the same 900-second agent/Pynguin budgets and 3600-second evaluation budget as
the validated Biopython workflow. Keep separate output directories so reports
and agent predictions are easy to audit (Pynguin caches are also keyed by
instance and are safe if directories are intentionally shared).

GeoPandas, pinned to the requested commit:

```bash
python -m swebench.eval_pipeline.run_pipeline \
  --eval_mode coverage_generation \
  --repo_url https://github.com/geopandas/geopandas.git \
  --base_commit 879ca939d490d66f8e6c7ab569a2827ab9bb8d85 \
  --agent_backend claude_code \
  --comparison_protocol agent_led_shared_targets \
  --model deepseek-v4-flash \
  --claude_code_timeout 900 \
  --traditional_test_generator pynguin \
  --pynguin_total_budget 900 \
  --coverage_eval_timeout 3600 \
  --output_dir outputs/geopandas_coverage \
  --run_id geopandas_coverage
```

Astropy, pinned to the requested commit:

```bash
python -m swebench.eval_pipeline.run_pipeline \
  --eval_mode coverage_generation \
  --repo_url https://github.com/astropy/astropy.git \
  --base_commit 1c9ff745b3247e9ec290c3492f773188c69db6fa \
  --agent_backend claude_code \
  --comparison_protocol agent_led_shared_targets \
  --model deepseek-v4-flash \
  --claude_code_timeout 900 \
  --traditional_test_generator pynguin \
  --pynguin_total_budget 900 \
  --coverage_eval_timeout 3600 \
  --output_dir outputs/astropy_coverage \
  --run_id astropy_coverage
```

Pass `--endpoint` and `--api_key` when they are not already supplied through
the server's Anthropic-compatible environment. GeoPandas excludes its `web`
marker and Astropy runs package tests only, so neither profile intentionally
enables network or documentation tests.

The pipeline stops before agent inference if repository setup, the complete
baseline tests, flaky reruns, or baseline coverage fail. This prevents spending
agent tokens on an invalid experiment. Generated patches are referenced by
absolute paths so evaluation is independent of the caller's `--log_dir` form.
For Claude Code coverage generation, the pipeline explicitly allows the `Bash`
tool in its disposable clone so the agent can run setup, tests, and coverage;
the configured permission mode still controls other tools. The prompt is sent
through stdin so variadic tool-list flags cannot consume it as a CLI argument.
If inference returns no patch, the CSV preserves the backend error and valid
baseline coverage rather than mislabeling the run as targeted coverage.
Interruption-style Claude Code exits (including 129/SIGHUP) are retried once by
default in the preserved working tree. Each attempt gets separate JSONL/text
logs; the prediction and CSV record attempt count, interrupted attempts, and
whether usage is only a partial observed lower bound. Configure this with
`--claude_code_interrupt_retries`. If all retries remain interrupted but leave
a usable patch, evaluation still records its scientific metrics, while the
overall status is `partial` rather than silently reporting a complete resolve.

The Biopython profile also configures Pynguin output and mutmut for its capitalized `Tests`
directory and project test runner. All three profiles select each arm's touched
test modules that exist in its clean checkout for marginal mutation evaluation,
and use mutmut's live
run summary because its separate results renderer is incompatible with the
Python 3.13/Pony ORM environment used in the observed run.
This touched-test-files-only score is explicitly labeled as **marginal mutation
effectiveness**, not whole-suite mutation adequacy.

A custom mutation command may use `{targets}` where the pipeline should insert
the comma-separated selected module paths. Mutation is skipped and explicitly
reported when no production module gains coverage.

The detailed result CSV records line/branch coverage and mutation-score deltas, complete
test-suite status, tests-only scope violations, separate baseline/generated-test
flakiness, added test/assertion evidence counts, runtime, token usage, cost, and
agent turns. The scope check accepts conventional `test`/`tests` trees and
`test_*.py`/`*_test.py` files, including test data below those trees. It rejects
`testing` package trees, production/configuration files, and `conftest.py`.
Removing existing test lines is reported as a conservative integrity violation;
the evaluator does not claim to prove semantic preservation of existing tests.
The CSV also records repository coverage scope and the exact mutation targets.
Raw scripts, logs, patches, and JSON reports are kept under
`logs/run_evaluation/<run_id>_coveragegen/<model>/<instance_id>/`.
Standalone runs also write `<run_id>_comparison.csv` with exactly one original
row, one agent row, and one Pynguin row when enabled. It includes method/version,
seed, status/failure, absolute and delta coverage, common mutation targets and
scores, test/assertion counts, flakiness, timing, and applicable token/cost data.
Pynguin installation, import, timeout, or per-module failures are retained in
its prediction metadata and do not prevent the original or agent arms from
finishing.

By default, Python >=3.7 uses `mutmut<3`, Python 3.6 uses
`mutmut<2`, and Python 3.5 records mutation testing as unsupported while still
measuring coverage. A custom mutation command can opt an older environment back
in.

The primary mutation score is conservative:
`100 * killed / (killed + timeout + survived + suspicious)`. Timeouts are not
treated as killed, skipped mutants are excluded, and a timeout-adjusted score is
also exported for comparison. Mutmut survivor/timeout exit bits are treated as
valid outcomes; only its internal-error bit makes mutation results unusable.

The original SWE-bench-instance path remains available when `--repo_url` is
omitted, for compatibility with earlier experiments. New coverage research
should use standalone `--repo_url` mode.
