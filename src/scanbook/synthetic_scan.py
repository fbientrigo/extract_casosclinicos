from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader

from scanbook.utils import ensure_dir

DEFAULT_SYNTHETIC_SCAN_PAGES: list[str] = [
    (
        "CLINICAL CASE 1\n"
        "Paciente adulto con dolor toracico y fiebre por 3 dias.\n"
        "No real patient data. Synthetic educational sample only."
    ),
    (
        "CLINICAL CASE 2\n"
        "Adult patient reports dry cough and chest discomfort.\n"
        "Plan: oral hydration, follow up in 48 hours."
    ),
    (
        "CLINICAL CASE 3\n"
        "Revision diagnostica: neumonia adquirida en la comunidad.\n"
        "Findings are synthetic and not linked to any real person."
    ),
]


def create_synthetic_scanned_pdf(
    output_pdf: Path,
    *,
    page_texts: Sequence[str] | None = None,
    output_images_dir: Path | None = None,
    image_size: tuple[int, int] = (1654, 2339),
    dpi: int = 200,
) -> Path:
    pages = list(page_texts or DEFAULT_SYNTHETIC_SCAN_PAGES)
    if not pages:
        raise ValueError("At least one synthetic page is required.")

    ensure_dir(output_pdf.parent)
    if output_images_dir is not None:
        ensure_dir(output_images_dir)

    images: list[Image.Image] = []
    for idx, text in enumerate(pages, start=1):
        image = _render_synthetic_page(
            text=text,
            page_number=idx,
            image_size=image_size,
        )
        if output_images_dir is not None:
            image.save(output_images_dir / f"page_{idx:03d}.png", format="PNG")
        images.append(image.convert("RGB"))

    first, *rest = images
    first.save(output_pdf, format="PDF", resolution=float(dpi), save_all=True, append_images=rest)
    _assert_no_embedded_text(output_pdf)
    return output_pdf


def _render_synthetic_page(text: str, page_number: int, image_size: tuple[int, int]) -> Image.Image:
    width, height = image_size
    image = Image.new("L", image_size, color=250)
    draw = ImageDraw.Draw(image)
    font = _load_font(size=42)
    margin_x = 120
    y = 120
    max_width_chars = max(28, int((width - margin_x * 2) / 18))
    for paragraph in text.splitlines():
        if not paragraph.strip():
            y += 26
            continue
        for line in textwrap.wrap(paragraph, width=max_width_chars):
            draw.text((margin_x, y), line, fill=15, font=font)
            y += 62
        y += 20
    draw.text((margin_x, height - 140), f"Page {page_number}", fill=70, font=_load_font(size=30))
    return image


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_name in ["DejaVuSans.ttf", "Arial.ttf", "LiberationSans-Regular.ttf"]:
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _assert_no_embedded_text(pdf_path: Path) -> None:
    reader = PdfReader(str(pdf_path))
    extracted = [str(page.extract_text() or "").strip() for page in reader.pages]
    if any(extracted):
        raise RuntimeError(
            f"Expected image-only synthetic PDF without digital text, but found extractable text in {pdf_path}."
        )
