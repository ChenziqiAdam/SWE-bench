"""Isolated, evidence-validated review of paper core algorithms.

The model context is constructed only from PAPER.md, a JSON schema, and the
selected paper PDF. Existing tasks, cases, reports, repositories, and audits
are deliberately outside the input path.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import requests
from pypdf import PdfReader


PAPER_IDS = ("0011", "0014", "0015", "0017", "0018", "0019", "0020", "0021", "0022")
DEFAULT_MODEL = "z-ai/glm-5.2:free"
REQUIRED_ENV_KEYS = ("ENDPOINT", "API_KEY")
ARXIV_0021_URL = "https://arxiv.org/pdf/2406.19339v3"
SCHEMA_VERSION = "core-algorithm-review-v2"
REASONING_CONFIG = {"effort": "minimal", "exclude": True}
ALLOWED_ROLES = {"core", "supporting", "baseline", "preprocessing", "evaluation"}
FORBIDDEN_PROMPT_MARKERS = (
    "curation_reports/",
    "core_algorithm_audits/",
    "scibench_replication_",
    "hidden_case_",
    "gold_outputs/",
    "[ALGORITHM PSEUDOCODE REDACTED",
)
REDACTION_MARKERS = (
    "[algorithm pseudocode redacted",
    "[redacted]",
    "content redacted",
    "pseudocode redacted",
)


FINAL_SCHEMA: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "paper_id": "four-digit paper id",
    "evidence_catalog": [
        {"id": "E1", "page": 1, "section": "section heading", "excerpt": "short exact quote"}
    ],
    "research_goal": {"summary": "string", "evidence": ["E1"]},
    "main_contributions": [
        {"id": "C1", "summary": "string", "evidence": ["E1"]}
    ],
    "contribution_graph": [
        {
            "from": "node",
            "to": "node",
            "relation": "string",
            "evidence": ["E1"],
        }
    ],
    "candidate_algorithms": [
        {
            "name": "string",
            "role": "core|supporting|baseline|preprocessing|evaluation",
            "description": "string",
            "evidence": ["E1"],
            "deletion_test": {
                "outcome": "FAILS_WITHOUT_ALGORITHM|SURVIVES_WITHOUT_ALGORITHM|UNCERTAIN",
                "reason": "string",
                "evidence": ["E1"],
            },
        }
    ],
    "selected_core_algorithm": "candidate name or null",
    "uniqueness_reason": "string",
    "scientific_contract": {
        "algorithm": "selected candidate name",
        "scientific_purpose": "string",
        "inputs": ["string"],
        "outputs": ["string"],
        "core_operations": ["string"],
        "assumptions": ["string"],
        "parameters": ["string"],
        "scientific_invariants": ["string"],
        "dependent_contributions": ["string"],
        "dependent_experiments_results": ["string"],
        "specificity_reason": "string",
        "evidence": ["E1"],
    },
    "gates": {
        **{
            gate: {"status": "PASS|REJECT", "reason": "string", "evidence": ["E1"]}
            for gate in ("G1", "G2", "G3", "G4", "G5")
        },
        **{
            gate: {
                "status": "NOT_EVALUATED",
                "reason": "deferred to later benchmark-design stage",
                "evidence": [],
            }
            for gate in ("G6", "G7", "G8")
        },
    },
    "evidence_gaps": ["string"],
    "decision": "ACCEPT_FOR_DESIGN|REJECT_PAPER",
}

EVIDENCE_SCHEMA = {"page": 1, "section": "section heading", "excerpt": "short exact quote"}

CHUNK_SCHEMA: dict[str, Any] = {
    "paper_id": "four-digit paper id",
    "page_range": [1, 2],
    "research_goal_evidence": ["Evidence"],
    "contribution_evidence": [
        {"summary": "string", "evidence": ["Evidence"]}
    ],
    "algorithm_evidence": [
        {
            "name": "string",
            "possible_role": "core|supporting|baseline|preprocessing|evaluation",
            "description": "string",
            "evidence": ["Evidence"],
        }
    ],
    "experiment_result_links": [
        {"summary": "string", "evidence": ["Evidence"]}
    ],
}


class ReviewError(RuntimeError):
    """Base review failure."""


class ResponseValidationError(ReviewError):
    """The model response is not a valid evidence-backed record."""


class ContextLengthError(ReviewError):
    """The endpoint explicitly rejected the context length."""


class CheckpointMismatchError(ReviewError):
    """A checkpoint belongs to different source inputs."""


@dataclass(frozen=True)
class PageText:
    number: int
    text: str
    sections: tuple[str, ...]


@dataclass(frozen=True)
class PaperSource:
    paper_id: str
    path: Path
    sha256: str
    pages: tuple[PageText, ...]
    char_count: int
    nonempty_page_ratio: float
    redaction_markers: tuple[str, ...]


@dataclass
class APIResult:
    text: str
    usage: dict[str, Any]
    response_id: str | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def read_env_file(path: Path) -> dict[str, str]:
    """Read only endpoint credentials without mutating os.environ."""
    found: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key not in REQUIRED_ENV_KEYS:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            found[key] = value
    missing = [key for key in REQUIRED_ENV_KEYS if not found.get(key)]
    if missing:
        raise ReviewError(f"missing required .env fields: {', '.join(missing)}")
    return found


def sanitize(value: str, secret: str | None) -> str:
    return value.replace(secret, "[REDACTED_API_KEY]") if secret else value


SECTION_RE = re.compile(
    r"(?m)^(?:\s*)(?:(?:\d+(?:\.\d+)*\.?|[A-Z])\s+)[A-Z][^\n]{2,100}$"
)


def _sections(text: str) -> tuple[str, ...]:
    headings = []
    for match in SECTION_RE.finditer(text):
        heading = " ".join(match.group(0).split())
        if heading not in headings:
            headings.append(heading)
    return tuple(headings)


def extract_pdf(path: Path, paper_id: str) -> PaperSource:
    reader = PdfReader(str(path), strict=False)
    pages: list[PageText] = []
    for index, page in enumerate(reader.pages, 1):
        # Default extraction includes rotated text; pypdf's layout mode warns
        # that it drops it, which would violate the no-truncation requirement.
        text = page.extract_text() or ""
        text = text.replace("\x00", "")
        pages.append(PageText(index, text, _sections(text)))
    if not pages:
        raise ReviewError(f"{paper_id}: PDF has no pages")
    char_count = sum(len(page.text) for page in pages)
    nonempty = sum(bool(page.text.strip()) for page in pages)
    ratio = nonempty / len(pages)
    if ratio < 0.9 or char_count < len(pages) * 250:
        raise ReviewError(
            f"{paper_id}: inadequate PDF text coverage: {char_count} chars, "
            f"{ratio:.1%} nonempty pages"
        )
    lower_text = "\n".join(page.text for page in pages).lower()
    markers = tuple(marker for marker in REDACTION_MARKERS if marker in lower_text)
    return PaperSource(
        paper_id=paper_id,
        path=path.resolve(),
        sha256=sha256_file(path),
        pages=tuple(pages),
        char_count=char_count,
        nonempty_page_ratio=ratio,
        redaction_markers=markers,
    )


def download_0021(destination: Path, timeout: float = 120.0) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    request = urllib.request.Request(ARXIV_0021_URL, headers={"User-Agent": "SciReplicate-review/2"})
    temporary = destination.with_suffix(".download")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, temporary.open("wb") as handle:
            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower():
                raise ReviewError(f"0021 arXiv response is not PDF: {content_type!r}")
            while block := response.read(1024 * 1024):
                handle.write(block)
        if temporary.read_bytes()[:5] != b"%PDF-":
            raise ReviewError("0021 arXiv download lacks PDF signature")
        os.replace(temporary, destination)
    except (OSError, urllib.error.URLError) as exc:
        raise ReviewError(f"failed to retrieve complete 0021 arXiv v3 PDF: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def copy_verified(source: Path, destination: Path) -> Path:
    """Copy a source artifact and prove that the destination is byte-identical."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected_hash = sha256_file(source)
    if destination.exists():
        if sha256_file(destination) != expected_hash:
            raise ReviewError(f"existing copied source has wrong SHA256: {destination}")
        return destination
    temporary = destination.with_suffix(".copy")
    try:
        shutil.copyfile(source, temporary)
        if sha256_file(temporary) != expected_hash:
            raise ReviewError(f"copied source failed SHA256 verification: {source}")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def resolve_pdf(repo_root: Path, output_root: Path, paper_id: str) -> Path:
    if paper_id == "0021":
        destination = output_root / "sources" / "0021_arxiv_2406.19339v3.pdf"
        prior_full_source = (
            repo_root
            / "paper_replication_tasks/core_algorithm_review_v2/sources/0021_arxiv_2406.19339v3.pdf"
        )
        if prior_full_source.is_file():
            return copy_verified(prior_full_source, destination)
        return download_0021(destination)
    if paper_id == "0022":
        path = repo_root / "paper_replication_tasks/curation_tools/ssarnoldi_paper/paper_original_arxiv_v3.pdf"
    else:
        path = repo_root / f"paper_replication_tasks/scibench_replication_{paper_id}/public/paper.pdf"
    if not path.is_file():
        raise ReviewError(f"{paper_id}: required paper PDF not found: {path}")
    return path


