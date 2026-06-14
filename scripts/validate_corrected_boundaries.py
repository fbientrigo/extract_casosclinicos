#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from scanbook.render_pages import render_pages

TRIM_DECISION_TO_PAGES = {
    "trim_1_leading_page": 1,
    "trim_2_leading_pages": 2,
}


@dataclass
class CaseValidation:
    case_id: str
    source_pdf_rel: str
    human_trim_pages: int
    original_exists: bool
    corrected_exists: bool
    original_page_count: int | None
    corrected_page_count: int | None
    expected_corrected_page_count: int | None
    page_count_match: bool
    original_sha256_before: str | None
    original_sha256_after: str | None
    original_stat_before: dict[str, Any] | None
    original_stat_after: dict[str, Any] | None
    original_modified_during_validation: bool
    original_thumb: str | None
    corrected_thumb: str | None
    corrected_thumb_page2: str | None
    corrected_page1_text_exists: bool | None
    corrected_page1_text_excerpt: str | None
    requires_visual_review: bool
    notes: list[str]


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_stat(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
    }


def _load_applied(applied_json: Path) -> list[dict[str, Any]]:
    payload = json.loads(applied_json.read_text(encoding="utf-8"))
    rows = payload.get("executed_trims", []) if isinstance(payload, dict) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        case_id = str(row.get("case_id", "")).strip()
        source_pdf = str(row.get("source_pdf", "")).replace("\\", "/").strip()
        trim_pages = _to_int(row.get("trim_leading_pages"))
        if not case_id or not source_pdf or trim_pages is None:
            continue
        if source_pdf.lower().startswith("book/"):
            source_pdf = source_pdf[5:]
        out.append({
            "case_id": case_id,
            "source_pdf": source_pdf,
            "trim_leading_pages": trim_pages,
        })
    return out


def _load_csv_decisions(csv_path: Path) -> dict[str, dict[str, Any]]:
    by_case: dict[str, dict[str, Any]] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            case_id = str(row.get("case_id", "")).strip()
            if not case_id:
                continue
            human_decision = str(row.get("human_decision", "")).strip()
            human_trim_pages = _to_int(row.get("human_trim_pages"))
            inferred_trim = TRIM_DECISION_TO_PAGES.get(human_decision)
            trim = human_trim_pages if human_trim_pages is not None else inferred_trim
            source_pdf = str(row.get("source_pdf", "")).replace("\\", "/").strip()
            by_case[case_id] = {
                "case_id": case_id,
                "human_decision": human_decision,
                "human_trim_pages": trim,
                "source_pdf": source_pdf,
            }
    return by_case


def _count_pages(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def _extract_text_page1(pdf_path: Path) -> tuple[bool | None, str | None]:
    try:
        reader = PdfReader(str(pdf_path))
        if not reader.pages:
            return None, None
        text = (reader.pages[0].extract_text() or "").strip()
        if not text:
            return False, None
        compact = " ".join(text.split())
        return True, compact[:220]
    except Exception:
        return None, None


def _render_single_page(pdf_path: Path, page_no_1_based: int, out_path: Path) -> str | None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = render_pages(
        input_pdf=pdf_path,
        output_dir=out_path.parent,
        pages_spec=str(page_no_1_based),
        dpi=144,
        contact_sheet=False,
    )
    if not rendered:
        return None
    src = rendered[0]
    if src != out_path:
        out_path.write_bytes(src.read_bytes())
        if src.exists() and src.name.startswith("page_"):
            src.unlink(missing_ok=True)
    return str(out_path.as_posix())


def _to_rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root).as_posix())
    except ValueError:
        return str(path.as_posix())


