#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse

from llmwiki_common import (
    add_collection_args,
    apply_filters,
    build_search_table,
    case_summary_row,
    collection_from_args,
    find_pdf_for_case,
    load_explorer_tables,
    print_table,
    score_cases_for_query,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Query curated clinical cases by concept/metadata.")
    add_collection_args(parser)
    parser.add_argument("query", nargs="?", default="", help="Natural-language query. Optional if filters are provided.")
    parser.add_argument("--concept", default=None, help="Extra concept keyword; appended to query.")
    parser.add_argument("--section", default=None)
    parser.add_argument("--subsection", default=None)
    parser.add_argument("--difficulty", default=None)
    parser.add_argument("--clinical-area", default=None)
    parser.add_argument("--case-type", default=None)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--show-pdf", action="store_true")
    args = parser.parse_args()

    paths = collection_from_args(args)
    tables = load_explorer_tables(paths)
    df = build_search_table(tables)
    df = apply_filters(df, args.section, args.subsection, args.difficulty, args.clinical_area, args.case_type)

    query = " ".join(x for x in [args.query, args.concept] if x).strip()
    if query:
        df = score_cases_for_query(df, query)
    else:
        df = df.copy()
        df["query_score"] = df.get("combined_star_score", 0.0)
        df["match_evidence"] = "metadata filters only"
        df = df.sort_values(["query_score", "case_number"], ascending=[False, True])

    top = df.head(args.top).copy()

    if args.show_pdf:
        pdf_paths = []
        for _, row in top.iterrows():
            p = find_pdf_for_case(paths, row)
            pdf_paths.append(str(p) if p else "")
        top["pdf_path"] = pdf_paths

    show_cols = [
        "case_number", "case_id", "title_clean", "section_label", "subsection_short",
        "difficulty", "case_type", "clinical_area", "query_score",
        "main_problem", "key_concepts_json", "learning_objectives_json",
        "match_evidence", "pdf_path",
    ]
    print(f"Collection: {paths.collection_id}")
    print(f"Results: {len(top)}")
    print_table(top, show_cols, max_colwidth=110)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
