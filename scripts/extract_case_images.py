#!/usr/bin/env python3
"""
Extract embedded images page-by-page from split clinical case PDFs.
Organizes extracted images under each case's OCR folder so they are ready
for multi-modal visual LLM execution (e.g. Gemini 1.5 Pro / Flash vision) in Google Colab.
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

from scanbook.utils import ensure_dir

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract embedded images from split clinical case PDFs for visual LLM processing."
    )
    parser.add_argument(
        "--book-id",
        required=True,
        help="ID of the book to process (mandatory)."
    )
    parser.add_argument(
        "--ocr-cases-dir",
        help="Root directory where completed OCR case folders live (defaults to data/curated/<book-id>/extracted_cases)."
    )
    parser.add_argument(
        "--split-cases-root",
        help="Root folder containing original split case PDFs (defaults to book/<book_id>)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run: print planned image extractions without writing to disk."
    )
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    book_id = args.book_id
    
    ocr_root = Path(args.ocr_cases_dir) if args.ocr_cases_dir else (project_root / "data" / "curated" / book_id / "extracted_cases")
    split_root = Path(args.split_cases_root) if args.split_cases_root else (project_root / "book" / book_id)
    
    if not ocr_root.exists():
        print(f"Error: OCR cases directory '{ocr_root}' does not exist. Run ocr_split_cases.py first.")
        return 1
    if not split_root.exists():
        print(f"Error: Split cases root directory '{split_root}' does not exist.")
        return 1

    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("Error: PyMuPDF (fitz) is not installed. Install it with: .\\.venv\\Scripts\\python -m pip install PyMuPDF")
        return 1

    print("======================================================================")
    print(f"CLINICAL CASE IMAGE EXTRACTION WORKFLOW - BOOK: {book_id}")
    print("======================================================================")
    print(f"OCR Cases Root: {ocr_root}")
    print(f"Split PDF Root: {split_root}")
    print(f"Mode:           {'DRY-RUN' if args.dry_run else 'EXECUTE'}\n")

    # Discover cases in the OCR folder
    cases = []
    for sec_dir in ocr_root.iterdir():
        if not sec_dir.is_dir() or not sec_dir.name.startswith("seccion"):
            continue
        for subsec_dir in sec_dir.iterdir():
            if not subsec_dir.is_dir():
                continue
            for case_dir in subsec_dir.iterdir():
                if not case_dir.is_dir():
                    continue
                
                # Check for metadata
                meta_file = case_dir / "case_metadata.json"
                if meta_file.exists():
                    cases.append({
                        "case_id": case_dir.name,
                        "section": sec_dir.name,
                        "subsection": subsec_dir.name,
                        "ocr_case_dir": case_dir,
                        "meta_file": meta_file
                    })

    cases.sort(key=lambda x: (x["section"], x["subsection"], x["case_id"]))
    print(f"Discovered {len(cases)} completed clinical cases.")

    total_images_extracted = 0
    cases_with_images = 0

    for idx, c in enumerate(cases, 1):
        case_id = c["case_id"]
        sec = c["section"]
        sub = c["subsection"]
        
        # Resolve source PDF path
        # Note: the PDF lives in book/<book_id>/<section>/<subsection>/<case_id>.pdf
        pdf_path = split_root / sec / sub / f"{case_id}.pdf"
        
        if not pdf_path.exists():
            print(f"[{idx}/{len(cases)}] Warning: Split PDF not found at {pdf_path}. Skipping.")
            continue
            
        # Open split PDF
        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            print(f"[{idx}/{len(cases)}] Error: Failed to open PDF at {pdf_path}: {e}")
            continue
            
        case_images = []
        image_idx_global = 1
        
        # Iterate pages to extract images
        for page_num_0based in range(len(doc)):
            page_num = page_num_0based + 1
            page = doc[page_num_0based]
            image_list = page.get_images(full=True)
            
            if not image_list:
                continue
                
            for img_info in image_list:
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    image_ext = base_image["ext"]
                    
                    # Target image name
                    img_filename = f"page_{page_num}_img_{image_idx_global}.{image_ext}"
                    dest_img_path = c["ocr_case_dir"] / "images" / img_filename
                    
                    if not args.dry_run:
                        ensure_dir(dest_img_path.parent)
                        dest_img_path.write_bytes(image_bytes)
                        
                    # Save relative path for metadata
                    rel_img_path = f"images/{img_filename}"
                    case_images.append({
                        "filename": img_filename,
                        "relative_path": rel_img_path,
                        "page_number": page_num,
                        "format": image_ext,
                        "dimensions": (base_image["width"], base_image["height"])
                    })
                    image_idx_global += 1
                    total_images_extracted += 1
                except Exception as e:
                    print(f"  Warning: Failed to extract image xref {xref} on page {page_num}: {e}")

        doc.close()
        
        if case_images:
            cases_with_images += 1
            print(f"[{idx}/{len(cases)}] Case '{case_id}': Found and extracted {len(case_images)} images.")
            
            # Update metadata json with list of images
            if not args.dry_run:
                try:
                    meta_data = json.loads(c["meta_file"].read_text(encoding="utf-8"))
                    meta_data["extracted_images"] = case_images
                    c["meta_file"].write_text(json.dumps(meta_data, indent=2, ensure_ascii=False), encoding="utf-8")
                except Exception as e:
                    print(f"  Error: Failed to update metadata for {case_id}: {e}")
        else:
            # Optionally remove key or set to empty
            if not args.dry_run:
                try:
                    meta_data = json.loads(c["meta_file"].read_text(encoding="utf-8"))
                    meta_data["extracted_images"] = []
                    c["meta_file"].write_text(json.dumps(meta_data, indent=2, ensure_ascii=False), encoding="utf-8")
                except Exception as e:
                    pass

    print("\n======================================================================")
    print("IMAGE EXTRACTION PROCESS COMPLETED")
    print("======================================================================")
    print(f"Total Cases with extracted images: {cases_with_images}")
    print(f"Total Images extracted:            {total_images_extracted}")
    if not args.dry_run:
        print(f"Images are saved in:             data/curated/{book_id}/extracted_cases/<section>/<subsection>/<case_id>/images/")
    return 0

if __name__ == "__main__":
    sys.exit(main())
