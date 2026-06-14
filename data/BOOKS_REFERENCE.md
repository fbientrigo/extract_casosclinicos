# Books Reference

This file catalogs books that have been tested with the scanbook-rag-lab pipeline.
It contains **bibliographic references only** — no copyrighted content is distributed.
You must obtain your own legal copy of each book before processing it.

## Tested Books

| Book ID | Domain | Language | Pages | Notes |
| --- | --- | --- | --- | --- |
| `2014_laboratorio` | Clinical Laboratory / Hematology | Spanish | ~783 | Scanned PDF. Clinical cases organized by medical specialty sections. Contains ~200+ clinical cases. |
| `2026_oftalmologia` | Ophthalmology | Spanish | ~300 | Digital PDF with text layer. Clinical cases organized by ophthalmic pathology sections. |

## Adding Your Own Book

1. Copy the example config:
   ```bash
   cp configs/book.example.yaml configs/book.<your_id>.yaml
   ```
2. Fill in chapter/section ranges from the book's table of contents.
3. Run the pipeline:
   ```bash
   uv run scanbook split --config configs/book.<your_id>.yaml
   ```
4. If you want to share the config, add your book to the table above in a PR.

> [!NOTE]
> The pipeline is book-agnostic. Any scanned or digital PDF with structured clinical cases can be processed.
