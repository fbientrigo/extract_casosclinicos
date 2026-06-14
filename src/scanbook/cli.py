from __future__ import annotations

import argparse
import json
from pathlib import Path

from scanbook.build_index import build_index
from scanbook.db import build_cases_db
from scanbook.extract_cases import extract_case_candidates
from scanbook.ocr.audit_env import audit_environment
from scanbook.ocr.runner import get_backend
from scanbook.qa import run_qa
from scanbook.query import query_index
from scanbook.render_pages import render_pages
from scanbook.split_pdf import split_pdf_from_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scanbook", description="Scanned-book OCR/RAG pipeline CLI.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_split = sub.add_parser("split", help="Split source PDF into chapter PDFs from config.")
    p_split.add_argument("--config", required=True, type=Path, help="Path to book config YAML.")
    p_split.set_defaults(func=cmd_split)

    p_render = sub.add_parser("render-pages", help="Render selected pages for manual inspection.")
    p_render.add_argument("--input-pdf", required=True, type=Path)
    p_render.add_argument("--pages", required=True, help='Page selection like "1,3-5".')
    p_render.add_argument("--dpi", type=int, default=144)
    p_render.add_argument("--output-dir", required=True, type=Path)
    p_render.add_argument("--contact-sheet", action="store_true")
    p_render.set_defaults(func=cmd_render_pages)

    p_ocr = sub.add_parser("ocr", help="Run OCR backend and write page JSONL.")
    p_ocr.add_argument("--backend", required=True, choices=["ocrmypdf", "docling", "marker", "paddle"])
    p_ocr.add_argument("--input-pdf", required=True, type=Path)
    p_ocr.add_argument("--output-jsonl", required=True, type=Path)
    p_ocr.add_argument("--lang", action="append", default=[])
    p_ocr.add_argument("--profile", default="balanced_multilang")
    p_ocr.add_argument("--chapter-id")
    p_ocr.add_argument("--output-pdf", type=Path, default=None)
    p_ocr.add_argument("--sidecar-txt", type=Path, default=None)
    p_ocr.set_defaults(func=cmd_ocr)

    p_qa = sub.add_parser("qa", help="Generate OCR QA summary from OCR JSONL.")
    p_qa.add_argument("--input-jsonl", required=True, type=Path)
    p_qa.add_argument("--report-dir", required=True, type=Path)
    p_qa.add_argument("--low-text-threshold", type=int, default=None)
    p_qa.set_defaults(func=cmd_qa)

    p_extract = sub.add_parser("extract-cases", help="Extract rule-based clinical-case candidates.")
    p_extract.add_argument("--input", required=True, nargs="+", type=Path)
    p_extract.add_argument("--output-jsonl", required=True, type=Path)
    p_extract.add_argument("--schema", type=Path, default=None)
    p_extract.set_defaults(func=cmd_extract_cases)

    p_index = sub.add_parser("build-index", help="Build local embedding index from case/chunk JSONL.")
    p_index.add_argument("--input-jsonl", required=True, type=Path)
    p_index.add_argument("--output-dir", required=True, type=Path)
    p_index.add_argument("--model-name", default="sentence-transformers/all-MiniLM-L6-v2")
    p_index.add_argument("--vector-store", choices=["none", "lexical", "faiss", "chroma"], default="lexical")
    p_index.add_argument("--batch-size", type=int, default=8)
    p_index.set_defaults(func=cmd_build_index)

    p_query = sub.add_parser("query", help="Query local index.")
    p_query.add_argument("--index-dir", required=True, type=Path)
    p_query.add_argument("--question", required=True)
    p_query.add_argument("--top-k", type=int, default=5)
    p_query.add_argument("--model-name", default=None)
    p_query.add_argument("--output-json", type=Path, default=None)
    p_query.set_defaults(func=cmd_query)

    p_build_db = sub.add_parser("build-db", help="Consolidate all OCR case outputs into a portable SQLite/DuckDB database.")
    p_build_db.add_argument("--book-id", required=True, help="ID of the book to process (mandatory).")
    p_build_db.add_argument("--db-engine", choices=["sqlite", "duckdb"], default="sqlite", help="Database engine to use (default: sqlite).")
    p_build_db.add_argument("--ocr-cases-dir", type=Path, default=None, help="Root directory where completed OCR case folders live.")
    p_build_db.add_argument("--manifest", type=Path, default=None, help="Path to book split manifest.")
    p_build_db.add_argument("--output-db", type=Path, default=None, help="Path to output database.")
    p_build_db.add_argument("--curated-dir", type=Path, default=None, help="Path to curated output files directory.")
    p_build_db.set_defaults(func=cmd_build_db)

    p_ask = sub.add_parser(
        "ask",
        help="Answer a question over a local index using a local LLM via Ollama (optional).",
    )
    p_ask.add_argument("--index-dir", required=True, type=Path)
    p_ask.add_argument("--question", required=True)
    # Default model is small and multilingual; runs in <5GB VRAM (also CPU-only).
    p_ask.add_argument("--model", default="qwen2.5:3b")
    p_ask.add_argument("--host", default=None, help="Ollama host (default: env OLLAMA_HOST or http://localhost:11434).")
    p_ask.add_argument("--top-k", type=int, default=5)
    p_ask.add_argument("--output-json", type=Path, default=None)
    p_ask.set_defaults(func=cmd_ask)

    p_audit = sub.add_parser("audit-env", help="Print environment and optional backend availability.")
    p_audit.set_defaults(func=cmd_audit_env)
    return parser


