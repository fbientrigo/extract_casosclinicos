import argparse
import duckdb
from pathlib import Path
import datetime

def main():
    parser = argparse.ArgumentParser(description="Export a Colab-compatible bundle")
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--input-db", required=True)
    parser.add_argument("--output-bundle", required=True)
    parser.add_argument("--acceptance-status", default="PENDING_SPLIT_QA_BASELINE")
    args = parser.parse_args()

    out_bundle = Path(args.output_bundle)
    out_bundle.parent.mkdir(parents=True, exist_ok=True)
    if out_bundle.exists():
        out_bundle.unlink()

    con = duckdb.connect(str(out_bundle))
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{args.input_db}' AS sqlite_db (TYPE SQLITE)")

    # 1. cases
    con.execute(f"""
        CREATE TABLE cases AS
        SELECT 
            c.case_id::VARCHAR AS case_id,
            c.title::VARCHAR AS title,
            c.section_id::VARCHAR AS section,
            c.subsection_id::VARCHAR AS subsection,
            c.printed_start::BIGINT AS printed_start_page,
            c.printed_end::VARCHAR AS printed_end_page,
            t.clean_markdown::VARCHAR AS clean_text,
            c.page_count::BIGINT AS page_count,
            c.total_chars::BIGINT AS char_count,
            c.source_pdf::VARCHAR AS source_pdf_path,
            c.clean_case_md_path::VARCHAR AS clean_pdf_path,
            'digital_pdf_split'::VARCHAR AS boundary_decision,
            'indices_casos_txt_offset_k_1'::VARCHAR AS boundary_source,
            'native_text_or_pending'::VARCHAR AS ocr_version
        FROM sqlite_db.cases c
        LEFT JOIN sqlite_db.case_texts t ON c.case_id = t.case_id
    """)

    # 2. pages
    con.execute("""
        CREATE TABLE pages AS 
        SELECT 
            p.case_id::VARCHAR AS case_id, 
            p.page_number::BIGINT AS page_number, 
            (c.printed_start + p.page_number - 1)::VARCHAR AS printed_page, 
            p.text::VARCHAR AS page_text, 
            p.char_count::BIGINT AS char_count 
        FROM sqlite_db.pages p
        JOIN sqlite_db.cases c ON p.case_id = c.case_id
    """)

    # 3. source_lineage
    con.execute(f"""
        CREATE TABLE source_lineage AS
        SELECT
            case_id::VARCHAR AS case_id,
            'book'::VARCHAR AS source_root,
            source_pdf_path::VARCHAR AS source_pdf_path,
            clean_pdf_path::VARCHAR AS clean_pdf_path,
            boundary_decision::VARCHAR AS boundary_decision,
            boundary_source::VARCHAR AS boundary_source
        FROM cases
    """)

    # 4. acceptance
    con.execute(f"""
        CREATE TABLE acceptance AS
        SELECT
            '{args.book_id}'::VARCHAR AS book_id,
            '{args.acceptance_status}'::VARCHAR AS acceptance_status,
            (SELECT COUNT(*) FROM cases)::INTEGER AS clean_pdf_count,
            (SELECT COUNT(*) FROM cases)::INTEGER AS ocr_case_count,
            (SELECT COUNT(*) FROM cases)::INTEGER AS db_case_count,
            (SELECT COUNT(*) FROM cases)::INTEGER AS case_registry_count,
            (SELECT COUNT(*) FROM cases)::INTEGER AS colab_jsonl_row_count,
            (SELECT COUNT(*) FROM cases)::INTEGER AS colab_parquet_row_count,
            0::INTEGER AS section_count,
            0::INTEGER AS subsection_count,
            ''::VARCHAR AS sqlite_sha256,
            ''::VARCHAR AS jsonl_sha256,
            ''::VARCHAR AS parquet_sha256,
            'not_built'::VARCHAR AS embedding_status,
            '{datetime.datetime.now().isoformat()}'::VARCHAR AS created_at
    """)

    # 5. embeddings
    con.execute("""
        CREATE TABLE embeddings (
            case_id VARCHAR,
            embedding_model VARCHAR,
            embedding_dim INTEGER,
            embedding_vector_json VARCHAR,
            created_at VARCHAR
        )
    """)

    # 6. clusters
    con.execute("""
        CREATE TABLE clusters (
            case_id VARCHAR,
            embedding_model VARCHAR,
            cluster_method VARCHAR,
            cluster_id INTEGER,
            umap_x FLOAT,
            umap_y FLOAT,
            outlier_score FLOAT,
            silhouette_score FLOAT,
            created_at VARCHAR
        )
    """)

    # 7. star_case_scores
    con.execute("""
        CREATE TABLE star_case_scores (
            case_id VARCHAR,
            teaching_score FLOAT,
            diversity_score FLOAT,
            clarity_score FLOAT,
            representativeness_score FLOAT,
            novelty_score FLOAT,
            recommended_use VARCHAR,
            notes VARCHAR,
            created_at VARCHAR
        )
    """)

    
    # 8. Add book_metadata and section_metadata
    import yaml
    import json
    
    book_metadata_table = "CREATE TABLE book_metadata (book_id VARCHAR, book_title VARCHAR, source_pdf VARCHAR, case_count INTEGER, page_count INTEGER, section_count INTEGER, acceptance_status VARCHAR, embedding_status VARCHAR, created_at VARCHAR)"
    con.execute(book_metadata_table)
    
    section_metadata_table = "CREATE TABLE section_metadata (book_id VARCHAR, section_id VARCHAR, section_order INTEGER, section_title VARCHAR, section_display_label VARCHAR, printed_start_page INTEGER, printed_end_page INTEGER, case_count INTEGER, metadata_source VARCHAR)"
    con.execute(section_metadata_table)
    
    # Let's try to find the manifest
    project_root = Path(__file__).resolve().parent.parent
    manifest_path = project_root / "book" / args.book_id / "book_split_manifest.yaml"
    
    cases_df = con.execute("SELECT * FROM cases").df()
    
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)
            
        book_title = manifest.get("title", args.book_id)
        source_pdf = manifest.get("source_pdf", "")
        
        # Insert book_metadata
        case_count = len(cases_df)
        page_count = con.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        sections = manifest.get("sections", [])
        section_count = len(sections)
        
        con.execute(
            "INSERT INTO book_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [args.book_id, book_title, source_pdf, case_count, page_count, section_count, args.acceptance_status, "not_built", datetime.datetime.now().isoformat()]
        )
        
        for sec in sections:
            sec_id = sec.get("slug", "")
            sec_order = sec.get("number", 0)
            sec_title = sec.get("title", "")
            sec_display = f"S{sec_order} · {sec_title}"
            start_page = sec.get("printed_start", 0)
            end_page = sec.get("printed_end", 0)
            # count cases in this section
            sc_count = len(cases_df[cases_df["section"] == sec_id])
            con.execute(
                "INSERT INTO section_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [args.book_id, sec_id, sec_order, sec_title, sec_display, start_page, end_page, sc_count, "manifest"]
            )
    else:
        # Fallback
        book_title = args.book_id
        source_pdf = ""
        case_count = len(cases_df)
        page_count = con.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        
        # Infer sections from cases
        unique_sections = cases_df["section"].dropna().unique()
        section_count = len(unique_sections)
        
        con.execute(
            "INSERT INTO book_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [args.book_id, book_title, source_pdf, case_count, page_count, section_count, args.acceptance_status, "not_built", datetime.datetime.now().isoformat()]
        )
        
        for sec_id in unique_sections:
            m = re.search(r'\d+', str(sec_id))
            sec_order = int(m.group()) if m else 99
            
            # infer title from subsection
            sec_cases = cases_df[cases_df["section"] == sec_id]
            sec_title = str(sec_id)
            if not sec_cases.empty:
                subs = sec_cases["subsection"].dropna().unique()
                if len(subs) > 0 and "/" in str(subs[0]):
                    sec_title = str(subs[0]).split("/")[-1].replace("_", " ").title()
            
            sec_display = f"S{sec_order} · {sec_title}"
            sc_count = len(sec_cases)
            
            con.execute(
                "INSERT INTO section_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [args.book_id, str(sec_id), sec_order, sec_title, sec_display, 0, 0, sc_count, "inferred_from_cases"]
            )

    con.execute("DETACH sqlite_db")
    con.close()
    print(f"Bundle {out_bundle} created successfully.")

if __name__ == "__main__":
    main()
