from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

from scanbook.errors import MissingDependencyError
from scanbook.ocr.base import BaseOcrBackend, OcrResult
from scanbook.utils import ensure_dir, write_jsonl


class OcrmypdfBackend(BaseOcrBackend):
    name = "ocrmypdf"

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
        if shutil.which("ocrmypdf") is None:
            raise MissingDependencyError("ocrmypdf executable not found in PATH.")

        langs = [str(lang).strip() for lang in language if str(lang).strip()] or ["eng"]
        ensure_dir(output_jsonl.parent)
        final_pdf = output_pdf or output_jsonl.with_name(f"{output_jsonl.stem}.searchable.pdf")
        final_sidecar = sidecar_txt or output_jsonl.with_name(f"{output_jsonl.stem}.sidecar.txt")
        ensure_dir(final_pdf.parent)
        ensure_dir(final_sidecar.parent)
        with tempfile.TemporaryDirectory(prefix="scanbook_ocrmypdf_") as tmp:
            tmp_dir = Path(tmp)
            out_pdf = tmp_dir / "ocr_output.pdf"
            sidecar = tmp_dir / "sidecar.txt"
            cmd = [
                "ocrmypdf",
                "--skip-text",
                "--sidecar",
                str(sidecar),
                "-l",
                "+".join(langs),
                str(input_pdf),
                str(out_pdf),
            ]
            if profile == "fast_latin":
                cmd.extend(["--tesseract-timeout", "30"])
            elif profile == "high_quality_tables":
                cmd.extend(["--deskew", "--clean-final", "--tesseract-timeout", "180"])
            subprocess.run(cmd, check=True)
            if out_pdf.exists():
                shutil.copyfile(out_pdf, final_pdf)
            if sidecar.exists():
                shutil.copyfile(sidecar, final_sidecar)

            text = sidecar.read_text(encoding="utf-8", errors="ignore") if sidecar.exists() else ""
            pages = [p.strip() for p in text.split("\f")]
            results: list[OcrResult] = []
            for i, page_text in enumerate(pages, start=1):
                results.append(
                    OcrResult(
                        page_num=i,
                        text=page_text,
                        extractor=self.name,
                        chapter_id=chapter_id,
                        metadata={"profile": profile, "lang": langs, "output_pdf": str(final_pdf)},
                    )
                )
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