def cmd_split(args: argparse.Namespace) -> int:
    manifest = split_pdf_from_config(args.config)
    print(f"Wrote manifest: {manifest}")
    return 0


def cmd_render_pages(args: argparse.Namespace) -> int:
    images = render_pages(
        input_pdf=args.input_pdf,
        output_dir=args.output_dir,
        pages_spec=args.pages,
        dpi=args.dpi,
        contact_sheet=args.contact_sheet,
    )
    print(f"Rendered {len(images)} page images to {args.output_dir}")
    return 0


def cmd_ocr(args: argparse.Namespace) -> int:
    backend = get_backend(args.backend)
    results = backend.run(
        input_pdf=args.input_pdf,
        output_jsonl=args.output_jsonl,
        language=args.lang or ["eng"],
        profile=args.profile,
        chapter_id=args.chapter_id,
        output_pdf=args.output_pdf,
        sidecar_txt=args.sidecar_txt,
    )
    print(f"OCR complete with backend={args.backend}; pages={len(results)}; out={args.output_jsonl}")
    return 0


def cmd_qa(args: argparse.Namespace) -> int:
    summary = run_qa(
        input_jsonl=args.input_jsonl,
        report_dir=args.report_dir,
        low_text_threshold=args.low_text_threshold,
    )
    print(
        f"QA complete: total_pages={summary['total_pages']}, "
        f"empty={len(summary['empty_pages'])}, suspicious={len(summary['suspicious_low_text_pages'])}"
    )
    return 0


def cmd_extract_cases(args: argparse.Namespace) -> int:
    rows = extract_case_candidates(
        inputs=args.input,
        output_jsonl=args.output_jsonl,
        schema_path=args.schema,
    )
    print(f"Extracted {len(rows)} case candidates to {args.output_jsonl}")
    return 0


def cmd_build_index(args: argparse.Namespace) -> int:
    meta = build_index(
        input_jsonl=args.input_jsonl,
        output_dir=args.output_dir,
        model_name=args.model_name,
        vector_store=args.vector_store,
        batch_size=args.batch_size,
    )
    print(json.dumps(meta, indent=2))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    hits = query_index(
        index_dir=args.index_dir,
        question=args.question,
        top_k=args.top_k,
        model_name=args.model_name,
    )
    if args.output_json:
        args.output_json.write_text(json.dumps(hits, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote query results to {args.output_json}")
    else:
        print(json.dumps(hits, indent=2, ensure_ascii=False))
    return 0


def cmd_build_db(args: argparse.Namespace) -> int:
    project_root = Path(__file__).resolve().parent.parent.parent
    book_id = args.book_id
    
    ocr_dir = args.ocr_cases_dir or (project_root / "data" / "ocr_cases" / book_id)
    manifest_path = args.manifest or (project_root / "book" / book_id / "book_split_manifest.yaml")
    
    if args.output_db:
        output_db = args.output_db
    else:
        db_ext = "duckdb" if args.db_engine == "duckdb" else "db"
        output_db = project_root / "data" / f"{book_id}.{db_ext}"
        
    curated_dir = args.curated_dir or (ocr_dir / "curated")

    if not ocr_dir.exists():
        print(f"Error: OCR cases directory '{ocr_dir}' does not exist.")
        return 1

    print(f"Consolidating OCR outputs into {args.db_engine.upper()} database and registry layer...")
    print(f"  - Book ID: {book_id}")
    print(f"  - OCR Dir: {ocr_dir}")
    print(f"  - Manifest: {manifest_path}")
    print(f"  - Output DB: {output_db}")
    print(f"  - Curated Dir: {curated_dir}")
    
    try:
        report = build_cases_db(
            ocr_cases_dir=ocr_dir,
            manifest_path=manifest_path,
            output_db=output_db,
            curated_dir=curated_dir,
            db_engine=args.db_engine
        )
        print(f"Database build successful! Total cases: {report['total_cases_inserted']}")
        return 0
    except Exception as e:
        print(f"Error: Failed to build cases database: {e}")
        import traceback
        traceback.print_exc()
        return 1


def cmd_ask(args: argparse.Namespace) -> int:
    # Lazy import: the local LLM feature is optional and isolated.
    from scanbook.local_llm import LocalLLMError, answer_question, format_answer

    try:
        result = answer_question(
            index_dir=args.index_dir,
            question=args.question,
            model=args.model,
            host=args.host,
            top_k=args.top_k,
        )
    except LocalLLMError as exc:
        print(str(exc))
        return 2

    if args.output_json:
        args.output_json.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Wrote answer to {args.output_json}")
    else:
        print(format_answer(result))
    return 0


def cmd_audit_env(args: argparse.Namespace) -> int:
    _ = args
    print(json.dumps(audit_environment(), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
