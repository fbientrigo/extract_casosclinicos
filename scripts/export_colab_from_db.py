#!/usr/bin/env python3
import argparse
import json
import sqlite3
import pandas as pd
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--db-path", help="Path to sqlite db (defaults to data/<book-id>.db)")
    parser.add_argument("--output-dir", help="Path to output (defaults to data/curated/<book-id>/colab_exports)")
    args = parser.parse_args()

    book_id = args.book_id
    project_root = Path(__file__).resolve().parent.parent
    
    db_path = Path(args.db_path) if args.db_path else (project_root / "data" / f"{book_id}.db")
    output_dir = Path(args.output_dir) if args.output_dir else (project_root / "data" / "curated" / book_id / "colab_exports")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(str(db_path))
    
    # Extract merged view of cases
    query = """
        SELECT 
            c.case_id,
            c.title,
            c.section_id AS section,
            c.subsection_id AS subsection,
            c.printed_start AS printed_start_page,
            c.printed_end AS printed_end_page,
            t.clean_markdown AS clean_text,
            c.page_count,
            c.total_chars AS char_count,
            c.source_pdf AS source_pdf_path,
            'native_pdf' AS ocr_version
        FROM cases c
        LEFT JOIN case_texts t ON c.case_id = t.case_id
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    jsonl_path = output_dir / "clinical_cases.jsonl"
    parquet_path = output_dir / "clinical_cases.parquet"
    embedding_manifest_path = output_dir / "embedding_manifest.json"
    
    records = df.to_dict("records")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for row in records:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            
    df.to_parquet(parquet_path, index=False)
    
    embedding_manifest_path.write_text(
        json.dumps(
            {
                "status": "not_built",
                "reason": "Embeddings intentionally deferred for clean canonical rebuild.",
                "record_count": len(records),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    
    print(f"Exported {len(records)} cases to {output_dir}")

if __name__ == "__main__":
    main()
