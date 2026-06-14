from __future__ import annotations

import sqlite3
import json
import csv
import math
import re
import yaml
from pathlib import Path
from typing import Any

SPANISH_STOPWORDS = {
    "de", "la", "que", "el", "en", "y", "a", "los", "del", "se", "las", "por", "un", "para", "con", "no", 
    "una", "su", "al", "lo", "como", "más", "o", "pero", "sus", "este", "le", "ya", "si", "sin", 
    "muy", "bien", "ser", "sus", "este", "esta", "estos", "estas", "había", "he", "has", "ha", "hemos", 
    "han", "habías", "había", "habíamos", "habíais", "habían", "será", "serán", "suya", "suyo", "suyas", 
    "suyos", "mi", "mis", "tu", "tus", "yo", "me", "nos", "él", "ella", "ellos", "ellas", "nosotros", 
    "nosotras", "vosotros", "vosotras", "otro", "otra", "otros", "otras", "porque", "también",
    "sobre", "entre", "hasta", "desde", "durante", "tras", "ante", "bajo", "cabe", "con", "contra", 
    "hacia", "según", "so", "mediante", "versus", "vía", "aquel", "aquella", "aquellos", "aquellas", 
    "ese", "esa", "esos", "esas", "cual", "cuales", "quien", "quienes", "todo", "toda", "todos", 
    "todas", "alguno", "alguna", "algunos", "algunas", "ninguno", "ninguna", "ningunos", "ningunas", 
    "mismo", "misma", "mismos", "mismas", "tanto", "tanta", "tantos", "tantas", "cuando", "donde", 
    "cuanto", "cuanta", "cuantos", "cuantas"
}

