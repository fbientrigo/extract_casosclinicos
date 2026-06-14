from __future__ import annotations

import json
import sqlite3
import csv
import yaml
from pathlib import Path
import pytest

from scanbook.db import build_cases_db, init_db, _clean_page_text, _calculate_metrics

def test_sqlite_schema_creation(tmp_path: Path) -> None:
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(db_file)
    init_db(conn)
    
    # Check that all 13 tables are created
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    
    expected_tables = {
        "sections", "subsections", "cases", "pages", "qa_reports", 
        "case_texts", "embeddings", "clusters", "tags", "concepts", 
        "case_metrics", "star_case_scores", "llm_case_cards"
    }
    
    # Check intersection and subset
    for t in expected_tables:
        assert t in tables, f"Expected table '{t}' was not found in SQLite master."
        
    conn.close()

def test_page_text_cleaning() -> None:
    raw_text = (
        "SECCIÓN I: BIOQUÍMICA CLÍNICA\n"
        "\n"
        "Caso problema 3\n"
        "Patricia, de 29 años, es aficionada al running.\n"
        "\n"
        "43\n"
    )
    repeated_headers = ["sección |: bioquímica clínica"]
    repeated_footers = ["43"]
    
    cleaned = _clean_page_text(raw_text, repeated_headers, repeated_footers)
    
    # Header and footer should be stripped, body should be intact
    assert "sección |: bioquímica clínica" not in cleaned.lower()
    assert "43" not in cleaned
    assert "Caso problema 3" in cleaned
    assert "Patricia, de 29 años, es aficionada al running." in cleaned

def test_calculate_metrics() -> None:
    text = "Patricia running. Patricia running. Patricia running."
    ttr, entropy = _calculate_metrics(text)
    
    assert ttr > 0.0
    assert entropy > 0.0
    
    # Empty text handles gracefully
    ttr_empty, entropy_empty = _calculate_metrics("")
    assert ttr_empty == 0.0
    assert entropy_empty == 0.0

