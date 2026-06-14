from __future__ import annotations

import json
import sys
from pathlib import Path
import pytest
from pypdf import PdfWriter

# Add project root and scripts to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from scripts.audit_digital_pdf_text_layer import main

def create_valid_dummy_pdf(dest_path: Path, pages_count: int = 2) -> None:
    writer = PdfWriter()
    for _ in range(pages_count):
        writer.add_blank_page(width=612, height=792)  # Letter size
    ensure_parent_dir(dest_path)
    with dest_path.open("wb") as f:
        writer.write(f)

def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def test_audit_digital_pdf_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. Setup temporary directories mimicking the workspace
    book_id = "test_ophthalmology_2026"
    book_dir = tmp_path / "book" / book_id
    pdf_path = book_dir / "2026_test_casosclinicos.pdf"
    
    # Create valid 3-page dummy PDF
    create_valid_dummy_pdf(pdf_path, pages_count=3)
    
    # Define custom audit output dir
    output_dir = tmp_path / "data/audits" / book_id
    
    # 2. Mock sys.argv
    args = [
        "audit_digital_pdf_text_layer.py",
        "--book-id", book_id,
        "--sample-pages", "2",
        "--output-dir", str(output_dir)
    ]
    
    # We monkeypatch the project_root variable inside the script to use our tmp_path
    monkeypatch.setattr("scripts.audit_digital_pdf_text_layer.project_root", tmp_path)
    monkeypatch.setattr(sys, "argv", args)
    
    # 3. Execute main audit script
    exit_code = main()
    assert exit_code == 0
    
    # 4. Verify output files are produced
    json_report_path = output_dir / "text_layer_audit.json"
    md_report_path = output_dir / "text_layer_audit.md"
    renders_dir = output_dir / "page_renders"
    
    assert json_report_path.exists()
    assert md_report_path.exists()
    assert renders_dir.exists()
    
    # 5. Validate JSON Structure and Path Resolution
    report = json.loads(json_report_path.read_text(encoding="utf-8"))
    
    # Verify Summary Section
    assert "summary" in report
    summary = report["summary"]
    assert summary["book_id"] == book_id
    assert summary["source_pdf"] == "2026_test_casosclinicos.pdf"
    assert summary["total_pages_in_pdf"] == 3
    assert summary["pages_audited_count"] == 2
    assert "recommended_ingestion_mode" in summary
    assert "vision_rag_recommended" in summary
    
    # Verify Pages audit records
    assert "pages" in report
    pages = report["pages"]
    assert len(pages) == 2
    
    for page_record in pages:
        assert "page_number" in page_record
        assert "character_count" in page_record
        assert "embedded_images_count" in page_record
        assert "text_excerpt" in page_record
        assert "render_path" in page_record
        assert "warnings" in page_record
        
        # Verify rendered image exists
        page_num = page_record["page_number"]
        render_path = renders_dir / f"page_{page_num}.png"
        assert render_path.exists()