def _build_markdown(summary: dict[str, Any], cases: list[CaseValidation]) -> str:
    lines: list[str] = []
    lines.append("# Corrected Boundary Validation")
    lines.append("")
    lines.append(f"- Generated UTC: `{summary['timestamp_utc']}`")
    lines.append(f"- Total applied trims: **{summary['total_applied_trims']}**")
    lines.append(f"- Corrected PDFs found: **{summary['corrected_pdfs_found']}**")
    lines.append(f"- Missing corrected PDFs: **{summary['missing_corrected_pdfs']}**")
    lines.append(f"- Page count mismatches: **{summary['page_count_mismatches']}**")
    lines.append(f"- Original PDFs missing: **{summary['original_pdfs_missing']}**")
    lines.append(f"- Original PDFs modified during validation: **{summary['original_pdfs_modified']}**")
    lines.append(f"- Cases requiring visual review: **{summary['cases_requiring_visual_review']}**")
    lines.append("")
    lines.append("## Sample Thumbnail Paths")
    lines.append("")
    sample = summary.get("sample_thumbnail_paths", [])
    if sample:
        for p in sample[:15]:
            lines.append(f"- `{p}`")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Cases Requiring Visual Review")
    lines.append("")
    flagged = [c for c in cases if c.requires_visual_review]
    if flagged:
        for c in flagged:
            lines.append(
                f"- `{c.case_id}` | original={c.original_page_count} corrected={c.corrected_page_count} trim={c.human_trim_pages} | notes: {'; '.join(c.notes) if c.notes else 'check manually'}"
            )
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def _build_contact_sheet(cases: list[CaseValidation], output_html: Path, project_root: Path) -> None:
    rows: list[str] = []
    base_dir = output_html.parent
    for c in cases:
        oimg = _to_rel(Path(c.original_thumb), base_dir) if c.original_thumb else ""
        cimg1 = _to_rel(Path(c.corrected_thumb), base_dir) if c.corrected_thumb else ""
        cimg2 = _to_rel(Path(c.corrected_thumb_page2), base_dir) if c.corrected_thumb_page2 else ""
        row = f"""
        <tr>
          <td><code>{c.case_id}</code></td>
          <td>{c.original_page_count if c.original_page_count is not None else ''}</td>
          <td>{c.corrected_page_count if c.corrected_page_count is not None else ''}</td>
          <td>{c.human_trim_pages}</td>
          <td>{f'<img src="{oimg}" alt="{c.case_id} original" />' if oimg else '<span class="missing">missing</span>'}</td>
          <td>{f'<img src="{cimg1}" alt="{c.case_id} corrected p1" />' if cimg1 else '<span class="missing">missing</span>'}</td>
          <td>{f'<img src="{cimg2}" alt="{c.case_id} corrected p2" />' if cimg2 else ''}</td>
        </tr>
        """
        rows.append(row)

    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>Corrected Boundary Validation Contact Sheet</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 16px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
    th, td {{ border: 1px solid #ddd; padding: 6px; vertical-align: top; }}
    th {{ background: #f5f5f5; position: sticky; top: 0; }}
    img {{ width: 170px; height: auto; border: 1px solid #ccc; background: #fff; }}
    .missing {{ color: #a00; font-weight: bold; }}
    code {{ font-size: 11px; }}
  </style>
</head>
<body>
  <h1>Corrected Boundary Validation Contact Sheet</h1>
  <table>
    <thead>
      <tr>
        <th>Case ID</th>
        <th>Original pages</th>
        <th>Corrected pages</th>
        <th>Trim applied</th>
        <th>Original p1</th>
        <th>Corrected p1</th>
        <th>Corrected p2</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate corrected boundary PDFs against decisions.")
    parser.add_argument("--book-id", required=True, help="ID of the book to process (mandatory).")
    parser.add_argument("--corrected-root", help="Root folder for corrected boundary PDFs (defaults to book_corrected/<book_id>).")
    parser.add_argument("--decisions", help="Path to Review decisions CSV (defaults to data/curated/boundary_review/<book_id>/review_decisions_merged.csv).")
    parser.add_argument("--output-dir", help="Output validation directory (defaults to data/curated/boundary_review/<book_id>/corrected_validation).")
    parser.add_argument("--book-root", help="Root folder for original split PDFs (defaults to book/<book_id>).")
    parser.add_argument("--applied-json", help="Path to applied review decisions JSON (defaults to data/curated/boundary_review/<book_id>/applied_review_decisions.json).")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    book_id = args.book_id

    applied_json_rel = args.applied_json or f"data/curated/boundary_review/{book_id}/applied_review_decisions.json"
    decisions_rel = args.decisions or f"data/curated/boundary_review/{book_id}/review_decisions_merged.csv"
    book_root_rel = args.book_root or f"book/{book_id}"
    corrected_root_rel = args.corrected_root or f"book_corrected/{book_id}"
    output_dir_rel = args.output_dir or f"data/curated/boundary_review/{book_id}/corrected_validation"

    applied_json = project_root / applied_json_rel
    merged_csv = project_root / decisions_rel
    book_root = project_root / book_root_rel
    corrected_root = project_root / corrected_root_rel
    validation_root = project_root / output_dir_rel

    out_suffix = "_v2" if "v2" in validation_root.name.lower() else ""
    out_json = validation_root / f"corrected_boundary_validation{out_suffix}.json"
    out_md = validation_root / f"corrected_boundary_validation{out_suffix}.md"
    out_html = validation_root / "index.html"
    validation_root.mkdir(parents=True, exist_ok=True)

    # Prefer applied JSON if present; otherwise derive trims from decisions CSV.
    if applied_json.exists():
        executed = _load_applied(applied_json)
    else:
        csv_seed = _load_csv_decisions(merged_csv)
        executed = [
            {
                "case_id": cid,
                "source_pdf": str(row.get("source_pdf", "")),
                "trim_leading_pages": int(row["human_trim_pages"]),
            }
            for cid, row in csv_seed.items()
            if row.get("human_trim_pages") in {1, 2}
        ]
    csv_rows = _load_csv_decisions(merged_csv)

    cases: list[CaseValidation] = []
    for row in executed:
        case_id = row["case_id"]
        source_pdf_rel = row["source_pdf"]
        trim_pages = int(row["trim_leading_pages"])

        csv_row = csv_rows.get(case_id)
        if csv_row and csv_row.get("human_trim_pages") in {1, 2}:
            trim_pages = int(csv_row["human_trim_pages"])
        if csv_row and csv_row.get("source_pdf"):
            source_pdf_rel = str(csv_row["source_pdf"])

        original_pdf = book_root / source_pdf_rel
        corrected_pdf = corrected_root / source_pdf_rel
        case_dir = validation_root / case_id
        notes: list[str] = []

        original_exists = original_pdf.exists()
        corrected_exists = corrected_pdf.exists()
        original_count: int | None = None
        corrected_count: int | None = None
        expected_count: int | None = None
        match = False

        before_hash: str | None = None
        after_hash: str | None = None
        before_stat: dict[str, Any] | None = None
        after_stat: dict[str, Any] | None = None
        modified_original = False

        orig_thumb: str | None = None
        corr_thumb: str | None = None
        corr_thumb2: str | None = None
        txt_exists: bool | None = None
        txt_excerpt: str | None = None

        if not original_exists:
            notes.append("original_pdf_missing")
        if not corrected_exists:
            notes.append("corrected_pdf_missing")

        if original_exists:
            before_hash = _file_sha256(original_pdf)
            before_stat = _file_stat(original_pdf)

        if original_exists:
            original_count = _count_pages(original_pdf)
        if corrected_exists:
            corrected_count = _count_pages(corrected_pdf)
        if original_count is not None:
            expected_count = original_count - trim_pages
        if corrected_count is not None and expected_count is not None:
            match = corrected_count == expected_count
            if not match:
                notes.append("page_count_mismatch")

        if original_exists:
            try:
                orig_thumb_p = case_dir / "original_page_1.png"
                p = _render_single_page(original_pdf, 1, orig_thumb_p)
                if p:
                    orig_thumb = p
            except Exception:
                notes.append("render_original_failed")

        if corrected_exists:
            try:
                corr_thumb_p = case_dir / "corrected_page_1.png"
                p = _render_single_page(corrected_pdf, 1, corr_thumb_p)
                if p:
                    corr_thumb = p
            except Exception:
                notes.append("render_corrected_p1_failed")

            if corrected_count and corrected_count >= 2:
                try:
                    corr_thumb_p2 = case_dir / "corrected_page_2.png"
                    p2 = _render_single_page(corrected_pdf, 2, corr_thumb_p2)
                    if p2:
                        corr_thumb2 = p2
                except Exception:
                    notes.append("render_corrected_p2_failed")

            txt_exists, txt_excerpt = _extract_text_page1(corrected_pdf)
            if txt_exists is False:
                notes.append("no_text_layer_corrected_p1")

        if original_exists:
            after_hash = _file_sha256(original_pdf)
            after_stat = _file_stat(original_pdf)
            modified_original = (after_hash != before_hash) or (after_stat != before_stat)
            if modified_original:
                notes.append("original_modified_during_validation")

        needs_review = (
            (not corrected_exists)
            or (not original_exists)
            or (not match)
            or modified_original
            or any(n.startswith("render_") for n in notes)
        )

        cases.append(
            CaseValidation(
                case_id=case_id,
                source_pdf_rel=source_pdf_rel,
                human_trim_pages=trim_pages,
                original_exists=original_exists,
                corrected_exists=corrected_exists,
                original_page_count=original_count,
                corrected_page_count=corrected_count,
                expected_corrected_page_count=expected_count,
                page_count_match=match,
                original_sha256_before=before_hash,
                original_sha256_after=after_hash,
                original_stat_before=before_stat,
                original_stat_after=after_stat,
                original_modified_during_validation=modified_original,
                original_thumb=orig_thumb,
                corrected_thumb=corr_thumb,
                corrected_thumb_page2=corr_thumb2,
                corrected_page1_text_exists=txt_exists,
                corrected_page1_text_excerpt=txt_excerpt,
                requires_visual_review=needs_review,
                notes=notes,
            )
        )

    corrected_found = sum(1 for c in cases if c.corrected_exists)
    missing_corrected = sum(1 for c in cases if not c.corrected_exists)
    mismatches = sum(1 for c in cases if c.corrected_exists and not c.page_count_match)
    original_missing = sum(1 for c in cases if not c.original_exists)
    original_modified = sum(1 for c in cases if c.original_modified_during_validation)
    needs_review_count = sum(1 for c in cases if c.requires_visual_review)

    sample_thumbs: list[str] = []
    for c in cases:
        if c.corrected_thumb:
            sample_thumbs.append(_to_rel(Path(c.corrected_thumb), project_root))
        if len(sample_thumbs) >= 20:
            break

    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "total_applied_trims": len(cases),
        "corrected_pdfs_found": corrected_found,
        "missing_corrected_pdfs": missing_corrected,
        "page_count_mismatches": mismatches,
        "original_pdfs_missing": original_missing,
        "original_pdfs_modified": original_modified,
        "cases_requiring_visual_review": needs_review_count,
        "sample_thumbnail_paths": sample_thumbs,
    }

    json_payload = {
        "summary": summary,
        "cases": [
            {
                "case_id": c.case_id,
                "source_pdf": c.source_pdf_rel,
                "human_trim_pages": c.human_trim_pages,
                "original_exists": c.original_exists,
                "corrected_exists": c.corrected_exists,
                "original_page_count": c.original_page_count,
                "corrected_page_count": c.corrected_page_count,
                "expected_corrected_page_count": c.expected_corrected_page_count,
                "page_count_match": c.page_count_match,
                "original_modified_during_validation": c.original_modified_during_validation,
                "original_sha256_before": c.original_sha256_before,
                "original_sha256_after": c.original_sha256_after,
                "original_stat_before": c.original_stat_before,
                "original_stat_after": c.original_stat_after,
                "original_page_1_png": _to_rel(Path(c.original_thumb), project_root) if c.original_thumb else None,
                "corrected_page_1_png": _to_rel(Path(c.corrected_thumb), project_root) if c.corrected_thumb else None,
                "corrected_page_2_png": _to_rel(Path(c.corrected_thumb_page2), project_root) if c.corrected_thumb_page2 else None,
                "corrected_page1_text_exists": c.corrected_page1_text_exists,
                "corrected_page1_text_excerpt": c.corrected_page1_text_excerpt,
                "requires_visual_review": c.requires_visual_review,
                "notes": c.notes,
            }
            for c in cases
        ],
    }

    out_json.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(_build_markdown(summary, cases), encoding="utf-8")
    _build_contact_sheet(cases, out_html, project_root)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
