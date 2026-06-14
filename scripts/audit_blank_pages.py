#!/usr/bin/env python3
"""
scripts/audit_blank_pages.py

Visual and structural audit of empty/blank pages in split case PDFs before embedding/clustering.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Ensure project src directory is in the path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

import numpy as np
from PIL import Image
from scanbook.render_pages import render_pages
from scanbook.utils import ensure_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit empty pages structurally and visually using Pillow and NumPy."
    )
    parser.add_argument(
        "--db-path",
        default="data/clinical_cases.db",
        help="Path to clinical cases SQLite database."
    )
    parser.add_argument(
        "--registry-path",
        default="data/curated/case_registry.jsonl",
        help="Path to curated case registry JSONL."
    )
    parser.add_argument(
        "--ocr-root",
        default="data/ocr_cases",
        help="Path to OCR cases output root."
    )
    parser.add_argument(
        "--book-root",
        default="book",
        help="Path to split case PDFs root."
    )
    parser.add_argument(
        "--output-dir",
        default="data/curated",
        help="Directory to write audit reports and rendered page images."
    )
    parser.add_argument(
        "--ink-threshold",
        type=int,
        default=250,
        help="Grayscale value threshold to consider a pixel as ink/non-white (0-255)."
    )
    return parser.parse_args()


def get_ink_density(image_path: Path, threshold: int = 250) -> float:
    """
    Open rendered page image, convert to grayscale, and return the fraction of
    non-white pixels (pixels below threshold).
    """
    with Image.open(image_path) as img:
        img_gray = img.convert("L")
        arr = np.array(img_gray)
        # Lower value = darker. Pixels below threshold are ink/dark details.
        ink_pixels = np.sum(arr < threshold)
        total_pixels = arr.size
        if total_pixels == 0:
            return 0.0
        return float(ink_pixels / total_pixels)


def main() -> int:
    args = parse_args()
    db_path = Path(args.db_path)
    registry_path = Path(args.registry_path)
    ocr_root = Path(args.ocr_root)
    book_root = Path(args.book_root)
    output_dir = Path(args.output_dir)

    # Output subdirectories
    audit_img_root = output_dir / "blank_page_audit"
    ensure_dir(audit_img_root)

    print("Starting empty page visual and structural audit...")
    print(f"  - Database: {db_path}")
    print(f"  - Case Registry: {registry_path}")
    print(f"  - OCR Cases Root: {ocr_root}")
    print(f"  - Book Split Root: {book_root}")
    print(f"  - Audit Output Dir: {output_dir}")

    # 1. Identify all cases where empty_pages is non-empty
    flagged_cases = []
    
    # We query the SQLite DB to find these cases
    if not db_path.exists():
        print(f"Error: Database {db_path} does not exist. Run build/creation first.")
        return 1
        
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        query = """
        SELECT c.case_id, c.section_id, c.subsection_id, c.slug, c.title, c.page_count,
               c.source_pdf, qr.empty_pages
        FROM cases c
        JOIN qa_reports qr ON c.case_id = qr.case_id
        WHERE qr.empty_pages IS NOT NULL AND qr.empty_pages != '' AND qr.empty_pages != '[]'
        """
        rows = cursor.execute(query).fetchall()
        for row in rows:
            case_id = row["case_id"]
            empty_pages_list = json.loads(row["empty_pages"])
            flagged_cases.append({
                "case_id": case_id,
                "section": row["section_id"],
                "subsection": row["subsection_id"].split("/")[-1] if "/" in row["subsection_id"] else row["subsection_id"],
                "title": row["title"],
                "page_count": row["page_count"],
                "source_pdf": row["source_pdf"],
                "empty_pages": empty_pages_list
            })
    except Exception as e:
        print(f"Database query error: {e}. Falling back to directory scan.")
    finally:
        conn.close()

    # Fallback to local files if SQLite query returned nothing but directories exist
    if not flagged_cases:
        print("No cases flagged in DB or DB query failed, scanning local directories...")
        for case_dir in ocr_root.rglob("qa.json"):
            try:
                qa_data = json.loads(case_dir.read_text(encoding="utf-8"))
                empty_list = qa_data.get("empty_pages", [])
                if empty_list:
                    case_parent = case_dir.parent
                    case_id = case_parent.name
                    meta_path = case_parent / "case_metadata.json"
                    if meta_path.exists():
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        flagged_cases.append({
                            "case_id": case_id,
                            "section": meta.get("section", ""),
                            "subsection": meta.get("subsection", ""),
                            "title": case_id.replace("_", " ").title(),
                            "page_count": meta.get("page_count", 0),
                            "source_pdf": meta.get("source_pdf", ""),
                            "empty_pages": empty_list
                        })
            except Exception as ex:
                print(f"Error scanning {case_dir}: {ex}")

    print(f"Found {len(flagged_cases)} flagged cases with empty pages.")

    audit_records = []

    for case in flagged_cases:
        case_id = case["case_id"]
        print(f"\nAuditing case: {case_id}")
        
        # Load local ocr metadata/pages files to capture counts
        # We search for the case folder under data/ocr_cases/
        case_folder = None
        for p in ocr_root.rglob("case_metadata.json"):
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
                if m.get("case_id") == case_id:
                    case_folder = p.parent
                    break
            except Exception:
                continue

        if not case_folder:
            print(f"  [Warning] Could not locate OCR output folder for case {case_id}")
            continue

        pages_file = case_folder / "pages.jsonl"
        meta_file = case_folder / "case_metadata.json"
        
        if not pages_file.exists() or not meta_file.exists():
            print(f"  [Warning] Missing pages.jsonl or case_metadata.json in {case_folder}")
            continue

        # Load page texts and character counts
        page_chars = {}
        try:
            with open(pages_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        page_data = json.loads(line)
                        p_num = page_data["page_num"]
                        text = page_data.get("text", "")
                        page_chars[p_num] = len(text)
        except Exception as e:
            print(f"  [Error] Reading pages.jsonl for {case_id}: {e}")
            continue

        # Locate source split PDF
        metadata = json.loads(meta_file.read_text(encoding="utf-8"))
        source_pdf_rel = metadata.get("source_pdf", "")
        
        # Resolve PDF absolute path
        pdf_path = book_root / source_pdf_rel
        if not pdf_path.exists():
            pdf_path = project_root / source_pdf_rel
        if not pdf_path.exists():
            # Try recursive search under book_root
            found_paths = list(book_root.rglob(Path(source_pdf_rel).name))
            if found_paths:
                pdf_path = found_paths[0]

        if not pdf_path.exists():
            print(f"  [Error] Source PDF not found for {case_id}: tried {source_pdf_rel}")
            continue

        # Create output case audit folder
        case_audit_dir = audit_img_root / case_id
        ensure_dir(case_audit_dir)

        # Audit each empty page
        for flagged_page in case["empty_pages"]:
            print(f"  - Auditing flagged Page {flagged_page}...")

            # Render page to PNG
            try:
                rendered_files = render_pages(
                    input_pdf=pdf_path,
                    output_dir=case_audit_dir,
                    pages_spec=str(flagged_page),
                    dpi=150
                )
                
                # We expect the file to be page_000N.png, let's copy/rename it to page_N.png
                rendered_img_path = None
                expected_rendered_name = f"page_{flagged_page:04d}.png"
                actual_rendered_path = case_audit_dir / expected_rendered_name
                
                target_img_path = case_audit_dir / f"page_{flagged_page}.png"
                if actual_rendered_path.exists():
                    if target_img_path.exists():
                        target_img_path.unlink()
                    actual_rendered_path.rename(target_img_path)
                    rendered_img_path = target_img_path
                else:
                    # Look in rendered_files
                    for rf in rendered_files:
                        if rf.exists():
                            if target_img_path.exists():
                                target_img_path.unlink()
                            rf.rename(target_img_path)
                            rendered_img_path = target_img_path
                            break
                            
                if not rendered_img_path or not rendered_img_path.exists():
                    print(f"    [Error] Failed to render page {flagged_page} to PNG.")
                    continue
            except Exception as e:
                print(f"    [Error] Rendering page {flagged_page} failed: {e}")
                continue

            # Compute visual ink density using Pillow and NumPy
            try:
                ink_density = get_ink_density(rendered_img_path, threshold=args.ink_threshold)
                try:
                    rel_p = rendered_img_path.relative_to(project_root)
                except ValueError:
                    rel_p = rendered_img_path
                print(f"    - Rendered PNG: {rel_p}")
                print(f"    - Ink density: {ink_density:.6f}")
            except Exception as e:
                print(f"    [Error] Computing ink density for page {flagged_page}: {e}")
                ink_density = 0.0

            # Capture character counts
            current_chars = page_chars.get(flagged_page, 0)
            prev_chars = page_chars.get(flagged_page - 1, None)
            next_chars = page_chars.get(flagged_page + 1, None)
            total_pages = case["page_count"]

            is_first_page = (flagged_page == 1)
            is_last_page = (flagged_page == total_pages)

            # Heuristics classification
            SUBSTANTIAL_TEXT_THRESHOLD = 300
            
            # Helper flags
            has_substantial_prev = (prev_chars is not None and prev_chars > SUBSTANTIAL_TEXT_THRESHOLD)
            has_substantial_next = (next_chars is not None and next_chars > SUBSTANTIAL_TEXT_THRESHOLD)

            # Determine likely reason
            if ink_density < 0.005:
                # Page is visually very light (no ink)
                if is_first_page:
                    likely_reason = "expected_blank_separator"
                    recommended_action = "safe_to_ignore_blank_separator"
                elif is_last_page:
                    likely_reason = "blank_due_to_range_padding"
                    recommended_action = "safe_to_ignore_trailing_blank"
                else:
                    likely_reason = "needs_manual_review"
                    recommended_action = "inspect_rendered_page"
            else:
                # Page has visible dark pixels (ink) but OCR characters are zero!
                likely_reason = "possible_ocr_failure"
                recommended_action = "rerun_ocr_page_or_case"

            # Override middle page rule explicitly
            if not is_first_page and not is_last_page:
                if likely_reason != "possible_ocr_failure":
                    likely_reason = "needs_manual_review"
                    recommended_action = "inspect_rendered_page"

            # Create path clickable format or local file link for report
            abs_img_path = rendered_img_path.resolve()
            img_url = f"file:///{abs_img_path.as_posix()}"

            record = {
                "case_id": case_id,
                "section": case["section"],
                "subsection": case["subsection"],
                "title": case["title"],
                "flagged_page": flagged_page,
                "page_count": total_pages,
                "current_chars": current_chars,
                "prev_chars": prev_chars,
                "next_chars": next_chars,
                "is_first_page": is_first_page,
                "is_last_page": is_last_page,
                "ink_density": round(ink_density, 6),
                "likely_reason": likely_reason,
                "recommended_action": recommended_action,
                "rendered_image_path": str(rendered_img_path.relative_to(project_root)) if (hasattr(rendered_img_path, "is_relative_to") and rendered_img_path.is_relative_to(project_root)) else str(rendered_img_path),
                "rendered_image_url": img_url
            }
            audit_records.append(record)

    # 7. Generate JSON report
    json_report_path = output_dir / "blank_page_audit.json"
    json_report_path.write_text(
        json.dumps({
            "total_flagged_cases": len(flagged_cases),
            "total_flagged_pages": len(audit_records),
            "audit_records": audit_records
        }, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"\nWritten JSON report to: {json_report_path}")

    # 8. Generate Markdown report
    md_report_path = output_dir / "blank_page_audit.md"
    
    md_lines = []
    md_lines.append("# Empty Page Visual & Structural Audit Report")
    md_lines.append("")
    md_lines.append(f"This report presents an audit of the empty pages detected during the database curation build. Total cases flagged: **{len(flagged_cases)}**, across **{len(audit_records)}** total flagged pages.")
    md_lines.append("")
    md_lines.append("## Summary Table")
    md_lines.append("")
    
    # Table headers
    headers = [
        "Case ID",
        "Sec",
        "Subseccion",
        "Page",
        "Tot Pgs",
        "Chars",
        "Prev Chars",
        "Next Chars",
        "First?",
        "Last?",
        "Ink Density",
        "Likely Reason",
        "Recommended Action",
        "Rendered Image"
    ]
    md_lines.append(" | ".join(headers))
    md_lines.append(" | ".join(["---"] * len(headers)))

    for r in audit_records:
        prev_str = str(r["prev_chars"]) if r["prev_chars"] is not None else "N/A"
        next_str = str(r["next_chars"]) if r["next_chars"] is not None else "N/A"
        row_cols = [
            f"`{r['case_id']}`",
            r["section"],
            r["subsection"],
            str(r["flagged_page"]),
            str(r["page_count"]),
            str(r["current_chars"]),
            prev_str,
            next_str,
            "Yes" if r["is_first_page"] else "No",
            "Yes" if r["is_last_page"] else "No",
            f"{r['ink_density']:.6f}",
            f"`{r['likely_reason']}`",
            f"`{r['recommended_action']}`",
            f"[View Image]({r['rendered_image_url']})"
        ]
        md_lines.append(" | ".join(row_cols))

    md_lines.append("")
    md_lines.append("## Detailed Audit Findings")
    md_lines.append("")
    
    for r in audit_records:
        md_lines.append(f"### Case: `{r['case_id']}` - Page {r['flagged_page']}")
        md_lines.append(f"- **Title**: {r['title']}")
        md_lines.append(f"- **Section/Subsection**: `{r['section']}` / `{r['subsection']}`")
        md_lines.append(f"- **Likely Reason**: `{r['likely_reason']}`")
        md_lines.append(f"- **Recommended Action**: `{r['recommended_action']}`")
        md_lines.append(f"- **Ink Density**: {r['ink_density']:.6f}")
        md_lines.append(f"- **Character Counts**: Current: `{r['current_chars']}` | Previous: `{r['prev_chars'] if r['prev_chars'] is not None else 'N/A'}` | Next: `{r['next_chars'] if r['next_chars'] is not None else 'N/A'}`")
        md_lines.append("")
        md_lines.append(f"![Rendered page {r['flagged_page']}]({r['rendered_image_url']})")
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    md_report_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Written Markdown report to: {md_report_path}")

    print("\nEmpty Page Audit Completed Successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
