from __future__ import annotations

import importlib.util
import platform
import shutil
from typing import Any


def _importable(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _which_any(names: list[str]) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def audit_environment() -> dict[str, Any]:
    ocrmypdf_path = shutil.which("ocrmypdf")
    tesseract_path = shutil.which("tesseract")
    qpdf_path = shutil.which("qpdf")
    ghostscript_path = _which_any(["gswin64c", "gswin32c", "gs"])

    report: dict[str, Any] = {
        "python_version": platform.python_version(),
        "executables": {
            "ocrmypdf_in_path": ocrmypdf_path is not None,
            "tesseract_in_path": tesseract_path is not None,
            "qpdf_in_path": qpdf_path is not None,
            "ghostscript_in_path": ghostscript_path is not None,
            "ocrmypdf_path": ocrmypdf_path,
            "tesseract_path": tesseract_path,
            "qpdf_path": qpdf_path,
            "ghostscript_path": ghostscript_path,
        },
        "optional_imports": {
            "docling": _importable("docling"),
            "marker": _importable("marker") or _importable("marker_pdf"),
            "paddleocr": _importable("paddleocr"),
            "pymupdf": _importable("fitz"),
        },
        "torch": {
            "installed": False,
            "cuda_available": False,
        },
    }
    if _importable("torch"):
        report["torch"]["installed"] = True
        try:
            import torch

            report["torch"]["cuda_available"] = bool(torch.cuda.is_available())
        except Exception:
            report["torch"]["cuda_available"] = False
    return report
