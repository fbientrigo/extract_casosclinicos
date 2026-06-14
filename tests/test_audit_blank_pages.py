from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import pytest
import sys
from PIL import Image

# Ensure project root is in path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from scripts.audit_blank_pages import get_ink_density, main


def test_get_ink_density(tmp_path: Path) -> None:
    # 1. Create a completely white image (all pixels 255)
    white_img_path = tmp_path / "white.png"
    white_img = Image.new("L", (100, 100), color=255)
    white_img.save(white_img_path)
    
    density = get_ink_density(white_img_path, threshold=250)
    assert density == 0.0

    # 2. Create an image with exactly 10% black pixels (value 0)
    spotted_img_path = tmp_path / "spotted.png"
    # Create white canvas, then paint 1000 out of 10000 pixels black
    spotted_img = Image.new("L", (100, 100), color=255)
    pixels = spotted_img.load()
    for y in range(10):
        for x in range(100):
            pixels[x, y] = 0
            
    spotted_img.save(spotted_img_path)
    density_spotted = get_ink_density(spotted_img_path, threshold=250)
    assert pytest.approx(density_spotted, abs=1e-5) == 0.1


def test_audit_execution_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Setup temporary directory structure to mimic the project structure
    db_path = tmp_path / "clinical_cases.db"
    registry_path = tmp_path / "case_registry.jsonl"
    ocr_root = tmp_path / "data/ocr_cases"
    book_root = tmp_path / "book"
    output_dir = tmp_path / "data/curated"

    ocr_root.mkdir(parents=True)
    book_root.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    # 1. Setup mock SQLite DB
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    # Create minimal cases and qa_reports tables
    cursor.execute("""
    CREATE TABLE cases (
        case_id TEXT PRIMARY KEY,
        section_id TEXT,
        subsection_id TEXT,
        slug TEXT,
        title TEXT,
        page_count INTEGER,
        source_pdf TEXT,
        case_md_path TEXT,
        clean_case_md_path TEXT,
        qa_json_path TEXT,
        metadata_json_path TEXT,
        status TEXT,
        needs_manual_review INTEGER,
        review_reason TEXT
    );
    """)
    cursor.execute("""
    CREATE TABLE qa_reports (
        case_id TEXT PRIMARY KEY,
        empty_pages TEXT,
        suspicious_low_text_pages TEXT,
        repeated_headers TEXT,
        repeated_footers TEXT,
        quality_flags TEXT
    );
    """)
    
    # Insert mock case 1: Page 1 empty, page_count = 3
    cursor.execute("""
    INSERT INTO cases (case_id, section_id, subsection_id, slug, title, page_count, source_pdf, status)
    VALUES ('101_mock_case_one', 'seccion1', 'seccion1/mock_sub', 'mock_case_one', 'Mock Case One', 3, 'seccion1/mock_sub/101_mock_case_one.pdf', 'success');
    """)
    cursor.execute("""
    INSERT INTO qa_reports (case_id, empty_pages, suspicious_low_text_pages, repeated_headers, repeated_footers, quality_flags)
    VALUES ('101_mock_case_one', '[1]', '[]', '[]', '[]', 'empty_pages');
    """)
    
    # Insert mock case 2: Page 3 (middle page) empty, page_count = 5
    cursor.execute("""
    INSERT INTO cases (case_id, section_id, subsection_id, slug, title, page_count, source_pdf, status)
    VALUES ('202_mock_case_two', 'seccion2', 'seccion2/mock_sub_two', 'mock_case_two', 'Mock Case Two', 5, 'seccion2/mock_sub_two/202_mock_case_two.pdf', 'success');
    """)
    cursor.execute("""
    INSERT INTO qa_reports (case_id, empty_pages, suspicious_low_text_pages, repeated_headers, repeated_footers, quality_flags)
    VALUES ('202_mock_case_two', '[3]', '[]', '[]', '[]', 'empty_pages');
    """)

    conn.commit()
    conn.close()

    # 2. Setup mock files under data/ocr_cases/
    # Case 1
    case1_dir = ocr_root / "seccion1" / "mock_sub" / "101_mock_case_one"
    case1_dir.mkdir(parents=True)
    (case1_dir / "case_metadata.json").write_text(json.dumps({
        "case_id": "101_mock_case_one",
        "section": "seccion1",
        "subsection": "mock_sub",
        "source_pdf": "seccion1/mock_sub/101_mock_case_one.pdf",
        "page_count": 3
    }), encoding="utf-8")
    (case1_dir / "qa.json").write_text(json.dumps({
        "empty_pages": [1],
        "suspicious_low_text_pages": []
    }), encoding="utf-8")
    (case1_dir / "pages.jsonl").write_text(
        json.dumps({"page_num": 1, "text": ""}) + "\n" +
        json.dumps({"page_num": 2, "text": "Substantial text for second page that exceeds three hundred characters to satisfy substantial next page heuristic."}) + "\n" +
        json.dumps({"page_num": 3, "text": "Some text for third page."}) + "\n",
        encoding="utf-8"
    )

    # Case 2
    case2_dir = ocr_root / "seccion2" / "mock_sub_two" / "202_mock_case_two"
    case2_dir.mkdir(parents=True)
    (case2_dir / "case_metadata.json").write_text(json.dumps({
        "case_id": "202_mock_case_two",
        "section": "seccion2",
        "subsection": "mock_sub_two",
        "source_pdf": "seccion2/mock_sub_two/202_mock_case_two.pdf",
        "page_count": 5
    }), encoding="utf-8")
    (case2_dir / "qa.json").write_text(json.dumps({
        "empty_pages": [3],
        "suspicious_low_text_pages": []
    }), encoding="utf-8")
    (case2_dir / "pages.jsonl").write_text(
        json.dumps({"page_num": 1, "text": "Page 1 content"}) + "\n" +
        json.dumps({"page_num": 2, "text": "Page 2 content"}) + "\n" +
        json.dumps({"page_num": 3, "text": ""}) + "\n" +
        json.dumps({"page_num": 4, "text": "Page 4 content"}) + "\n" +
        json.dumps({"page_num": 5, "text": "Page 5 content"}) + "\n",
        encoding="utf-8"
    )

    # 3. Create dummy PDF files so split PDF checks succeed
    pdf1 = book_root / "seccion1" / "mock_sub" / "101_mock_case_one.pdf"
    pdf1.parent.mkdir(parents=True, exist_ok=True)
    pdf1.touch()

    pdf2 = book_root / "seccion2" / "mock_sub_two" / "202_mock_case_two.pdf"
    pdf2.parent.mkdir(parents=True, exist_ok=True)
    pdf2.touch()

    # Mock `render_pages` in `scripts.audit_blank_pages` to return a mock PNG file
    def mock_render_pages(input_pdf: Path, output_dir: Path, pages_spec: str, dpi: int = 144, contact_sheet: bool = False) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        # Create a mock white image for page spec
        p_num = int(pages_spec)
        img_path = output_dir / f"page_{p_num:04d}.png"
        
        # If it's case 2 (middle page 3), let's draw some black spots to test OCR failure heuristic
        if "202_mock_case_two" in str(output_dir):
            img = Image.new("L", (100, 100), color=255)
            pixels = img.load()
            for y in range(20):
                for x in range(100):
                    pixels[x, y] = 0
            img.save(img_path)
        else:
            img = Image.new("L", (100, 100), color=255)
            img.save(img_path)
            
        return [img_path]

    monkeypatch.setattr("scripts.audit_blank_pages.render_pages", mock_render_pages)

    # 4. Mock sys.argv to point to our temp files
    args = [
        "audit_blank_pages.py",
        "--db-path", str(db_path),
        "--registry-path", str(registry_path),
        "--ocr-root", str(ocr_root),
        "--book-root", str(book_root),
        "--output-dir", str(output_dir)
    ]
    monkeypatch.setattr(sys, "argv", args)

    # 5. Run main
    exit_code = main()
    assert exit_code == 0

    # 6. Verify outputs exist
    json_path = output_dir / "blank_page_audit.json"
    md_path = output_dir / "blank_page_audit.md"
    assert json_path.exists()
    assert md_path.exists()

    # Load and check JSON structure
    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["total_flagged_cases"] == 2
    assert report["total_flagged_pages"] == 2

    # Case 1 (101_mock_case_one, page 1) is empty (white png, low density), is_first_page = True
    c1 = next(r for r in report["audit_records"] if r["case_id"] == "101_mock_case_one")
    assert c1["likely_reason"] == "expected_blank_separator"
    assert c1["recommended_action"] == "safe_to_ignore_blank_separator"
    assert c1["ink_density"] == 0.0

    # Case 2 (202_mock_case_two, page 3) is a middle page, spotted png (10% black, ink density = 0.20)
    c2 = next(r for r in report["audit_records"] if r["case_id"] == "202_mock_case_two")
    assert c2["likely_reason"] == "possible_ocr_failure"
    assert c2["recommended_action"] == "rerun_ocr_page_or_case"
    assert c2["ink_density"] == 0.20

    # Check that PNGs are correctly renamed to page_N.png
    png1 = output_dir / "blank_page_audit" / "101_mock_case_one" / "page_1.png"
    png2 = output_dir / "blank_page_audit" / "202_mock_case_two" / "page_3.png"
    assert png1.exists()
    assert png2.exists()
