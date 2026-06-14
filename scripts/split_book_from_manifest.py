#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import yaml
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from scanbook.utils import ensure_dir, sha256_file

# Reconfigure stdout/stderr to UTF-8 to prevent any Windows encoding crashes
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract and split full clinical cases book based on a YAML manifest."
    )
    parser.add_argument(
        "--book-id",
        required=True,
        help="ID of the book to process (mandatory)."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Path to the book split YAML manifest (defaults to book/<book_id>/book_split_manifest.yaml).",
    )
    parser.add_argument(
        "--input-pdf",
        type=Path,
        help="Path to the source book PDF (defaults to scanning book/<book_id> for .pdf files).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Root folder for output splits (defaults to book/<book_id>).",
    )
    # Default is dry-run, unless --execute is passed
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run in dry-run mode (default).",
    )
    parser.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="Run in execute mode (create folders and split PDFs).",
    )
    # Flags for sections vs cases
    parser.add_argument(
        "--sections-only",
        action="store_true",
        help="Only extract section-level PDFs (e.g. sectionN.pdf).",
    )
    parser.add_argument(
        "--cases-only",
        action="store_true",
        help="Only extract case-level PDFs.",
    )
    # Filtering by section slug (e.g. seccion2 or all)
    parser.add_argument(
        "--section",
        type=str,
        default="all",
        help="Specific section slug to process (e.g. seccion2, seccion1, prefacio, all). (default: all).",
    )
    # Limit number of cases processed
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of cases processed for debugging.",
    )
    return parser.parse_args()


def print_dry_run_table(calculated_items: list[dict]) -> None:
    # Compact table headers
    header_format = "| {:8s} | {:9s} | {:30s} | {:35s} | {:5s} | {:5s} | {:6s} | {:6s} | {:6s} | {:6s} | {:5s} | {:45s} |"
    divider = "+" + "-"*10 + "+" + "-"*11 + "+" + "-"*32 + "+" + "-"*37 + "+" + "-"*7 + "+" + "-"*7 + "+" + "-"*8 + "+" + "-"*8 + "+" + "-"*8 + "+" + "-"*8 + "+" + "-"*7 + "+" + "-"*47 + "+"
    
    print("\n" + divider)
    print(header_format.format(
        "Type", "Sec Slug", "Subsect Slug", "Title", "Pr.St", "Pr.En", "PDF.St", "PDF.En", "Int.St", "Int.En", "Pages", "Output Path"
    ))
    print(divider)
    
    for item in calculated_items:
        sub_slug = item.get("subsection_slug") or ""
        out_path = item["output_path"] if item["output_path"] else "None"
        print(header_format.format(
            item["type"],
            item["section_slug"],
            sub_slug[:30],
            item["title"][:35],
            str(item["printed_start"]),
            str(item["printed_end"]),
            str(item["pdf_viewer_start"]),
            str(item["pdf_viewer_end"]),
            str(item["internal_start_index"]),
            str(item["internal_end_exclusive"]),
            str(item["expected_page_count"]),
            out_path[:45]
        ))
    print(divider + "\n")


