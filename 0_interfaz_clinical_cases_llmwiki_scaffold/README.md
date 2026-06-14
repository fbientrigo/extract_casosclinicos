# Clinical Cases LLMWiki (Agent Interface)

Local interface for exploring **curated clinical cases** with the help of scripts and an LLM assistant.
Designed for teaching. **Not** for diagnosis or real clinical decisions.

This directory is the **agent interface layer**: a lightweight model (e.g., Gemini, GPT, or a local LLM via Ollama) orchestrates the scripts below instead of reasoning over raw files. Operational rules for the agent are in [`AGENTS.md`](AGENTS.md).

> **Data not included.** This repository publishes only the architecture. The
> actual collections (`book/`, `data/`, `llm_wiki/`) are generated locally with
> the `scanbook` pipeline from the root repository and are git-ignored.
> See the main [README](../README.md) for the full pipeline.

## Prerequisites

1. Run the main `scanbook` pipeline to produce a `clinical_cases_bundle.duckdb` (see [recommended pipeline](../docs/recommended_pipeline.md)).
2. Optionally run the Colab notebooks (`notebooks/`) for SOTA embeddings + GPT annotations.
3. Place the resulting bundles in `data/<collection>/`.

## Collections

Each collection (a book/domain) lives in:

- `book/<collection>/` — Case PDFs.
- `data/<collection>/` — Databases and curated bundles.
- `llm_wiki/<collection>/` — Explorer/LLMWiki exports.
- `data_updated/<collection>/` — Mutable overlay (agent outputs).

Configure the active collection in `data/manifest.json`
(see [`data/manifest.example.json`](data/manifest.example.json)).

## Quick Setup

### Windows

```powershell
.\setup_windows.ps1
```

### Manual

```bash
python -m pip install -r requirements.txt
```

### Environment

On Windows, load `env.ps1` in your PowerShell session:

```powershell
. .\env.ps1
```

## First Check

```bash
python scripts/validate_bundle.py --collection <collection_id>
```

Must finish with `VALIDATION PASSED`.

## Quick Command Reference

Replace `<collection>` with your collection ID. If there's only one collection, `--collection` is optional.

| Task | Command |
|---|---|
| List collections | `python scripts/list_collections.py` |
| Validate bundle | `python scripts/validate_bundle.py --collection <collection>` |
| Recommend cases | `python scripts/recommend_cases.py "query text" --top 5 --neighbors 3 --collection <collection>` |
| Search cases | `python scripts/query_cases.py "query text" --top 10 --collection <collection>` |
| Inspect a case | `python scripts/inspect_case.py <case_number> --collection <collection>` |
| Open case PDFs | `python scripts/open_case_pdf.py <n1> <n2> <n3> --collection <collection>` |
| Query map | `python scripts/plot_query_cases.py "query" --top 12 --neighbors 5 --open --collection <collection>` |
| Neighborhood map | `python scripts/plot_case_neighborhood.py <case_number> --neighbors 10 --open --collection <collection>` |
| Teacher review | `python scripts/update_teacher_review.py <case_number> --accepted-star yes --rating 5 --notes "..." --collection <collection>` |

## What the Agent Does (Summary)

- Understands the user's teaching request and uses local scripts.
- Recommends a small set of cases with pedagogical justification.
- Can open PDFs when asked.
- Generates interactive Plotly maps for visual exploration.
- Records teacher reviews in the mutable overlay.

## Simple Rules

- Do not modify `data/`, `book/`, or `llm_wiki/` (read-only).
- New files go to `data_updated/`.
- If something goes wrong, delete `data_updated/<collection>/` and start over.
- This system is for teaching only, not for diagnosis or treatment of real patients.
