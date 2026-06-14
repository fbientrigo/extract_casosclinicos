#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse

from llmwiki_common import (
    add_collection_args,
    build_search_table,
    collection_from_args,
    find_pdf_for_case,
    load_explorer_tables,
    open_path,
    resolve_case_id,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Open one or more case PDFs.")
    add_collection_args(parser)
    parser.add_argument("cases", nargs="+", help="Case numbers or case_ids.")
    parser.add_argument("--max-open", type=int, default=3, help="Safety limit. Default: 3.")
    parser.add_argument("--force", action="store_true", help="Allow opening more than --max-open.")
    args = parser.parse_args()

    if len(args.cases) > args.max_open and not args.force:
        raise SystemExit(f"Refusing to open {len(args.cases)} PDFs. Limit is {args.max_open}. Use --force if intentional.")

    paths = collection_from_args(args)
    tables = load_explorer_tables(paths)
    df = build_search_table(tables)

    opened = 0
    for ref in args.cases:
        case_id = resolve_case_id(df, ref)
        row = df[df["case_id"].astype(str) == case_id].iloc[0]
        pdf = find_pdf_for_case(paths, row)
        if pdf is None:
            print(f"PDF not found for {ref} -> {case_id}")
            continue
        print(f"Opening case {row.get('case_number')} · {row.get('title_clean')}: {pdf}")
        open_path(pdf)
        opened += 1

    print(f"Opened {opened}/{len(args.cases)} PDFs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
