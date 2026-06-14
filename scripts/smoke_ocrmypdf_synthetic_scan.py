from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

from pypdf import PdfReader

from scanbook.synthetic_scan import create_synthetic_scanned_pdf
from scanbook.utils import read_jsonl


def _exe_status() -> dict[str, str | None]:
    return {
        "scanbook": shutil.which("scanbook"),
        "ocrmypdf": shutil.which("ocrmypdf"),
        "tesseract": shutil.which("tesseract"),
        "qpdf": shutil.which("qpdf"),
        "ghostscript": shutil.which("gswin64c") or shutil.which("gswin32c") or shutil.which("gs"),
    }


def _run_scanbook(args: Sequence[str]) -> None:
    cmd = ["scanbook", *args]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.stderr.strip():
        print(completed.stderr.strip())


def main() -> int:
    status = _exe_status()
    print("Dependency status:")
    for key, path in status.items():
        print(f"- {key}: {path or 'MISSING'}")

    missing_required = [name for name in ("ocrmypdf", "tesseract") if status[name] is None]
    if missing_required:
        print(f"SKIP: missing required executables for OCRmyPDF smoke: {', '.join(missing_required)}")
        return 0

    anchors = ["clinical", "paciente", "adult", "cough", "patient"]

    try:
        with tempfile.TemporaryDirectory(prefix="scanbook_ocrmypdf_smoke_") as tmp:
            work_dir = Path(tmp)
            input_pdf = work_dir / "synthetic_scanned_input.pdf"
            output_pdf = work_dir / "synthetic_scanned_output.searchable.pdf"
            output_jsonl = work_dir / "synthetic_scanned_pages.jsonl"
            sidecar_txt = work_dir / "synthetic_scanned_output.sidecar.txt"
            qa_dir = work_dir / "qa"
            create_synthetic_scanned_pdf(input_pdf)

            _run_scanbook(
                [
                    "ocr",
                    "--backend",
                    "ocrmypdf",
                    "--input-pdf",
                    str(input_pdf),
                    "--output-jsonl",
                    str(output_jsonl),
                    "--output-pdf",
                    str(output_pdf),
                    "--sidecar-txt",
                    str(sidecar_txt),
                    "--lang",
                    "eng",
                    "--lang",
                    "spa",
                    "--profile",
                    "fast_latin",
                ]
            )
            _run_scanbook(
                [
                    "qa",
                    "--input-jsonl",
                    str(output_jsonl),
                    "--report-dir",
                    str(qa_dir),
                ]
            )

            if not output_pdf.exists() or output_pdf.stat().st_size <= 0:
                raise RuntimeError("Searchable output PDF missing or empty.")
            if not sidecar_txt.exists() or sidecar_txt.stat().st_size <= 0:
                raise RuntimeError("Sidecar TXT missing or empty.")
            if not output_jsonl.exists() or output_jsonl.stat().st_size <= 0:
                raise RuntimeError("Page JSONL missing or empty.")
            qa_json = qa_dir / "qa_summary.json"
            if not qa_json.exists():
                raise RuntimeError("QA summary JSON missing.")

            sidecar_text = sidecar_txt.read_text(encoding="utf-8", errors="ignore").lower()
            present = [anchor for anchor in anchors if anchor in sidecar_text]
            if len(present) < 3:
                raise RuntimeError(
                    f"OCR sidecar missing expected anchors. Found={present}, expected at least 3 of {anchors}."
                )

            rows = read_jsonl(output_jsonl)
            if len(rows) < 2:
                raise RuntimeError("Expected at least 2 OCR pages in JSONL output.")

            searchable_text = "\n".join(
                (page.extract_text() or "") for page in PdfReader(str(output_pdf)).pages
            ).lower()
            if not searchable_text.strip():
                raise RuntimeError("Searchable PDF has no extractable text.")

            qa_summary = json.loads(qa_json.read_text(encoding="utf-8"))
            if int(qa_summary.get("total_pages", 0)) < 2:
                raise RuntimeError("QA summary reported fewer than 2 pages.")

        print("PASS: OCRmyPDF synthetic scanned smoke test")
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
