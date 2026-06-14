from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from scanbook.synthetic_scan import create_synthetic_scanned_pdf


def test_create_synthetic_scanned_pdf_is_image_only(tmp_path: Path) -> None:
    output_pdf = tmp_path / "synthetic_scanned.pdf"
    create_synthetic_scanned_pdf(
        output_pdf,
        page_texts=[
            "Paciente adulto con dolor toracico y fiebre.",
            "Adult patient with cough and chest pain.",
        ],
    )

    reader = PdfReader(str(output_pdf))
    assert len(reader.pages) == 2
    extracted = [str(page.extract_text() or "").strip() for page in reader.pages]
    assert extracted == ["", ""]
