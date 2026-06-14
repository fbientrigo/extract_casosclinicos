from __future__ import annotations

import json
from pathlib import Path
import pytest
import sys
import os

from scripts.ocr_split_cases import discover_cases, main


def test_discover_cases(tmp_path: Path) -> None:
    # Set up synthetic split case PDF directories
    input_root = tmp_path / "book"
    output_root = tmp_path / "data/ocr_cases"
    
    sec2_dir = input_root / "seccion2"
    subsec_dir = sec2_dir / "anemias_microciticas"
    subsec_dir.mkdir(parents=True)
    
    # Create section level PDF (should be ignored)
    section_pdf = sec2_dir / "section2.pdf"
    section_pdf.touch()
    
    # Create subsection case PDFs (should be discovered)
    case1_pdf = subsec_dir / "112_anemia_ferropiva.pdf"
    case1_pdf.touch()
    case2_pdf = subsec_dir / "117_anemia_de_enfermedades_cronicas.pdf"
    case2_pdf.touch()
    
    # Create non-pdf file (should be ignored)
    txt_file = subsec_dir / "121_notes.txt"
    txt_file.touch()
    
    # Run discovery
    cases = discover_cases(
        input_root=input_root,
        output_root=output_root,
        section_filter=None,
        subsection_filter=None,
        case_glob="*.pdf",
        force=False
    )
    
    assert len(cases) == 2
    case_ids = [c["case_file_stem"] for c in cases]
    assert "112_anemia_ferropiva" in case_ids
    assert "117_anemia_de_enfermedades_cronicas" in case_ids
    assert all(c["section"] == "seccion2" for c in cases)
    assert all(c["subsection"] == "anemias_microciticas" for c in cases)
    
    # Test printed start page inference
    c1 = next(c for c in cases if c["case_file_stem"] == "112_anemia_ferropiva")
    assert c1["printed_start_page"] == 112
    assert c1["title_slug"] == "anemia_ferropiva"


def test_dryrun_manifest_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Setup directories
    input_root = tmp_path / "book"
    output_root = tmp_path / "data/ocr_cases"
    
    subsec_dir = input_root / "seccion2" / "anemias_microciticas"
    subsec_dir.mkdir(parents=True)
    (subsec_dir / "112_anemia_ferropiva.pdf").touch()
    
    # Mock sys.argv
    args = [
        "ocr_split_cases.py",
        "--book-id", "test_book",
        "--input-root", str(input_root),
        "--output-root", str(output_root),
        "--dry-run"
    ]
    monkeypatch.setattr(sys, "argv", args)
    
    exit_code = main()
    assert exit_code == 0
    
    manifest_path = output_root / "ocr_cases_dryrun_manifest.json"
    assert manifest_path.exists()
    
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "generated_at" in manifest
    assert len(manifest["cases"]) == 1
    c = manifest["cases"][0]
    assert c["case_id"] == "112_anemia_ferropiva"
    assert c["will_skip"] is False


def test_skip_completed_cases(tmp_path: Path) -> None:
    input_root = tmp_path / "book"
    output_root = tmp_path / "data/ocr_cases"
    
    subsec_dir = input_root / "seccion2" / "anemias_microciticas"
    subsec_dir.mkdir(parents=True)
    (subsec_dir / "112_anemia_ferropiva.pdf").touch()
    
    # Create fake completed outputs
    output_dir = output_root / "seccion2" / "anemias_microciticas" / "112_anemia_ferropiva"
    output_dir.mkdir(parents=True)
    
    for f_name in ["ocr.pdf", "sidecar.txt", "pages.jsonl", "case.md", "qa.json", "qa.md"]:
        (output_dir / f_name).touch()
        
    # Write success case_metadata.json
    (output_dir / "case_metadata.json").write_text(
        json.dumps({"case_id": "112_anemia_ferropiva", "status": "success"}), encoding="utf-8"
    )
    
    # Run discovery without force
    cases = discover_cases(
        input_root=input_root,
        output_root=output_root,
        section_filter=None,
        subsection_filter=None,
        case_glob="*.pdf",
        force=False
    )
    assert cases[0]["will_skip"] is True
    assert cases[0]["skip_reason"] == "already_completed"
    
    # Run discovery with force
    cases_force = discover_cases(
        input_root=input_root,
        output_root=output_root,
        section_filter=None,
        subsection_filter=None,
        case_glob="*.pdf",
        force=True
    )
    assert cases_force[0]["will_skip"] is False
    assert cases_force[0]["skip_reason"] == ""


