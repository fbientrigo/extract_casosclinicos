#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import pandas as pd

from llmwiki_common import (
    add_collection_args,
    apply_filters,
    build_search_table,
    collection_from_args,
    collect_neighbors,
    compact,
    find_pdf_for_case,
    list_to_inline,
    load_explorer_tables,
    score_cases_for_query,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Recommend teaching cases from a natural-language request.")
    add_collection_args(parser)
    parser.add_argument("request", help="Teaching request, e.g. 'casos de anemia para clase introductoria'.")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--neighbors", type=int, default=3)
    parser.add_argument("--section", default=None)
    parser.add_argument("--subsection", default=None)
    parser.add_argument("--difficulty", default=None)
    parser.add_argument("--clinical-area", default=None)
    parser.add_argument("--case-type", default=None)
    args = parser.parse_args()

    paths = collection_from_args(args)
    tables = load_explorer_tables(paths)
    df = build_search_table(tables)
    df = apply_filters(df, args.section, args.subsection, args.difficulty, args.clinical_area, args.case_type)
    scored = score_cases_for_query(df, args.request)
    top = scored.head(args.top).copy()

    if top.empty:
        print("No cases found.")
        return 1

    neighbor_edges = collect_neighbors(tables, top["case_id"].astype(str).tolist(), args.neighbors)

    print(f"Collection: {paths.collection_id}")
    print(f"Request: {args.request}")
    print(f"Recommended cases: {len(top)}\n")

    for i, (_, row) in enumerate(top.iterrows(), start=1):
        pdf = find_pdf_for_case(paths, row)
        print(f"{i}. Case {row.get('case_number')} · {row.get('title_clean')}")
        print(f"   case_id: {row.get('case_id')}")
        print(f"   section: {row.get('section_label')} / {row.get('subsection_short')}")
        print(f"   difficulty: {row.get('difficulty')} | type: {row.get('case_type')} | area: {row.get('clinical_area')}")
        print(f"   score: {row.get('query_score'):.3f} | star: {row.get('combined_star_score')}")
        print(f"   main problem: {compact(row.get('main_problem'), 240)}")
        print(f"   key concepts: {list_to_inline(row.get('key_concepts_json'), max_items=6)}")
        print(f"   learning objectives: {list_to_inline(row.get('learning_objectives_json'), max_items=4)}")
        print(f"   evidence: {compact(row.get('match_evidence'), 280)}")
        print(f"   pdf: {pdf if pdf else '(not found)'}")

        edges = neighbor_edges[neighbor_edges["source_case_id"] == str(row.get("case_id"))]
        if not edges.empty:
            rel = []
            for _, e in edges.iterrows():
                nid = e["neighbor_case_id"]
                nrow = df[df["case_id"].astype(str) == str(nid)]
                if not nrow.empty:
                    nr = nrow.iloc[0]
                    rel.append(f"{nr.get('case_number')} ({nid})")
                else:
                    rel.append(str(nid))
            print(f"   related: {', '.join(rel)}")
        print()

    print("Next useful actions:")
    print("- To visualize this request: python scripts/plot_query_cases.py \"...\" --top 12 --neighbors 5 --open")
    print("- To inspect one case: python scripts/inspect_case.py <case_number>")
    print("- To open up to 3 PDFs: python scripts/open_case_pdf.py <case_number1> <case_number2> <case_number3>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
