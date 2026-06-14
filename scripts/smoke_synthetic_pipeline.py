from __future__ import annotations

import json
import tempfile
from pathlib import Path

from pypdf import PdfWriter

from scanbook.build_index import build_index
from scanbook.extract_cases import extract_case_candidates
from scanbook.qa import run_qa
from scanbook.query import query_index
from scanbook.render_pages import render_pages
from scanbook.split_pdf import split_pdf_by_ranges


def _create_synthetic_pdf(path: Path, pages: int = 3) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as f:
        writer.write(f)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    synthetic_ocr = root / "examples" / "synthetic" / "ocr_pages.jsonl"
    synthetic_notes = root / "examples" / "synthetic" / "case_notes.md"

    try:
        with tempfile.TemporaryDirectory(prefix="scanbook_smoke_") as tmp:
            work = Path(tmp)
            pdf_path = work / "synthetic.pdf"
            _create_synthetic_pdf(pdf_path)

            chapters_dir = work / "chapters"
            split_pdf_by_ranges(
                input_pdf=pdf_path,
                chapters=[{"chapter_id": "syn01", "start_page": 1, "end_page": 3, "title": "Synthetic"}],
                output_dir=chapters_dir,
                source_hash="synthetic",
            )

            render_dir = work / "renders"
            render_pages(
                input_pdf=chapters_dir / "syn01.pdf",
                pages_spec="1-2",
                output_dir=render_dir,
                dpi=96,
                contact_sheet=False,
            )

            qa_dir = work / "qa"
            qa_summary = run_qa(input_jsonl=synthetic_ocr, report_dir=qa_dir)
            if qa_summary["total_pages"] <= 0:
                raise RuntimeError("QA produced zero pages")

            cases_path = work / "cases.jsonl"
            rows = extract_case_candidates(inputs=[synthetic_notes], output_jsonl=cases_path)
            if not rows:
                raise RuntimeError("No extracted case candidates")

            index_dir = work / "index"
            build_index(input_jsonl=cases_path, output_dir=index_dir, vector_store="lexical")
            hits = query_index(index_dir=index_dir, question="adult patient with chest pain", top_k=3)
            if not hits:
                raise RuntimeError("No lexical query hits")
        print("PASS: synthetic split/render/qa/extract/lexical-index/query pipeline")
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