def load_source(repo_root: Path, output_root: Path, paper_id: str) -> PaperSource:
    source = extract_pdf(resolve_pdf(repo_root, output_root, paper_id), paper_id)
    if source.redaction_markers:
        raise ReviewError(f"{paper_id}: redaction markers detected: {source.redaction_markers}")
    return source


def render_pages(pages: Sequence[PageText]) -> str:
    rendered = []
    for page in pages:
        section_text = " | ".join(page.sections) if page.sections else "(no heading detected)"
        rendered.append(
            f"===== PAGE {page.number} =====\n"
            f"DETECTED SECTION BOUNDARIES: {section_text}\n"
            f"{page.text.rstrip()}"
        )
    return "\n\n".join(rendered)


def audit_prompt(prompt: str) -> None:
    matches = [marker for marker in FORBIDDEN_PROMPT_MARKERS if marker.lower() in prompt.lower()]
    if matches:
        raise ReviewError(f"prompt contamination markers detected: {matches}")


def build_full_prompt(paper_id: str, rubric: str, pages: Sequence[PageText]) -> str:
    prompt = (
        "===== GOVERNING RUBRIC (PAPER.md) =====\n"
        f"{rubric.rstrip()}\n\n"
        "===== REQUIRED JSON OUTPUT SCHEMA =====\n"
        "Put each unique quotation once in evidence_catalog; every other evidence array contains "
        "only catalog IDs such as E1.\n"
        f"Return this object directly (do not add an output_object wrapper):\n{json.dumps(FINAL_SCHEMA, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "Return compact single-line JSON only: no Markdown fence and no indentation. Every evidence "
        "reference list must contain exactly one strongest catalog ID. Every summary, description, reason, graph "
        "relation, and contract list item must be at most 30 words; every excerpt must be 8-25 "
        "words. Keep the complete response under 6,000 tokens while listing every distinct candidate. "
        "Apply only G1-G5 at this paper-selection stage. "
        "G6-G8 must be NOT_EVALUATED. Classify every algorithmic candidate, apply the "
        "deletion test, and use short verbatim evidence excerpts with the printed PDF page "
        "number and section. Select exactly one core candidate only if justified. The fixed "
        "decision rule is ACCEPT_FOR_DESIGN iff G1-G5 all PASS and exactly one candidate "
        "has role core; otherwise REJECT_PAPER. Do not infer evidence not present in the paper.\n\n"
        f"===== COMPLETE PAPER {paper_id} =====\n{render_pages(pages)}\n\n"
        "===== OUTPUT REMINDER AFTER THE COMPLETE PAPER =====\n"
        "Return the required root object directly as compact single-line JSON, without a fence. "
        "Target at most 4,500 tokens. Use short candidate names (at most 12 words), phrases rather "
        "than prose where possible, and exactly one catalog ID per evidence reference list. Each catalog excerpt "
        "must be one contiguous, exact 8-25-word substring copied from its cited page: never "
        "paraphrase, repair wording, or omit intervening symbols/words. Recheck every excerpt "
        "against the paper text above before returning. The page field is the N in the nearest "
        "preceding `===== PAGE N =====` marker, not a page inferred from section order or article pagination.\n"
    )
    audit_prompt(prompt)
    return prompt


def build_chunk_prompt(
    paper_id: str, rubric: str, pages: Sequence[PageText]
) -> str:
    prompt = (
        "===== GOVERNING RUBRIC (PAPER.md) =====\n"
        f"{rubric.rstrip()}\n\n"
        "===== CONTRIBUTION-EVIDENCE JSON SCHEMA =====\n"
        f"Evidence objects have this shape: {json.dumps(EVIDENCE_SCHEMA, ensure_ascii=False)}\n"
        f"Return this object directly (do not add an output_object wrapper):\n{json.dumps(CHUNK_SCHEMA, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "Return compact single-line JSON without a Markdown fence, using exactly one 8-25-word "
        "excerpt per evidence list and at most 30 words per summary or description. "
        "This is a page-boundary context fallback. Extract contribution and candidate-algorithm "
        "evidence only; do not make the final gate decision. Return one JSON object only. Every "
        "claim must cite a short verbatim excerpt, printed page number, and section.\n\n"
        f"===== PAPER {paper_id} PAGES {pages[0].number}-{pages[-1].number} =====\n"
        f"{render_pages(pages)}\n\n"
        "Return compact single-line JSON now. Copy each excerpt as one exact contiguous substring "
        "from the cited page without repairing PDF spacing or hyphenation. Set page to the N in "
        "the excerpt's nearest preceding `===== PAGE N =====` marker.\n"
    )
    audit_prompt(prompt)
    return prompt


