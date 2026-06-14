#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone

import pandas as pd

from llmwiki_common import (
    add_collection_args,
    build_search_table,
    collection_from_args,
    collection_output_dir,
    load_explorer_tables,
    resolve_case_id,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Append/update human teacher review overlay.")
    add_collection_args(parser)
    parser.add_argument("case", help="Case number or case_id.")
    parser.add_argument("--accepted-star", choices=["yes", "no", "unknown"], default="unknown")
    parser.add_argument("--rating", type=float, default=None, help="Teacher rating, e.g. 1-5.")
    parser.add_argument("--time-min", type=int, default=None, help="Estimated teaching time in minutes.")
    parser.add_argument("--level", default="", help="Course level, e.g. pregrado, internado, avanzado.")
    parser.add_argument("--notes", default="", help="Teacher notes.")
    parser.add_argument("--reviewed-by", default="", help="Reviewer name/alias.")
    args = parser.parse_args()

    paths = collection_from_args(args)
    tables = load_explorer_tables(paths)
    df = build_search_table(tables)
    case_id = resolve_case_id(df, args.case)
    row = df[df["case_id"].astype(str) == case_id].iloc[0]

    out_dir = collection_output_dir(paths, "teacher_review")
    review_path = out_dir / "teacher_review.csv"

    new_row = {
        "collection_id": paths.collection_id,
        "case_id": case_id,
        "case_number": row.get("case_number"),
        "title_clean": row.get("title_clean"),
        "accepted_as_star_case": args.accepted_star,
        "teacher_rating": args.rating,
        "estimated_class_time_min": args.time_min,
        "recommended_course_level": args.level,
        "teacher_notes": args.notes,
        "reviewed_by": args.reviewed_by,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }

    if review_path.exists():
        existing = pd.read_csv(review_path)
        existing = existing[existing["case_id"].astype(str) != str(case_id)]
        out = pd.concat([existing, pd.DataFrame([new_row])], ignore_index=True)
    else:
        out = pd.DataFrame([new_row])

    out.to_csv(review_path, index=False)
    print("Wrote:", review_path)
    print(pd.DataFrame([new_row]).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
