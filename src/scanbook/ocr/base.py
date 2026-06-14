from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


@dataclass(slots=True)
class OcrResult:
    page_num: int
    text: str
    extractor: str
    confidence: float | None = None
    ocr_quality: float | None = None
    chapter_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseOcrBackend(ABC):
    name: str = "base"

    @abstractmethod
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
        raise NotImplementedError
