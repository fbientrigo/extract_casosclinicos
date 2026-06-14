#!/usr/bin/env python3
import json
import re
import sqlite3
import hashlib
from pathlib import Path
import datetime

try:
    import duckdb
except ImportError:
    print("Error: duckdb is missing. Please install it:")
    print("  .\\.venv\\Scripts\\python -m pip install duckdb")
    exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "clinical_cases.db"
PARQUET_PATH = PROJECT_ROOT / "data" / "colab_exports" / "clinical_cases.parquet"
MANIFEST_PATH = PROJECT_ROOT / "data" / "curated" / "2014_lab" / "clean_case_pdf_manifest.json"
ACCEPTANCE_PATH = PROJECT_ROOT / "data" / "curated" / "2014_lab" / "final_clean_rebuild_acceptance.json"
BUNDLE_PATH = PROJECT_ROOT / "data" / "clinical_cases_bundle.duckdb"

def main():
    print(f"Building DuckDB bundle: {BUNDLE_PATH}")
    
    # Ensure output directory exists
    BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Remove existing bundle if it exists to ensure clean rebuild
    if BUNDLE_PATH.exists():
        BUNDLE_PATH.unlink()
    
    con = duckdb.connect(str(BUNDLE_PATH))
    
    # A. cases table
    print("Creating 'cases' table...")
    con.execute(f"CREATE TABLE cases AS SELECT * FROM read_parquet('{PARQUET_PATH}')")
    
    # B. pages table
    print("Creating 'pages' table from SQLite...")
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{DB_PATH}' AS sqlite_db (TYPE SQLITE)")
    con.execute("""
        CREATE TABLE pages AS 
        SELECT 
            p.case_id, 
            p.page_number, 
            (c.printed_start_page + p.page_number - 1)::TEXT AS printed_page, 
            p.text AS page_text, 
            p.char_count 
        FROM sqlite_db.pages p
        JOIN cases c ON p.case_id = c.case_id
    """)
    con.execute("DETACH sqlite_db")
    
    # C. source_lineage table
    print("Creating 'source_lineage' table from manifest...")
    lineage_rows = []
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        for c in manifest.get("cases", []):
            if c.get("case_id") == "prefacio_27_28":
                continue
            lineage_rows.append({
                "case_id": c["case_id"],
                "source_root": c.get("source_root", "book"),
                "source_pdf_path": c.get("source_pdf_path", ""),
                "clean_pdf_path": c.get("clean_pdf_path", ""),
                "boundary_decision": c.get("decision", ""),
                "boundary_source": c.get("boundary_source", "review_decisions_rule_v2.csv")
            })
    
    # Create source_lineage table in DuckDB
    # We can use a temporary file or just insert them
    con.execute("""
        CREATE TABLE source_lineage (
            case_id TEXT,
            source_root TEXT,
            source_pdf_path TEXT,
            clean_pdf_path TEXT,
            boundary_decision TEXT,
            boundary_source TEXT
        )
    """)
    # Insert in batches or all at once if not too large
    for row in lineage_rows:
        con.execute("INSERT INTO source_lineage VALUES (?, ?, ?, ?, ?, ?)", list(row.values()))

    # D. acceptance table
    print("Creating 'acceptance' table...")
    acc = {}
    if ACCEPTANCE_PATH.exists():
        acc = json.loads(ACCEPTANCE_PATH.read_text(encoding="utf-8"))
    counts = acc.get("counts", {})
    shas = acc.get("sha256", {})
    
    acceptance_row = {
        "acceptance_status": acc.get("acceptance_status", "UNKNOWN"),
        "clean_pdf_count": counts.get("clean_pdf_count", 0),
        "ocr_case_count": counts.get("ocr_case_count", 0),
        "db_case_count": counts.get("db_case_count", 0),
        "case_registry_count": counts.get("case_registry_count", 0),
        "colab_jsonl_row_count": counts.get("colab_jsonl_row_count", 0),
        "colab_parquet_row_count": counts.get("colab_parquet_row_count", 0),
        "section_count": counts.get("section_count", 0),
        "subsection_count": counts.get("subsection_count", 0),
        "sqlite_sha256": shas.get("data/clinical_cases.db", ""),
        "jsonl_sha256": shas.get("data/colab_exports/clinical_cases.jsonl", ""),
        "parquet_sha256": shas.get("data/colab_exports/clinical_cases.parquet", ""),
        "embedding_status": acc.get("embedding", {}).get("status", "not_built"),
        "created_at": datetime.datetime.now().isoformat()
    }
    
    con.execute("""
        CREATE TABLE acceptance (
            acceptance_status TEXT,
            clean_pdf_count INTEGER,
            ocr_case_count INTEGER,
            db_case_count INTEGER,
            case_registry_count INTEGER,
            colab_jsonl_row_count INTEGER,
            colab_parquet_row_count INTEGER,
            section_count INTEGER,
            subsection_count INTEGER,
            sqlite_sha256 TEXT,
            jsonl_sha256 TEXT,
            parquet_sha256 TEXT,
            embedding_status TEXT,
            created_at TEXT
        )
    """)
    con.execute("INSERT INTO acceptance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", list(acceptance_row.values()))

    # E. embeddings
    print("Creating empty 'embeddings' table...")
    con.execute("""
        CREATE TABLE embeddings (
            case_id TEXT,
            embedding_model TEXT,
            embedding_dim INTEGER,
            embedding_vector_json TEXT,
            created_at TEXT
        )
    """)

    # F. clusters
    print("Creating empty 'clusters' table...")
    con.execute("""
        CREATE TABLE clusters (
            case_id TEXT,
            embedding_model TEXT,
            cluster_method TEXT,
            cluster_id INTEGER,
            umap_x REAL,
            umap_y REAL,
            outlier_score REAL,
            silhouette_score REAL,
            created_at TEXT
        )
    """)

    # G. star_case_scores
    print("Creating empty 'star_case_scores' table...")
    con.execute("""
        CREATE TABLE star_case_scores (
            case_id TEXT,
            teaching_score REAL,
            diversity_score REAL,
            clarity_score REAL,
            representativeness_score REAL,
            novelty_score REAL,
            recommended_use TEXT,
            notes TEXT,
            created_at TEXT
        )
    """)

    
    # book_metadata and section_metadata
    import yaml
    
    con.execute("CREATE TABLE book_metadata (book_id TEXT, book_title TEXT, source_pdf TEXT, case_count INTEGER, page_count INTEGER, section_count INTEGER, acceptance_status TEXT, embedding_status TEXT, created_at TEXT)")
    con.execute("CREATE TABLE section_metadata (book_id TEXT, section_id TEXT, section_order INTEGER, section_title TEXT, section_display_label TEXT, printed_start_page INTEGER, printed_end_page INTEGER, case_count INTEGER, metadata_source TEXT)")
    
    book_id = "2014_lab" # the default for clinical cases
    manifest_path = PROJECT_ROOT / "book" / book_id / "book_split_manifest.yaml"
    cases_df = con.execute("SELECT * FROM cases").df()
    page_count = con.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)
        book_title = manifest.get("title", book_id)
        source_pdf = manifest.get("source_pdf", "")
        sections = manifest.get("sections", [])
        con.execute("INSERT INTO book_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [book_id, book_title, source_pdf, len(cases_df), page_count, len(sections), "UNKNOWN", "not_built", datetime.datetime.now().isoformat()])
        
        for sec in sections:
            sec_id = sec.get("slug", "")
            sec_order = sec.get("number", 0)
            sec_title = sec.get("title", "")
            sec_display = f"S{sec_order} · {sec_title}"
            start_page = sec.get("printed_start", 0)
            end_page = sec.get("printed_end", 0)
            sc_count = len(cases_df[cases_df["section"] == sec_id]) if "section" in cases_df.columns else 0
            con.execute("INSERT INTO section_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [book_id, sec_id, sec_order, sec_title, sec_display, start_page, end_page, sc_count, "manifest"])
    else:
        con.execute("INSERT INTO book_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [book_id, book_id, "", len(cases_df), page_count, 0, "UNKNOWN", "not_built", datetime.datetime.now().isoformat()])
        if "section" in cases_df.columns:
            unique_sections = cases_df["section"].dropna().unique()
            for sec_id in unique_sections:
                m = re.search(r'\d+', str(sec_id))
                sec_order = int(m.group()) if m else 99
                sec_cases = cases_df[cases_df["section"] == sec_id]
                sec_title = str(sec_id)
                if not sec_cases.empty and "subsection" in sec_cases.columns:
                    subs = sec_cases["subsection"].dropna().unique()
                    if len(subs) > 0 and "/" in str(subs[0]):
                        sec_title = str(subs[0]).split("/")[-1].replace("_", " ").title()
                sec_display = f"S{sec_order} · {sec_title}"
                con.execute("INSERT INTO section_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [book_id, str(sec_id), sec_order, sec_title, sec_display, 0, 0, len(sec_cases), "inferred_from_cases"])

    con.close()
    print("Bundle created successfully.")

if __name__ == "__main__":
    main()
