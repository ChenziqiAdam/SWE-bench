"""Tests for exporting concrete mutmut code changes."""
import sqlite3

from swebench.eval_pipeline import mutation_export


def test_export_mutants_joins_cache_metadata_with_mutmut_diff(tmp_path, monkeypatch):
    cache = tmp_path / ".mutmut-cache"
    with sqlite3.connect(cache) as connection:
        connection.executescript(
            """
            CREATE TABLE SourceFile (
                id INTEGER PRIMARY KEY, filename TEXT NOT NULL, hash TEXT NOT NULL
            );
            CREATE TABLE Line (
                id INTEGER PRIMARY KEY, sourcefile INTEGER NOT NULL,
                line TEXT NOT NULL, line_number INTEGER NOT NULL
            );
            CREATE TABLE Mutant (
                id INTEGER PRIMARY KEY, line INTEGER NOT NULL, "index" INTEGER NOT NULL,
                tested_against_hash TEXT NOT NULL, status TEXT NOT NULL
            );
            INSERT INTO SourceFile VALUES (1, 'pkg/core.py', 'hash');
            INSERT INTO Line VALUES (1, 1, 'return value', 12);
            INSERT INTO Mutant VALUES (3, 1, 0, 'hash', 'ok_killed');
            """
        )

    monkeypatch.setattr(
        mutation_export,
        "_render_diff",
        lambda *args: (
            "--- a/pkg/core.py\n+++ b/pkg/core.py\n-return value\n+return None"
        ),
    )
    output = tmp_path / "mutants.json"
    payload = mutation_export.export_mutants(cache, output)

    assert payload["summary"] == {"ok_killed": 1}
    assert payload["mutants"][0]["file"] == "pkg/core.py"
    assert payload["mutants"][0]["line"] == 12
    assert "+return None" in payload["mutants"][0]["diff"]
    assert output.is_file()