def test_case_md_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # This tests the output formatting structure of case.md and case_metadata.json
    input_root = tmp_path / "book"
    output_root = tmp_path / "data/ocr_cases"
    
    subsec_dir = input_root / "seccion2" / "anemias_microciticas"
    subsec_dir.mkdir(parents=True)
    (subsec_dir / "112_anemia_ferropiva.pdf").touch()
    
    # We mock Backend.run and run_qa so we don't need real PDF or OCRmyPDF installation
    class MockBackend:
        def run(self, input_pdf, output_jsonl, language, profile, chapter_id, output_pdf, sidecar_txt):
            # Create dummy output files
            output_pdf.touch()
            sidecar_txt.touch()
            # Write two dummy pages to pages.jsonl
            pages = [
                {"page_num": 1, "text": "Page 1 Content here", "extractor": "ocrmypdf"},
                {"page_num": 2, "text": "Page 2 Content here", "extractor": "ocrmypdf"},
            ]
            with open(output_jsonl, "w", encoding="utf-8") as f:
                for p in pages:
                    f.write(json.dumps(p) + "\n")
            return []

    def mock_run_qa(input_jsonl, report_dir):
        # Create dummy qa_summary.json and qa_summary.md
        (report_dir / "qa_summary.json").write_text(json.dumps({
            "empty_pages": [],
            "suspicious_low_text_pages": [],
            "repeated_headers": [],
            "repeated_footers": []
        }), encoding="utf-8")
        (report_dir / "qa_summary.md").write_text("# Mock QA", encoding="utf-8")
        return {}

    monkeypatch.setattr("scripts.ocr_split_cases.OcrmypdfBackend", MockBackend)
    monkeypatch.setattr("scripts.ocr_split_cases.run_qa", mock_run_qa)
    
    # Mock sys.argv to execute
    args = [
        "ocr_split_cases.py",
        "--book-id", "test_book",
        "--input-root", str(input_root),
        "--output-root", str(output_root),
        "--execute",
        "--limit", "1"
    ]
    monkeypatch.setattr(sys, "argv", args)
    
    exit_code = main()
    assert exit_code == 0
    
    output_dir = output_root / "seccion2" / "anemias_microciticas" / "112_anemia_ferropiva"
    assert output_dir.exists()
    
    case_md_path = output_dir / "case.md"
    assert case_md_path.exists()
    
    md_content = case_md_path.read_text(encoding="utf-8")
    # Verify frontmatter formatting
    assert "section: seccion2" in md_content
    assert "subsection: anemias_microciticas" in md_content
    assert "case_id: 112_anemia_ferropiva" in md_content
    assert "ocr_engine: ocrmypdf" in md_content
    assert "languages: [spa, eng]" in md_content
    assert "printed_start_page: 112" in md_content
    
    # Verify title & text formatting
    assert "# 112 Anemia ferropiva" in md_content
    assert "## Page 1" in md_content
    assert "Page 1 Content here" in md_content
    assert "## Page 2" in md_content
    assert "Page 2 Content here" in md_content
    
    # Verify metadata formatting
    meta_path = output_dir / "case_metadata.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["case_id"] == "112_anemia_ferropiva"
    assert meta["page_count"] == 2
    assert meta["status"] == "success"


