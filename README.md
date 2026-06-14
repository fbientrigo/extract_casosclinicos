# scanbook-rag-lab

Local-first Python 3.11 lab for scanned-book OCR/RAG workflows with pluggable OCR backends, QA checks, rule-based clinical-case candidate extraction, and optional local indexes.

> **Bring Your Own Book (BYOB):** This repository ships only the pipeline code, configs, schemas, tests, synthetic examples, and an agent-powered exploration interface. No copyrighted books, PDFs, OCR text, or derived databases are included. You supply the book; the pipeline does the rest.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        scanbook CLI                             │
├──────────┬──────────┬──────────┬──────────┬──────────┬──────────┤
│  split   │  render  │   ocr    │    qa    │ extract  │  index   │
│          │  pages   │          │          │  cases   │  + query │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
     │           │          │          │          │           │
     ▼           ▼          ▼          ▼          ▼           ▼
  configs/    data/       data/     reports/    data/       data/
  *.yaml      pages/      ocr/                 json/       index/
```

**Core pipeline:** `split → render → OCR → QA → extract-cases → build-index → query`

**Agent interface:** The [`0_interfaz_clinical_cases_llmwiki_scaffold/`](0_interfaz_clinical_cases_llmwiki_scaffold/) directory provides a ready-to-use agent interface for exploring curated clinical cases with an LLM assistant. See its [README](0_interfaz_clinical_cases_llmwiki_scaffold/README.md).

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

## Quick Start (Synthetic — No Book Needed)

This path is dependency-light and does not require OCRmyPDF, Docling, Marker, PaddleOCR, sentence-transformers, FAISS, or Chroma.

```bash
uv sync --extra core --extra dev
uv run pytest
uv run python scripts/smoke_synthetic_pipeline.py
uv run scanbook --help
uv run scanbook audit-env
```

### OCRmyPDF Scanned Smoke Test (Optional)

Exercises a realistic scanned input flow built from synthetic page images (no copyrighted material):

```bash
uv sync --extra core --extra dev
uv run python scripts/smoke_ocrmypdf_synthetic_scan.py
```

Required executables: `ocrmypdf`, `tesseract`. Commonly also: `qpdf`, Ghostscript (`gs` / `gswin64c`).

## Bring Your Own Book: Full Workflow

### 1. Create a book config

Copy the example and adjust chapter/section ranges from your book's table of contents:

```bash
cp configs/book.example.yaml configs/book.mybook.yaml
# Edit chapter ranges, languages, page_offset, etc.
```

See [`configs/book.example.yaml`](configs/book.example.yaml) for the full config schema.

### 2. Split source PDF by chapter ranges

```bash
uv run scanbook split --config configs/book.mybook.yaml
```

### 3. Render selected pages for manual review

```bash
uv run scanbook render-pages --input-pdf data/chapters/ch01.pdf --pages 1-6 --dpi 144 --output-dir data/pages/ch01 --contact-sheet
```

### 4. OCR a chapter

```bash
uv run scanbook ocr --backend ocrmypdf --input-pdf data/chapters/ch01.pdf --output-jsonl data/ocr/ch01.jsonl --lang spa --lang eng
```

Optional explicit outputs:
```bash
uv run scanbook ocr --backend ocrmypdf --input-pdf data/chapters/ch01.pdf \
  --output-jsonl data/ocr/ch01.jsonl \
  --output-pdf data/ocr/ch01.searchable.pdf \
  --sidecar-txt data/ocr/ch01.sidecar.txt \
  --lang spa --lang eng
```

### 5. Run OCR QA

```bash
uv run scanbook qa --input-jsonl data/ocr/ch01.jsonl --report-dir reports
```

### 6. Extract rule-based case candidates

```bash
uv run scanbook extract-cases --input data/markdown/ch01.md --output-jsonl data/json/ch01.cases.jsonl --schema schemas/clinical_case.schema.json
```

### 7. Build local index

```bash
uv run scanbook build-index --input-jsonl data/json/ch01.cases.jsonl --output-dir data/index/ch01 --vector-store lexical
```

### 8. Query local index

```bash
uv run scanbook query --index-dir data/index/ch01 --question "adult patient with chest pain"
```

`vector-store` modes:
- `lexical`: dependency-light searchable index (`chunks.jsonl` + `lexical_index.json`).
- `none`: only writes `chunks.jsonl` + `index_meta.json`.
- `faiss` / `chroma`: optional heavy embedding stores.

## First Real Book Workflow

1. Manually inspect the source PDF table of contents and numbering quirks.
2. Create chapter ranges in config with validated page offsets.
3. Run `split` and render sample pages per chapter.
4. Compare OCRmyPDF vs Docling on a 10-20 page sample before scaling.
5. Run QA on sample OCR outputs.
6. Batch full chapters only after sample quality is acceptable.

See [`docs/recommended_pipeline.md`](docs/recommended_pipeline.md) for the detailed pipeline guide.

## OCR Split Clinical Cases

Batch OCR, automated QA checks, and text extraction for already-split clinical-case PDFs. All output directories are structured under `data/ocr_cases/` which is fully Git-ignored.

The pipeline is completely resumable: already-processed cases are skipped automatically unless the `--force` flag is specified.

### Usage Examples

```bash
# Dry-run discovery
.\.venv\Scripts\python scripts/ocr_split_cases.py --dry-run --section seccion2 --subsection anemias_microciticas