def test_build_cases_db_integration(tmp_path: Path) -> None:
    ocr_dir = tmp_path / "ocr_cases"
    manifest_path = tmp_path / "manifest.yaml"
    db_file = tmp_path / "clinical_cases.db"
    curated_dir = tmp_path / "curated"
    
    ocr_dir.mkdir()
    
    # Create fake completed case folder structure
    case_folder_name = "43_hiponatremia"
    case_dir = ocr_dir / "seccion1" / "equilibrio_electrolitico_y_acido_base" / case_folder_name
    case_dir.mkdir(parents=True)
    
    # Write synthetic case metadata
    meta = {
        "case_id": case_folder_name,
        "section": "seccion1",
        "subsection": "equilibrio_electrolitico_y_acido_base",
        "source_pdf": "seccion1/equilibrio_electrolitico_y_acido_base/43_hiponatremia.pdf",
        "status": "success",
        "page_count": 2
    }
    (case_dir / "case_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    
    # Write synthetic source manifest
    source_manifest = {
        "source_pdf": "synthetic_clinical_cases.pdf",
        "page_range": [44, 48]
    }
    (case_dir / "source_manifest.json").write_text(json.dumps(source_manifest), encoding="utf-8")
    
    # Write synthetic pages.jsonl
    pages = [
        {"page_num": 1, "text": "SECCIÓN I: BIOQUÍMICA CLÍNICA\n\nCaso 3\nPatricia running.\n" + "Patricia running to keep in shape and manage stress. She runs three times per week, 10 kilometers each time. Today she decided to participate in a marathon. She is extremely motivated and prepared. " * 5 + "\n\n43", "extractor": "ocrmypdf"},
        {"page_num": 2, "text": "BIOQUÍMICA CLÍNICA: CASOS PROBLEMA\n\nPreguntas y respuestas.\n" + "This is a very long clinical case analysis containing many questions and answers about biochemistry, lab methods, ion selective electrodes, and patient diagnosis. We need this text to be longer than 500 characters to pass the manual review character check. " * 5 + "\n\n44", "extractor": "ocrmypdf"}
    ]
    (case_dir / "pages.jsonl").write_text("".join(json.dumps(p) + "\n" for p in pages), encoding="utf-8")
    
    # Write synthetic case.md
    case_md_content = (
        "---\n"
        "section: seccion1\n"
        "subsection: equilibrio_electrolitico_y_acido_base\n"
        "case_id: 43_hiponatremia\n"
        "---\n\n"
        "# 43 Hiponatremia\n\n"
        "## Page 1\n"
        "SECCIÓN I: BIOQUÍMICA CLÍNICA\n\nCaso 3\nPatricia running.\n" + "Patricia running to keep in shape and manage stress. She runs three times per week, 10 kilometers each time. Today she decided to participate in a marathon. She is extremely motivated and prepared. " * 5 + "\n\n43\n\n"
        "## Page 2\n"
        "BIOQUÍMICA CLÍNICA: CASOS PROBLEMA\n\nPreguntas y respuestas.\n" + "This is a very long clinical case analysis containing many questions and answers about biochemistry, lab methods, ion selective electrodes, and patient diagnosis. We need this text to be longer than 500 characters to pass the manual review character check. " * 5 + "\n\n44\n"
    )
    (case_dir / "case.md").write_text(case_md_content, encoding="utf-8")
    
    # Write synthetic qa.json
    qa = {
        "total_pages": 2,
        "empty_pages": [],
        "suspicious_low_text_pages": [],
        "repeated_headers": [{"line": "SECCIÓN I: BIOQUÍMICA CLÍNICA", "count": 3}, {"line": "BIOQUÍMICA CLÍNICA: CASOS PROBLEMA", "count": 3}],
        "repeated_footers": [{"line": "43", "count": 3}, {"line": "44", "count": 3}]
    }
    (case_dir / "qa.json").write_text(json.dumps(qa), encoding="utf-8")
    
    # Write synthetic sidecar.txt
    sidecar_content = (
        "SECCIÓN I: BIOQUÍMICA CLÍNICA\n\nCaso 3\nPatricia running.\n" + 
        "Patricia running to keep in shape and manage stress. She runs three times per week, 10 kilometers each time. Today she decided to participate in a marathon. She is extremely motivated and prepared. " * 5 + "\n\n43\n\n"
        "BIOQUÍMICA CLÍNICA: CASOS PROBLEMA\n\nPreguntas y respuestas.\n" + 
        "This is a very long clinical case analysis containing many questions and answers about biochemistry, lab methods, ion selective electrodes, and patient diagnosis. We need this text to be longer than 500 characters to pass the manual review character check. " * 5 + "\n\n44"
    )
    (case_dir / "sidecar.txt").write_text(sidecar_content, encoding="utf-8")
    
    # 2. Write synthetic manifest
    manifest_data = {
        "sections": [
            {
                "title": "SECCIÓN I. BIOQUÍMICA CLÍNICA",
                "number": 1,
                "slug": "seccion1",
                "printed_start": 29,
                "printed_end": 53,
                "subsections": [
                    {
                        "title": "Equilibrio electrolítico y ácido-base",
                        "slug": "equilibrio_electrolitico_y_acido_base",
                        "printed_start": 43,
                        "printed_end": 53,
                        "cases": [
                            {
                                "title": "Hiponatremia",
                                "slug": "hiponatremia",
                                "printed_start": 43,
                                "printed_end": 47
                            }
                        ]
                    }
                ]
            }
        ]
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest_data, f)
        
    # 3. Execute database build
    report = build_cases_db(
        ocr_cases_dir=ocr_dir,
        manifest_path=manifest_path,
        output_db=db_file,
        curated_dir=curated_dir
    )
    
    # Assert report data
    assert report["total_cases_inserted"] == 1
    assert report["total_pages_inserted"] == 2
    assert report["sections_count"] == 1
    assert report["subsections_count"] == 1
    assert report["cases_needing_manual_review"] == 0
    
    # Assert database exists and contains expected data
    assert db_file.exists()
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    # Check section title resolved from manifest
    cursor.execute("SELECT title FROM sections WHERE section_id='seccion1';")
    sec_title = cursor.fetchone()[0]
    assert sec_title == "SECCIÓN I. BIOQUÍMICA CLÍNICA"
    
    # Check subsection title resolved from manifest
    cursor.execute("SELECT title FROM subsections WHERE subsection_id='seccion1/equilibrio_electrolitico_y_acido_base';")
    subsec_title = cursor.fetchone()[0]
    assert subsec_title == "Equilibrio electrolítico y ácido-base"
    
    # Check case resolved title and printed end page
    cursor.execute("SELECT title, printed_end, needs_manual_review FROM cases WHERE case_id='43_hiponatremia';")
    c_title, c_end, c_review = cursor.fetchone()
    assert c_title == "Hiponatremia"
    assert c_end == 47
    assert c_review == 0
    
    # Check cleaned text strips repeated headers and footers
    cursor.execute("SELECT text FROM pages WHERE page_id='43_hiponatremia/page_1';")
    cleaned_p1_text = cursor.fetchone()[0]
    assert "SECCIÓN I: BIOQUÍMICA CLÍNICA" not in cleaned_p1_text
    assert "43" not in cleaned_p1_text
    assert "Caso 3" in cleaned_p1_text
    
    # Check concepts computed from TF-IDF
    cursor.execute("SELECT concept FROM concepts WHERE case_id='43_hiponatremia';")
    concepts = [row[0] for row in cursor.fetchall()]
    assert "patricia" in concepts
    assert "running" in concepts
    
    conn.close()
    
    # Check curation outputs
    assert (curated_dir / "case_registry.jsonl").exists()
    assert (curated_dir / "case_registry.csv").exists()
    assert (curated_dir / "database_build_report.json").exists()
    assert (curated_dir / "database_build_report.md").exists()
    assert (curated_dir / "clean_cases" / "seccion1" / "equilibrio_electrolitico_y_acido_base" / "43_hiponatremia" / "clean_case.md").exists()
    
    # Verify CSV file layout
    with open(curated_dir / "case_registry.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["case_id"] == "43_hiponatremia"
        assert rows[0]["title"] == "Hiponatremia"
        assert rows[0]["page_count"] == "2"
