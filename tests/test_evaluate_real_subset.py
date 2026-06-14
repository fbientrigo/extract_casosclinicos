from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

from scanbook.synthetic_scan import create_synthetic_scanned_pdf
from scanbook.utils import read_jsonl

pytestmark = [
    pytest.mark.skipif(shutil.which("ocrmypdf") is None, reason="ocrmypdf executable not found"),
    pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract executable not found"),
]


def test_evaluate_real_subset_synthetic_run(tmp_path: Path) -> None:
    input_pdf = tmp_path / "input.synthetic.pdf"
    work_dir = tmp_path / "work_dir"
    
    # Create a 3-page synthetic scanned PDF
    create_synthetic_scanned_pdf(
        input_pdf,
        page_texts=[
            "First page of synthetic academic text.",
            "Second page with some tables and text.",
            "Third page of case notes with severe layout issues.",
        ],
    )
    
    # We will evaluate page 1 and page 3 (skipping page 2)
    # This verifies that mapping maps physical page 2 of subset back to physical page 3 of input!
    cmd = [
        sys.executable,
        "scripts/evaluate_real_subset.py",
        "--input-pdf",
        str(input_pdf),
        "--pages",
        "1,3",
        "--book-id",
        "testbook123",
        "--work-dir",
        str(work_dir),
        "--lang",
        "eng",
        "--lang",
        "spa",
        "--dpi",
        "150",
        "--profile",
        "fast_latin",
    ]
    
    # Run the script as a subprocess to verify CLI interface
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Script failed with stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    
    # Verify outputs
    searchable_pdf = work_dir / "subset_searchable.pdf"
    sidecar_txt = work_dir / "subset_sidecar.txt"
    pages_jsonl = work_dir / "subset_pages.jsonl"
    manifest_json = work_dir / "manifest.json"
    contact_sheet = work_dir / "contact_sheet.png"
    qa_json = work_dir / "qa" / "qa_summary.json"
    qa_md = work_dir / "qa" / "qa_summary.md"
    
    assert searchable_pdf.exists() and searchable_pdf.stat().st_size > 0
    assert sidecar_txt.exists() and sidecar_txt.stat().st_size > 0
    assert pages_jsonl.exists() and pages_jsonl.stat().st_size > 0
    assert manifest_json.exists() and manifest_json.stat().st_size > 0
    assert contact_sheet.exists() and contact_sheet.stat().st_size > 0
    assert qa_json.exists() and qa_json.stat().st_size > 0
    assert qa_md.exists() and qa_md.stat().st_size > 0
    
    # Read manifest and check fields
    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    assert manifest["book_id"] == "testbook123"
    assert manifest["pages_spec"] == "1,3"
    assert manifest["selected_pages"] == [1, 3]
    assert manifest["languages"] == ["eng", "spa"]
    assert manifest["ocr_profile"] == "fast_latin"
    assert "source_sha256" in manifest
    assert manifest["docling_comparison_slot"] is None
    
    # Verify page mapping in subset_pages.jsonl
    records = read_jsonl(pages_jsonl)
    assert len(records) == 2
    
    # Physical page 1 in subset maps to original page 1
    assert records[0]["page_num"] == 1
    assert records[0]["metadata"]["subset_index"] == 1
    
    # Physical page 2 in subset maps to original page 3
    assert records[1]["page_num"] == 3
    assert records[1]["metadata"]["subset_index"] == 2
    
    # Validate searchable PDF content via PdfReader
    reader = PdfReader(str(searchable_pdf))
    assert len(reader.pages) == 2
    
    # Check that stdout has evaluation summary
    assert "SUBSET EVALUATION COMPLETE SUMMARY" in result.stdout
    assert "Page-by-Page Character Counts" in result.stdout
    assert "Anomalies & Alerts" in result.stdout
    assert "Output Files Path Map" in result.stdout


def test_evaluate_real_subset_bounds_checking(tmp_path: Path) -> None:
    input_pdf = tmp_path / "input.synthetic.pdf"
    work_dir = tmp_path / "work_dir"
    
    create_synthetic_scanned_pdf(
        input_pdf,
        page_texts=["Single page PDF."],
    )
    
    # Try out of bounds page (2) on 1-page PDF
    cmd = [
        sys.executable,
        "scripts/evaluate_real_subset.py",
        "--input-pdf",
        str(input_pdf),
        "--pages",
        "1,2",
        "--book-id",
        "testbook_err",
        "--work-dir",
        str(work_dir),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0
    assert "is out of bounds" in result.stderr
