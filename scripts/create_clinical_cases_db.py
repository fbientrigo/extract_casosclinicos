#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

# Add project root and src/ to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from scanbook.db import build_cases_db

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consolidate all OCR case outputs into a portable SQLite/DuckDB database and curation registries."
    )
    parser.add_argument(
        "--book-id",
        required=True,
        help="ID of the book to process (mandatory)."
    )
    parser.add_argument(
        "--db-engine",
        choices=["sqlite", "duckdb"],
        default="sqlite",
        help="Database engine to use (default: sqlite)."
    )
    parser.add_argument(
        "--ocr-cases-dir",
        help="Root directory where completed OCR case folders live (defaults to data/ocr_cases/<book-id>)."
    )
    parser.add_argument(
        "--manifest",
        help="Path to book split manifest (defaults to book/<book-id>/book_split_manifest.yaml)."
    )
    parser.add_argument(
        "--output-db",
        help="Path to output database (defaults to data/<book-id>.[db|duckdb])."
    )
    parser.add_argument(
        "--curated-dir",
        help="Path to curated output files directory (defaults to data/ocr_cases/<book-id>/curated)."
    )
    
    args = parser.parse_args()
    book_id = args.book_id
    
    ocr_dir = Path(args.ocr_cases_dir) if args.ocr_cases_dir else (project_root / "data" / "ocr_cases" / book_id)
    manifest_path = Path(args.manifest) if args.manifest else (project_root / "book" / book_id / "book_split_manifest.yaml")
    
    if args.output_db:
        output_db = Path(args.output_db)
    else:
        db_ext = "duckdb" if args.db_engine == "duckdb" else "db"
        output_db = project_root / "data" / f"{book_id}.{db_ext}"
        
    curated_dir = Path(args.curated_dir) if args.curated_dir else (ocr_dir / "curated")
    
    if not ocr_dir.exists():
        print(f"Error: OCR cases directory '{ocr_dir}' does not exist.")
        return 1
        
    print(f"Consolidating OCR outputs into {args.db_engine.upper()} database and registry layer...")
    print(f"  - Book ID: {book_id}")
    print(f"  - OCR Dir: {ocr_dir}")
    print(f"  - Manifest: {manifest_path}")
    print(f"  - Output DB: {output_db}")
    print(f"  - Curated Dir: {curated_dir}")
    
    try:
        report = build_cases_db(
            ocr_cases_dir=ocr_dir,
            manifest_path=manifest_path,
            output_db=output_db,
            curated_dir=curated_dir,
            db_engine=args.db_engine
        )
        print("\nDatabase and curation registry build successful!")
        print(f"  - Total Cases Inserted: {report['total_cases_inserted']}")
        print(f"  - Total Pages Inserted: {report['total_pages_inserted']}")
        print(f"  - Total Clean Characters: {report['total_characters']:,}")
        print(f"  - Cases Needing Review: {report['cases_needing_manual_review']}")
        print(f"  - Database Size: {report['database_size_bytes'] / (1024*1024):.2f} MB")
        print(f"  - Registry and build report written to: {curated_dir}")
        return 0
    except Exception as e:
        print(f"\nError: Failed to build cases database: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
