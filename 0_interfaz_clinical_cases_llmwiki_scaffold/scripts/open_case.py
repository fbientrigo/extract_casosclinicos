#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unified, cross-machine case opener.

Gives the teacher reliable access to both a case PDF and its extracted text.

Modes:
    --mode pdf    Request the OS (or an explicit viewer) to open the PDF.
    --mode text   Write a UTF-8 transcript and open it in Notepad.
    --mode both   Do both.
    --mode auto   Try the PDF; if the launch raises (or --fallback-text is
                  set), also open the transcript in Notepad.
    --diagnose    Print a compact diagnostic report and exit.

Design rule: a clean launch return NEVER proves a viewer window is visible.
This tool only ever reports "launch requested" or "launch failed".
"""

from __future__ import annotations

import argparse
import platform
import sys

from llmwiki_common import (
    add_collection_args,
    build_search_table,
    collection_from_args,
    find_pdf_for_case,
    launch_pdf,
    load_explorer_tables,
    open_in_notepad,
    pdf_association_info,
    resolve_case_id,
    resolve_viewer,
    select_case_text,
    write_case_transcript,
)


def _load_case(args):
    paths = collection_from_args(args)
    tables = load_explorer_tables(paths)
    df = build_search_table(tables)
    case_id = resolve_case_id(df, args.case)
    row = df[df["case_id"].astype(str) == case_id].iloc[0]
    pdf = find_pdf_for_case(paths, row)
    return paths, row, pdf


def _do_pdf(row, pdf, viewer):
    if pdf is None:
        print(f"PDF: not found for case {row.get('case_number')} · {row.get('case_id')}")
        return "missing"
    print(f"PDF path : {pdf}  (file found)")
    result = launch_pdf(pdf, viewer=viewer)
    if result["status"] == "launch_requested":
        print(f"PDF: launch requested via {result['mechanism']} "
              f"(a visible window is NOT confirmed).")
    elif result["status"] == "launch_failed":
        print(f"PDF: launch failed via {result['mechanism']}: {result['error']}")
    else:
        print(f"PDF: {result['error']}")
    return result["status"]


def _do_text(paths, row, pdf):
    selection = select_case_text(row)
    if not selection["text"]:
        print("TEXT: no transcription available for this case (nothing written).")
        return None, "missing"
    out_path = write_case_transcript(paths, row, selection, pdf_path=pdf)
    trunc = "  [TRUNCATED preview]" if selection["truncated"] else ""
    print(f"TEXT path: {out_path}  (source: {selection['source_field']}{trunc})")
    result = open_in_notepad(out_path)
    if result["status"] == "launch_requested":
        print(f"TEXT: launch requested via {result['mechanism']} "
              f"(a visible window is NOT confirmed).")
    elif result["status"] == "launch_failed":
        print(f"TEXT: launch failed via {result['mechanism']}: {result['error']}")
    return out_path, result["status"]


def _do_diagnose(paths, row, pdf, viewer):
    info = pdf_association_info()
    selection = select_case_text(row)
    print("=" * 60)
    print("OPEN-CASE DIAGNOSTIC")
    print("=" * 60)
    print(f"platform        : {info['platform']}")
    print(f"python          : {sys.executable}")
    print(f"collection      : {paths.collection_id}")
    print(f"case            : {row.get('case_number')} · {row.get('case_id')}")
    print(f"pdf resolved    : {pdf if pdf else '(not found)'}")
    print(f"pdf exists      : {bool(pdf and pdf.exists())}")
    if info.get("pdf_progid"):
        print(f"pdf association : {info['pdf_progid']}")
    elif info.get("pdf_progid_error"):
        print(f"pdf association : (could not read: {info['pdf_progid_error']})")
    detected = ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in info.get("viewers", {}).items())
    if detected:
        print(f"viewers detected: {detected}")
    print(f"text source     : {selection['source_field'] or '(none)'}"
          + ("  [TRUNCATED preview]" if selection["truncated"] else ""))
    # A launch attempt is the only observable evidence: does it raise or not?
    if pdf is not None:
        probe = launch_pdf(pdf, viewer=viewer)
        print(f"launch attempt  : {probe['status']} via {probe['mechanism']}"
              + (f" ({probe['error']})" if probe["error"] else ""))
        if probe["status"] == "launch_requested":
            print("next action     : if no window appeared, use --mode text for a "
                  "reliable Notepad transcript.")
        else:
            print("next action     : PDF launch failed; use --mode text for the transcript.")
    else:
        print("next action     : PDF not found; use --mode text, or check the book/ directory.")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Open a case PDF and/or its extracted text.")
    add_collection_args(parser)
    parser.add_argument("case", help="Case number or case_id.")
    parser.add_argument("--mode", choices=["auto", "pdf", "text", "both"], default="auto")
    parser.add_argument("--viewer", choices=["edge", "acrobat"], default=None,
                        help="Force an explicit installed PDF viewer instead of the OS default.")
    parser.add_argument("--fallback-text", action="store_true",
                        help="In auto mode, always open the transcript too.")
    parser.add_argument("--diagnose", action="store_true",
                        help="Print a diagnostic report and exit.")
    args = parser.parse_args()

    viewer = None
    if args.viewer:
        viewer = resolve_viewer(args.viewer)
        if viewer is None:
            print(f"Requested viewer '{args.viewer}' not found; using OS default.", file=sys.stderr)

    try:
        paths, row, pdf = _load_case(args)
    except Exception as exc:  # noqa: BLE001 - resolution failures must be nonzero
        print(f"Could not resolve case {args.case!r}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"Collection: {paths.collection_id}")
    print(f"Case {row.get('case_number')} · {row.get('title_clean')}  [{row.get('case_id')}]")

    if args.diagnose:
        _do_diagnose(paths, row, pdf, viewer)
        return 0

    failed = False
    if args.mode in ("pdf", "both"):
        status = _do_pdf(row, pdf, viewer)
        failed = failed or status in ("missing", "launch_failed")
    if args.mode in ("text", "both"):
        _, status = _do_text(paths, row, pdf)
        failed = failed or status == "missing"
    if args.mode == "auto":
        pdf_status = _do_pdf(row, pdf, viewer)
        if pdf_status in ("missing", "launch_failed") or args.fallback_text:
            _, text_status = _do_text(paths, row, pdf)
            failed = failed or (pdf_status in ("missing", "launch_failed") and text_status == "missing")
        else:
            print("Tip: if the PDF window did not appear, run with --mode text "
                  "(or --fallback-text) for a Notepad transcript.")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
