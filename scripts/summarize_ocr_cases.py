#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

# Add project root to path if needed (though running with python scripts/... should work)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ocr_split_cases import build_global_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild global OCR summary JSON and Markdown reports."
    )
    parser.add_argument(
        "--book-id",
        required=True,
        help="ID of the book to process (mandatory)."
    )
    parser.add_argument(
        "--input-root",
        help="Root directory containing split case PDFs (defaults to book/<book_id>)."
    )
    parser.add_argument(
        "--output-root",
        help="Directory where OCR outputs live (defaults to data/ocr_cases/<book_id>)."
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    book_id = args.book_id
    input_root = Path(args.input_root) if args.input_root else (Path("book") / book_id)
    output_root = Path(args.output_root) if args.output_root else (Path("data") / "ocr_cases" / book_id)

    if not input_root.exists():
        print(f"Error: input root '{input_root}' does not exist.")
        return 1
    if not output_root.exists():
        print(f"Error: output root '{output_root}' does not exist.")
        return 1

    print("Scanning data/ocr_cases/ and rebuilding global summaries...")
    summary_data, md_summary = build_global_summary(input_root, output_root)

    summary_json_path = output_root / "ocr_cases_global_summary.json"
    summary_md_path = output_root / "ocr_cases_global_summary.md"

    summary_json_path.write_text(
        json.dumps(summary_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    summary_md_path.write_text(md_summary, encoding="utf-8")

    print("\nSummary Rebuild Successful!")
    print(f"  - Total Discovered Cases: {summary_data['total_discovered_cases']}")
    print(f"  - Completed Cases: {summary_data['total_discovered_cases'] - summary_data['failed_cases'] - summary_data['already_completed_skipped_cases'] - summary_data['newly_processed_cases'] if 'pending' in summary_data else 'See MD report for details'}")
    print(f"  - Already Completed / Skipped: {summary_data['already_completed_skipped_cases']}")
    print(f"  - Newly Processed: {summary_data['newly_processed_cases']}")
    print(f"  - Failed: {summary_data['failed_cases']}")
    print(f"  - Total Pages: {summary_data['total_pages_processed']}")
    print(f"  - Total Characters: {summary_data['total_ocr_characters']:,}")
    print(f"  - Cases with Empty Pages: {summary_data['cases_with_empty_pages']}")
    print(f"  - Cases with Suspicious Low-Text Pages: {summary_data['cases_with_suspicious_low_text_pages']}")

    print(f"\nWritten JSON to: {summary_json_path}")
    print(f"Written Markdown to: {summary_md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