def main() -> int:
    args = parse_args()
    book_id = args.book_id
    
    output_root = args.output_root if args.output_root else (Path("book") / book_id)
    output_root = output_root.resolve()
    
    manifest_path = args.manifest if args.manifest else (output_root / "book_split_manifest.yaml")
    manifest_path = manifest_path.resolve()
    
    if args.input_pdf:
        input_pdf = args.input_pdf.resolve()
    else:
        # Scan output_root for PDF files
        pdf_files = list(output_root.glob("*.pdf"))
        # Exclude generated/section files
        pdf_files = [p for p in pdf_files if not p.name.startswith("section") and p.name != "ocr.pdf"]
        if len(pdf_files) == 1:
            input_pdf = pdf_files[0].resolve()
        elif len(pdf_files) > 1:
            # Prefer files starting with the year/book name
            matching = [p for p in pdf_files if p.name.startswith(book_id.split("_")[0])]
            input_pdf = matching[0].resolve() if matching else pdf_files[0].resolve()
        else:
            print(f"Error: No source PDF found in {output_root}", file=sys.stderr)
            return 1

    print("======================================================================")
    print(f"CLINICAL CASES SPLITTING WORKFLOW - MODE: {'DRY-RUN' if args.dry_run else 'EXECUTE'}")
    print("======================================================================")
    print(f"Manifest:     {manifest_path}")
    print(f"Source PDF:   {input_pdf}")
    print(f"Output Root:  {output_root}")
    print(f"Filter Sec:   {args.section}")
    print(f"Secs Only:    {args.sections_only}")
    print(f"Cases Only:   {args.cases_only}")
    if args.limit:
        print(f"Limit cases:  {args.limit}")

    if not manifest_path.exists():
        print(f"Error: Manifest not found at {manifest_path}", file=sys.stderr)
        return 1

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = yaml.safe_load(f)

    def clean_manifest_path(p: str) -> str:
        p_clean = p.replace("\\", "/")
        if p_clean.startswith("book/"):
            return p_clean[5:]
        return p_clean

    # Flatten manifest into items based on parameters
    sections_list = manifest_data.get("sections", [])
    
    flat_items = []
    cases_added = 0
    
    for sec in sections_list:
        sec_slug = sec["slug"]
        
        # Filter by section if requested
        if args.section != "all" and args.section != sec_slug:
            continue
            
        # 1. Add section itself if --cases-only is not active
        if not args.cases_only:
            # We map Section properties to match calculated_items structure
            flat_items.append({
                "type": "section",
                "section_slug": sec_slug,
                "subsection_slug": None,
                "title": sec["title"],
                "printed_start": sec["printed_start"],
                "printed_end": sec["printed_end"],
                "pdf_viewer_start": sec["printed_start"] + 1,
                "pdf_viewer_end": sec["printed_end"] + 1,
                "internal_start_index": sec["printed_start"],
                "internal_end_exclusive": sec["printed_end"] + 1,
                "expected_page_count": sec["expected_page_count"],
                "output_path": str(output_root / clean_manifest_path(sec["output_path"])) if sec.get("output_path") else None
            })
            
        # 2. Add cases if --sections-only is not active
        if not args.sections_only:
            for sub in sec.get("subsections", []):
                for case in sub.get("cases", []):
                    if args.limit is not None and cases_added >= args.limit:
                        break
                    
                    flat_items.append({
                        "type": "case",
                        "section_slug": sec_slug,
                        "subsection_slug": sub["slug"],
                        "title": case["title"],
                        "printed_start": case["printed_start"],
                        "printed_end": case["printed_end"],
                        "pdf_viewer_start": case["pdf_viewer_start"],
                        "pdf_viewer_end": case["pdf_viewer_end"],
                        "internal_start_index": case["internal_start_index"],
                        "internal_end_exclusive": case["internal_end_exclusive"],
                        "expected_page_count": case["expected_page_count"],
                        "output_path": str(output_root / clean_manifest_path(case["output_path"])) if case.get("output_path") else None
                    })
                    cases_added += 1

    if args.dry_run:
        print_dry_run_table(flat_items)
        
        # Write dry-run manifest
        dryrun_manifest_path = output_root / "book_split_dryrun_manifest.json"
        ensure_dir(dryrun_manifest_path.parent)
        
        dryrun_data = {
            "mode": "dry-run",
            "source_pdf": str(input_pdf),
            "filter_section": args.section,
            "sections_only": args.sections_only,
            "cases_only": args.cases_only,
            "limit": args.limit,
            "calculated_items": flat_items,
        }
        dryrun_manifest_path.write_text(json.dumps(dryrun_data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Dry-run manifest written successfully: {dryrun_manifest_path}")
        print("PASS")
        return 0

    # EXECUTE MODE
    if not input_pdf.exists():
        print(f"Error: Source PDF not found at {input_pdf}", file=sys.stderr)
        return 1

    print("\nCalculating source PDF hash...")
    source_sha256 = sha256_file(input_pdf)
    print(f"SHA256 Checksum: {source_sha256}")

    # Read original PDF
    reader = PdfReader(str(input_pdf))
    total_pages = len(reader.pages)
    print(f"Total pages in source PDF: {total_pages}")

    split_manifest = []
    print("\nStarting PDF extraction...")
    for item in flat_items:
        if not item["output_path"]:
            continue
            
        full_path = Path(item["output_path"])
        ensure_dir(full_path.parent)
        
        internal_start = item["internal_start_index"]
        internal_end = item["internal_end_exclusive"]
        expected_pages = item["expected_page_count"]
        
        # Bounds checking
        if internal_start < 0 or internal_end > total_pages:
            print(f"Error: Range [{internal_start}, {internal_end}) is out of bounds for {item['title']}", file=sys.stderr)
            return 1
            
        # Slicing page range
        writer = PdfWriter()
        for idx in range(internal_start, internal_end):
            writer.add_page(reader.pages[idx])
            
        with full_path.open("wb") as f:
            writer.write(f)
            
        # Validation: Reopen and count pages
        check_reader = PdfReader(str(full_path))
        actual_pages = len(check_reader.pages)
        
        print(f"  - Extracted: {full_path.relative_to(output_root)} | Expected: {expected_pages} | Actual: {actual_pages}")
        
        # Loud assertion
        if actual_pages != expected_pages:
            raise RuntimeError(
                f"Validation FAILED for {item['title']}.\n"
                f"Expected page count: {expected_pages}, but got actual page count: {actual_pages}!"
            )
            
        split_manifest.append({
            "type": item["type"],
            "section_slug": item["section_slug"],
            "subsection_slug": item.get("subsection_slug"),
            "title": item["title"],
            "output_path": str(full_path.relative_to(output_root)),
            "printed_page_range": f"{item['printed_start']}-{item['printed_end']}",
            "pdf_viewer_page_range": f"{item['pdf_viewer_start']}-{item['pdf_viewer_end']}",
            "internal_slice": [internal_start, internal_end],
            "expected_page_count": expected_pages,
            "actual_page_count": actual_pages,
            "source_file_sha256": source_sha256
        })

    # Write execute manifest
    execute_manifest_path = output_root / "book_split_execute_manifest.json"
    execute_data = {
        "mode": "execute",
        "source_pdf": str(input_pdf),
        "source_sha256": source_sha256,
        "split_items": split_manifest
    }
    execute_manifest_path.write_text(json.dumps(execute_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nExecute manifest written successfully: {execute_manifest_path}")
    print("PASS")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
