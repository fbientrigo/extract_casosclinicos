from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Sequence

from scanbook.errors import MissingDependencyError
from scanbook.ocr.base import BaseOcrBackend, OcrResult


class MarkerBackend(BaseOcrBackend):
    name = "marker"

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
        # Marker is treated as optional due licensing/dependency complexity.
        if (
            importlib.util.find_spec("marker") is None
            and importlib.util.find_spec("marker_pdf") is None
        ):
            raise MissingDependencyError(
                "Marker backend dependencies not installed. "
                "Enable only where licensing/deployment constraints are acceptable."
            )
        raise NotImplementedError(
            "Marker backend adapter is intentionally left as a placeholder pending "
            "license-compliant integration in your environment."
        )
