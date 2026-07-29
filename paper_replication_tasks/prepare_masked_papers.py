#!/usr/bin/env python3
"""Create manually curated, result-masked papers from authoritative sources.

The source root must contain:
  0007/**/src/tex/ms.tex             author repository source
  0008/manuscript.tex                arXiv 2303.00602 source
  0009/main.tex                      arXiv 2010.14577 source

This script uses reviewed, source-version-specific line ranges. It intentionally
fails when source hashes change so that a curator must review a new revision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import textwrap
import unicodedata
from pathlib import Path

from anonymized_dossiers import DOSSIERS
from task_registry import TASK_REGISTRY, select_validated

ROOT = Path(__file__).resolve().parent
CURATED = ROOT / "masked_paper_sources"

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verbatim_ngram_overlap(source: str, dossier: str, size: int = 12) -> float:
    """Fraction of dossier word n-grams that occur verbatim in the source."""
    tokenize = lambda value: re.findall(r"[a-z0-9]+", value.lower())
    source_words = tokenize(source)
    dossier_words = tokenize(dossier)
    source_ngrams = {
        tuple(source_words[index : index + size])
        for index in range(max(0, len(source_words) - size + 1))
    }
    dossier_ngrams = [
        tuple(dossier_words[index : index + size])
        for index in range(max(0, len(dossier_words) - size + 1))
    ]
    if not dossier_ngrams:
        return 0.0
    return sum(ngram in source_ngrams for ngram in dossier_ngrams) / len(
        dossier_ngrams
    )


def ascii_lines(text: str, width: int = 92) -> list[str]:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "replace").decode()
    output: list[str] = []
    for raw in text.splitlines():
        if not raw.strip():
            output.append("")
            continue
        indent = len(raw) - len(raw.lstrip())
        prefix = " " * min(indent, 8)
        output.extend(
            textwrap.wrap(
                raw.strip(),
                width=width,
                initial_indent=prefix,
                subsequent_indent=prefix,
                replace_whitespace=False,
                drop_whitespace=True,
            )
            or [""]
        )
    return output


def write_pdf(path: Path, text: str) -> None:
    lines = ascii_lines(text)
    per_page = 58
    pages = [lines[index : index + per_page] for index in range(0, len(lines), per_page)]
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # populated after page object numbers are known
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    ]
    page_numbers = []
    for page in pages:
        page_number = len(objects) + 1
        stream_number = page_number + 1
        page_numbers.append(page_number)
        commands = ["BT", "/F1 8 Tf", "44 754 Td"]
        for index, line in enumerate(page):
            if index:
                commands.append("0 -12 Td")
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({escaped}) Tj")
        commands.append("ET")
        stream = "\n".join(commands).encode("ascii")
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {stream_number} 0 R >>"
            ).encode()
        )
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    kids = " ".join(f"{number} 0 R" for number in page_numbers)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_numbers)} >>".encode()
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--accept-source-changes", action="store_true")
    parser.add_argument("--task", action="append", dest="tasks")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    task_ids = select_validated(args.tasks)
    suffixes = [task_id.rsplit("_", 1)[-1] for task_id in task_ids]
    paths = {}
    for task_id, suffix in zip(task_ids, suffixes):
        pattern = TASK_REGISTRY[task_id]["mask_source"]
        matches = sorted(source_root.glob(pattern))
        if len(matches) != 1:
            raise RuntimeError(f"expected one source for {task_id}, found {matches}")
        paths[suffix] = matches[0]
    actual_hashes = {suffix: sha256(path) for suffix, path in paths.items()}
    mismatches = {
        key: (
            TASK_REGISTRY[f"scibench_replication_{key}"]["source_sha256"],
            actual,
        )
        for key, actual in actual_hashes.items()
        if TASK_REGISTRY[f"scibench_replication_{key}"]["source_sha256"] != actual
    }
    if mismatches and not args.accept_source_changes:
        raise RuntimeError(
            "authoritative sources changed; manually review before using "
            f"--accept-source-changes: {mismatches}"
        )
    values = {suffix: DOSSIERS[suffix] for suffix in suffixes}
    CURATED.mkdir(exist_ok=True)
    provenance_path = CURATED / "masking_provenance.json"
    previous = (
        json.loads(provenance_path.read_text(encoding="utf-8"))
        if args.tasks and provenance_path.is_file()
        else None
    )
    provenance = previous or {
        "schema_version": 1,
        "manual_review": {
            "policy": (
                "publish a manually rewritten anonymous replication dossier; retain "
                "only necessary methods, equations, and experiment settings; remove "
                "identity metadata, bibliographic fingerprints, verbatim narrative, "
                "result values, figures/tables, conclusions, and implementation identities"
            ),
            "reviewed_task_ids": [],
        },
        "deidentification": {
            "document_type": "manually_rewritten_replication_dossier",
            "removed": [
                "paper_title",
                "authors",
                "affiliations",
                "contact_information",
                "abstract",
                "introduction",
                "citations_and_references",
                "acknowledgements",
                "implementation_links",
                "result_values_and_figures",
            ],
            "residual_risk": (
                "necessary equations, model structure, and experimental settings may "
                "still permit semantic re-identification"
            ),
        },
        "sources": {},
    }
    source_kinds = {
        "0007": {"kind": "author_repository_latex"},
        "0008": {"kind": "arxiv_source", "identifier": "2303.00602"},
        "0009": {"kind": "arxiv_source", "identifier": "2010.14577"},
        "0011": {"kind": "author_repository_latex"},
        "0012": {"kind": "arxiv_source", "identifier": "2404.19539v2"},
    }
    for suffix in suffixes:
        provenance["sources"][suffix] = {
            **source_kinds[suffix],
            "source_file_sha256": actual_hashes[suffix],
        }
    provenance["manual_review"]["reviewed_task_ids"] = sorted(
        set(provenance["manual_review"]["reviewed_task_ids"]) | set(suffixes)
    )
    for suffix, text in values.items():
        task_id = f"scibench_replication_{suffix}"
        source_path = CURATED / f"{task_id}.txt"
        source_path.write_text(
            "SCIBENCH ANONYMIZED REPLICATION DOSSIER\n"
            "This is a manually rewritten scientific specification, not the original "
            "paper text.\n"
            "Identity metadata, bibliographic fingerprints, and benchmark answers "
            "are intentionally withheld.\n\n"
            + text.strip()
            + "\n",
            encoding="utf-8",
        )
        public = ROOT / task_id / "public"
        public.mkdir(parents=True, exist_ok=True)
        write_pdf(public / "masked_paper.pdf", source_path.read_text())
        overlap = verbatim_ngram_overlap(
            paths[suffix].read_text(encoding="utf-8", errors="ignore"),
            source_path.read_text(encoding="utf-8"),
        )
        if overlap > 0.005:
            raise RuntimeError(
                f"{task_id} has excessive 12-word verbatim overlap: {overlap:.4%}"
            )
        provenance["sources"][suffix]["verbatim_12gram_overlap"] = overlap
    for suffix in values:
        task_id = f"scibench_replication_{suffix}"
        provenance["sources"][suffix]["curated_text_sha256"] = sha256(
            CURATED / f"{task_id}.txt"
        )
        provenance["sources"][suffix]["masked_pdf_sha256"] = sha256(
            ROOT / task_id / "public/masked_paper.pdf"
        )
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )
    print(f"Generated {len(values)} manually rewritten anonymized replication dossier(s).")


if __name__ == "__main__":
    main()
