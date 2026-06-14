#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export canonical Colab datasets without embeddings.")
    parser.add_argument("--manifest", default=str(PROJECT_ROOT / "data/curated/clean_case_pdf_manifest.json"))
    parser.add_argument("--ocr-root", default=str(PROJECT_ROOT / "data/ocr_cases"))
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "data/colab_exports"))
    parser.add_argument("--ocr-version", default="clean_v2")
    args = parser.parse_args()

    manifest = _load_json(Path(args.manifest))
    by_case = {c["case_id"]: c for c in manifest.get("cases", [])}
    ocr_root = Path(args.ocr_root)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for meta_path in sorted(ocr_root.rglob("case_metadata.json")):
        meta = _load_json(meta_path)
        case_id = meta.get("case_id") or meta_path.parent.name
        m = by_case.get(case_id)
        if not m:
            continue
        clean_text = (meta_path.parent / "sidecar.txt").read_text(encoding="utf-8") if (meta_path.parent / "sidecar.txt").exists() else ""
        rows.append(
            {
                "case_id": case_id,
                "title": meta.get("title", ""),
                "section": m.get("section", ""),
                "subsection": m.get("subsection", ""),
                "printed_start_page": m.get("printed_start_page"),
                "printed_end_page": m.get("printed_end_page"),
                "clean_text": clean_text,
                "page_count": meta.get("page_count", 0),
                "char_count": len(clean_text),
                "source_pdf_path": m.get("source_pdf_path", ""),
                "clean_pdf_path": m.get("clean_pdf_path", ""),
                "boundary_decision": m.get("decision", ""),
                "boundary_source": m.get("boundary_source", "review_decisions_rule_v2.csv"),
                "ocr_version": args.ocr_version,
            }
        )

    df = pd.DataFrame(rows)
    jsonl_path = out_dir / "clinical_cases.jsonl"
    parquet_path = out_dir / "clinical_cases.parquet"
    sample_path = out_dir / "clinical_cases_sample.csv"
    embedding_manifest_path = out_dir / "embedding_manifest.json"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    df.to_parquet(parquet_path, index=False)
    df.head(25).to_csv(sample_path, index=False, quoting=csv.QUOTE_MINIMAL)
    embedding_manifest_path.write_text(
        json.dumps(
            {
                "status": "not_built",
                "reason": "Embeddings intentionally deferred for clean canonical rebuild.",
                "record_count": len(rows),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"exported={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
