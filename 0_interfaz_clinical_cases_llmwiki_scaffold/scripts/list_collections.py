#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

from llmwiki_common import discover_collections, project_root


def main() -> int:
    root = project_root()
    df = discover_collections(root)
    print("Project root:", root)
    if df.empty:
        print("No collections discovered.")
        print("Expected at least one llm_wiki/<collection>/clinical_cases_explorer_llmwiki.duckdb")
        return 1
    print(df.to_string(index=False, max_colwidth=120))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
