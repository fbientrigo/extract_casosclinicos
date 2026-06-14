from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scanbook.utils import ensure_dir

CASE_KEYWORDS = [
    "case",
    "clinical case",
    "caso clinico",
    "caso clínico",
    "vignette",
    "patient",
    "paciente",
]

CASE_HEADING_RE = re.compile(
    r"^\s{0,3}(#{1,6}\s*)?(case|clinical case|caso cl[ií]nico|vignette)\b",
    re.IGNORECASE,
)


def extract_case_candidates(inputs: list[Path], output_jsonl: Path, schema_path: Path | None = None) -> list[dict]:
    records: list[dict[str, Any]] = []
    for input_path in inputs:
        if input_path.is_dir():
            for p in sorted(input_path.rglob("*")):
                if p.suffix.lower() in {".md", ".txt"}:
                    records.extend(_extract_from_file(p))
        elif input_path.suffix.lower() in {".md", ".txt"}:
            records.extend(_extract_from_file(input_path))

    if schema_path:
        _validate_schema(records, schema_path)
    ensure_dir(output_jsonl.parent)
    with output_jsonl.open("w", encoding="utf-8") as f:
        for row in records:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return records


def _extract_from_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    candidates: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    doc_id = path.stem

    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        starts_case = bool(CASE_HEADING_RE.match(line))
        keyword_hits = _keyword_hits(line)
        if starts_case:
            if current is not None:
                _finalize_candidate(current, candidates)
            current = {
                "case_id": f"{doc_id}-cand-{len(candidates) + 1:04d}",
                "source_file": str(path),
                "title": line if line else "Untitled case candidate",
                "start_line": idx,
                "end_line": idx,
                "text_lines": [raw_line],
                "keywords": sorted(set(keyword_hits)),
                "detection": {"rule": "heading_match", "score": 1.0},
            }
            continue

        if current is not None:
            current["text_lines"].append(raw_line)
            current["end_line"] = idx
            current["keywords"] = sorted(set(current["keywords"] + keyword_hits))
        elif keyword_hits and len(line) < 120:
            # Lightweight heuristic to catch inline labels in plain text sources.
            current = {
                "case_id": f"{doc_id}-cand-{len(candidates) + 1:04d}",
                "source_file": str(path),
                "title": line,
                "start_line": idx,
                "end_line": idx,
                "text_lines": [raw_line],
                "keywords": sorted(set(keyword_hits)),
                "detection": {"rule": "inline_keyword", "score": 0.5},
            }

    if current is not None:
        _finalize_candidate(current, candidates)
    return candidates


def _finalize_candidate(current: dict[str, Any], out: list[dict[str, Any]]) -> None:
    body = "\n".join(current.pop("text_lines")).strip()
    if len(body) < 40:
        return
    current["text"] = body
    if not current.get("keywords"):
        current["keywords"] = ["case"]
    out.append(current)


def _keyword_hits(line: str) -> list[str]:
    low = line.lower()
    return [kw for kw in CASE_KEYWORDS if kw in low]


def _validate_schema(records: list[dict[str, Any]], schema_path: Path) -> None:
    try:
        import jsonschema
    except ImportError:
        return
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for idx, row in enumerate(records):
        errors = sorted(validator.iter_errors(row), key=lambda e: e.path)
        if errors:
            first = errors[0]
            raise ValueError(f"Schema validation failed for record {idx}: {first.message}")