def build_synthesis_prompt(paper_id: str, rubric: str, chunk_records: Sequence[Mapping[str, Any]]) -> str:
    prompt = (
        "===== GOVERNING RUBRIC (PAPER.md) =====\n"
        f"{rubric.rstrip()}\n\n"
        "===== REQUIRED JSON OUTPUT SCHEMA =====\n"
        "Put each unique quotation once in evidence_catalog; all evidence arrays contain only its IDs.\n"
        f"Return this object directly (do not add an output_object wrapper):\n{json.dumps(FINAL_SCHEMA, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "Return compact single-line JSON only: no Markdown fence or indentation, exactly one catalog ID "
        "per evidence reference list, at most 30 words per summary/reason/list item, and 8-25 words per catalog excerpt. "
        "Keep the complete response under 6,000 tokens. The complete paper was transmitted in page-boundary chunks "
        "after an explicit endpoint context-length rejection. Synthesize only from the validated, "
        "page-linked extraction below. Apply G1-G5; set G6-G8 to NOT_EVALUATED. The decision is "
        "ACCEPT_FOR_DESIGN iff G1-G5 all PASS and exactly one candidate has role core.\n\n"
        "===== COMPLETE VALIDATED CONTRIBUTION EVIDENCE FROM ALL PAPER PAGES =====\n"
        f"{json.dumps(list(chunk_records), ensure_ascii=False, indent=2)}\n\n"
        "Return the direct root object as compact single-line JSON under 4,500 tokens, with exactly "
        "one validated evidence catalog ID per reference list.\n"
    )
    audit_prompt(prompt)
    return prompt


def normalize_evidence_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\u00ad", "")
    value = value.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"}))
    value = re.sub(r"(?<=\w)-\s+(?=\w)", "", value)
    return " ".join(value.split()).casefold()


def compact_evidence_text(value: str) -> str:
    value = re.sub(r"(?<=\w)[-‐‑](?=\w)", "", value)
    return re.sub(r"\s+", "", value)