def test_section_all_discovery(tmp_path: Path) -> None:
    input_root = tmp_path / "book"
    output_root = tmp_path / "data/ocr_cases"
    
    # Create section 1 and 2
    (input_root / "seccion1" / "subsec1").mkdir(parents=True)
    (input_root / "seccion2" / "subsec2").mkdir(parents=True)
    
    # Create section level PDFs (ignored)
    (input_root / "seccion1" / "section1.pdf").touch()
    (input_root / "seccion2" / "section2.pdf").touch()
    
    # Create case PDFs (discovered)
    (input_root / "seccion1" / "subsec1" / "101_case1.pdf").touch()
    (input_root / "seccion2" / "subsec2" / "201_case2.pdf").touch()
    
    # Create generated OCR PDF in subsection (ignored)
    (input_root / "seccion2" / "subsec2" / "ocr.pdf").touch()
    
    # Create non-pdf file (ignored)
    (input_root / "seccion1" / "subsec1" / "notes.txt").touch()
    
    # Run discovery for all
    cases = discover_cases(
        input_root=input_root,
        output_root=output_root,
        section_filter="all",
        subsection_filter=None,
        case_glob="*.pdf",
        force=False
    )
    
    assert len(cases) == 2
    stems = [c["case_file_stem"] for c in cases]
    assert "101_case1" in stems
    assert "201_case2" in stems
    assert "section1" not in stems
    assert "ocr" not in stems


def test_global_summary_generation_and_rebuild(tmp_path: Path) -> None:
    input_root = tmp_path / "book"
    output_root = tmp_path / "data/ocr_cases"
    
    # Create 3 cases in book
    (input_root / "seccion1" / "subsec1").mkdir(parents=True)
    (input_root / "seccion1" / "subsec1" / "101_case1.pdf").touch()
    (input_root / "seccion1" / "subsec1" / "102_case2.pdf").touch()
    (input_root / "seccion1" / "subsec1" / "103_case3.pdf").touch()
    
    # Setup outputs:
    # 1. 101_case1: success
    out1 = output_root / "seccion1" / "subsec1" / "101_case1"
    out1.mkdir(parents=True)
    (out1 / "case_metadata.json").write_text(json.dumps({
        "case_id": "101_case1",
        "status": "success",
        "page_count": 5
    }), encoding="utf-8")
    (out1 / "sidecar.txt").write_text("Hello OCR world!", encoding="utf-8") # 16 chars
    (out1 / "qa.json").write_text(json.dumps({
        "empty_pages": [2],
        "suspicious_low_text_pages": []
    }), encoding="utf-8")
    
    # 2. 102_case2: failed
    out2 = output_root / "seccion1" / "subsec1" / "102_case2"
    out2.mkdir(parents=True)
    (out2 / "case_metadata.json").write_text(json.dumps({
        "case_id": "102_case2",
        "status": "failed",
        "error": "OCR engine crashed"
    }), encoding="utf-8")
    
    # 3. 103_case3: pending (no metadata)
    out3 = output_root / "seccion1" / "subsec1" / "103_case3"
    out3.mkdir(parents=True)
    
    # Write execute manifest marking 101_case1 as newly processed
    (output_root / "ocr_cases_execute_manifest.json").write_text(json.dumps({
        "newly_processed_case_ids": ["101_case1"],
        "cases": []
    }), encoding="utf-8")
    
    # Run build_global_summary (from scripts.ocr_split_cases)
    from scripts.ocr_split_cases import build_global_summary
    summary, md = build_global_summary(input_root, output_root)
    
    assert summary["total_discovered_cases"] == 3
    assert summary["newly_processed_cases"] == 1
    assert summary["already_completed_skipped_cases"] == 0
    assert summary["failed_cases"] == 1
    assert summary["total_pages_processed"] == 5
    assert summary["total_ocr_characters"] == 16
    assert summary["cases_with_empty_pages"] == 1
    assert len(summary["failed_case_list"]) == 1
    assert summary["failed_case_list"][0]["case_id"] == "102_case2"
    assert "OCR engine crashed" in summary["failed_case_list"][0]["error"]
    assert "retry_command" in summary["failed_case_list"][0]
    
    # Verify Markdown contains metrics
    assert "**Total Discovered Cases** | 3" in md
    assert "**Failed Cases** | 1" in md
    assert "OCR engine crashed" in md

