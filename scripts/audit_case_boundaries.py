#!/usr/bin/env python3
"""
Audit OCR case boundaries before embeddings/clustering/database final use.

This script:
- discovers completed OCR cases from data/ocr_cases/seccion*/**/case_metadata.json
- detects split-boundary anomalies from constrained footer checks + content markers
- validates source PDF page count against split manifest expectations
- optionally renders first/last page thumbnails for flagged cases
- writes reproducible v2 JSON + Markdown + correction plan artifacts
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

FOOTER_WINDOW = 5
FOOTER_BOTTOM_NONEMPTY_LINES = 12
LEADING_CONTAMINATION_PAGE_WINDOW = 3
MAX_REASONABLE_TRIM = 10

SECTION_KEYWORDS: list[str] = [
    "Caso Problema",
    "Presentación",
    "Preguntas",
    "Respuestas y comentarios",
    "Comentarios adicionales",
    "Lecturas sugeridas",
]

PAGE1_PREVIOUS_TAIL_MARKERS: list[str] = [
    "Respuestas y comentarios",
    "Comentarios adicionales",
    "Lecturas sugeridas",
    "Pregunta 4:",
    "Pregunta 5:",
    "Pregunta 6:",
    "Pregunta 7:",
]

_ACCENT_MAP = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
_INT_LINE_RE = re.compile(r"^\s*(\d{1,4})\s*$")
_OCR_NOISE_ALLOWED_LINE_RE = re.compile(r"^[0-9OoIl|SsBbGgZzQq\[\]\(\)\{\}\.\,\:\;\'\"\-_/\\\s]{1,20}$")
_OCR_NOISE_TOKEN_RE = re.compile(r"^[0-9OoIl|SsBbGgZzQq]{1,4}$")
_OCR_NOISE_PUNCT_RE = re.compile(r"[\s\[\]\(\)\{\}\.\,\:\;\'\"\-_/\\]")
_WORD_INT_RE = re.compile(r"\b(\d{1,4})\b")

_OCR_DIGIT_MAP = str.maketrans(
    {
        "O": "0",
        "o": "0",
        "I": "1",
        "l": "1",
        "|": "1",
        "S": "5",
        "s": "5",
        "B": "8",
        "b": "6",
        "G": "6",
        "g": "9",
        "Z": "2",
        "z": "2",
        "Q": "0",
        "q": "9",
    }
)

_BANNED_TOKENS = [
    "pregunta",
    "respuesta",
    "opcion",
    " mg",
    " ml",
    "%",
    "ano",
    "rev",
    "vol",
    "isbn",
    "doi",
]

_OPTION_MARKER_RE = re.compile(r"\b[abcde]\)")


@dataclass
class FooterDetection:
    candidate: int | None
    confidence: str
    out_of_window_candidates: list[int] = field(default_factory=list)


@dataclass
class CaseAuditResult:
    case_id: str
    section: str
    subsection: str
    expected_start: int
    metadata_printed_start: int | None
    source_pdf: str
    metadata_page_count: int | None
    manifest_expected_page_count: int | None
    pages_jsonl_page_count: int | None

    first_detected_footer: int | None = None
    first_reliable_footer: int | None = None
    footer_confidence: str = "low"
    footer_delta: int | None = None
    all_footers: list[int | None] = field(default_factory=list)
    all_footer_confidences: list[str] = field(default_factory=list)
    first_caso_problema_page: int | None = None
    keyword_first_pages: dict[str, int] = field(default_factory=dict)

    pdf_page_count: int | None = None
    thumbnails_saved: list[str] = field(default_factory=list)

    footer_flags: list[str] = field(default_factory=list)
    content_flags: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    severity: str = "low_confidence_review"
    suggested_action: str = "inspect_manual"
    suggested_trim_pages: int | None = None
    expected_new_start_footer: int | None = None
    footer_sequence_confirms_shift: bool = False
    reason: str = ""
    unreliable_footer_candidates: list[int] = field(default_factory=list)


def parse_expected_start(case_id: str) -> int | None:
    match = re.match(r"^(\d+)_", case_id)
    if not match:
        return None
    return int(match.group(1))


def normalize_relpath(path_str: str) -> str:
    norm = path_str.replace("\\", "/").strip()
    if norm.startswith("./"):
        norm = norm[2:]
    if norm.lower().startswith("book/"):
        norm = norm[5:]
    return norm.lower()


def parse_printed_start_from_frontmatter(content: str) -> int | None:
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end == -1:
        return None
    fm = content[4:end]
    match = re.search(r"printed_start_page:\s*(\d+)", fm)
    if not match:
        return None
    return int(match.group(1))


def split_case_md_by_page(content: str) -> list[tuple[int, str]]:
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            content = content[end + 4 :]

    pattern = re.compile(r"^## Page (\d+)\s*$", re.MULTILINE)
    markers = list(pattern.finditer(content))
    pages: list[tuple[int, str]] = []
    for i, marker in enumerate(markers):
        page_num = int(marker.group(1))
        start = marker.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(content)
        pages.append((page_num, content[start:end].strip()))
    return pages


def read_pages_jsonl(pages_jsonl_path: Path) -> list[tuple[int, str]]:
    if not pages_jsonl_path.exists():
        return []
    pages: list[tuple[int, str]] = []
    try:
        with pages_jsonl_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                page_num = int(item.get("page_num"))
                page_text = str(item.get("text", "")).strip()
                pages.append((page_num, page_text))
    except Exception:
        return []
    return sorted(pages, key=lambda x: x[0])


def _normalize(text: str) -> str:
    return text.translate(_ACCENT_MAP).lower()


def keyword_in_page(keyword: str, page_text: str) -> bool:
    return _normalize(keyword) in _normalize(page_text)


def find_keyword_first_pages(pages: list[tuple[int, str]], keywords: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for keyword in keywords:
        key = keyword.lower()
        for page_num, page_text in pages:
            if keyword_in_page(keyword, page_text):
                out.setdefault(key, page_num)
                break
    return out


def load_manifest_expected_page_counts(project_dir: Path) -> tuple[dict[str, int], str | None]:
    mapping: dict[str, int] = {}

    execute_candidates = [
        project_dir / "book" / "book_split_execute_manifest.json",
        project_dir / "book_split_execute_manifest.json",
    ]
    for execute_path in execute_candidates:
        if not execute_path.exists():
            continue
        try:
            payload = json.loads(execute_path.read_text(encoding="utf-8"))
            split_items = payload.get("split_items", [])
            for item in split_items:
                if item.get("type") != "case":
                    continue
                output_path = item.get("output_path")
                expected_page_count = item.get("expected_page_count")
                if not output_path or expected_page_count is None:
                    continue
                mapping[normalize_relpath(str(output_path))] = int(expected_page_count)
            if mapping:
                return mapping, str(execute_path)
        except Exception:
            continue

    yaml_candidates = [
        project_dir / "book" / "book_split_manifest.yaml",
        project_dir / "book_split_manifest.yaml",
    ]
    for yaml_path in yaml_candidates:
        if not yaml_path.exists():
            continue
        try:
            import yaml  # type: ignore

            payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            sections = payload.get("sections", [])
            for section in sections:
                for subsection in section.get("subsections", []):
                    for case in subsection.get("cases", []):
                        output_path = case.get("output_path")
                        expected_page_count = case.get("expected_page_count")
                        if not output_path or expected_page_count is None:
                            continue
                        mapping[normalize_relpath(str(output_path))] = int(expected_page_count)
            if mapping:
                return mapping, str(yaml_path)
        except Exception:
            continue

    return mapping, None


def open_pdf_page_count(pdf_path: Path) -> int | None:
    try:
        import fitz  # type: ignore

        doc = fitz.open(str(pdf_path))
        page_count = doc.page_count
        doc.close()
        return page_count
    except Exception:
        pass
    try:
        import pypdfium2 as pdfium  # type: ignore

        doc = pdfium.PdfDocument(str(pdf_path))
        page_count = len(doc)
        doc.close()
        return page_count
    except Exception:
        return None


def render_thumbnails(pdf_path: Path, case_id: str, audit_dir: Path, page_count: int | None) -> list[str]:
    if page_count is None or page_count < 1:
        return []

    out_dir = audit_dir / case_id
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = [(1, "first_page.png")]
    if page_count > 1:
        targets.append((page_count, "last_page.png"))

    saved: list[str] = []
    try:
        import fitz  # type: ignore

        doc = fitz.open(str(pdf_path))
        matrix = fitz.Matrix(150 / 72.0, 150 / 72.0)
        try:
            for page_num, file_name in targets:
                page = doc.load_page(page_num - 1)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                out_path = out_dir / file_name
                pix.save(str(out_path))
                saved.append(str(out_path))
        finally:
            doc.close()
        return saved
    except Exception:
        pass

    try:
        import pypdfium2 as pdfium  # type: ignore

        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            for page_num, file_name in targets:
                page = doc[page_num - 1]
                bitmap = page.render(scale=150 / 72.0)
                image = bitmap.to_pil()
                out_path = out_dir / file_name
                image.save(str(out_path))
                saved.append(str(out_path))
        finally:
            doc.close()
        return saved
    except Exception:
        return []


def _bottom_nonempty_lines(page_text: str, take_last: int = FOOTER_BOTTOM_NONEMPTY_LINES) -> list[str]:
    lines = [line for line in page_text.splitlines() if line.strip()]
    if not lines:
        return []
    return lines[-take_last:]


def _line_has_banned_token(line: str) -> bool:
    nline = _normalize(line)
    if _OPTION_MARKER_RE.search(nline):
        return True
    for token in _BANNED_TOKENS:
        if token in nline:
            return True
    return False


def _allow_small_integer(candidate: int, expected_start: int) -> bool:
    if candidate > 3:
        return True
    return abs(expected_start - candidate) <= FOOTER_WINDOW


def _parse_footer_candidate_from_line(line: str, expected_start: int) -> tuple[int | None, str]:
    if _line_has_banned_token(line):
        return None, "low"

    m = _INT_LINE_RE.match(line)
    if m:
        candidate = int(m.group(1))
        if _allow_small_integer(candidate, expected_start):
            return candidate, "high"
        return None, "low"

    stripped = line.strip()
    if not _OCR_NOISE_ALLOWED_LINE_RE.match(stripped):
        return None, "low"
    token = _OCR_NOISE_PUNCT_RE.sub("", stripped)
    if not token:
        return None, "low"
    if not _OCR_NOISE_TOKEN_RE.match(token):
        return None, "low"
    mapped = token.translate(_OCR_DIGIT_MAP)
    if not mapped.isdigit():
        return None, "low"
    candidate = int(mapped)
    if not _allow_small_integer(candidate, expected_start):
        return None, "low"
    return candidate, "medium"


def detect_reliable_footer_in_page(page_text: str, expected_start: int, page_num: int) -> FooterDetection:
    expected_footer = expected_start + page_num - 1
    lines = _bottom_nonempty_lines(page_text, take_last=FOOTER_BOTTOM_NONEMPTY_LINES)

    best_candidate: int | None = None
    best_conf = "low"
    best_score: tuple[int, int] | None = None
    out_of_window_candidates: list[int] = []

    for reverse_idx, line in enumerate(reversed(lines), start=1):
        candidate, confidence = _parse_footer_candidate_from_line(line, expected_start)
        if candidate is None:
            continue

        in_expected_window = abs(candidate - expected_footer) <= FOOTER_WINDOW
        in_start_window = page_num <= LEADING_CONTAMINATION_PAGE_WINDOW and abs(candidate - expected_start) <= FOOTER_WINDOW
        if not (in_expected_window or in_start_window):
            out_of_window_candidates.append(candidate)
            continue

        conf_rank = 2 if confidence == "high" else 1
        distance = abs(candidate - expected_footer)
        score = (-conf_rank, distance, reverse_idx)
        if best_score is None or score < best_score:
            best_score = score
            best_candidate = candidate
            best_conf = confidence

    if best_candidate is None:
        return FooterDetection(candidate=None, confidence="low", out_of_window_candidates=out_of_window_candidates)
    return FooterDetection(candidate=best_candidate, confidence=best_conf, out_of_window_candidates=out_of_window_candidates)


def detect_footer_in_page(page_text: str) -> int | None:
    # Compatibility wrapper used by legacy tests.
    tail = page_text[-300:] if len(page_text) > 300 else page_text
    candidates = [int(m.group(1)) for m in _WORD_INT_RE.finditer(tail)]
    return candidates[-1] if candidates else None


def _page_text_lookup(pages: list[tuple[int, str]]) -> dict[int, str]:
    return {page_num: text for page_num, text in pages}


def _detect_previous_case_tail_page1(pages: list[tuple[int, str]], first_caso_page: int | None) -> bool:
    if first_caso_page is None or first_caso_page <= 1:
        return False
    page1_map = _page_text_lookup(pages)
    page1_text = page1_map.get(1, "")
    if not page1_text:
        return False
    for marker in PAGE1_PREVIOUS_TAIL_MARKERS:
        if keyword_in_page(marker, page1_text):
            return True
    return False


def _is_unclear_footer_sequence(reliable: list[tuple[int, int]]) -> bool:
    if len(reliable) < 2:
        return False
    for i in range(1, len(reliable)):
        prev_page, prev_footer = reliable[i - 1]
        cur_page, cur_footer = reliable[i]
        expected_delta = cur_page - prev_page
        if cur_footer - prev_footer != expected_delta:
            return True
    return False


def _sequence_confirms_trim_shift(reliable: list[tuple[int, int]], expected_start: int, trim_pages: int) -> bool:
    if trim_pages <= 0:
        return False
    aligned = 0
    for page_num, footer in reliable:
        expected_shifted = expected_start + page_num - 1 - trim_pages
        if abs(footer - expected_shifted) <= 1:
            aligned += 1
    return aligned >= 2


def apply_boundary_rules(result: CaseAuditResult, pages: list[tuple[int, str]]) -> None:
    footer_flags: list[str] = []
    content_flags: list[str] = []

    cp_page = result.keyword_first_pages.get("caso problema")
    result.first_caso_problema_page = cp_page

    previous_case_tail = _detect_previous_case_tail_page1(pages, cp_page)
    if previous_case_tail:
        content_flags.append("previous_case_tail")

    if result.first_reliable_footer is None:
        footer_flags.append("footer_unresolved")
        if result.unreliable_footer_candidates:
            candidate = result.unreliable_footer_candidates[0]
            if abs(result.expected_start - candidate) > MAX_REASONABLE_TRIM:
                footer_flags.append("unreliable_footer_detection")
    else:
        result.footer_delta = result.first_reliable_footer - result.expected_start
        delta = result.footer_delta
        if delta < 0:
            implied_trim = abs(delta)
            if implied_trim > MAX_REASONABLE_TRIM:
                footer_flags.append("unreliable_footer_detection")
            elif implied_trim <= FOOTER_WINDOW:
                footer_flags.append("leading_contamination")
                if result.footer_confidence in {"high", "medium"}:
                    result.suggested_trim_pages = implied_trim
                    result.expected_new_start_footer = result.expected_start
            else:
                footer_flags.append("unclear_sequence")
        elif delta > 0:
            if delta <= FOOTER_WINDOW:
                footer_flags.append("missing_initial_pages")
            elif delta > MAX_REASONABLE_TRIM:
                footer_flags.append("unreliable_footer_detection")
            else:
                footer_flags.append("unclear_sequence")

    reliable_seq = [(i + 1, f) for i, f in enumerate(result.all_footers) if f is not None]
    if _is_unclear_footer_sequence(reliable_seq):
        footer_flags.append("unclear_sequence")

    if result.suggested_trim_pages:
        result.footer_sequence_confirms_shift = _sequence_confirms_trim_shift(
            reliable_seq, result.expected_start, result.suggested_trim_pages
        )
        if result.suggested_trim_pages > MAX_REASONABLE_TRIM:
            footer_flags.append("unreliable_footer_detection")
            result.suggested_trim_pages = None
            result.expected_new_start_footer = None

    if result.pdf_page_count is not None and result.manifest_expected_page_count is not None:
        if result.pdf_page_count != result.manifest_expected_page_count:
            footer_flags.append("pdf_page_count_mismatch")

    footer_flags = sorted(set(footer_flags))
    content_flags = sorted(set(content_flags))
    result.footer_flags = footer_flags
    result.content_flags = content_flags
    result.flags = sorted(set(footer_flags + content_flags))

    has_reliable = result.footer_confidence in {"high", "medium"}
    if has_reliable and ("leading_contamination" in footer_flags or "missing_initial_pages" in footer_flags):
        result.severity = "confirmed_boundary_error"
    elif "previous_case_tail" in content_flags and cp_page is not None and cp_page > 1:
        result.severity = "probable_boundary_error"
    elif "footer_unresolved" in footer_flags or "unclear_sequence" in footer_flags or "unreliable_footer_detection" in footer_flags:
        result.severity = "low_confidence_review"
    elif result.first_reliable_footer == result.expected_start and "previous_case_tail" not in content_flags:
        result.severity = "clean"
    else:
        result.severity = "low_confidence_review"

    result.suggested_action = "inspect_manual"
    if result.severity == "clean":
        result.suggested_action = "no_action"
    elif (
        result.severity == "confirmed_boundary_error"
        and result.suggested_trim_pages is not None
        and 1 <= result.suggested_trim_pages <= 5
        and (
            "previous_case_tail" in result.content_flags
            or result.footer_sequence_confirms_shift
        )
    ):
        result.suggested_action = "trim_leading_pages"

    if result.severity == "clean":
        result.reason = "first reliable footer matches expected start and no previous-case tail markers."
    elif result.severity == "confirmed_boundary_error":
        result.reason = (
            f"reliable footer detected ({result.footer_confidence}); "
            f"first_reliable_footer={result.first_reliable_footer}, expected_start={result.expected_start}."
        )
    elif result.severity == "probable_boundary_error":
        result.reason = "page 1 contains previous-case tail markers before first 'Caso Problema'."
    else:
        if "footer_unresolved" in footer_flags:
            result.reason = "no reliable footer found in constrained footer window."
        elif "unreliable_footer_detection" in footer_flags:
            result.reason = "candidate footer implies impossible trim; classified as unreliable detection."
        else:
            result.reason = "footer sequence is unclear or inconsistent."


def discover_completed_cases(ocr_root: Path) -> list[Path]:
    candidates = sorted(ocr_root.glob("seccion*/**/case_metadata.json"))
    completed: list[Path] = []
    for meta_path in candidates:
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        status = str(payload.get("status", "")).strip().lower()
        if status in {"", "success", "completed", "ok"}:
            completed.append(meta_path)
    return completed


def audit_one_case(
    meta_path: Path,
    book_root: Path,
    manifest_expected_page_counts: dict[str, int],
    audit_img_dir: Path,
    render_flagged: bool = True,
) -> CaseAuditResult | None:
    try:
        meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] cannot parse {meta_path}: {e}")
        return None

    case_id = str(meta.get("case_id", meta_path.parent.name))
    expected_start = parse_expected_start(case_id)
    if expected_start is None:
        return None

    section = str(meta.get("section", ""))
    subsection = str(meta.get("subsection", ""))
    source_pdf = str(meta.get("source_pdf", ""))
    metadata_page_count = meta.get("page_count")
    metadata_printed_start = meta.get("printed_start_page")
    if metadata_printed_start is not None:
        metadata_printed_start = int(metadata_printed_start)

    case_md_path = meta_path.parent / "case.md"
    pages_jsonl_path = meta_path.parent / "pages.jsonl"

    pages: list[tuple[int, str]] = []
    if case_md_path.exists():
        content = case_md_path.read_text(encoding="utf-8", errors="replace")
        if metadata_printed_start is None:
            metadata_printed_start = parse_printed_start_from_frontmatter(content)
        pages = split_case_md_by_page(content)

    pages_from_jsonl = read_pages_jsonl(pages_jsonl_path)
    if not pages and pages_from_jsonl:
        pages = pages_from_jsonl

    detections = [
        detect_reliable_footer_in_page(page_text=page_text, expected_start=expected_start, page_num=page_num)
        for page_num, page_text in pages
    ]
    all_footers = [d.candidate for d in detections]
    all_confidences = [d.confidence for d in detections]
    first_idx = next((i for i, d in enumerate(detections) if d.candidate is not None), None)
    first_reliable_footer = detections[first_idx].candidate if first_idx is not None else None
    footer_confidence = detections[first_idx].confidence if first_idx is not None else "low"
    unreliable_footer_candidates: list[int] = []
    for d in detections:
        if d.out_of_window_candidates:
            unreliable_footer_candidates.extend(d.out_of_window_candidates)
    keyword_first_pages = find_keyword_first_pages(pages, SECTION_KEYWORDS)

    source_key = normalize_relpath(source_pdf)
    manifest_expected_page_count = manifest_expected_page_counts.get(source_key)

    pdf_path = book_root / source_pdf
    if not pdf_path.exists():
        found = list(book_root.rglob(Path(source_pdf).name))
        if found:
            pdf_path = found[0]
    pdf_page_count = open_pdf_page_count(pdf_path) if pdf_path.exists() else None

    result = CaseAuditResult(
        case_id=case_id,
        section=section,
        subsection=subsection,
        expected_start=expected_start,
        metadata_printed_start=metadata_printed_start,
        source_pdf=source_pdf,
        metadata_page_count=metadata_page_count if metadata_page_count is None else int(metadata_page_count),
        manifest_expected_page_count=manifest_expected_page_count,
        pages_jsonl_page_count=len(pages_from_jsonl) if pages_from_jsonl else None,
        first_detected_footer=first_reliable_footer,
        first_reliable_footer=first_reliable_footer,
        footer_confidence=footer_confidence,
        all_footers=all_footers,
        all_footer_confidences=all_confidences,
        keyword_first_pages=keyword_first_pages,
        pdf_page_count=pdf_page_count,
        unreliable_footer_candidates=unreliable_footer_candidates,
    )
    apply_boundary_rules(result, pages)

    if render_flagged and result.severity != "clean" and pdf_path.exists():
        result.thumbnails_saved = render_thumbnails(
            pdf_path=pdf_path,
            case_id=case_id,
            audit_dir=audit_img_dir,
            page_count=pdf_page_count,
        )

    return result


def build_json_report(results: list[CaseAuditResult], output_path: Path) -> None:
    clean = [r for r in results if r.severity == "clean"]
    flagged = [r for r in results if r.severity != "clean"]
    severity_counts: dict[str, int] = {
        "clean": 0,
        "low_confidence_review": 0,
        "probable_boundary_error": 0,
        "confirmed_boundary_error": 0,
    }
    for case in results:
        severity_counts[case.severity] = severity_counts.get(case.severity, 0) + 1

    payload: dict[str, Any] = {
        "total_cases_audited": len(results),
        "total_clean_boundaries": len(clean),
        "total_flagged": len(flagged),
        "severity_counts": severity_counts,
        "flagged_cases": [asdict(r) for r in flagged],
        "clean_case_ids": [r.case_id for r in clean],
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[Report] wrote {output_path}")


def build_markdown_report(results: list[CaseAuditResult], output_path: Path) -> None:
    clean = [r for r in results if r.severity == "clean"]
    flagged = [r for r in results if r.severity != "clean"]
    severity_counts: dict[str, int] = {
        "clean": 0,
        "low_confidence_review": 0,
        "probable_boundary_error": 0,
        "confirmed_boundary_error": 0,
    }
    for case in results:
        severity_counts[case.severity] = severity_counts.get(case.severity, 0) + 1

    by_section: dict[str, int] = {}
    for case in flagged:
        by_section[case.section] = by_section.get(case.section, 0) + 1

    lines: list[str] = [
        "# Case Boundary Audit Report v2",
        "",
        "## Summary",
        "",
        f"- total cases audited: {len(results)}",
        f"- total clean boundaries: {len(clean)}",
        f"- total flagged: {len(flagged)}",
        f"- clean: {severity_counts.get('clean', 0)}",
        f"- low_confidence_review: {severity_counts.get('low_confidence_review', 0)}",
        f"- probable_boundary_error: {severity_counts.get('probable_boundary_error', 0)}",
        f"- confirmed_boundary_error: {severity_counts.get('confirmed_boundary_error', 0)}",
        "",
        "### Flagged by section",
        "",
    ]
    if by_section:
        for section, count in sorted(by_section.items()):
            lines.append(f"- {section}: {count}")
    else:
        lines.append("- none")
    lines.append("")

    lines += [
        "## Flagged Cases",
        "",
        "| case_id | severity | expected_start | first_reliable_footer | footer_confidence | first_caso_problema_page | footer_flags | content_flags | suggested_action | suggested_trim_pages | source_pdf |",
        "|---|---|---:|---:|---|---:|---|---|---|---:|---|",
    ]
    for case in flagged:
        lines.append(
            f"| {case.case_id} | {case.severity} | {case.expected_start} | "
            f"{case.first_reliable_footer} | {case.footer_confidence} | "
            f"{case.first_caso_problema_page} | {', '.join(case.footer_flags)} | "
            f"{', '.join(case.content_flags)} | {case.suggested_action} | "
            f"{case.suggested_trim_pages} | {case.source_pdf} |"
        )
    lines.append("")

    special_case = next((r for r in results if r.case_id == "762_loxoscelismo"), None)
    lines += ["## Special Case: 762_loxoscelismo", ""]
    if special_case is None:
        lines += ["case not found in audited set.", ""]
    else:
        lines += [
            f"- severity: {special_case.severity}",
            f"- expected_start: {special_case.expected_start}",
            f"- first_reliable_footer: {special_case.first_reliable_footer}",
            f"- footer_confidence: {special_case.footer_confidence}",
            f"- first_caso_problema_page: {special_case.first_caso_problema_page}",
            f"- footer_flags: {', '.join(special_case.footer_flags) if special_case.footer_flags else 'none'}",
            f"- content_flags: {', '.join(special_case.content_flags) if special_case.content_flags else 'none'}",
            f"- suggested_trim_pages: {special_case.suggested_trim_pages}",
            f"- suggested_action: {special_case.suggested_action}",
            "",
        ]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[Report] wrote {output_path}")


def build_correction_plan(results: list[CaseAuditResult], output_path: Path) -> None:
    records: list[dict[str, Any]] = []
    for case in results:
        if case.severity == "clean":
            continue

        action = "inspect_manual"
        trim = None
        if (
            case.severity == "confirmed_boundary_error"
            and case.suggested_trim_pages is not None
            and 1 <= case.suggested_trim_pages <= 5
            and (
                "previous_case_tail" in case.content_flags
                or case.footer_sequence_confirms_shift
            )
            and "leading_contamination" in case.footer_flags
        ):
            action = "trim_leading_pages"
            trim = case.suggested_trim_pages

        records.append(
            {
                "case_id": case.case_id,
                "severity": case.severity,
                "action": action,
                "trim_leading_pages": trim,
                "expected_new_start_footer": case.expected_new_start_footer if action == "trim_leading_pages" else None,
                "reason": case.reason,
                "footer_confidence": case.footer_confidence,
                "footer_flags": case.footer_flags,
                "content_flags": case.content_flags,
                "footer_sequence_confirms_shift": case.footer_sequence_confirms_shift,
                "affected_paths": [
                    case.source_pdf,
                    f"data/ocr_cases/{case.section}/{case.subsection}/{case.case_id}/case.md",
                    f"data/ocr_cases/{case.section}/{case.subsection}/{case.case_id}/pages.jsonl",
                    f"data/ocr_cases/{case.section}/{case.subsection}/{case.case_id}/case_metadata.json",
                ],
            }
        )
    output_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[Report] wrote {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit OCR case split boundaries.")
    parser.add_argument("--ocr-root", default="data/ocr_cases")
    parser.add_argument("--book-root", default="book")
    parser.add_argument("--output-dir", default="data/curated")
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--no-thumbnails", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    ocr_root = Path(args.ocr_root)
    book_root = Path(args.book_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    audit_img_dir = output_dir / "boundary_audit"
    audit_img_dir.mkdir(parents=True, exist_ok=True)

    manifest_expected_page_counts, manifest_source = load_manifest_expected_page_counts(project_root)
    if manifest_source:
        print(
            f"[Audit] loaded {len(manifest_expected_page_counts)} manifest case page counts "
            f"from {manifest_source}"
        )
    else:
        print("[Audit] no manifest expected page counts found; pdf mismatch checks may be partial.")

    meta_paths = discover_completed_cases(ocr_root)
    if args.case_id:
        meta_paths = [p for p in meta_paths if p.parent.name == args.case_id]

    print(f"[Audit] discovered {len(meta_paths)} completed case(s).")

    results: list[CaseAuditResult] = []
    for meta_path in meta_paths:
        result = audit_one_case(
            meta_path=meta_path,
            book_root=book_root,
            manifest_expected_page_counts=manifest_expected_page_counts,
            audit_img_dir=audit_img_dir,
            render_flagged=not args.no_thumbnails,
        )
        if result is not None:
            results.append(result)

    clean = [r for r in results if r.severity == "clean"]
    flagged = [r for r in results if r.severity != "clean"]
    confirmed = [r for r in results if r.severity == "confirmed_boundary_error"]
    probable = [r for r in results if r.severity == "probable_boundary_error"]
    low_conf = [r for r in results if r.severity == "low_confidence_review"]
    print(
        "[Audit] done. "
        f"total={len(results)} clean={len(clean)} flagged={len(flagged)} "
        f"confirmed={len(confirmed)} probable={len(probable)} low_confidence={len(low_conf)}"
    )

    json_path = output_dir / "case_boundary_audit_v2.json"
    md_path = output_dir / "case_boundary_audit_v2.md"
    plan_path = output_dir / "case_boundary_correction_plan_v2.json"

    build_json_report(results, json_path)
    build_markdown_report(results, md_path)
    build_correction_plan(results, plan_path)

    if flagged:
        print("[Audit] flagged cases:")
        for case in flagged:
            print(
                f"  - {case.case_id} | severity={case.severity} "
                f"| footer_confidence={case.footer_confidence} "
                f"| first_reliable_footer={case.first_reliable_footer} "
                f"| expected={case.expected_start} "
                f"| trim={case.suggested_trim_pages}"
            )

    loxo = next((r for r in results if r.case_id == "762_loxoscelismo"), None)
    if loxo:
        print(
            f"[Audit] 762_loxoscelismo severity={loxo.severity} "
            f"flags={','.join(loxo.flags)} trim={loxo.suggested_trim_pages}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