def parse_json_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ResponseValidationError(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ResponseValidationError("response root must be a JSON object")
    return value


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ResponseValidationError(message)


def iter_evidence(value: Any, path: str = "$") -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key == "evidence":
                _expect(isinstance(child, list), f"{child_path} must be an array")
                for index, item in enumerate(child):
                    _expect(isinstance(item, dict), f"{child_path}[{index}] must be an object")
                    yield f"{child_path}[{index}]", item
            else:
                yield from iter_evidence(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_evidence(child, f"{path}[{index}]")


def _validate_evidence_object(evidence: Mapping[str, Any], path: str, page_map: Mapping[int, str]) -> None:
    _expect(set(evidence) == {"page", "section", "excerpt"}, f"{path} has invalid fields")
    page_number = evidence.get("page")
    section = evidence.get("section")
    excerpt = evidence.get("excerpt")
    _expect(isinstance(page_number, int) and page_number in page_map, f"{path}.page out of range")
    _expect(isinstance(section, str) and bool(section.strip()), f"{path}.section is empty")
    _expect(isinstance(excerpt, str) and 8 <= len(excerpt) <= 500, f"{path}.excerpt length invalid")
    normalized_excerpt = normalize_evidence_text(excerpt)
    page_text = page_map[page_number]
    compact_excerpt = compact_evidence_text(normalized_excerpt)
    compact_page = compact_evidence_text(page_text)
    _expect(
        normalized_excerpt in page_text or compact_excerpt in compact_page,
        f"{path}.excerpt does not match PDF page {page_number}",
    )


def validate_inline_evidence(record: Mapping[str, Any], pages: Sequence[PageText]) -> None:
    page_map = {page.number: normalize_evidence_text(page.text) for page in pages}
    evidence_count = 0
    for path, evidence in iter_evidence(record):
        evidence_count += 1
        _validate_evidence_object(evidence, path, page_map)
    _expect(evidence_count > 0, "response contains no evidence")


def validate_catalog_evidence(record: Mapping[str, Any], pages: Sequence[PageText]) -> None:
    catalog = record.get("evidence_catalog")
    _expect(isinstance(catalog, list) and catalog, "$.evidence_catalog must be nonempty")
    page_map = {page.number: normalize_evidence_text(page.text) for page in pages}
    evidence_ids: set[str] = set()
    for index, item in enumerate(catalog):
        path = f"$.evidence_catalog[{index}]"
        _expect(isinstance(item, dict), f"{path} must be an object")
        _expect(set(item) == {"id", "page", "section", "excerpt"}, f"{path} has invalid fields")
        evidence_id = item.get("id")
        _expect(isinstance(evidence_id, str) and re.fullmatch(r"E[1-9][0-9]*", evidence_id) is not None, f"{path}.id invalid")
        _expect(evidence_id not in evidence_ids, f"duplicate evidence id {evidence_id}")
        evidence_ids.add(evidence_id)
        _validate_evidence_object({k: item[k] for k in ("page", "section", "excerpt")}, path, page_map)

    reference_count = 0
    def walk(value: Any, path: str = "$") -> None:
        nonlocal reference_count
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if key == "evidence":
                    _expect(isinstance(child, list), f"{child_path} must be an array")
                    for index, evidence_id in enumerate(child):
                        _expect(evidence_id in evidence_ids, f"{child_path}[{index}] unknown evidence id")
                        reference_count += 1
                elif key != "evidence_catalog":
                    walk(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
    walk(record)
    _expect(reference_count > 0, "response contains no evidence references")


def _validate_gate_shape(gates: Any) -> None:
    _expect(isinstance(gates, dict), "$.gates must be an object")
    _expect(set(gates) == {f"G{i}" for i in range(1, 9)}, "$.gates must contain exactly G1-G8")
    for gate in ("G1", "G2", "G3", "G4", "G5"):
        result = gates[gate]
        _expect(isinstance(result, dict), f"$.gates.{gate} must be an object")
        _expect(result.get("status") in {"PASS", "REJECT"}, f"$.gates.{gate}.status invalid")
        _expect(isinstance(result.get("reason"), str) and result["reason"].strip(), f"$.gates.{gate}.reason missing")
        _expect(isinstance(result.get("evidence"), list) and result["evidence"], f"$.gates.{gate}.evidence missing")
    for gate in ("G6", "G7", "G8"):
        result = gates[gate]
        _expect(isinstance(result, dict), f"$.gates.{gate} must be an object")
        _expect(result.get("status") == "NOT_EVALUATED", f"$.gates.{gate} must be NOT_EVALUATED")
        _expect(result.get("evidence") == [], f"$.gates.{gate}.evidence must be empty")


def validate_final_record(record: dict[str, Any], source: PaperSource) -> dict[str, Any]:
    required = set(FINAL_SCHEMA)
    _expect(set(record) == required, f"response fields must be exactly {sorted(required)}")
    _expect(record.get("schema_version") == SCHEMA_VERSION, "schema_version mismatch")
    _expect(record.get("paper_id") == source.paper_id, "paper_id mismatch")
    goal = record.get("research_goal")
    _expect(isinstance(goal, dict) and isinstance(goal.get("summary"), str) and goal.get("evidence"), "research_goal invalid")
    _expect(isinstance(record.get("main_contributions"), list) and record["main_contributions"], "main_contributions empty")
    _expect(isinstance(record.get("contribution_graph"), list) and record["contribution_graph"], "contribution_graph empty")
    candidates = record.get("candidate_algorithms")
    _expect(isinstance(candidates, list) and candidates, "candidate_algorithms empty")
    names: list[str] = []
    for index, candidate in enumerate(candidates):
        _expect(isinstance(candidate, dict), f"candidate_algorithms[{index}] invalid")
        _expect(
            set(candidate) == {"name", "role", "description", "evidence", "deletion_test"},
            f"candidate_algorithms[{index}] fields invalid",
        )
        _expect(isinstance(candidate["name"], str) and candidate["name"].strip(), f"candidate {index} name invalid")
        _expect(candidate["role"] in ALLOWED_ROLES, f"candidate {index} role invalid")
        _expect(candidate["evidence"], f"candidate {index} evidence empty")
        deletion = candidate["deletion_test"]
        _expect(isinstance(deletion, dict), f"candidate {index} deletion_test invalid")
        _expect(
            deletion.get("outcome") in {"FAILS_WITHOUT_ALGORITHM", "SURVIVES_WITHOUT_ALGORITHM", "UNCERTAIN"},
            f"candidate {index} deletion outcome invalid",
        )
        _expect(deletion.get("evidence"), f"candidate {index} deletion evidence empty")
        names.append(candidate["name"])
    _expect(len(names) == len(set(names)), "candidate names must be unique")
    core_names = [candidate["name"] for candidate in candidates if candidate["role"] == "core"]
    selected = record.get("selected_core_algorithm")
    _expect(selected is None or selected in names, "selected_core_algorithm is not a candidate")
    _expect(isinstance(record.get("uniqueness_reason"), str) and record["uniqueness_reason"].strip(), "uniqueness_reason missing")
    _validate_gate_shape(record.get("gates"))
    all_pass = all(record["gates"][f"G{i}"]["status"] == "PASS" for i in range(1, 6))
    accepted = all_pass and len(core_names) == 1
    _expect((len(core_names) == 1) == (selected is not None), "selected core and core-role count inconsistent")
    if selected is not None:
        _expect(selected == core_names[0], "selected core name inconsistent")
        contract = record.get("scientific_contract")
        contract_fields = set(FINAL_SCHEMA["scientific_contract"])
        _expect(isinstance(contract, dict) and set(contract) == contract_fields, "scientific_contract invalid")
        _expect(contract.get("algorithm") == selected, "scientific_contract algorithm mismatch")
        for field in contract_fields - {"algorithm", "evidence"}:
            _expect(bool(contract.get(field)), f"scientific_contract.{field} is empty")
        _expect(contract.get("evidence"), "scientific_contract.evidence empty")
    else:
        _expect(record.get("scientific_contract") is None, "scientific_contract must be null without selected core")
    expected_decision = "ACCEPT_FOR_DESIGN" if accepted else "REJECT_PAPER"
    _expect(record.get("decision") == expected_decision, "decision inconsistent with hard gates/core count")
    _expect(record["gates"]["G2"]["status"] == ("PASS" if len(core_names) == 1 else "REJECT"), "G2 inconsistent with core count")
    _expect(isinstance(record.get("evidence_gaps"), list), "evidence_gaps must be an array")
    validate_catalog_evidence(record, source.pages)
    return record


def validate_chunk_record(
    record: dict[str, Any], source: PaperSource, chunk_pages: Sequence[PageText]
) -> dict[str, Any]:
    _expect(set(record) == set(CHUNK_SCHEMA), "chunk response fields invalid")
    _expect(record.get("paper_id") == source.paper_id, "chunk paper_id mismatch")
    _expect(record.get("page_range") == [chunk_pages[0].number, chunk_pages[-1].number], "chunk page_range mismatch")
    for field in ("research_goal_evidence", "contribution_evidence", "algorithm_evidence", "experiment_result_links"):
        _expect(isinstance(record.get(field), list), f"chunk {field} must be an array")
    allowed_pages = tuple(page for page in source.pages if chunk_pages[0].number <= page.number <= chunk_pages[-1].number)
    validate_inline_evidence(record, allowed_pages)
    return record


def is_context_length_error(status: int | None, message: str) -> bool:
    if status not in {400, 413, 422}:
        return False
    lower = message.lower()
    return any(
        marker in lower
        for marker in (
            "context length",
            "context_length",
            "maximum context",
            "too many tokens",
            "prompt is too long",
            "request too large",
        )
    )


def is_temporary_provider_error(status: int, message: str) -> bool:
    """Recognize transient provider routing failures without masking bad model IDs."""
    lower = message.lower()
    permanent = ("invalid model", "model not found", "unknown model", "not a valid model")
    if any(marker in lower for marker in permanent):
        return False
    transient = (
        "temporarily unavailable",
        "provider unavailable",
        "provider is unavailable",
        "no endpoints found",
        "no available endpoints",
        "no available providers",
        "upstream overloaded",
    )
    return status in {400, 404, 408, 409, 425, 429, 503} and any(
        marker in lower for marker in transient
    )


def build_correction_prompt(original_prompt: str, response: str, validator_error: str) -> str:
    """Request a schema/evidence-only correction while preserving scientific judgments."""
    return (
        f"{original_prompt.rstrip()}\n\n"
        "===== CORRECTION RETRY =====\n"
        "Your previous response failed the strict validator. Fix only its JSON structure and "
        "evidence citations; do not change unrelated scientific judgments, candidate names, "
        "core uniqueness, gates, or decision. The corrected response must still satisfy every "
        "scientific constraint above.\n"
        f"EXACT VALIDATOR ERROR:\n{validator_error}\n"
        f"ORIGINAL RESPONSE:\n{response}\n"
        "Return only the corrected compact JSON root object.\n"
    )


def retry_delay_from_response(
    headers: Mapping[str, str], body: str, fallback: float
) -> float:
    """Read Retry-After from either HTTP headers or OpenAI-compatible error metadata."""
    candidates: list[Any] = [headers.get("Retry-After")]
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            error = parsed.get("error", {})
            metadata = error.get("metadata", {}) if isinstance(error, dict) else {}
            if isinstance(metadata, dict):
                candidates.extend(
                    [metadata.get("retry_after_seconds"), metadata.get("retry_after_seconds_raw")]
                )
                nested_headers = metadata.get("headers", {})
                if isinstance(nested_headers, dict):
                    candidates.append(nested_headers.get("Retry-After"))
    except json.JSONDecodeError:
        pass
    delays: list[float] = []
    for candidate in candidates:
        try:
            delays.append(max(0.0, float(candidate)))
        except (TypeError, ValueError):
            continue
    return max(delays, default=fallback)


class PersistentRateLimiter:
    def __init__(
        self,
        state_path: Path,
        rpm: float,
        *,
        reserve_rpm: float = 0.0,
        audit_path: Path | None = None,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if rpm <= 0 or reserve_rpm < 0 or reserve_rpm >= rpm:
            raise ValueError("rpm must be positive and reserve_rpm must be in [0, rpm)")
        self.state_path = state_path
        self.lock_path = state_path.with_suffix(state_path.suffix + ".lock")
        self.audit_path = audit_path
        self.rpm = rpm
        self.reserve_rpm = reserve_rpm
        self.effective_rpm = rpm - reserve_rpm
        self.interval = 60.0 / self.effective_rpm
        self.clock = clock
        self.sleeper = sleeper

    def wait(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = self._read_state()
            now = self.clock()
            calls = sorted(
                float(value)
                for value in state.get("call_epochs", [])
                if isinstance(value, (int, float)) and float(value) > now - 60.0
            )
            legacy_last = float(state.get("last_call_epoch", 0.0))
            last_reserved = max(calls[-1] if calls else 0.0, legacy_last)
            scheduled = max(now, last_reserved + self.interval, float(state.get("next_allowed_epoch", 0.0)))
            capacity = max(1, int(self.effective_rpm))
            if len(calls) >= capacity:
                scheduled = max(scheduled, calls[-capacity] + 60.0)
            calls.append(scheduled)
            updated = {
                "schema_version": 2,
                "rpm": self.rpm,
                "reserve_rpm": self.reserve_rpm,
                "effective_rpm": self.effective_rpm,
                "call_epochs": calls,
                "last_call_epoch": scheduled,
                "next_allowed_epoch": 0.0,
            }
            self._write_state(updated)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        delay = max(0.0, scheduled - self.clock())
        if delay:
            self.sleeper(delay)

    def _read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            value = json.loads(self.state_path.read_text())
            return value if isinstance(value, dict) else {}
        except (ValueError, OSError, json.JSONDecodeError):
            return {}

    def _write_state(self, state: Mapping[str, Any]) -> None:
        atomic_write_json(self.state_path, state)
        if self.audit_path is not None and self.audit_path != self.state_path:
            atomic_write_json(self.audit_path, state)

    def defer(self, delay: float) -> None:
        """Persist a provider cooldown shared by every cooperating process."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = self._read_state()
            state["next_allowed_epoch"] = max(
                float(state.get("next_allowed_epoch", 0.0)), self.clock() + max(0.0, delay)
            )
            state.setdefault("call_epochs", [])
            state.setdefault("last_call_epoch", self.clock())
            state.update(
                {
                    "schema_version": 2,
                    "rpm": self.rpm,
                    "reserve_rpm": self.reserve_rpm,
                    "effective_rpm": self.effective_rpm,
                }
            )
            self._write_state(state)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class HTTPTransport:
    def __init__(self, endpoint: str, api_key: str, timeout: float) -> None:
        endpoint = endpoint.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout

    def __call__(self, payload: Mapping[str, Any]) -> tuple[int, Mapping[str, str], str]:
        try:
            response = requests.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise TimeoutError("model endpoint timed out") from exc
        except requests.RequestException as exc:
            raise ConnectionError(f"model endpoint request failed: {exc}") from exc
        return response.status_code, response.headers, response.text


class ReviewAPI:
    def __init__(
        self,
        model: str,
        transport: Callable[[Mapping[str, Any]], tuple[int, Mapping[str, str], str]],
        limiter: PersistentRateLimiter,
        *,
        max_retries: int = 3,
        max_provider_retries: int | None = None,
        max_output_tokens: int = 8000,
        sleeper: Callable[[float], None] = time.sleep,
        error_sink: Callable[[Mapping[str, Any]], None] | None = None,
        response_sink: Callable[[Mapping[str, Any]], None] | None = None,
        call_sink: Callable[[Mapping[str, Any]], None] | None = None,
        secret: str | None = None,
    ) -> None:
        self.model = model
        self.transport = transport
        self.limiter = limiter
        self.max_retries = max_retries
        self.max_provider_retries = max_retries if max_provider_retries is None else max_provider_retries
        self.max_output_tokens = max_output_tokens
        self.sleeper = sleeper
        self.error_sink = error_sink or (lambda _: None)
        self.response_sink = response_sink or (lambda _: None)
        self.call_sink = call_sink or (lambda _: None)
        self.secret = secret
        self.call_count = 0
        self.usage: list[dict[str, Any]] = []

    def complete(
        self,
        prompt: str,
        validator: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        stage: str,
    ) -> tuple[dict[str, Any], str, APIResult]:
        last_error: Exception | None = None
        active_prompt = prompt
        attempt = 0
        validation_failures = 0
        provider_failures = 0
        while True:
            attempt += 1
            response_text: Any = None
            try:
                self.limiter.wait()
                self.call_count += 1
                self.call_sink(
                    {
                        "timestamp": utc_now(),
                        "stage": stage,
                        "attempt": attempt,
                        "sequence": self.call_count,
                        "model": self.model,
                        "correction_retry": attempt > 1 and active_prompt != prompt,
                    }
                )
                status, headers, body = self.transport(
                    {
                        "model": self.model,
                        "messages": [{"role": "user", "content": active_prompt}],
                        "temperature": 0,
                        "max_tokens": self.max_output_tokens,
                        "reasoning": REASONING_CONFIG,
                    }
                )
                if status >= 400:
                    self.response_sink(
                        {
                            "timestamp": utc_now(),
                            "stage": stage,
                            "attempt": attempt,
                            "text": sanitize(body, self.secret),
                            "usage": {},
                            "response_id": None,
                            "finish_reason": None,
                            "message_fields": [],
                            "http_status": status,
                            "response_kind": "http_error",
                        }
                    )
                    if is_context_length_error(status, body):
                        raise ContextLengthError(sanitize(body[:1000], self.secret))
                    if status == 429:
                        delay = retry_delay_from_response(
                            headers, body, min(60.0, 2.0 ** provider_failures)
                        )
                        raise _RetryableHTTPError(status, sanitize(body[:1000], self.secret), delay)
                    if status >= 500:
                        raise _RetryableHTTPError(status, sanitize(body[:1000], self.secret), min(60.0, 2.0 ** (attempt - 1)))
                    if is_temporary_provider_error(status, body):
                        raise _RetryableHTTPError(
                            status, sanitize(body[:1000], self.secret), min(60.0, 2.0 ** (attempt - 1))
                        )
                    raise ReviewError(f"endpoint HTTP {status}: {sanitize(body[:1000], self.secret)}")
                try:
                    envelope = json.loads(body)
                    choice = envelope["choices"][0]
                    message = choice["message"]
                    response_text = message["content"]
                except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                    raise ResponseValidationError(f"invalid endpoint response envelope: {exc}") from exc
                usage = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
                self.usage.append(usage)
                self.response_sink(
                    {
                        "timestamp": utc_now(),
                        "stage": stage,
                        "attempt": attempt,
                        "text": response_text,
                        "usage": usage,
                        "response_id": envelope.get("id"),
                        "finish_reason": choice.get("finish_reason"),
                        "message_fields": sorted(message) if isinstance(message, dict) else [],
                    }
                )
                if not isinstance(response_text, str) or not response_text.strip():
                    raise ResponseValidationError(
                        "endpoint returned empty message.content "
                        f"(finish_reason={choice.get('finish_reason')!r}, fields={sorted(message)})"
                    )
                record = validator(parse_json_response(response_text))
                result = APIResult(response_text, usage, envelope.get("id"))
                return record, response_text, result
            except ContextLengthError:
                raise
            except (_RetryableHTTPError, TimeoutError, ConnectionError, ResponseValidationError) as exc:
                last_error = exc
                if isinstance(exc, ResponseValidationError) and isinstance(response_text, str):
                    active_prompt = build_correction_prompt(prompt, response_text, str(exc))
                self.error_sink(
                    {
                        "timestamp": utc_now(),
                        "stage": stage,
                        "attempt": attempt,
                        "type": type(exc).__name__,
                        "message": sanitize(str(exc), self.secret),
                    }
                )
                if isinstance(exc, ResponseValidationError):
                    validation_failures += 1
                    exhausted = validation_failures > self.max_retries
                else:
                    provider_failures += 1
                    exhausted = provider_failures > self.max_provider_retries
                if exhausted:
                    break
                delay = exc.delay if isinstance(exc, _RetryableHTTPError) else min(30.0, 2.0 ** (attempt - 1))
                if isinstance(exc, _RetryableHTTPError) and hasattr(self.limiter, "defer"):
                    self.limiter.defer(delay)
                self.sleeper(delay)
        raise ReviewError(f"{stage} failed after {attempt} attempts: {last_error}")


class _RetryableHTTPError(ReviewError):
    def __init__(self, status: int, message: str, delay: float) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.delay = delay


def page_chunks(pages: Sequence[PageText], token_budget: int) -> list[tuple[PageText, ...]]:
    if token_budget <= 0:
        raise ValueError("chunk token budget must be positive")
    chunks: list[tuple[PageText, ...]] = []
    current: list[PageText] = []
    estimated = 0
    for page in pages:
        page_tokens = max(1, (len(page.text) + 3) // 4)
        if current and estimated + page_tokens > token_budget:
            chunks.append(tuple(current))
            current = []
            estimated = 0
        current.append(page)
        estimated += page_tokens
    if current:
        chunks.append(tuple(current))
    return chunks


def extract_chunk_with_split(
    api: ReviewAPI,
    source: PaperSource,
    rubric: str,
    pages: tuple[PageText, ...],
) -> list[dict[str, Any]]:
    prompt = build_chunk_prompt(source.paper_id, rubric, pages)
    validator = lambda record: validate_chunk_record(record, source, pages)
    try:
        record, _, _ = api.complete(prompt, validator, stage=f"chunk-{pages[0].number}-{pages[-1].number}")
        return [record]
    except ContextLengthError:
        if len(pages) == 1:
            raise ReviewError(f"single PDF page {pages[0].number} exceeds endpoint context")
        midpoint = len(pages) // 2
        return extract_chunk_with_split(api, source, rubric, pages[:midpoint]) + extract_chunk_with_split(
            api, source, rubric, pages[midpoint:]
        )


def metadata_for(
    source: PaperSource,
    rubric_hash: str,
    prompt_hash: str,
    model: str,
    max_output_tokens: int = 8000,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "paper_id": source.paper_id,
        "source_path": str(source.path),
        "source_sha256": source.sha256,
        "rubric_sha256": rubric_hash,
        "prompt_sha256": prompt_hash,
        "model": model,
        "page_count": len(source.pages),
        "character_count": source.char_count,
        "nonempty_page_ratio": source.nonempty_page_ratio,
        "redaction_markers": list(source.redaction_markers),
        "request_config": {
            "temperature": 0,
            "max_output_tokens": max_output_tokens,
            "reasoning": REASONING_CONFIG,
        },
    }


def checkpoint_status(paper_dir: Path, expected: Mapping[str, Any]) -> str:
    metadata_path = paper_dir / "metadata.json"
    record_path = paper_dir / "record.json"
    if not metadata_path.exists() and not record_path.exists():
        return "absent"
    if not metadata_path.exists():
        raise CheckpointMismatchError(f"{paper_dir.name}: record exists without metadata")
    actual = json.loads(metadata_path.read_text(encoding="utf-8"))
    identity = (
        "schema_version",
        "paper_id",
        "source_sha256",
        "rubric_sha256",
        "prompt_sha256",
        "model",
        "request_config",
    )
    differences = {key: (actual.get(key), expected.get(key)) for key in identity if actual.get(key) != expected.get(key)}
    if differences:
        raise CheckpointMismatchError(f"{paper_dir.name}: checkpoint hash/model mismatch: {differences}")
    return "complete" if record_path.exists() else "incomplete"


def review_one(
    source: PaperSource,
    rubric: str,
    rubric_hash: str,
    output_root: Path,
    api: ReviewAPI,
    *,
    resume: bool,
    chunk_token_budget: int,
) -> dict[str, Any]:
    paper_dir = output_root / source.paper_id
    full_prompt = build_full_prompt(source.paper_id, rubric, source.pages)
    metadata = metadata_for(
        source,
        rubric_hash,
        sha256_bytes(full_prompt.encode()),
        api.model,
        api.max_output_tokens,
    )
    status = checkpoint_status(paper_dir, metadata)
    if status != "absent" and not resume:
        raise ReviewError(f"{source.paper_id}: output exists; pass --resume")
    if status == "complete":
        record = json.loads((paper_dir / "record.json").read_text(encoding="utf-8"))
        validate_final_record(record, source)
        return {"paper_id": source.paper_id, "status": "RESUMED", "record": record}

    paper_dir.mkdir(parents=True, exist_ok=True)
    errors_path = paper_dir / "errors.json"
    raw_path = paper_dir / "raw_responses.json"
    calls_path = paper_dir / "call_events.json"
    errors: list[dict[str, Any]] = json.loads(errors_path.read_text()) if errors_path.exists() else []
    raw_responses: list[dict[str, Any]] = json.loads(raw_path.read_text()) if raw_path.exists() else []
    call_events: list[dict[str, Any]] = json.loads(calls_path.read_text()) if calls_path.exists() else []
    if not call_events and raw_responses:
        call_events = [
            {"timestamp": response.get("timestamp"), "stage": response.get("stage"), "attempt": response.get("attempt"), "sequence": index}
            for index, response in enumerate(raw_responses, 1)
        ]
        atomic_write_json(calls_path, call_events)
    api.error_sink = lambda error: (errors.append(dict(error)), atomic_write_json(paper_dir / "errors.json", errors))
    api.response_sink = lambda response: (
        raw_responses.append(dict(response)),
        atomic_write_json(raw_path, raw_responses),
    )
    api.call_sink = lambda event: (
        call_events.append(dict(event)),
        atomic_write_json(calls_path, call_events),
    )
    for path, value in ((errors_path, errors), (raw_path, raw_responses), (calls_path, call_events)):
        if not path.exists():
            atomic_write_json(path, value)
    atomic_write_json(paper_dir / "metadata.json", metadata)
    mode = "single_full_call"
    try:
        record = None
        request_prompt = full_prompt
        request_stage = "full-review"
        for previous in reversed(raw_responses):
            if (
                previous.get("stage") not in {"full-review", "full-review-resume-correction"}
                or previous.get("response_kind") == "http_error"
                or not isinstance(previous.get("text"), str)
            ):
                continue
            try:
                record = validate_final_record(parse_json_response(previous["text"]), source)
                mode = "recovered_valid_full_response"
                break
            except ResponseValidationError as exc:
                request_prompt = build_correction_prompt(full_prompt, previous["text"], str(exc))
                request_stage = "full-review-resume-correction"
                mode = "resume_correction"
                break
        if record is None:
            try:
                record, _, _ = api.complete(
                    request_prompt,
                    lambda value: validate_final_record(value, source),
                    stage=request_stage,
                )
            except ContextLengthError as exc:
                mode = "page_chunk_fallback"
                errors.append({"timestamp": utc_now(), "stage": "full-review", "attempt": 1, "type": type(exc).__name__, "message": str(exc)})
                atomic_write_json(paper_dir / "errors.json", errors)
                chunks = page_chunks(source.pages, chunk_token_budget)
                chunk_records: list[dict[str, Any]] = []
                for chunk in chunks:
                    chunk_records.extend(extract_chunk_with_split(api, source, rubric, chunk))
                atomic_write_json(paper_dir / "chunk_records.json", chunk_records)
                synthesis = build_synthesis_prompt(source.paper_id, rubric, chunk_records)
                record, _, _ = api.complete(
                    synthesis,
                    lambda value: validate_final_record(value, source),
                    stage="synthesis",
                )
        atomic_write_json(raw_path, raw_responses)
        final_metadata = {
            **metadata,
            "completed_at": utc_now(),
            "call_count": len(call_events),
            "token_usage": [response.get("usage", {}) for response in raw_responses],
            "call_mode": mode,
        }
        atomic_write_json(paper_dir / "metadata.json", final_metadata)
        atomic_write_json(paper_dir / "record.json", record)
        stale_failure = paper_dir / "failure.json"
        if stale_failure.exists():
            stale_failure.unlink()
        return {"paper_id": source.paper_id, "status": "COMPLETE", "record": record}
    except Exception as exc:
        error = {"timestamp": utc_now(), "stage": "paper", "type": type(exc).__name__, "message": sanitize(str(exc), api.secret)}
        errors.append(error)
        atomic_write_json(paper_dir / "errors.json", errors)
        atomic_write_json(
            paper_dir / "metadata.json",
            {
                **metadata,
                "failed_at": utc_now(),
                "call_count": len(call_events),
                "token_usage": [response.get("usage", {}) for response in raw_responses],
                "call_mode": mode,
            },
        )
        atomic_write_json(
            paper_dir / "failure.json",
            {
                "paper_id": source.paper_id,
                "status": "FAILED",
                "error": error,
                "call_count": len(call_events),
            },
        )
        raise


def build_summary(results: Sequence[Mapping[str, Any]], output_root: Path, model: str) -> dict[str, Any]:
    papers = []
    for result in results:
        item: dict[str, Any] = {"paper_id": result["paper_id"], "status": result["status"]}
        if "record" in result:
            record = result["record"]
            item.update(
                {
                    "selected_core_algorithm": record["selected_core_algorithm"],
                    "gates": {gate: record["gates"][gate]["status"] for gate in record["gates"]},
                    "decision": record["decision"],
                    "evidence_gaps": record["evidence_gaps"],
                }
            )
        else:
            item["error"] = result.get("error", "unknown failure")
        papers.append(item)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "model": model,
        "complete_count": sum(item["status"] in {"COMPLETE", "RESUMED"} for item in papers),
        "failed_count": sum(item["status"] == "FAILED" for item in papers),
        "papers": papers,
    }
    atomic_write_json(output_root / "summary.json", summary)
    lines = ["# Core Algorithm Review v2", "", f"Model: `{model}`", "", "| Paper | Core algorithm | G1–G5 | Decision | Evidence gaps |", "| --- | --- | --- | --- | --- |"]
    for item in papers:
        if item["status"] == "FAILED":
            lines.append(f"| {item['paper_id']} | — | — | FAILED | {item['error']} |")
            continue
        gates = ", ".join(f"{gate}:{item['gates'][gate]}" for gate in ("G1", "G2", "G3", "G4", "G5"))
        core = item["selected_core_algorithm"] or "—"
        gaps = "; ".join(item["evidence_gaps"]) or "None stated"
        lines.append(f"| {item['paper_id']} | {core} | {gates} | {item['decision']} | {gaps} |")
    atomic_write_text(output_root / "summary.md", "\n".join(lines) + "\n")
    return summary


def build_comparison(output_root: Path, baseline_root: Path) -> dict[str, Any]:
    """Compare model runs without treating baseline failures as disagreements."""
    current = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))
    baseline = json.loads((baseline_root / "summary.json").read_text(encoding="utf-8"))
    current_by_id = {item["paper_id"]: item for item in current["papers"]}
    baseline_by_id = {item["paper_id"]: item for item in baseline["papers"]}
    papers: list[dict[str, Any]] = []
    disagreement_count = 0
    comparable_count = 0
    for paper_id in PAPER_IDS:
        old = baseline_by_id.get(paper_id, {"status": "MISSING"})
        new = current_by_id.get(paper_id, {"status": "MISSING"})
        old_complete = old.get("status") in {"COMPLETE", "RESUMED"}
        new_complete = new.get("status") in {"COMPLETE", "RESUMED"}
        item: dict[str, Any] = {
            "paper_id": paper_id,
            "v2_status": old.get("status", "MISSING"),
            "glm52_status": new.get("status", "MISSING"),
            "comparable": old_complete and new_complete,
            "disagreement": None,
        }
        if old_complete and new_complete:
            comparable_count += 1
            gate_comparison = {
                gate: {
                    "v2": old["gates"][gate],
                    "glm52": new["gates"][gate],
                    "match": old["gates"][gate] == new["gates"][gate],
                }
                for gate in ("G1", "G2", "G3", "G4", "G5")
            }
            core_match = old.get("selected_core_algorithm") == new.get("selected_core_algorithm")
            decision_match = old.get("decision") == new.get("decision")
            disagreement = not core_match or not decision_match or any(
                not comparison["match"] for comparison in gate_comparison.values()
            )
            disagreement_count += int(disagreement)
            item.update(
                {
                    "core_algorithm": {
                        "v2": old.get("selected_core_algorithm"),
                        "glm52": new.get("selected_core_algorithm"),
                        "match": core_match,
                    },
                    "gates": gate_comparison,
                    "decision": {
                        "v2": old.get("decision"),
                        "glm52": new.get("decision"),
                        "match": decision_match,
                    },
                    "disagreement": disagreement,
                }
            )
        elif not old_complete:
            item["note"] = "v2 was not complete; this is not a model disagreement"
        else:
            item["note"] = "GLM-5.2 run was not complete; no model comparison"
        papers.append(item)

    comparison = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "v2_model": baseline.get("model"),
        "glm52_model": current.get("model"),
        "coverage": {
            "v2_complete": baseline.get("complete_count", 0),
            "v2_failed": baseline.get("failed_count", 0),
            "glm52_complete": current.get("complete_count", 0),
            "glm52_failed": current.get("failed_count", 0),
            "jointly_complete": comparable_count,
        },
        "disagreement_count": disagreement_count,
        "papers": papers,
        "aggregation": "none; no merge or vote was performed",
    }
    atomic_write_json(output_root / "comparison_v2.json", comparison)
    lines = [
        "# Core Algorithm Review v2 Comparison",
        "",
        f"Models: `{baseline.get('model')}` vs `{current.get('model')}`",
        "",
        "No merge or vote was performed. A FAILED run is not a model disagreement.",
        "",
        "| Paper | v2 | GLM-5.2 | Core match | G1–G5 match | Decision match |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in papers:
        if not item["comparable"]:
            lines.append(
                f"| {item['paper_id']} | {item['v2_status']} | {item['glm52_status']} | — | — | — |"
            )
            continue
        gate_match = all(value["match"] for value in item["gates"].values())
        lines.append(
            f"| {item['paper_id']} | {item['v2_status']} | {item['glm52_status']} | "
            f"{'yes' if item['core_algorithm']['match'] else 'no'} | "
            f"{'yes' if gate_match else 'no'} | {'yes' if item['decision']['match'] else 'no'} |"
        )
    atomic_write_text(output_root / "comparison_v2.md", "\n".join(lines) + "\n")
    return comparison


def ensure_output_isolation(output_root: Path, baseline_root: Path) -> None:
    output = output_root.resolve()
    baseline = baseline_root.resolve()
    if output == baseline or output in baseline.parents or baseline in output.parents:
        raise ReviewError("GLM output root must be strictly separate from core_algorithm_review_v2")


def is_retryable_run_failure(message: str) -> bool:
    lower = message.lower()
    return any(
        marker in lower
        for marker in (
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "temporarily unavailable",
            "provider unavailable",
            "no endpoints found",
            "timed out",
            "connectionerror",
            "request failed",
        )
    )


def dry_run(repo_root: Path, output_root: Path, rubric_hash: str) -> int:
    rows = []
    failures = 0
    for paper_id in PAPER_IDS:
        try:
            source = load_source(repo_root, output_root, paper_id)
            rows.append(
                {
                    "paper_id": paper_id,
                    "source_path": str(source.path),
                    "pages": len(source.pages),
                    "characters": source.char_count,
                    "estimated_tokens": (source.char_count + 3) // 4,
                    "source_sha256": source.sha256,
                    "rubric_sha256": rubric_hash,
                    "nonempty_page_ratio": source.nonempty_page_ratio,
                    "redaction_markers": list(source.redaction_markers),
                    "expected_call_mode": "single_full_call; page chunks only after explicit context error",
                }
            )
        except Exception as exc:
            failures += 1
            rows.append({"paper_id": paper_id, "status": "FAILED", "error": str(exc)})
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--output-root", type=Path, default=Path("paper_replication_tasks/core_algorithm_review_v2_glm52")
    )
    parser.add_argument("--rpm", type=float, default=20.0)
    parser.add_argument(
        "--rpm-reserve",
        type=float,
        default=0.0,
        help="RPM reserved for non-cooperating processes (effective RPM is --rpm minus this value)",
    )
    parser.add_argument(
        "--rate-limit-state",
        type=Path,
        help="shared rolling-window state; defaults to paper_replication_tasks/.review_api_rate_limit.json",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--resume-rounds",
        type=int,
        default=1,
        help="fair retry sweeps over only transiently failed papers; use with --resume",
    )
    parser.add_argument(
        "--resume-round-delay",
        type=float,
        default=0.0,
        help="seconds to wait between transient-failure resume sweeps",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-provider-retries", type=int, default=12)
    parser.add_argument("--max-output-tokens", type=int, default=8000)
    parser.add_argument("--chunk-token-budget", type=int, default=24000)
    parser.add_argument("--paper-id", action="append", choices=PAPER_IDS, dest="paper_ids")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    output_root = args.output_root.resolve()
    baseline_root = (repo_root / "paper_replication_tasks/core_algorithm_review_v2").resolve()
    ensure_output_isolation(output_root, baseline_root)
    rubric_path = repo_root / "PAPER.md"
    rubric = rubric_path.read_text(encoding="utf-8")
    rubric_hash = sha256_bytes(rubric.encode())
    if args.dry_run:
        return dry_run(repo_root, output_root, rubric_hash)
    if args.resume_rounds <= 0:
        raise ReviewError("--resume-rounds must be positive")
    if args.resume_round_delay < 0:
        raise ReviewError("--resume-round-delay must be nonnegative")
    if args.resume_rounds > 1 and not args.resume:
        raise ReviewError("--resume-rounds > 1 requires --resume")

    env = read_env_file(args.env_file)
    output_root.mkdir(parents=True, exist_ok=True)
    shared_limit_path = (
        args.rate_limit_state.resolve()
        if args.rate_limit_state
        else repo_root / "paper_replication_tasks/.review_api_rate_limit.json"
    )
    limiter = PersistentRateLimiter(
        shared_limit_path,
        args.rpm,
        reserve_rpm=args.rpm_reserve,
        audit_path=output_root / "rate_limit.json",
    )
    provider_retries = 0 if args.resume_rounds > 1 else args.max_provider_retries
    api = ReviewAPI(
        args.model,
        HTTPTransport(env["ENDPOINT"], env["API_KEY"], args.timeout),
        limiter,
        max_retries=args.max_retries,
        max_provider_retries=provider_retries,
        max_output_tokens=args.max_output_tokens,
        secret=env["API_KEY"],
    )
    paper_ids = tuple(args.paper_ids or PAPER_IDS)
    latest: dict[str, dict[str, Any]] = {}
    pending = list(paper_ids)
    for round_number in range(1, args.resume_rounds + 1):
        if round_number > 1:
            print(f"[resume round {round_number}] pending={','.join(pending)}", file=sys.stderr, flush=True)
        for paper_id in pending:
            print(f"[{paper_id}] extracting and reviewing", file=sys.stderr, flush=True)
            try:
                source = load_source(repo_root, output_root, paper_id)
                result = review_one(
                    source,
                    rubric,
                    rubric_hash,
                    output_root,
                    api,
                    resume=args.resume,
                    chunk_token_budget=args.chunk_token_budget,
                )
            except Exception as exc:
                message = sanitize(str(exc), env["API_KEY"])
                result = {"paper_id": paper_id, "status": "FAILED", "error": message}
                failure_dir = output_root / paper_id
                failure_dir.mkdir(parents=True, exist_ok=True)
                failure_path = failure_dir / "failure.json"
                if not failure_path.exists():
                    atomic_write_json(failure_path, result)
                print(f"[{paper_id}] FAILED: {message}", file=sys.stderr, flush=True)
            latest[paper_id] = result
        pending = [
            paper_id
            for paper_id in pending
            if latest[paper_id]["status"] == "FAILED"
            and is_retryable_run_failure(str(latest[paper_id].get("error", "")))
        ]
        round_results = [latest[paper_id] for paper_id in paper_ids]
        build_summary(round_results, output_root, args.model)
        if baseline_root.joinpath("summary.json").is_file():
            build_comparison(output_root, baseline_root)
        if not pending:
            break
        if round_number < args.resume_rounds and args.resume_round_delay:
            print(
                f"[resume wait] {args.resume_round_delay:g}s before round {round_number + 1}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(args.resume_round_delay)
    results = [latest[paper_id] for paper_id in paper_ids]
    summary = build_summary(results, output_root, args.model)
    if baseline_root.joinpath("summary.json").is_file():
        build_comparison(output_root, baseline_root)
    print(json.dumps({"summary": str(output_root / "summary.json"), "complete": summary["complete_count"], "failed": summary["failed_count"]}))
    return 1 if summary["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
