from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Sequence

from scanbook.errors import MissingDependencyError
from scanbook.ocr.base import BaseOcrBackend, OcrResult


class DoclingBackend(BaseOcrBackend):
    name = "docling"

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
        if importlib.util.find_spec("docling") is None:
            raise MissingDependencyError("docling is not installed.")
        raise NotImplementedError(
            "Docling backend is a placeholder adapter. "
            "Integrate project-specific docling invocation before production use."
        )
