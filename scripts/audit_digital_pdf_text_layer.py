#!/usr/bin/env python3
"""
Audit the embedded text layer and embedded images of a digital PDF.
Generates comprehensive JSON and Markdown reports to help decide whether
to use native text extraction, full OCR, or a hybrid vision-based RAG mode.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root and src/ to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from scanbook.utils import ensure_dir, parse_page_spec

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit a digital PDF to check text layer density and count embedded images."
    )
    parser.add_argument(
        "--book-id",
        required=True,
        help="ID of the book to audit (mandatory)."
    )
    parser.add_argument(
        "--sample-pages",
        type=int,
        default=5,
        help="Number of pages to sample if --pages is not specified (default: 5)."
    )
    parser.add_argument(
        "--pages",
        help="Optional comma-separated list of physical page ranges to audit (e.g. '1,5,10-12')."
    )
    parser.add_argument(
        "--output-dir",
        help="Custom output directory for audit reports (defaults to data/audits/<book_id>)."
    )
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    book_id = args.book_id
    
    book_dir = project_root / "book" / book_id
    if not book_dir.exists():
        print(f"Error: Book directory '{book_dir}' does not exist.")
        return 1
        
    # Discover PDF in book_dir
    pdf_files = list(book_dir.glob("*.pdf"))
    pdf_files = [p for p in pdf_files if not p.name.startswith("section") and p.name != "ocr.pdf"]
    if not pdf_files:
        print(f"Error: No source PDF found in '{book_dir}'.")
        return 1
    
    source_pdf = pdf_files[0]
    
    output_dir = Path(args.output_dir) if args.output_dir else (project_root / "data" / "audits" / book_id)
    renders_dir = output_dir / "page_renders"
    
    ensure_dir(output_dir)
    ensure_dir(renders_dir)
    
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("Error: PyMuPDF (fitz) is not installed. Run: .\\.venv\\Scripts\\python -m pip install PyMuPDF")
        return 1
        
    try:
        doc = fitz.open(source_pdf)
    except Exception as e:
        print(f"Error: Failed to open PDF '{source_pdf}': {e}")
        return 1
        
    total_pages = len(doc)
    print(f"Opened PDF: {source_pdf.name}")
    print(f"Total Pages: {total_pages}")
    
    # Determine page numbers to audit
    if args.pages:
        try:
            pages_to_audit = parse_page_spec(args.pages)
            # Filter pages within bounds
            pages_to_audit = [p for p in pages_to_audit if 1 <= p <= total_pages]
        except Exception as e:
            print(f"Error parsing --pages option: {e}")
            doc.close()
            return 1
    else:
        # Uniform sampling across the book
        n_samples = min(args.sample_pages, total_pages)
        if n_samples <= 1:
            pages_to_audit = [1]
        elif n_samples == total_pages:
            pages_to_audit = list(range(1, total_pages + 1))
        else:
            pages_to_audit = [
                int(1 + i * (total_pages - 1) / (n_samples - 1))
                for i in range(n_samples)
            ]
            
    print(f"Auditing pages: {pages_to_audit}")
    
    audit_records = []
    total_chars = 0
    total_images = 0
    pages_with_warnings = 0
    
    for page_num in pages_to_audit:
        # PyMuPDF uses 0-indexed pages
        page = doc[page_num - 1]
        
        # 1. Text extraction
        text = page.get_text()
        char_count = len(text)
        total_chars += char_count
        excerpt = text[:500]
        
        # 2. Embedded images count
        images = page.get_images(full=True)
        img_count = len(images)
        total_images += img_count
        
        # 3. Render page to PNG
        render_filename = f"page_{page_num}.png"
        dest_render_path = renders_dir / render_filename
        
        try:
            pix = page.get_pixmap(dpi=144)
            pix.save(str(dest_render_path))
            # Get path relative to the workspace root for portable viewing
            rel_render_path = str(dest_render_path.relative_to(project_root)).replace("\\", "/")
        except Exception as e:
            print(f"  Warning: Failed to render page {page_num}: {e}")
            rel_render_path = None
            
        # 4. Warnings check
        warnings = []
        if char_count == 0:
            warnings.append("empty_text")
        elif char_count < 100:
            warnings.append("suspiciously_short_text")
        if img_count > 3:
            warnings.append("many_images")
            
        if warnings:
            pages_with_warnings += 1
            
        audit_records.append({
            "page_number": page_num,
            "character_count": char_count,
            "embedded_images_count": img_count,
            "text_excerpt": excerpt,
            "render_path": rel_render_path,
            "warnings": warnings
        })
        
    doc.close()
    
    # Calculate statistics and mode recommendations
    avg_chars = total_chars / len(pages_to_audit) if pages_to_audit else 0
    avg_images = total_images / len(pages_to_audit) if pages_to_audit else 0
    
    # Dynamic Recommendation Logic
    if avg_chars > 200:
        recommended_mode = "Native Text Extraction"
        rationale = "The PDF contains a rich embedded digital text layer. Running a heavy OCR pipeline would waste significant time and computational resources."
    elif avg_chars < 50 and avg_images > 0.5:
        recommended_mode = "Full OCRmyPDF Pipeline"
        rationale = "The pages contain very little embedded digital text but have significant visual elements, indicating scanned page assets."
    else:
        recommended_mode = "Hybrid Mode (Native Text + Image Vision RAG)"
        rationale = "The PDF contains an embedded text layer alongside critical visual diagrams/images. Native text extraction combined with page image parsing yields the best results."
        
    if avg_images > 0.5:
        vision_rag_capable = True
        vision_rationale = f"Page analysis indicates an average of {avg_images:.1f} embedded images per page. Extracting these images and passing them via visual LLM is highly recommended."
    else:
        vision_rag_capable = False
        vision_rationale = "Few or no embedded images detected on sample pages. Text-only RAG will be sufficient."
        
    audit_summary = {
        "book_id": book_id,
        "source_pdf": source_pdf.name,
        "total_pages_in_pdf": total_pages,
        "pages_audited_count": len(pages_to_audit),
        "pages_audited_list": pages_to_audit,
        "average_characters_per_page": round(avg_chars, 2),
        "average_embedded_images_per_page": round(avg_images, 2),
        "pages_with_warnings_count": pages_with_warnings,
        "recommended_ingestion_mode": recommended_mode,
        "recommended_rationale": rationale,
        "vision_rag_recommended": vision_rag_capable,
        "vision_rag_rationale": vision_rationale
    }
    
    # 5. Write JSON report
    json_path = output_dir / "text_layer_audit.json"
    json_payload = {
        "summary": audit_summary,
        "pages": audit_records
    }
    json_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote JSON audit report to: {json_path}")
    
    # 6. Write Markdown report
    md_lines = [
        f"# PDF Text Layer & Visual Density Audit: {book_id}\n",
        f"**Source PDF File:** `{source_pdf.name}`",
        f"**Total Pages in Book:** {total_pages}",
        f"**Sampled Audit Pages:** {len(pages_to_audit)} pages ({', '.join(map(str, pages_to_audit))})\n",
        "## Ingestion Strategy Recommendation\n",
        f"### 🏆 Recommended Mode: **{recommended_mode}**\n",
        f"> **Rationale:** {rationale}\n",
        f"### 👁️ Multi-modal / Vision RAG Readiness\n",
        f"- **Vision-RAG Recommended:** {'Yes ⚠️' if vision_rag_capable else 'No'}",
        f"- **Detail:** {vision_rationale}\n",
        "## Key Statistics Summary\n",
        "| Metric | Value |",
        "| --- | --- |",
        f"| **Average Chars / Page** | {avg_chars:.1f} |",
        f"| **Average Images / Page** | {avg_images:.1f} |",
        f"| **Pages with Warnings** | {pages_with_warnings} of {len(pages_to_audit)} |",
        f"| **Recommended Action** | {'Extract native text + separate images' if vision_rag_capable else 'Extract native text only'} |\n",
        "## Sample Page In-Depth Audit\n",
        "| Page | Char Count | Embedded Images | Warnings | Image Render | Excerpt (First 150 chars) |",
        "| --- | --- | --- | --- | --- | --- |"
    ]
    
    for r in audit_records:
        warnings_str = " ".join([f"`{w}` ⚠️" for w in r["warnings"]]) if r["warnings"] else "None"
        render_link = f"[View Page PNG]({r['render_path']})" if r["render_path"] else "None"
        
        # Safe escape of excerpt text for Markdown table
        excerpt_clean = r["text_excerpt"][:150].replace("\n", " ").replace("|", "\\|").strip()
        if len(r["text_excerpt"]) > 150:
            excerpt_clean += "..."
            
        md_lines.append(
            f"| {r['page_number']} | {r['character_count']} | {r['embedded_images_count']} | {warnings_str} | {render_link} | {excerpt_clean} |"
        )
        
    md_lines.append("\n## Audit Warnings Details\n")
    if pages_with_warnings > 0:
        md_lines.append("Review the following pages flagged with warning indicators:")
        for r in audit_records:
            if r["warnings"]:
                md_lines.append(f"- **Page {r['page_number']}:** {', '.join(r['warnings'])}")
    else:
        md_lines.append("*No warnings detected on any sampled pages! The PDF structure is clean.*")
        
    md_report = "\n".join(md_lines)
    md_path = output_dir / "text_layer_audit.md"
    md_path.write_text(md_report, encoding="utf-8")
    print(f"Wrote Markdown audit report to: {md_path}")
    print("\nAudit complete! Review the reports in the data/audits folder.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