# Limit test (process 2 cases)
.\.venv\Scripts\python scripts/ocr_split_cases.py --execute --section seccion2 --subsection anemias_microciticas --limit 2

# Full subsection
.\.venv\Scripts\python scripts/ocr_split_cases.py --execute --section seccion2 --subsection anemias_microciticas
```

## Colab Notebooks

The `notebooks/` directory contains Colab notebooks for GPU-accelerated post-processing:

| Notebook | Purpose | Requirements |
|---|---|---|
| `1_unified_to_sota_gptoss20b_clean.ipynb` | Build SOTA semantic layer: embeddings, neighbors, clusters, UMAP, GPT-OSS annotations | GPU (A100 recommended), `clinical_cases_bundle.duckdb` |
| `2_explorer_llmwiki_clean.ipynb` | Build explorer database + LLMWiki export: case catalog, star cases, interactive Plotly maps | CPU only, output of notebook 1 |

> **Note:** These notebooks are designed to work with the `clinical_cases_bundle.duckdb` produced by this pipeline. They serve as reference implementations — adapt the bundle path and configuration for your own book's data.

## Agent Interface (LLMWiki Scaffold)

The [`0_interfaz_clinical_cases_llmwiki_scaffold/`](0_interfaz_clinical_cases_llmwiki_scaffold/) directory provides a standalone agent interface for exploring curated clinical cases interactively. It includes:

- **Query and recommendation scripts** for finding cases by concept, difficulty, or clinical area
- **Interactive Plotly maps** (UMAP-based) for visual exploration
- **PDF viewer integration** for reading original case documents
- **Teacher review overlay** for recording pedagogical feedback
- **Multi-collection support** for managing multiple books/domains

See its [README](0_interfaz_clinical_cases_llmwiki_scaffold/README.md) and [AGENTS.md](0_interfaz_clinical_cases_llmwiki_scaffold/AGENTS.md) for agent operational rules.

## Optional Artifacts

Derived artifacts (DuckDB bundles, embeddings, vector indexes) are **not** included in this repository. They can be:

1. **Regenerated** from your own book using the pipeline above
2. **Shared** via external hosting (GitHub Releases, Google Drive, HuggingFace) for books you have rights to

See [`docs/optional_artifacts.md`](docs/optional_artifacts.md) for the full artifact schema and regeneration guide, and [`data/BOOKS_REFERENCE.md`](data/BOOKS_REFERENCE.md) for a catalog of books tested with the pipeline.

## Gemini CLI Handoff Workflow

This repo does **not** require Gemini for local extraction.
Use Gemini CLI externally after local chapter outputs are prepared:

1. Run split + OCR + QA + extraction locally.
2. Export chapter/subchapter markdown/json batches.
3. Send only needed batches to Gemini CLI for higher-level analysis/summarization.
4. Merge Gemini outputs back as separate derived artifacts (outside this repository if sensitive).

## OCR Profiles

- `fast_latin`: low DPI, quick inspection.
- `balanced_multilang`: mixed language academic text.
- `high_quality_tables`: higher DPI, slower, more robust for complex layouts.

Profiles are selected through config + backend flags; exact behavior depends on backend.

## Resource Policy

- Do not intentionally exceed about 40% system RAM or 40% VRAM.
- Keep OCR/index jobs batched (chapter-by-chapter and page subsets first).

## Copyright / Data Policy

- **Do not** commit source books, chapter PDFs, rendered pages, OCR outputs, markdown dumps, full extracted text, embeddings, or vector DB files.
- Keep this repo publish-safe: scripts/configs/schemas/tests/synthetic examples only.
- The `.gitignore` enforces this with defense-in-depth rules.
- See [`CONTRIBUTING.md`](CONTRIBUTING.md) for contribution guidelines.

## License

[MIT](LICENSE)
