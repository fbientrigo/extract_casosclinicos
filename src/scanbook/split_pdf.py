from __future__ import annotations

from pathlib import Path
from typing import Any

from scanbook.config import get_chapters, load_yaml
from scanbook.errors import MissingDependencyError
from scanbook.utils import ensure_dir, sha256_file, write_jsonl


def split_pdf_from_config(config_path: Path) -> Path:
    cfg = load_yaml(config_path)
    source_pdf = Path(cfg["source_pdf"])
    if not source_pdf.is_absolute():
        source_pdf = (config_path.parent / source_pdf).resolve()
    chapters = get_chapters(cfg)
    page_offset = int(cfg.get("page_offset", 0))
    outputs = cfg.get("outputs", {})
    chapters_dir = Path(outputs.get("chapters_dir", "data/chapters"))
    if not chapters_dir.is_absolute():
        chapters_dir = (config_path.parent.parent / chapters_dir).resolve()
    ensure_dir(chapters_dir)
    manifest_path = chapters_dir / "manifest.jsonl"
    source_hash = sha256_file(source_pdf)
    records = split_pdf_by_ranges(
        input_pdf=source_pdf,
        chapters=chapters,
        output_dir=chapters_dir,
        source_hash=source_hash,
        page_offset=page_offset,
    )
    write_jsonl(records, manifest_path)
    return manifest_path


def split_pdf_by_ranges(
    input_pdf: Path,
    chapters: list[dict[str, Any]],
    output_dir: Path,
    source_hash: str,
    page_offset: int = 0,
) -> list[dict[str, Any]]:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise MissingDependencyError(
            "pypdf is required for split_pdf. Install with extras: core."
        ) from exc

    ensure_dir(output_dir)
    manifest: list[dict[str, Any]] = []
    src_pdf = PdfReader(str(input_pdf))
    total_pages = len(src_pdf.pages)
    for chapter in chapters:
        chapter_id = str(chapter["chapter_id"])
        start_logical = int(chapter["start_page"])
        end_logical = int(chapter["end_page"])
        if end_logical < start_logical:
            raise ValueError(f"Invalid range for {chapter_id}: {start_logical}-{end_logical}")
        start_physical = start_logical + page_offset
        end_physical = end_logical + page_offset
        if start_physical < 1 or end_physical > total_pages:
            raise ValueError(
                f"Range out of bounds for {chapter_id}: "
                f"{start_physical}-{end_physical} over {total_pages} pages"
            )
        out_pdf_path = output_dir / f"{chapter_id}.pdf"
        writer = PdfWriter()
        for page_number in range(start_physical, end_physical + 1):
            writer.add_page(src_pdf.pages[page_number - 1])
        with out_pdf_path.open("wb") as f:
            writer.write(f)
        manifest.append(
            {
                "chapter_id": chapter_id,
                "title": chapter.get("title"),
                "source_pdf": str(input_pdf),
                "source_sha256": source_hash,
                "page_offset": page_offset,
                "start_page_logical": start_logical,
                "end_page_logical": end_logical,
                "start_page_physical": start_physical,
                "end_page_physical": end_physical,
                "output_pdf": str(out_pdf_path),
            }
        )
    return manifest