def init_db(conn: sqlite3.Connection | Any) -> None:
    cursor = conn.cursor()
    is_sqlite = "sqlite3" in type(conn).__module__
    
    if is_sqlite:
        tag_id_def = "tag_id INTEGER PRIMARY KEY AUTOINCREMENT"
        concept_id_def = "concept_id INTEGER PRIMARY KEY AUTOINCREMENT"
    else:
        cursor.execute("CREATE SEQUENCE IF NOT EXISTS tag_id_seq;")
        cursor.execute("CREATE SEQUENCE IF NOT EXISTS concept_id_seq;")
        tag_id_def = "tag_id INTEGER PRIMARY KEY DEFAULT nextval('tag_id_seq')"
        concept_id_def = "concept_id INTEGER PRIMARY KEY DEFAULT nextval('concept_id_seq')"
        
    # 1. sections
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sections (
        section_id TEXT PRIMARY KEY,
        title TEXT,
        printed_start INTEGER,
        printed_end INTEGER
    );
    """)
    
    # 2. subsections
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS subsections (
        subsection_id TEXT PRIMARY KEY,
        section_id TEXT,
        slug TEXT,
        title TEXT,
        printed_start INTEGER,
        printed_end INTEGER,
        FOREIGN KEY(section_id) REFERENCES sections(section_id)
    );
    """)
    
    # 3. cases
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cases (
        case_id TEXT PRIMARY KEY,
        section_id TEXT,
        subsection_id TEXT,
        slug TEXT,
        title TEXT,
        printed_start INTEGER,
        printed_end INTEGER,
        page_count INTEGER,
        total_chars INTEGER,
        source_pdf TEXT,
        case_md_path TEXT,
        clean_case_md_path TEXT,
        qa_json_path TEXT,
        metadata_json_path TEXT,
        status TEXT,
        needs_manual_review INTEGER,
        review_reason TEXT,
        FOREIGN KEY(section_id) REFERENCES sections(section_id),
        FOREIGN KEY(subsection_id) REFERENCES subsections(subsection_id)
    );
    """)
    
    # 4. pages
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pages (
        page_id TEXT PRIMARY KEY,
        case_id TEXT,
        page_number INTEGER,
        text TEXT,
        char_count INTEGER,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
    """)
    
    # 5. qa_reports
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qa_reports (
        case_id TEXT PRIMARY KEY,
        empty_pages TEXT,
        suspicious_low_text_pages TEXT,
        repeated_headers TEXT,
        repeated_footers TEXT,
        quality_flags TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
    """)
    
    # 6. case_texts
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS case_texts (
        case_id TEXT PRIMARY KEY,
        raw_markdown TEXT,
        clean_markdown TEXT,
        full_text TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
    """)
    
    # 7. embeddings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS embeddings (
        embedding_id TEXT PRIMARY KEY,
        case_id TEXT,
        level TEXT,
        model_name TEXT,
        vector_dim INTEGER,
        vector_blob BLOB,
        created_at TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
    """)
    
    # 8. clusters
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS clusters (
        cluster_id TEXT,
        case_id TEXT,
        embedding_model TEXT,
        method TEXT,
        k INTEGER,
        silhouette_score REAL,
        distance_to_centroid REAL,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
    """)
    
    # 9. tags
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS tags (
        {tag_id_def},
        case_id TEXT,
        tag_family TEXT,
        tag_value TEXT,
        confidence REAL,
        source TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
    """)
    
    # 10. concepts
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS concepts (
        {concept_id_def},
        case_id TEXT,
        concept TEXT,
        score REAL,
        source TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
    """)
    
    # 11. case_metrics
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS case_metrics (
        case_id TEXT PRIMARY KEY,
        lexical_diversity REAL,
        tfidf_concept_count INTEGER,
        concept_entropy REAL,
        teaching_density_score REAL,
        diversity_score REAL,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
    """)
    
    # 12. star_case_scores
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS star_case_scores (
        case_id TEXT PRIMARY KEY,
        section_id TEXT,
        score REAL,
        rationale TEXT,
        source TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id),
        FOREIGN KEY(section_id) REFERENCES sections(section_id)
    );
    """)
    
    # 13. llm_case_cards
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS llm_case_cards (
        case_id TEXT PRIMARY KEY,
        model_name TEXT,
        card_json TEXT,
        created_at TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
    """)
    
    conn.commit()

def _normalize_line(line: str) -> str:
    return " ".join(line.lower().strip().split())

def _clean_page_text(raw_text: str, repeated_headers: list[str], repeated_footers: list[str]) -> str:
    lines = raw_text.splitlines()
    if not lines:
        return ""
    
    norm_headers = {_normalize_line(h) for h in repeated_headers if h}
    norm_footers = {_normalize_line(f) for f in repeated_footers if f}
    
    # Identify first non-empty line index
    first_idx = -1
    for idx, ln in enumerate(lines):
        if ln.strip():
            first_idx = idx
            break
            
    # Identify last non-empty line index
    last_idx = -1
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx].strip():
            last_idx = idx
            break
            
    # Clean header if matches
    if first_idx != -1:
        norm_first = _normalize_line(lines[first_idx])
        if norm_first in norm_headers:
            lines[first_idx] = ""
            
    # Clean footer if matches (ensure not double-cleaning same single line)
    if last_idx != -1 and last_idx != first_idx:
        norm_last = _normalize_line(lines[last_idx])
        if norm_last in norm_footers:
            lines[last_idx] = ""
            
    cleaned_body = "\n".join(lines)
    # Normalize excessive newlines (3+ consecutive newlines -> exactly 2)
    cleaned_body = re.sub(r"\n{3,}", "\n\n", cleaned_body)
    return cleaned_body.strip()

def _calculate_metrics(text: str) -> tuple[float, float]:
    tokens = re.findall(r"[a-záéíóúüñ0-9]+", text.lower())
    if not tokens:
        return 0.0, 0.0
        
    ttr = len(set(tokens)) / len(tokens)
    
    # Concept entropy (Shannon entropy of filtered words)
    filtered = [t for t in tokens if t not in SPANISH_STOPWORDS and len(t) >= 3]
    if not filtered:
        return ttr, 0.0
        
    counts = {}
    for t in filtered:
        counts[t] = counts.get(t, 0) + 1
        
    entropy = 0.0
    total = len(filtered)
    for c in counts.values():
        p = c / total
        entropy -= p * math.log(p)
        
    return ttr, entropy

def build_cases_db(
    ocr_cases_dir: Path,
    manifest_path: Path,
    output_db: Path,
    curated_dir: Path | None = None,
    db_engine: str = "sqlite"
) -> dict[str, Any]:
    if curated_dir is None:
        curated_dir = ocr_cases_dir.parent / "curated"
        
    curated_dir.mkdir(parents=True, exist_ok=True)
    clean_cases_dir = curated_dir / "clean_cases"
    clean_cases_dir.mkdir(parents=True, exist_ok=True)
    
    output_db.parent.mkdir(parents=True, exist_ok=True)
    
    # 1. Parse manifest
    manifest_sections = []
    manifest_subsections = []
    manifest_cases = []
    
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = yaml.safe_load(f)
                
            for sec_idx, sec in enumerate(manifest_data.get("sections", [])):
                sec_slug = sec.get("slug") or f"seccion{sec_idx}"
                sec_title = sec.get("title")
                sec_start = sec.get("printed_start")
                sec_end = sec.get("printed_end")
                
                manifest_sections.append({
                    "section_id": sec_slug,
                    "title": sec_title,
                    "printed_start": sec_start,
                    "printed_end": sec_end
                })
                
                for subsec in sec.get("subsections", []):
                    subsec_slug = subsec.get("slug")
                    subsec_title = subsec.get("title")
                    subsec_start = subsec.get("printed_start")
                    subsec_end = subsec.get("printed_end")
                    subsec_id = f"{sec_slug}/{subsec_slug}"
                    
                    manifest_subsections.append({
                        "subsection_id": subsec_id,
                        "section_id": sec_slug,
                        "slug": subsec_slug,
                        "title": subsec_title,
                        "printed_start": subsec_start,
                        "printed_end": subsec_end
                    })
                    
                    for case_item in subsec.get("cases", []):
                        case_slug = case_item.get("slug")
                        case_title = case_item.get("title")
                        case_start = case_item.get("printed_start")
                        case_end = case_item.get("printed_end")
                        
                        manifest_cases.append({
                            "section_id": sec_slug,
                            "subsection_id": subsec_id,
                            "slug": case_slug,
                            "title": case_title,
                            "printed_start": case_start,
                            "printed_end": case_end
                        })
        except Exception as e:
            print(f"Warning: Failed to parse manifest: {e}")
            
    # Connect to database
    if db_engine == "duckdb":
        import duckdb
        conn = duckdb.connect(str(output_db))
    else:
        import sqlite3
        conn = sqlite3.connect(output_db)
    init_db(conn)
    
    # Discover all completed cases
    discovered_folders = []
    # Search structure: ocr_cases_dir / seccionN / subsection_slug / case_folder
    if ocr_cases_dir.exists():
        for sec_dir in ocr_cases_dir.iterdir():
            if not sec_dir.is_dir() or not sec_dir.name.startswith("seccion"):
                continue
            for subsec_dir in sec_dir.iterdir():
                if not subsec_dir.is_dir():
                    continue
                for case_dir in subsec_dir.iterdir():
                    if not case_dir.is_dir():
                        continue
                    
                    expected_files = ["case_metadata.json", "pages.jsonl", "case.md", "qa.json", "sidecar.txt"]
                    if all((case_dir / f).exists() for f in expected_files):
                        discovered_folders.append((sec_dir.name, subsec_dir.name, case_dir.name, case_dir))
                        
    discovered_folders.sort(key=lambda x: (x[0], x[1], x[2]))
    
    # Maps for database insert
    inserted_sections = {}
    inserted_subsections = {}
    
    cases_to_insert = []
    pages_to_insert = []
    qa_reports_to_insert = []
    case_texts_to_insert = []
    case_metrics_to_insert = []
    concepts_to_insert = []
    
    all_case_word_frequencies = {} # case_id -> term count
    document_frequencies = {} # term -> document count
    
    for sec_slug, subsec_slug, case_folder, case_dir in discovered_folders:
        case_id = case_folder
        
        # Parse printed_start and title_slug from case_folder
        match = re.match(r"^(\d+)_(.*)$", case_folder)
        if match:
            folder_start = int(match.group(1))
            folder_slug = match.group(2)
        else:
            folder_start = None
            folder_slug = case_folder
            
        # Match manifest case
        matched_case = None
        for mc in manifest_cases:
            if mc["section_id"] == sec_slug and mc["slug"] == folder_slug:
                matched_case = mc
                break
        if not matched_case and folder_start is not None:
            for mc in manifest_cases:
                if mc["section_id"] == sec_slug and mc["printed_start"] == folder_start:
                    matched_case = mc
                    break
                    
        # Resolve titles and page ranges
        resolved_title = folder_slug.replace("_", " ").capitalize()
        resolved_start = folder_start
        resolved_end = folder_start
        
        if matched_case:
            resolved_title = matched_case["title"]
            resolved_start = matched_case["printed_start"]
            resolved_end = matched_case["printed_end"]
            
        subsec_id = f"{sec_slug}/{subsec_slug}"
        
        # Load section title and ranges
        sec_title = sec_slug.replace("_", " ").capitalize()
        sec_start = None
        sec_end = None
        for ms in manifest_sections:
            if ms["section_id"] == sec_slug:
                sec_title = ms["title"]
                sec_start = ms["printed_start"]
                sec_end = ms["printed_end"]
                break
                
        # Load subsection title and ranges
        subsec_title = subsec_slug.replace("_", " ").capitalize()
        subsec_start = None
        subsec_end = None
        for mss in manifest_subsections:
            if mss["subsection_id"] == subsec_id:
                subsec_title = mss["title"]
                subsec_start = mss["printed_start"]
                subsec_end = mss["printed_end"]
                break
                
        # Store resolved sections/subsections
        if sec_slug not in inserted_sections:
            inserted_sections[sec_slug] = (sec_slug, sec_title, sec_start, sec_end)
        if subsec_id not in inserted_subsections:
            inserted_subsections[subsec_id] = (subsec_id, sec_slug, subsec_slug, subsec_title, subsec_start, subsec_end)
            
        # Load case metadata
        meta_path = case_dir / "case_metadata.json"
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
            
        # Load QA
        qa_path = case_dir / "qa.json"
        with open(qa_path, "r", encoding="utf-8") as f:
            qa = json.load(f)
            
        # Load pages and clean text
        pages_path = case_dir / "pages.jsonl"
        raw_pages_data = []
        with open(pages_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    raw_pages_data.append(json.loads(line))
                    
        # Extract headers and footers to clean
        repeated_headers = [h.get("line", "") for h in qa.get("repeated_headers", [])]
        repeated_footers = [f.get("line", "") for f in qa.get("repeated_footers", [])]
        
        cleaned_pages = []
        full_text_parts = []
        
        for p in raw_pages_data:
            page_num = p["page_num"]
            raw_p_text = p.get("text", "")
            cleaned_p_text = _clean_page_text(raw_p_text, repeated_headers, repeated_footers)
            
            cleaned_pages.append((page_num, cleaned_p_text, len(raw_p_text)))
            full_text_parts.append(cleaned_p_text)
            
            page_id = f"{case_id}/page_{page_num}"
            pages_to_insert.append((page_id, case_id, page_num, cleaned_p_text, len(cleaned_p_text)))
            
        full_text = "\n\n".join(full_text_parts)
        
        # Load case.md
        case_md_path = case_dir / "case.md"
        raw_md = case_md_path.read_text(encoding="utf-8")
        
        # Construct clean_case.md
        # Extract frontmatter and first case title from raw_md
        frontmatter_parts = raw_md.split("---")
        header_markdown = ""
        if len(frontmatter_parts) >= 3:
            header_markdown = f"---\n{frontmatter_parts[1].strip()}\n---\n\n"
            # Extract anything between the second '---' and the first '## Page'
            body_pre = frontmatter_parts[2]
            first_page_match = re.search(r"^## Page", body_pre, re.MULTILINE)
            if first_page_match:
                pre_page_text = body_pre[:first_page_match.start()].strip()
                if pre_page_text:
                    header_markdown += pre_page_text + "\n\n"
                    
        clean_md_body_parts = []
        for page_num, cleaned_p_text, _ in cleaned_pages:
            clean_md_body_parts.append(f"## Page {page_num}\n{cleaned_p_text}")
            
        clean_markdown = header_markdown + "\n\n".join(clean_md_body_parts) + "\n"
        
        # Write clean case Markdown to data/curated/clean_cases/
        clean_out_dir = clean_cases_dir / sec_slug / subsec_slug / case_id
        clean_out_dir.mkdir(parents=True, exist_ok=True)
        clean_case_md_file = clean_out_dir / "clean_case.md"
        clean_case_md_file.write_text(clean_markdown, encoding="utf-8")
        
        # Determine QA flags and Manual Review
        empty_pages = qa.get("empty_pages", [])
        suspicious_pages = qa.get("suspicious_low_text_pages", [])
        
        review_reasons = []
        if empty_pages:
            review_reasons.append(f"Has empty pages: {empty_pages}")
        if suspicious_pages:
            review_reasons.append(f"Has suspicious low-text pages: {suspicious_pages}")
        if len(full_text) < 500:
            review_reasons.append(f"Total character count is extremely low: {len(full_text)}")
            
        needs_review = 1 if review_reasons else 0
        review_reason = "; ".join(review_reasons) if review_reasons else None
        
        quality_flags = []
        if empty_pages:
            quality_flags.append("empty_pages")
        if suspicious_pages:
            quality_flags.append("suspicious_low_text")
        quality_flags_str = ",".join(quality_flags) if quality_flags else None
        
        # Compute baseline metrics (TTR and Shannon Entropy)
        ttr, entropy = _calculate_metrics(full_text)
        
        # Collect word counts for TF-IDF
        case_tokens = re.findall(r"[a-záéíóúüñ]{3,}", full_text.lower())
        case_filtered = [t for t in case_tokens if t not in SPANISH_STOPWORDS]
        
        term_counts = {}
        for t in case_filtered:
            term_counts[t] = term_counts.get(t, 0) + 1
            
        all_case_word_frequencies[case_id] = term_counts
        
        # Update Document Frequencies
        for term in term_counts.keys():
            document_frequencies[term] = document_frequencies.get(term, 0) + 1
            
        # Store table records
        cases_to_insert.append((
            case_id, sec_slug, subsec_id, folder_slug, resolved_title,
            resolved_start, resolved_end, len(cleaned_pages), len(full_text),
            str(meta.get("source_pdf") or ""), str(case_md_path), str(clean_case_md_file),
            str(qa_path), str(meta_path), meta.get("status", "success"),
            needs_review, review_reason
        ))
        
        qa_reports_to_insert.append((
            case_id,
            json.dumps(empty_pages),
            json.dumps(suspicious_pages),
            json.dumps(repeated_headers),
            json.dumps(repeated_footers),
            quality_flags_str
        ))
        
        case_texts_to_insert.append((case_id, raw_md, clean_markdown, full_text))
        
        case_metrics_to_insert.append((
            case_id, ttr, 10, entropy, 0.0, 0.0
        ))
        
    # Calculate and insert TF-IDF terms into 'concepts' table
    num_docs = len(discovered_folders)
    for case_id, term_counts in all_case_word_frequencies.items():
        total_terms = sum(term_counts.values())
        if total_terms == 0:
            continue
            
        case_tf_idf = []
        for term, count in term_counts.items():
            tf = count / total_terms
            df = document_frequencies.get(term, 0)
            idf = math.log(1.0 + num_docs / (1.0 + df))
            tfidf_score = tf * idf
            case_tf_idf.append((term, tfidf_score))
            
        case_tf_idf.sort(key=lambda x: x[1], reverse=True)
        top_concepts = case_tf_idf[:10]
        
        for term, score in top_concepts:
            concepts_to_insert.append((case_id, term, score, "tfidf"))
            
    # Insert in transaction
    cursor = conn.cursor()
    
    # Clear out any existing records
    cursor.execute("DELETE FROM llm_case_cards;")
    cursor.execute("DELETE FROM star_case_scores;")
    cursor.execute("DELETE FROM case_metrics;")
    cursor.execute("DELETE FROM concepts;")
    cursor.execute("DELETE FROM tags;")
    cursor.execute("DELETE FROM clusters;")
    cursor.execute("DELETE FROM embeddings;")
    cursor.execute("DELETE FROM case_texts;")
    cursor.execute("DELETE FROM qa_reports;")
    cursor.execute("DELETE FROM pages;")
    cursor.execute("DELETE FROM cases;")
    cursor.execute("DELETE FROM subsections;")
    cursor.execute("DELETE FROM sections;")
    
    # Insert sections
    cursor.executemany("""
    INSERT INTO sections (section_id, title, printed_start, printed_end)
    VALUES (?, ?, ?, ?);
    """, list(inserted_sections.values()))
    
    # Insert subsections
    cursor.executemany("""
    INSERT INTO subsections (subsection_id, section_id, slug, title, printed_start, printed_end)
    VALUES (?, ?, ?, ?, ?, ?);
    """, list(inserted_subsections.values()))
    
    # Insert cases
    cursor.executemany("""
    INSERT INTO cases (
        case_id, section_id, subsection_id, slug, title,
        printed_start, printed_end, page_count, total_chars,
        source_pdf, case_md_path, clean_case_md_path,
        qa_json_path, metadata_json_path, status,
        needs_manual_review, review_reason
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, cases_to_insert)
    
    # Insert pages
    cursor.executemany("""
    INSERT INTO pages (page_id, case_id, page_number, text, char_count)
    VALUES (?, ?, ?, ?, ?);
    """, pages_to_insert)
    
    # Insert QA
    cursor.executemany("""
    INSERT INTO qa_reports (case_id, empty_pages, suspicious_low_text_pages, repeated_headers, repeated_footers, quality_flags)
    VALUES (?, ?, ?, ?, ?, ?);
    """, qa_reports_to_insert)
    
    # Insert text
    cursor.executemany("""
    INSERT INTO case_texts (case_id, raw_markdown, clean_markdown, full_text)
    VALUES (?, ?, ?, ?);
    """, case_texts_to_insert)
    
    # Insert metrics
    cursor.executemany("""
    INSERT INTO case_metrics (case_id, lexical_diversity, tfidf_concept_count, concept_entropy, teaching_density_score, diversity_score)
    VALUES (?, ?, ?, ?, ?, ?);
    """, case_metrics_to_insert)
    
    # Insert concepts
    cursor.executemany("""
    INSERT INTO concepts (case_id, concept, score, source)
    VALUES (?, ?, ?, ?);
    """, concepts_to_insert)
    
    conn.commit()
    conn.close()
    
    # Compile registries and reports
    # 1. case_registry.jsonl and case_registry.csv
    registry_jsonl_path = curated_dir / "case_registry.jsonl"
    registry_csv_path = curated_dir / "case_registry.csv"
    
    registry_rows = []
    for c in cases_to_insert:
        # Columns: case_id, section_id, subsection_id, title, page_count, total_chars, clean_case_md_path, quality_flags, needs_manual_review
        c_id = c[0]
        # find matching qa
        q_flags = None
        for qr in qa_reports_to_insert:
            if qr[0] == c_id:
                q_flags = qr[5]
                break
                
        registry_rows.append({
            "case_id": c_id,
            "section_id": c[1],
            "subsection_id": c[2],
            "title": c[4],
            "page_count": c[7],
            "total_chars": c[8],
            "clean_case_md_path": c[11],
            "quality_flags": q_flags,
            "needs_manual_review": c[15]
        })
        
    with open(registry_jsonl_path, "w", encoding="utf-8") as f:
        for r in registry_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            
    with open(registry_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "case_id", "section_id", "subsection_id", "title", "page_count", 
            "total_chars", "clean_case_md_path", "quality_flags", "needs_manual_review"
        ])
        writer.writeheader()
        writer.writerows(registry_rows)
        
    # Get database size and top 20 lowest char cases
    db_size = output_db.stat().st_size if output_db.exists() else 0
    
    sorted_cases_by_char = sorted(cases_to_insert, key=lambda x: x[8])
    top_20_lowest = []
    for c in sorted_cases_by_char[:20]:
        top_20_lowest.append({
            "case_id": c[0],
            "section_id": c[1],
            "subsection_id": c[2],
            "title": c[4],
            "page_count": c[7],
            "total_chars": c[8],
            "needs_manual_review": c[15]
        })
        
    total_pages = sum(c[7] for c in cases_to_insert)
    total_chars = sum(c[8] for c in cases_to_insert)
    needs_review_count = sum(1 for c in cases_to_insert if c[15] == 1)
    
    report_data = {
        "total_cases_inserted": len(cases_to_insert),
        "total_pages_inserted": total_pages,
        "total_characters": total_chars,
        "sections_count": len(inserted_sections),
        "subsections_count": len(inserted_subsections),
        "cases_needing_manual_review": needs_review_count,
        "top_20_lowest_character_cases": top_20_lowest,
        "database_path": str(output_db),
        "database_size_bytes": db_size,
        "next_steps": "embeddings + clustering/silhouette analysis"
    }
    
    report_json_path = curated_dir / "database_build_report.json"
    report_json_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
    
    # format md report
    md_review_rows = []
    for c in cases_to_insert:
        if c[15] == 1:
            md_review_rows.append(f"| `{c[0]}` | `{c[1]}` | `{c[2]}` | {c[16]} |")
            
    md_review_table = "\n".join(md_review_rows) if md_review_rows else "| None | - | - | - |"
    
    md_lowest_rows = []
    for idx, c in enumerate(top_20_lowest):
        md_lowest_rows.append(f"| {idx+1} | `{c['case_id']}` | {c['total_chars']:,} | {c['page_count']} | {'Yes ⚠️' if c['needs_manual_review'] else 'No'} |")
        
    md_report = f"""# Database Build Report

This report summarizes the construction of the curated teaching clinical cases database from completed OCR outputs.

## Database Information
- **Database Path:** `{output_db}`
- **Database File Size:** `{db_size / (1024*1024):.2f} MB` ({db_size:,} bytes)
- **Status:** Complete & Ready

## High-Level Summary
- **Total Sections:** {len(inserted_sections)}
- **Total Subsections:** {len(inserted_subsections)}
- **Total Cases Inserted:** {len(cases_to_insert)}
- **Total Pages Inserted:** {total_pages}
- **Total Characters (Cleaned Text):** {total_chars:,}
- **Cases Needing Manual Review:** {needs_review_count}

---

## Top 20 Lowest Character-Count Cases
These cases are candidates for auditing or scanning review due to their small volume of text:

| Rank | Case ID | Characters | Pages | Needs Review |
|---|---|---|---|---|
{chr(10).join(md_lowest_rows)}

---

## Cases Needing Manual Review
The following cases have QA flags (empty pages, low-text pages) and should be inspected:

| Case ID | Section | Subsection | Reason |
|---|---|---|---|
{md_review_table}

---

## Next Steps Recommended
1. **Semantic Search & Vector Embeddings:** Load `data/clinical_cases.db` in Google Colab, generate embeddings using a multilingual model (e.g. `LaBSE` or `text-embedding-004`), and write them into the `embeddings` table.
2. **Clustering & Silhouette Analysis:** Run K-Means and compute Silhouette scores to cluster cases by clinical concept groupings.
3. **Teaching Star Selection:** Use LLM prompts to score teaching density and designate "star cases" per section.
"""
    
    report_md_path = curated_dir / "database_build_report.md"
    report_md_path.write_text(md_report, encoding="utf-8")
    
    return report_data
