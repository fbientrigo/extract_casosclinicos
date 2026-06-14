from __future__ import annotations

import shutil
from pathlib import Path
from typing import Sequence

from scanbook.errors import MissingDependencyError
from scanbook.ocr.base import BaseOcrBackend, OcrResult
from scanbook.utils import ensure_dir, write_jsonl


class NativePdfBackend(BaseOcrBackend):
    name = "native_pdf"

    def run(
        self,
        input_pdf: Path,
        output_jsonl: Path,
        *,
        language: Sequence[str] = (),
        profile: str | None = None,
        chapter_id: str | None = None,
        output_pdf: Path | None = None,
        sidecar_txt: Path | None = None,
    ) -> list[OcrResult]:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise MissingDependencyError("PyMuPDF (fitz) is not installed.")

        ensure_dir(output_jsonl.parent)
        final_pdf = output_pdf or output_jsonl.with_name(f"{output_jsonl.stem}.searchable.pdf")
        final_sidecar = sidecar_txt or output_jsonl.with_name(f"{output_jsonl.stem}.sidecar.txt")
        ensure_dir(final_pdf.parent)
        ensure_dir(final_sidecar.parent)
        
        # Native extraction doesn't create a new searchable PDF via OCR, we just copy the original
        if final_pdf != input_pdf:
            shutil.copyfile(input_pdf, final_pdf)

        doc = fitz.open(input_pdf)
        results: list[OcrResult] = []
        full_text_pages = []
        
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text")
            full_text_pages.append(text)
            
            results.append(
                OcrResult(
                    page_num=i,
                    text=text,
                    extractor=self.name,
                    chapter_id=chapter_id,
                    metadata={"profile": profile, "output_pdf": str(final_pdf)},
                )
            )
            
        doc.close()
        
        # Write sidecar.txt separated by form feeds (\f) just like OCRmyPDF
        final_sidecar.write_text("\f".join(full_text_pages), encoding="utf-8")
            
        write_jsonl(
            [
                {
                    "page_num": r.page_num,
                    "text": r.text,
                    "extractor": r.extractor,
                    "confidence": r.confidence,
                    "ocr_quality": r.ocr_quality,
                    "chapter_id": r.chapter_id,
                    **r.metadata,
                }
                for r in results
            ],
            output_jsonl,
        )
        return results
