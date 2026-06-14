#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from scanbook.ocr.ocrmypdf_backend import OcrmypdfBackend
from scanbook.qa import run_qa
from scanbook.render_pages import render_pages
from scanbook.utils import (
    ensure_dir,
    parse_page_spec,
    read_jsonl,
    sha256_file,
    write_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Controlled real-subset evaluation workflow for scanned academic books."
    )
    parser.add_argument(
        "--input-pdf",
        type=Path,
        required=True,
        help="Path to the input scanned PDF book.",
    )
    parser.add_argument(
        "--pages",
        type=str,
        required=True,
        help="Comma-separated physical pages or ranges to process (e.g. 1-3,20-25).",
    )
    parser.add_argument(
        "--book-id",
        type=str,
        required=True,
        help="Identifier for the book, used in work directory naming.",
    )
    parser.add_argument(
        "--lang",
        action="append",
        default=[],
        help="Language(s) to pass to OCR (e.g. --lang spa --lang eng). Can be specified multiple times.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Custom working directory. Defaults to data/real_subset/<book_id>.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=180,
        help="DPI resolution for rendering and OCR (default: 180).",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default="fast_latin",
        choices=["fast_latin", "balanced_multilang", "high_quality_tables"],
        help="OCR profile to run with OCRmyPDF (default: fast_latin).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_pdf = args.input_pdf.resolve()
    if not input_pdf.exists():
        print(f"Error: Input PDF not found at {input_pdf}", file=sys.stderr)
        return 1

    # Resolve languages, default to eng, spa if none provided
    languages = args.lang if args.lang else ["eng", "spa"]

    # Parse and validate selected pages
    try:
        selected_pages = parse_page_spec(args.pages)
    except ValueError as exc:
        print(f"Error parsing pages specification: {exc}", file=sys.stderr)
        return 1

    if not selected_pages:
        print("Error: No valid pages selected.", file=sys.stderr)
        return 1

    # Check bounds
    reader = PdfReader(str(input_pdf))
    total_pages = len(reader.pages)
    for p in selected_pages:
        if p < 1 or p > total_pages:
            print(
                f"Error: Page {p} is out of bounds for PDF with {total_pages} pages.",
                file=sys.stderr,
            )
            return 1

    # Resolve work directory
    book_id = args.book_id.strip()
    work_dir = args.work_dir
    if work_dir is None:
        work_dir = Path("data/real_subset") / book_id
    work_dir = work_dir.resolve()
    ensure_dir(work_dir)

    print("======================================================================")
    print(f"STARTING SUBSET EVALUATION FOR BOOK ID: {book_id}")
    print("======================================================================")
    print(f"- Input PDF:    {input_pdf}")
    print(f"- Page Range:   {args.pages}")
    print(f"- Selected:     {len(selected_pages)} pages: {selected_pages}")
    print(f"- Languages:    {languages}")
    print(f"- OCR Profile:  {args.profile}")
    print(f"- DPI:          {args.dpi}")
    print(f"- Work Dir:     {work_dir}")

    # 1. Calculate Source PDF Hash
    print("\n[1/5] Calculating source PDF hash...")
    source_sha256 = sha256_file(input_pdf)
    print(f"      SHA256: {source_sha256}")

    # 2. Render Page Images and Contact Sheet
    print("\n[2/5] Rendering page images and contact sheet...")
    rendered_images = render_pages(
        input_pdf=input_pdf,
        output_dir=work_dir,
        pages_spec=args.pages,
        dpi=args.dpi,
        contact_sheet=True,
    )
    print(f"      Rendered {len(rendered_images)} page images.")
    contact_sheet_path = work_dir / "contact_sheet.png"
    if contact_sheet_path.exists():
        print(f"      Created contact sheet at: {contact_sheet_path}")

    # 3. Create Temporary Subset PDF
    print("\n[3/5] Creating temporary subset PDF...")
    temp_subset_pdf = work_dir / "temp_subset.pdf"
    writer = PdfWriter()
    for p in selected_pages:
        writer.add_page(reader.pages[p - 1])
    with temp_subset_pdf.open("wb") as f:
        writer.write(f)
    print(f"      Temporary subset PDF written to: {temp_subset_pdf}")

    # 4. Run OCRmyPDF on the temporary subset PDF
    print("\n[4/5] Running OCRmyPDF on the subset...")
    temp_pages_jsonl = work_dir / "temp_pages.jsonl"
    searchable_pdf = work_dir / "subset_searchable.pdf"
    sidecar_txt = work_dir / "subset_sidecar.txt"

    backend = OcrmypdfBackend()
    try:
        backend.run(
            input_pdf=temp_subset_pdf,
            output_jsonl=temp_pages_jsonl,
            language=languages,
            profile=args.profile,
            chapter_id=f"{book_id}_subset",
            output_pdf=searchable_pdf,
            sidecar_txt=sidecar_txt,
        )
    except Exception as exc:
        print(f"Error during OCR execution: {exc}", file=sys.stderr)
        # Cleanup temporary files
        if temp_subset_pdf.exists():
            temp_subset_pdf.unlink()
        return 1
    finally:
        # Always cleanup the temporary subset PDF
        if temp_subset_pdf.exists():
            temp_subset_pdf.unlink()

    # 5. Post-Process Page Numbers and Map Back to Original Pages
    print("\n[5/5] Mapping page numbers back to original source PDF...")
    final_pages_jsonl = work_dir / "subset_pages.jsonl"
    if temp_pages_jsonl.exists():
        raw_records = read_jsonl(temp_pages_jsonl)
        mapped_records = []
        for record in raw_records:
            # record page number 1..N maps to selected_pages[page_num - 1]
            temp_pnum = int(record.get("page_num", 1))
            if 1 <= temp_pnum <= len(selected_pages):
                original_pnum = selected_pages[temp_pnum - 1]
            else:
                original_pnum = temp_pnum
            
            record["page_num"] = original_pnum
            # Add metadata about original page number
            record["metadata"] = record.get("metadata", {})
            record["metadata"]["subset_index"] = temp_pnum
            mapped_records.append(record)
        
        write_jsonl(mapped_records, final_pages_jsonl)
        temp_pages_jsonl.unlink()
        print(f"      Mapped JSONL written to: {final_pages_jsonl}")
    else:
        print("Warning: Temp pages JSONL not found. Could not map page numbers.", file=sys.stderr)

    # 6. Run QA Analysis
    print("\n[QA] Running OCR QA analysis...")
    qa_dir = work_dir / "qa"
    qa_summary = run_qa(input_jsonl=final_pages_jsonl, report_dir=qa_dir)
    print("      QA reports generated.")

    # 7. Write Manifest
    def rel_path(p: Path) -> str:
        try:
            return str(p.relative_to(Path.cwd()))
        except ValueError:
            return str(p)

    manifest_path = work_dir / "manifest.json"
    manifest_data = {
        "book_id": book_id,
        "source_pdf": str(input_pdf),
        "source_sha256": source_sha256,
        "pages_spec": args.pages,
        "selected_pages": selected_pages,
        "languages": languages,
        "dpi": args.dpi,
        "ocr_profile": args.profile,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "outputs": {
            "searchable_pdf": rel_path(searchable_pdf),
            "sidecar_txt": rel_path(sidecar_txt),
            "pages_jsonl": rel_path(final_pages_jsonl),
            "qa_json": rel_path(qa_dir / "qa_summary.json"),
            "qa_md": rel_path(qa_dir / "qa_summary.md"),
            "contact_sheet": rel_path(contact_sheet_path),
            "manifest": rel_path(manifest_path),
        },
        "docling_comparison_slot": None,
    }
    manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"      Manifest written to: {manifest_path}")

    # Print Compact Summary
    print("\n" + "=" * 70)
    print(f"SUBSET EVALUATION COMPLETE SUMMARY (Book ID: {book_id})")
    print("=" * 70)
    print(f"- Selected Physical Pages: {args.pages} ({len(selected_pages)} pages total)")
    print(f"- Languages:               {', '.join(languages)}")
    print(f"- OCR Profile:             {args.profile}")
    
    print("\nPage-by-Page Character Counts:")
    for stat in qa_summary.get("page_stats", []):
        pnum = stat.get("page_num")
        chars = stat.get("char_count", 0)
        empty_str = " [EMPTY]" if stat.get("is_empty") else ""
        print(f"  - Page {pnum:04d}: {chars:5d} chars{empty_str}")

    empty_pages = qa_summary.get("empty_pages", [])
    susp_pages = qa_summary.get("suspicious_low_text_pages", [])
    low_text_thresh = qa_summary.get("low_text_threshold", 40)
    repeated_headers = qa_summary.get("repeated_headers", [])
    repeated_footers = qa_summary.get("repeated_footers", [])

    print("\nAnomalies & Alerts:")
    if empty_pages:
        print(f"  - Empty pages: {empty_pages}")
    else:
        print("  - Empty pages: None detected")
        
    if susp_pages:
        print(f"  - Suspicious low-text pages (< {low_text_thresh} chars): {susp_pages}")
    else:
        print(f"  - Suspicious low-text pages (< {low_text_thresh} chars): None detected")

    if repeated_headers:
        headers_str = ", ".join(f"'{x['line']}' ({x['count']}x)" for x in repeated_headers)
        print(f"  - Repeated headers (likely headers/footers): {headers_str}")
    else:
        print("  - Repeated headers: None detected")

    if repeated_footers:
        footers_str = ", ".join(f"'{x['line']}' ({x['count']}x)" for x in repeated_footers)
        print(f"  - Repeated footers (likely page numbers): {footers_str}")
    else:
        print("  - Repeated footers: None detected")

    print("\nOutput Files Path Map:")
    for key, path_str in manifest_data["outputs"].items():
        print(f"  - {key.replace('_', ' ').title():15s}: {path_str}")

    print("=" * 70)
    print("Use reports/templates/ocr_subset_review.md to manually evaluate this run.")
    print("=" * 70 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
