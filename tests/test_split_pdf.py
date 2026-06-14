from __future__ import annotations

from pathlib import Path

from scanbook.split_pdf import split_pdf_by_ranges


def test_split_pdf_by_ranges(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    src = tmp_path / "source.pdf"
    pdf = PdfWriter()
    for _ in range(6):
        pdf.add_blank_page(width=612, height=792)
    with src.open("wb") as f:
        pdf.write(f)

    chapters = [
        {"chapter_id": "ch01", "start_page": 1, "end_page": 2, "title": "A"},
        {"chapter_id": "ch02", "start_page": 3, "end_page": 6, "title": "B"},
    ]
    out_dir = tmp_path / "chapters"
    manifest = split_pdf_by_ranges(
        input_pdf=src,
        chapters=chapters,
        output_dir=out_dir,
        source_hash="dummyhash",
    )

    assert len(manifest) == 2
    assert (out_dir / "ch01.pdf").exists()
    assert (out_dir / "ch02.pdf").exists()
    assert manifest[0]["start_page_physical"] == 1
    assert manifest[1]["end_page_physical"] == 6
