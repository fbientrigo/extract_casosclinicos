from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Sequence

from scanbook.errors import MissingDependencyError
from scanbook.ocr.base import BaseOcrBackend, OcrResult
from scanbook.utils import ensure_dir, write_jsonl


class PaddleBackend(BaseOcrBackend):
    name = "paddle"

    def run(
        self,
        input_pdf: Path,
        output_jsonl: Path,
        *,
        language: Sequence[str],
        profile: str | None = None,
        chapter_id: str | None = None,
        output_pdf: Path | None = None,
        sidecar_txt: Path | None = None,
    ) -> list[OcrResult]:
        try:
            import fitz
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise MissingDependencyError("PaddleOCR backend requires paddleocr and PyMuPDF.") from exc

        lang = (list(language) or ["en"])[0]
        ocr = PaddleOCR(use_angle_cls=True, lang=lang)
        doc = fitz.open(str(input_pdf))
        results: list[OcrResult] = []
        try:
            for i in range(doc.page_count):
                page = doc.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
                # Write page images to temporary PNG files and feed file paths to PaddleOCR.
                # This avoids fragile assumptions about raw pixmap byte layout/channel order.
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_png:
                    tmp_path = Path(tmp_png.name)
                try:
                    pix.save(str(tmp_path))
                    page_result = ocr.ocr(str(tmp_path), cls=True)
                finally:
                    tmp_path.unlink(missing_ok=True)
                text_items: list[str] = []
                conf_items: list[float] = []
                if page_result:
                    for line in page_result[0]:
                        text_items.append(str(line[1][0]))
                        conf_items.append(float(line[1][1]))
                results.append(
                    OcrResult(
                        page_num=i + 1,
                        text="\n".join(text_items),
                        extractor=self.name,
                        confidence=(sum(conf_items) / len(conf_items)) if conf_items else None,
                        chapter_id=chapter_id,
                        metadata={"profile": profile, "lang": lang},
                    )
                )
        finally:
            doc.close()

        ensure_dir(output_jsonl.parent)
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
