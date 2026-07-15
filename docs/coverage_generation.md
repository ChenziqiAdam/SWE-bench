# Coverage-generation pipeline

`coverage_generation` is a standalone repository experiment. It asks an agent
to add meaningful tests, then independently evaluates the patch at a fixed
commit. No issue, PR, spreadsheet, gold patch, or SWE-bench instance is needed.
It first measures whole-repository branch coverage, gives the per-file report to
the agent, and lets the agent choose poorly tested modules. It then measures
whole-repository coverage again and runs mutation testing only on production
modules whose coverage increased.

```bash
python -m swebench.eval_pipeline.run_pipeline \
  --eval_mode coverage_generation \
  --repo_url https://github.com/owner/repository.git \
  --base_commit <full-commit-sha> \
  --agent_backend claude_code \
  --run_id coverage_001
```

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

Biopython has a built-in standalone profile. For its GitHub URL, default CLI
values automatically build C extensions in place and use Biopython's official
offline `Tests/run_tests.py` suite for both testing and coverage. Explicit
command overrides still take precedence.

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

A custom mutation command may use `{targets}` where the pipeline should insert
the comma-separated selected module paths. Mutation is skipped and explicitly
reported when no production module gains coverage.

The result CSV records line/branch coverage and mutation-score deltas, complete
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
