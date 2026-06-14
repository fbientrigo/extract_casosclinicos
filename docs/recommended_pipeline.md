# Recommended Pipeline

## Overview

This guide walks through the end-to-end workflow for processing a scanned academic book into searchable, indexed clinical cases. Each step is designed for modest hardware with page-level or small-batch processing.

For the full "Bring Your Own Book" setup, start with the main [README](../README.md).

---

## 1) Manual TOC Inspection

1. Inspect the scanned PDF table of contents manually.
2. Decide chapter/subchapter ranges in physical page numbers.
3. Record ranges in `configs/book.<id>.yaml` with a `page_offset` if needed.
4. See [`configs/book.example.yaml`](../configs/book.example.yaml) for the config schema.

## 2) Chapter Splitting

```bash
uv run scanbook split --config configs/book.<id>.yaml
```

Outputs:
- Chapter PDFs in `data/chapters/`
- `manifest.jsonl` with source hash and page range metadata

## 3) OCR Multi-Backend Comparison

Use a small sample (for example 10-20 pages per chapter) and compare:
- `ocrmypdf` — reliable, good for Latin scripts
- `docling` — modern, layout-aware
- `paddle` — strong for complex layouts and CJK
- `marker` (optional, dependency/license complexity)

Keep runs small-batch to fit constrained hardware.

## 4) QA

```bash
uv run scanbook qa --input-jsonl data/ocr/ch01.jsonl --report-dir reports
```

Review:
- empty pages
- low-text pages
- repeated header/footer noise

Use the manual review template at `reports/templates/ocr_subset_review.md` for structured evaluation.

## 5) Case Extraction

Run rule-based candidate extraction:

```bash
uv run scanbook extract-cases --input data/markdown/ch01.md --output-jsonl data/json/ch01.cases.jsonl
```

No clinical inference is performed; only candidate block detection.

## 6) RAG Indexing

Build local embeddings/index:

```bash
uv run scanbook build-index --input-jsonl data/json/ch01.cases.jsonl --output-dir data/index/ch01 --vector-store faiss
```

Available `vector-store` modes:
- `lexical`: lightweight, no embedding dependencies
- `none`: writes chunks only
- `faiss` / `chroma`: full embedding stores (requires `--extra rag`)

Batch processing is recommended for large books.

## 7) Colab Notebooks (Optional, GPU)

For advanced semantic analysis, use the Colab notebooks in `notebooks/`:

1. **Notebook 1** (`1_unified_to_sota_gptoss20b_clean.ipynb`): Builds the SOTA quantitative semantic layer with embeddings, neighbors, consensus clustering, UMAP, and GPT-OSS structured annotations. Requires a GPU.
2. **Notebook 2** (`2_explorer_llmwiki_clean.ipynb`): Post-processes into an explorer database with star cases, interactive maps, and LLMWiki exports. CPU-only.

These produce the `clinical_cases_bundle_sota_gptoss20b.duckdb` and explorer databases used by the agent interface.

## 8) Agent Interface (Optional)

After producing the DuckDB bundles, set up the agent scaffold for interactive exploration:

1. Copy bundles into `0_interfaz_clinical_cases_llmwiki_scaffold/data/<collection>/`.
2. Configure `data/manifest.json` (see `data/manifest.example.json`).
3. Run `python scripts/validate_bundle.py` to verify.
4. Use the agent scripts for case recommendation, querying, and visualization.

See the [scaffold README](../0_interfaz_clinical_cases_llmwiki_scaffold/README.md) for details.

## 9) Gemini Analysis Batches (External, Optional)

This repository does not require Gemini to run local extraction.

Suggested handoff:
1. Export selected chapter case JSON/markdown.
2. Submit batches externally via Gemini CLI.
3. Store derived analysis separately from raw copyrighted material.

## Optional Artifacts

All derived artifacts (databases, embeddings, bundles) are documented in [`docs/optional_artifacts.md`](optional_artifacts.md). They can be regenerated from any configured book using the steps above.
