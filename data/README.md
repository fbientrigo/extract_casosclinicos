# `data/` — Runtime Outputs (Not Version-Controlled)

This directory contains **locally generated artifacts** produced by the `scanbook` pipeline: chapter PDFs, rendered pages, OCR JSONL, indexes, databases, and exports.

All contents are **ignored by git** on purpose (see `.gitignore`). Copyrighted derived material is never committed.

## Expected Directory Structure

| Subdirectory | Contents | Producer |
|---|---|---|
| `raw/` | Source PDFs (user input) | Manual |
| `chapters/` | Split chapter/section PDFs | `scanbook split` |
| `pages/` | Rendered page images for inspection | `scanbook render-pages` |
| `ocr/` | OCR JSONL outputs (per chapter) | `scanbook ocr` |
| `ocr_cases/` | OCR outputs for individual split cases | `scripts/ocr_split_cases.py` |
| `json/` | Clinical case candidate JSONL | `scanbook extract-cases` |
| `index/` | Local indexes (lexical / FAISS / Chroma) | `scanbook build-index` |
| `curated/` | Manual curation overlays | Curation scripts |
| `bundles/` | Portable DuckDB bundles | `scripts/build_duckdb_bundle.py` |
| `audits/` | Audit reports and boundary reviews | Audit scripts |
| `colab_exports/` | Outputs from Colab notebooks | Notebooks |

## Per-Book Data

Each book gets its own subdirectory under `data/`:

```
data/
├── <book_id>/
│   ├── clinical_cases.db           # SQLite: OCR + case metadata
│   ├── clinical_cases_bundle.duckdb # DuckDB: curated bundle
│   └── ...
├── ocr_cases/
│   └── <book_id>/                  # OCR outputs per book
└── curated/
    └── <book_id>/                  # Curations per book
```

## Regeneration

You can delete this entire directory and regenerate it by re-running the pipeline. See the [recommended pipeline](../docs/recommended_pipeline.md) and [optional artifacts guide](../docs/optional_artifacts.md) for details.

## Book Reference

See [`BOOKS_REFERENCE.md`](BOOKS_REFERENCE.md) for a catalog of books tested with the pipeline.
