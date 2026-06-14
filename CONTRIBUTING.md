# Contributing to scanbook-rag-lab

Thanks for your interest! **scanbook-rag-lab** is a local-first OCR/RAG pipeline
for scanned academic books. Contributions of any size are welcome — bug fixes,
new features, docs improvements, or pipeline enhancements.

## ⚠️ Golden Rule

> **Never commit copyrighted material.**
>
> This includes PDFs, OCR text, extracted content, embeddings, and vector
> databases. The `.gitignore` is configured to block these paths (`data/`,
> `books/`, `*.pdf`, `*.faiss`, etc.). **Do not override it.**
>
> The repository contains only *code and configuration*. All derived data
> stays on your local machine.

## Running Tests

We use **synthetic examples only** — no real book data in CI.

```bash
uv sync --extra core --extra dev
uv run pytest
```

## Adding Support for a New Book

1. Create a config YAML under `configs/` describing the book layout.
2. Run the pipeline locally to verify OCR and chunking quality.
3. Keep all derived data (`data/`, `books/`) local — commit only the config.

## Code Style

- **Python ≥ 3.11**
- Lint with [ruff](https://docs.astral.sh/ruff/):

```bash
uv run ruff check
```

- Fix auto-fixable issues:

```bash
uv run ruff check --fix
```

## Pull Request Guidelines

1. **Keep changes minimal** — one logical change per PR.
2. **Add or update tests** for any new functionality.
3. **Do not touch** `data/` or `books/` directories.
4. Ensure `uv run pytest` and `uv run ruff check` pass before opening a PR.
5. Write a clear PR description explaining *why*, not just *what*.

## License

By contributing you agree that your contributions will be licensed under the
[MIT License](LICENSE).
