# Optional Artifacts

All databases, embedding vectors, and curated bundles in this repository are
**derived artifacts** — they are produced entirely from a user's own scanned
book by running the pipeline. They are not required to clone or use the
scaffold; they can be downloaded separately or regenerated from scratch.

## What counts as an optional artifact?

| Artifact | Format | Produced by |
|---|---|---|
| OCR + case metadata | SQLite (`.db`) | `scanbook extract-cases` |
| Curated bundle | DuckDB (`.duckdb`) | bundle-export notebook |
| Embedding vectors | BLOB / `.npy` | Colab embedding notebook |
| FAISS search index | `.faiss` | `scanbook build-index` |
| UMAP coordinates | JSON / Parquet | Colab UMAP notebook |
| LLM annotation layer | JSON in SQLite | Gemini / GPT batch job |

None of these are checked into the main branch. They live under `data/` and
are git-ignored by default.

## Directory layout

```
data/
├── <book_id>/
│   ├── clinical_cases.db             # SQLite: OCR + case metadata
│   ├── clinical_cases_bundle.duckdb  # DuckDB: curated bundle
│   ├── index/                        # FAISS index files
│   └── embeddings/                   # .npy vectors, UMAP coords
├── ocr_cases/                        # OCR JSONL outputs
├── bundles/                          # Portable DuckDB bundles
└── curated/                          # Manual curation overlays
```

Each `<book_id>` directory is self-contained: you can delete it and regenerate
everything from the source PDF and its config file.

## How to regenerate from your own book

1. **Configure** — create `configs/book.<id>.yaml` with chapter ranges and
   `page_offset` (see `docs/recommended_pipeline.md`).
2. **Run the local pipeline** — split → OCR → QA → extract → index:
   ```bash
   uv run scanbook split   --config configs/book.<id>.yaml
   uv run scanbook ocr     --config configs/book.<id>.yaml
   uv run scanbook qa      --input-jsonl data/ocr/<chapter>.jsonl --report-dir reports
   uv run scanbook extract-cases --input data/markdown/<chapter>.md --output-jsonl data/json/<chapter>.cases.jsonl
   uv run scanbook build-index   --input-jsonl data/json/<chapter>.cases.jsonl --output-dir data/<id>/index
   ```
3. **SOTA embeddings + LLM annotations** — open the Colab notebooks in
   `notebooks/` to generate dense vectors (e.g., `text-embedding-3-large`)
   and GPT/Gemini case-card annotations.
4. **Explore** — use the agent scaffold or the Streamlit app to query the
   resulting index and database.

## Sharing artifacts

If you hold distribution rights for the source material, you may share your
derived bundles so others can explore the data without re-running the pipeline.

Recommended hosts:

- **GitHub Releases** — attach `.duckdb` files to a tagged release.
- **Google Drive / HuggingFace Datasets** — for larger bundles (>100 MB).

The scaffold does not hard-code any remote URL. Point it to any local path:

```yaml
# configs/book.<id>.yaml
bundle_path: data/bundles/my_book_bundle.duckdb
```

> [!IMPORTANT]
> Never distribute raw OCR text from copyrighted books. Share only the
> structured metadata and derived annotations you are licensed to distribute.

## Schema reference

For the full SQLite table definitions (13 tables), see
[clinical_cases_database_schema.md](clinical_cases_database_schema.md).
