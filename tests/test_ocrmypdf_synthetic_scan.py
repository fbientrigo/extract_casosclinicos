from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pypdf import PdfReader

from scanbook.ocr.ocrmypdf_backend import OcrmypdfBackend
from scanbook.qa import run_qa
from scanbook.synthetic_scan import create_synthetic_scanned_pdf

pytestmark = [
    pytest.mark.skipif(shutil.which("ocrmypdf") is None, reason="ocrmypdf executable not found"),
    pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract executable not found"),
]


def test_ocrmypdf_backend_on_synthetic_scanned_pdf(tmp_path: Path) -> None:
    input_pdf = tmp_path / "input.synthetic_scanned.pdf"
    output_pdf = tmp_path / "output.searchable.pdf"
    sidecar_txt = tmp_path / "output.sidecar.txt"
    output_jsonl = tmp_path / "pages.jsonl"
    qa_dir = tmp_path / "qa"

    create_synthetic_scanned_pdf(
        input_pdf,
        page_texts=[
            "Paciente adulto con fiebre y dolor toracico.",
            "Adult patient with dry cough and chest discomfort.",
        ],
    )

    backend = OcrmypdfBackend()
    results = backend.run(
        input_pdf=input_pdf,
        output_jsonl=output_jsonl,
        language=["eng", "spa"],
        profile="fast_latin",
        chapter_id="synthetic",
        output_pdf=output_pdf,
        sidecar_txt=sidecar_txt,
    )

    assert len(results) >= 2
    assert output_pdf.exists() and output_pdf.stat().st_size > 0
    assert sidecar_txt.exists() and sidecar_txt.stat().st_size > 0
    assert output_jsonl.exists() and output_jsonl.stat().st_size > 0

    sidecar_text = sidecar_txt.read_text(encoding="utf-8", errors="ignore").lower()
    for anchor in ["paciente", "adult", "cough"]:
        assert anchor in sidecar_text

    searchable_text = "\n".join((page.extract_text() or "") for page in PdfReader(str(output_pdf)).pages)
    assert searchable_text.strip()

    qa_summary = run_qa(input_jsonl=output_jsonl, report_dir=qa_dir)
    assert int(qa_summary["total_pages"]) >= 2
    assert (qa_dir / "qa_summary.json").exists()
