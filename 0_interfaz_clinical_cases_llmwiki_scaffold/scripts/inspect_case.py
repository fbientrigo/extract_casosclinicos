#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse

from llmwiki_common import (
    add_collection_args,
    build_search_table,
    collect_neighbors,
    collection_from_args,
    compact,
    find_pdf_for_case,
    list_to_bullets,
    load_explorer_tables,
    resolve_case_id,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect one case with teaching metadata and neighbors.")
    add_collection_args(parser)
    parser.add_argument("case", help="Case number or case_id.")
    parser.add_argument("--neighbors", type=int, default=5)
    args = parser.parse_args()

    paths = collection_from_args(args)
    tables = load_explorer_tables(paths)
    df = build_search_table(tables)
    case_id = resolve_case_id(df, args.case)
    row = df[df["case_id"].astype(str) == case_id].iloc[0]
    pdf = find_pdf_for_case(paths, row)

    print(f"Collection: {paths.collection_id}")
    print(f"Case {row.get('case_number')} · {row.get('title_clean')}")
    print(f"case_id: {row.get('case_id')}")
    print(f"section: {row.get('section_label')} / {row.get('subsection_short')}")
    print(f"difficulty: {row.get('difficulty')}")
    print(f"type: {row.get('case_type')}")
    print(f"clinical_area: {row.get('clinical_area')}")
    print(f"combined_star_score: {row.get('combined_star_score')}")
    print(f"pdf: {pdf if pdf else '(not found)'}")
    print("\nMain problem:")
    print(compact(row.get("main_problem"), 800))

    print("\nKey concepts:")
    print(list_to_bullets(row.get("key_concepts_json"), max_items=12) or "(empty)")

    print("\nLearning objectives:")
    print(list_to_bullets(row.get("learning_objectives_json"), max_items=12) or "(empty)")

    print("\nLaboratory / technical methods:")
    print(list_to_bullets(row.get("laboratory_methods_json"), max_items=12) or "(empty)")

    print("\nTeaching rationale:")
    print(compact(row.get("star_case_rationale"), 1000) or "(empty)")

    edges = collect_neighbors(tables, [case_id], args.neighbors)
    if not edges.empty:
        print("\nRelated cases:")
        for _, e in edges.iterrows():
            nid = str(e["neighbor_case_id"])
            nrow = df[df["case_id"].astype(str) == nid]
            if nrow.empty:
                print(f"- {nid}")
                continue
            nr = nrow.iloc[0]
            print(f"- {nr.get('case_number')} · {nr.get('title_clean')} [{nid}] sim={e.get('similarity')}")
    else:
        print("\nRelated cases: none found in neighbor tables.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
