# Coverage-generation pipeline

`coverage_generation` asks an agent to add meaningful tests, then independently
evaluates the patch at the fixed base commit. It runs the complete pytest suite,
branch coverage, and mutation testing before and after the generated test patch.

```bash
python -m swebench.eval_pipeline.run_pipeline \
  --eval_mode coverage_generation \
  --agent_backend claude_code \
  --instance_ids owner__repo-123 \
  --coverage_target src/package/target_module.py \
  --run_id coverage_001
```

Repeat `--coverage_target` for multiple modules. Without it, targets are inferred
from Python implementation files touched by each instance's gold patch and
captured in `file_contents`. The repository and fixed commit come from the
selected SWE-bench instance; use `--instance_ids` or `--repos` to select them.
For batches whose repositories need different targets, set `coverage_targets`
on each instance instead of using the global CLI override.

The result CSV records line/branch coverage and mutation-score deltas, complete
test-suite status, tests-only scope violations, separate baseline/generated-test
flakiness, added test/assertion evidence counts, runtime, token usage, cost, and
agent turns. The scope check accepts conventional `test`/`tests` trees and
`test_*.py`/`*_test.py` files, including test data below those trees. It rejects
`testing` package trees, production/configuration files, and `conftest.py`.
Removing existing test lines is reported as a conservative integrity violation;
the evaluator does not claim to prove semantic preservation of existing tests.
Raw scripts, logs, patches, and JSON reports are kept under
`logs/run_evaluation/<run_id>_coveragegen/<model>/<instance_id>/`.

Python/pytest is the default. Instances may override `coverage_test_command`,
`coverage_command`, `mutation_command`, `mutation_results_command`, and
`coverage_tool_install_command` when a repository needs a specialized
invocation. By default, Python >=3.7 uses `mutmut<3`, Python 3.6 uses
`mutmut<2`, and Python 3.5 records mutation testing as unsupported while still
measuring coverage. A custom mutation command can opt an older environment back
in.

The primary mutation score is conservative:
`100 * killed / (killed + timeout + survived + suspicious)`. Timeouts are not
treated as killed, skipped mutants are excluded, and a timeout-adjusted score is
also exported for comparison. Mutmut survivor/timeout exit bits are treated as
valid outcomes; only its internal-error bit makes mutation results unusable.
