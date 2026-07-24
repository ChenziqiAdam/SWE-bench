# Test Comparison Viewer

Start the local viewer from the repository root:

```bash
PYTHONPATH=. uv run uvicorn frontend.server:app --reload --port 8000
```

Open <http://127.0.0.1:8000>. The viewer reads existing artifacts from
`outputs/` and does not modify experiment data.

It provides:

- agent-generated tests beside human PR tests for bug-reproduction runs;
- agent-generated tests beside Pynguin tests for coverage test-generation runs.
- a filterable mutant list with status, production file, line, and exact code
  diff for coverage runs that saved `*.mutants.json` catalogs.

Tests are displayed as the original unified diff patches stored by the
evaluation pipeline.

Older coverage runs saved aggregate mutation logs but not concrete mutant
catalogs. Rerun their mutation comparison with the current evaluator to populate
the mutation-details panel.
