#!/usr/bin/env python3
import argparse
import datetime
import json
import sqlite3
from pathlib import Path

try:
    import duckdb
except ImportError:
    print("Error: duckdb is missing.")
    exit(1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--book-id", required=True)
    args = parser.parse_args()

    book_id = args.book_id
    project_root = Path(__file__).resolve().parent.parent
    
    db_path = project_root / "data" / f"{book_id}.db"
    parquet_path = project_root / "data" / "curated" / book_id / "colab_exports" / "clinical_cases.parquet"
    bundle_path = project_root / "data" / "curated" / book_id / f"{book_id}_bundle.duckdb"
    
    print(f"Building DuckDB bundle: {bundle_path}")
    
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    if bundle_path.exists():
        bundle_path.unlink()
    
    con = duckdb.connect(str(bundle_path))
    
    # A. cases table
    print("Creating 'cases' table...")
    con.execute(f"CREATE TABLE cases AS SELECT * FROM read_parquet('{parquet_path}')")
    
    # B. pages table
    print("Creating 'pages' table from SQLite...")
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{db_path}' AS sqlite_db (TYPE SQLITE)")
    con.execute("""
        CREATE TABLE pages AS 
        SELECT 
            p.case_id, 
            p.page_number, 
            (c.printed_start + p.page_number - 1)::TEXT AS printed_page, 
            p.text AS page_text, 
            p.char_count 
        FROM sqlite_db.pages p
        JOIN sqlite_db.cases c ON p.case_id = c.case_id
    """)
    con.execute("DETACH sqlite_db")
    
    # C. embeddings (empty)
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

    # D. clusters (empty)
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

    # E. star_case_scores (empty)
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

    
    # metadata
    import yaml
    import datetime
    
    con.execute("CREATE TABLE book_metadata (book_id VARCHAR, book_title VARCHAR, source_pdf VARCHAR, case_count INTEGER, page_count INTEGER, section_count INTEGER, acceptance_status VARCHAR, embedding_status VARCHAR, created_at VARCHAR)")
    con.execute("CREATE TABLE section_metadata (book_id VARCHAR, section_id VARCHAR, section_order INTEGER, section_title VARCHAR, section_display_label VARCHAR, printed_start_page INTEGER, printed_end_page INTEGER, case_count INTEGER, metadata_source VARCHAR)")
    
    manifest_path = project_root / "book" / book_id / "book_split_manifest.yaml"
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
