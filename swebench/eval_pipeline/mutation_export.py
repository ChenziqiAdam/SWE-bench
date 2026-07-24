"""Export mutmut v2 cache entries and their concrete source diffs as JSON."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sqlite3
from collections import Counter
from pathlib import Path


def _render_diff(
    filename: str,
    original_line: str,
    line_number: int,
    index: int,
) -> str:
    """Reproduce the mutation from the cached source line without reparsing a file."""
    from mutmut import Context, RelativeMutationID, mutate

    added_indentation = not original_line.startswith((" ", "\t"))
    wrapped_line = f"    {original_line}" if added_indentation else original_line
    indentation = wrapped_line[: len(wrapped_line) - len(wrapped_line.lstrip())]
    source = f"def __mutmut_export__():\n{wrapped_line}\n"
    if wrapped_line.rstrip().endswith(":"):
        source += f"{indentation}    pass\n"
    mutation_id = RelativeMutationID(
        line=wrapped_line,
        index=index,
        line_number=1,
        filename=filename,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        mutated_source, mutation_count = mutate(
            Context(
                source=source,
                filename=filename,
                mutation_id=mutation_id,
                dict_synonyms=None,
            )
        )
    if not mutation_count:
        return ""
    mutated_line = mutated_source.splitlines()[1]
    if added_indentation:
        mutated_line = mutated_line[4:]
    return (
        f"--- {filename}\n"
        f"+++ {filename}\n"
        f"@@ -{line_number},1 +{line_number},1 @@\n"
        f"-{original_line}\n"
        f"+{mutated_line}"
    )


def export_mutants(cache_path: Path, output_path: Path) -> dict:
    """Write one browser-friendly record per mutant in a mutmut v2 cache."""
    with sqlite3.connect(cache_path) as connection:
        rows = connection.execute(
            """
            SELECT Mutant.id, Mutant.status, Mutant."index",
                   SourceFile.filename, Line.line_number, Line.line
            FROM Mutant
            JOIN Line ON Line.id = Mutant.line
            JOIN SourceFile ON SourceFile.id = Line.sourcefile
            ORDER BY SourceFile.filename, Line.line_number, Mutant."index"
            """
        ).fetchall()

    mutants = []
    for mutant_id, status, index, filename, line_number, original_line in rows:
        try:
            diff = _render_diff(filename, original_line, line_number, index)
        except Exception:  # noqa: BLE001 - retain the rest of a partial catalog
            diff = ""
        mutants.append(
            {
                "id": mutant_id,
                "status": status,
                "index": index,
                "file": filename,
                "line": line_number,
                "original_line": original_line,
                "diff": diff,
            }
        )

    payload = {
        "format_version": 1,
        "summary": dict(Counter(mutant["status"] for mutant in mutants)),
        "mutants": mutants,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(".mutmut-cache"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export_mutants(args.cache, args.output)


if __name__ == "__main__":
    main()
