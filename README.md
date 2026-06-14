# scanbook-rag-lab

Local-first Python 3.11 lab for scanned-book OCR/RAG workflows with pluggable OCR backends, QA checks, rule-based clinical-case candidate extraction, and optional local indexes.

## Purpose

This repository is for **reproducible pipeline code**, configs, schemas, tests, and synthetic examples.  
It is designed for large scanned academic books processed in **page-level / small-batch jobs** on modest hardware.

Resource policy default:
- Do not intentionally exceed about 40% system RAM or 40% VRAM.
- Keep OCR/index jobs batched (for example chapter-by-chapter and page subsets first).

## Install

Using `uv` (recommended):

```bash
uv python install 3.11
uv venv --python 3.11
uv sync --extra core --extra dev
```

Optional heavy OCR/RAG extras:

```bash
uv sync --extra core --extra ocr --extra rag --extra dev
```

Run CLI:

```bash
uv run scanbook --help
```

## Lightweight Smoke Test (Default)

This path is dependency-light and does not require OCRmyPDF, Docling, Marker, PaddleOCR, sentence-transformers, FAISS, or Chroma.

```bash
uv sync --extra core --extra dev
uv run pytest
uv run python scripts/smoke_synthetic_pipeline.py
uv run scanbook --help
uv run scanbook audit-env
```

## OCRmyPDF Scanned Smoke Test (Optional)

This path exercises a realistic scanned input flow built from synthetic page images (no copyrighted material).  
It is optional and skips cleanly when required OCR executables are unavailable.

```bash
uv sync --extra core --extra dev
uv run python scripts/smoke_ocrmypdf_synthetic_scan.py
```

Required runtime executables for this optional smoke:
- `ocrmypdf`
- `tesseract`

Commonly needed by OCRmyPDF depending on platform/install:
- `qpdf`
- Ghostscript (`gs` or `gswin64c` / `gswin32c`)

## Workflow

1. Create a book config from [`configs/book.example.yaml`](configs/book.example.yaml).
2. Split source PDF by chapter ranges:
   - `uv run scanbook split --config configs/book.example.yaml`
3. Render selected pages for manual review:
   - `uv run scanbook render-pages --input-pdf data/chapters/ch01.pdf --pages 1-6 --dpi 144 --output-dir data/pages/ch01 --contact-sheet`
4. OCR a chapter using a chosen backend:
   - `uv run scanbook ocr --backend ocrmypdf --input-pdf data/chapters/ch01.pdf --output-jsonl data/ocr/ch01.jsonl --lang spa --lang eng`
   - Optional explicit outputs:
   - `uv run scanbook ocr --backend ocrmypdf --input-pdf data/chapters/ch01.pdf --output-jsonl data/ocr/ch01.jsonl --output-pdf data/ocr/ch01.searchable.pdf --sidecar-txt data/ocr/ch01.sidecar.txt --lang spa --lang eng`
5. Run OCR QA:
   - `uv run scanbook qa --input-jsonl data/ocr/ch01.jsonl --report-dir reports`
6. Extract rule-based case candidates:
   - `uv run scanbook extract-cases --input examples/synthetic/case_notes.md --output-jsonl data/json/cases.synthetic.jsonl --schema schemas/clinical_case.schema.json`
7. Build local index (default lexical):
   - `uv run scanbook build-index --input-jsonl data/json/cases.synthetic.jsonl --output-dir data/index/synthetic --vector-store lexical`
8. Query local index:
   - `uv run scanbook query --index-dir data/index/synthetic --question "adult patient with chest pain"`

`vector-store` modes:
- `lexical`: dependency-light searchable index (`chunks.jsonl` + `lexical_index.json`).
- `none`: only writes `chunks.jsonl` + `index_meta.json`.
- `faiss` / `chroma`: optional heavy embedding stores.

Smoke scripts:
- lightweight synthetic pipeline: `uv run python scripts/smoke_synthetic_pipeline.py`
- OCRmyPDF synthetic scanned pipeline: `uv run python scripts/smoke_ocrmypdf_synthetic_scan.py`

## First Real Book Workflow

1. Manually inspect the source PDF table of contents and numbering quirks.
2. Create chapter ranges in config with validated page offsets.
3. Run `split` and render sample pages per chapter.
4. Compare OCRmyPDF vs Docling on a 10-20 page sample before scaling.
5. Run QA on sample OCR outputs.
6. Batch full chapters only after sample quality is acceptable.

## First Real Subset Evaluation

To safely evaluate OCR quality on a small, user-selected subset of real scanned pages without committing copyrighted outputs to Git, use the `evaluate_real_subset.py` evaluation script.

This script isolates all intermediate and final outputs under local Git-ignored directories and runs a targeted page-range evaluation.

Example command:
```bash
uv run python scripts/evaluate_real_subset.py --input-pdf data/raw/book.pdf --book-id book783 --pages 1-3,20-25,100-105 --lang spa --lang eng
```

The script performs the following steps:
1. Validates the selected page ranges against the source PDF.
2. Computes the SHA256 checksum of the source PDF.
3. Renders the selected pages and generates a unified `contact_sheet.png` in the work directory.
4. Runs OCRmyPDF on the extracted page subset.
5. Maps page numbers in the output JSONL back to their original physical pages in the source PDF.
6. Generates automated QA JSON and Markdown reports.
7. Outputs a complete execution `manifest.json`.
8. Prints a detailed console summary of page char counts, empty/suspicious pages, repeated headers/footers, and file output paths.

Use the manual review template located at `reports/templates/ocr_subset_review.md` to evaluate the quality of this subset and decide on the next actions (tuning profiles, testing other backends like Docling/PaddleOCR, or scaling to full chapter/book processing).

## Copyright / Data Policy

- Do not commit source books, chapter PDFs, rendered pages, OCR outputs, markdown dumps, full extracted text, embeddings, or vector DB files.
- Keep this repo publish-safe: scripts/configs/schemas/tests/synthetic examples only.
- Respect copyright and licensing constraints for any external OCR/model tool.

## Recommended OCR Profiles

- `fast_latin`: low DPI, quick inspection.
- `balanced_multilang`: mixed language academic text.
- `high_quality_tables`: higher DPI, slower, more robust for complex layouts.

Profiles are selected through config + backend flags; exact behavior depends on backend.

## Gemini CLI Handoff Workflow

This repo does **not** require Gemini for local extraction.  
Use Gemini CLI externally after local chapter outputs are prepared:

1. Run split + OCR + QA + extraction locally.
2. Export chapter/subchapter markdown/json batches.
3. Send only needed batches to Gemini CLI for higher-level analysis/summarization.
4. Merge Gemini outputs back as separate derived artifacts (outside this repository if sensitive).

## OCR split clinical cases

Batch OCR, automated QA checks, and text extraction for already-split clinical-case PDFs. All output directories are structured under `data/ocr_cases/` which is fully Git-ignored to ensure publish-safety.

The pipeline is completely resumable: already-processed cases are skipped automatically unless the `--force` flag is specified.

### Usage Examples:

1. **Dry-Run Discovery Mode** (default):
   ```bash
   .\.venv\Scripts\python scripts/ocr_split_cases.py --dry-run --section seccion2 --subsection anemias_microciticas
   ```

2. **Limit Test Execution** (processes exactly 2 new cases):
   ```bash
   .\.venv\Scripts\python scripts/ocr_split_cases.py --execute --section seccion2 --subsection anemias_microciticas --limit 2
   ```

3. **Full Subsection Execution**:
   ```bash
   .\.venv\Scripts\python scripts/ocr_split_cases.py --execute --section seccion2 --subsection anemias_microciticas
   ```

