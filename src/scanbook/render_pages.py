from __future__ import annotations

from pathlib import Path

from scanbook.errors import MissingDependencyError
from scanbook.utils import ensure_dir, parse_page_spec


def render_pages(
    input_pdf: Path,
    output_dir: Path,
    pages_spec: str,
    dpi: int = 144,
    contact_sheet: bool = False,
) -> list[Path]:
    pages = parse_page_spec(pages_spec)
    ensure_dir(output_dir)
    output_files: list[Path] = []
    try:
        import fitz

        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        doc = fitz.open(str(input_pdf))
        try:
            for page_num in pages:
                if page_num < 1 or page_num > doc.page_count:
                    continue
                page = doc.load_page(page_num - 1)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                out_path = output_dir / f"page_{page_num:04d}.png"
                pix.save(str(out_path))
                output_files.append(out_path)
        finally:
            doc.close()
    except ImportError:
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            raise MissingDependencyError(
                "render-pages requires PyMuPDF or pypdfium2. Install extras: core."
            ) from exc
        pdf = pdfium.PdfDocument(str(input_pdf))
        try:
            for page_num in pages:
                if page_num < 1 or page_num > len(pdf):
                    continue
                page = pdf[page_num - 1]
                bitmap = page.render(scale=dpi / 72.0)
                image = bitmap.to_pil()
                out_path = output_dir / f"page_{page_num:04d}.png"
                image.save(out_path)
                output_files.append(out_path)
        finally:
            pdf.close()

    if contact_sheet and output_files:
        _create_contact_sheet(output_files, output_dir / "contact_sheet.png")
    return output_files


def _create_contact_sheet(image_paths: list[Path], output_path: Path, thumb_size: int = 280) -> None:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise MissingDependencyError("Pillow is required for contact sheet creation.") from exc

    cols = 4
    rows = (len(image_paths) + cols - 1) // cols
    padding = 12
    width = cols * thumb_size + (cols + 1) * padding
    height = rows * thumb_size + (rows + 1) * padding
    canvas = Image.new("RGB", (width, height), color="white")

    for idx, img_path in enumerate(image_paths):
        with Image.open(img_path) as img:
            thumb = ImageOps.contain(img.convert("RGB"), (thumb_size, thumb_size))
            x = padding + (idx % cols) * (thumb_size + padding)
            y = padding + (idx // cols) * (thumb_size + padding)
            canvas.paste(thumb, (x, y))
    canvas.save(output_path)
