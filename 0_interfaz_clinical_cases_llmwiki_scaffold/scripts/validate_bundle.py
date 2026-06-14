#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from llmwiki_common import (
    add_collection_args,
    collection_from_args,
    find_pdf_for_case,
    load_explorer_tables,
    build_search_table,
    read_table,
    table_exists,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Clinical Cases LLMWiki collection.")
    add_collection_args(parser)
    parser.add_argument("--expected-cases", type=int, default=None, help="Expected number of cases. If omitted, inferred from explorer DB.")
    parser.add_argument("--require-pdfs", action="store_true", help="Fail if one or more PDFs cannot be found under book_dir.")
    parser.add_argument("--require-full-llm", action="store_true", help="Require source_case_llm_annotations coverage.")
    args = parser.parse_args()

    paths = collection_from_args(args)
    print("Resolved collection:")
    for k, v in paths.as_dict().items():
        print(f"  {k}: {v}")

    assert paths.explorer_db.exists(), f"Missing explorer DB: {paths.explorer_db}"
    assert paths.wiki_dir.exists(), f"Missing wiki dir: {paths.wiki_dir}"
    assert paths.book_dir.exists(), f"Missing book dir: {paths.book_dir}"

    tables = load_explorer_tables(paths)
    search_df = build_search_table(tables)

    n_cases = search_df["case_id"].astype(str).nunique()
    expected = args.expected_cases or n_cases

    checks = []

    def add(name: str, passed: bool, detail: str):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    add("case_count", n_cases == expected, f"{n_cases}/{expected}")

    if "umap2_x" in search_df.columns and "umap2_y" in search_df.columns:
        n_proj = search_df.dropna(subset=["umap2_x", "umap2_y"])["case_id"].nunique()
        add("2d_projection_coverage", n_proj == n_cases, f"{n_proj}/{n_cases}")
    else:
        add("2d_projection_coverage", False, "Missing umap2_x/umap2_y")

    if "umap3_x" in search_df.columns and "umap3_y" in search_df.columns and "umap3_z" in search_df.columns:
        n_proj3 = search_df.dropna(subset=["umap3_x", "umap3_y", "umap3_z"])["case_id"].nunique()
        add("3d_projection_coverage", n_proj3 == n_cases, f"{n_proj3}/{n_cases}")
    else:
        add("3d_projection_coverage", False, "Missing 3D UMAP columns")

    llm = tables.get("source_case_llm_annotations", pd.DataFrame())
    if not llm.empty and "case_id" in llm.columns:
        n_llm = llm["case_id"].astype(str).nunique()
        add("llm_annotation_coverage", n_llm == n_cases, f"{n_llm}/{n_cases}")
    else:
        add("llm_annotation_coverage", not args.require_full_llm, "source_case_llm_annotations missing or empty")

    star_cases = tables.get("star_cases", pd.DataFrame())
    add("star_cases_present", not star_cases.empty, f"rows={len(star_cases)}")

    star_neighbors = tables.get("star_neighbors", pd.DataFrame())
    add("star_neighbors_present", not star_neighbors.empty, f"rows={len(star_neighbors)}")

    missing_pdfs = []
    for _, row in search_df.iterrows():
        p = find_pdf_for_case(paths, row)
        if p is None:
            missing_pdfs.append(row.get("case_id"))

    add("pdf_resolution", len(missing_pdfs) == 0 or not args.require_pdfs, f"missing={len(missing_pdfs)}")

    report = pd.DataFrame(checks)
    print("\nValidation report:")
    print(report.to_string(index=False))

    if missing_pdfs:
        print("\nFirst missing PDFs:")
        for cid in missing_pdfs[:20]:
            print(" -", cid)

    if paths.bundle_db:
        print("\nFull bundle exists:", paths.bundle_db.exists(), paths.bundle_db)
    if paths.base_db:
        print("Base DB exists:", paths.base_db.exists(), paths.base_db)

    failed = report[~report["passed"]]
    if not failed.empty:
        raise SystemExit("Validation failed. Fix collection paths or data coverage before using the agent.")

    print("\nVALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
