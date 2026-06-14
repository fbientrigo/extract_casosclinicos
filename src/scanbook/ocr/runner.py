from __future__ import annotations

from scanbook.ocr.base import BaseOcrBackend
from scanbook.ocr.docling_backend import DoclingBackend
from scanbook.ocr.marker_backend import MarkerBackend
from scanbook.ocr.ocrmypdf_backend import OcrmypdfBackend
from scanbook.ocr.paddle_backend import PaddleBackend


def get_backend(name: str) -> BaseOcrBackend:
    key = name.strip().lower()
    backends: dict[str, BaseOcrBackend] = {
        "ocrmypdf": OcrmypdfBackend(),
        "docling": DoclingBackend(),
        "marker": MarkerBackend(),
        "paddle": PaddleBackend(),
    }
    if key not in backends:
        available = ", ".join(sorted(backends))
        raise ValueError(f"Unknown backend '{name}'. Available backends: {available}")
    return backends[key]

