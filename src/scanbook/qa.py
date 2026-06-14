from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from scanbook.utils import ensure_dir, read_jsonl


def run_qa(input_jsonl: Path, report_dir: Path, low_text_threshold: int | None = None) -> dict[str, Any]:
    rows = read_jsonl(input_jsonl)
    page_stats: list[dict[str, Any]] = []
    for row in rows:
        text = str(row.get("text", "") or "")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        header = lines[0] if lines else ""
        footer = lines[-1] if lines else ""
        page_stats.append(
            {
                "page_num": int(row.get("page_num", len(page_stats) + 1)),
                "char_count": len(text),
                "is_empty": len(text.strip()) == 0,
                "header": _normalize_line(header),
                "footer": _normalize_line(footer),
                "extractor": row.get("extractor"),
            }
        )

    non_empty_char_counts = [p["char_count"] for p in page_stats if p["char_count"] > 0]
    median_len = int(statistics.median(non_empty_char_counts)) if non_empty_char_counts else 0
    threshold = low_text_threshold if low_text_threshold is not None else max(40, int(median_len * 0.15))

    empty_pages = [p["page_num"] for p in page_stats if p["is_empty"]]
    suspicious_pages = [
        p["page_num"] for p in page_stats if (not p["is_empty"]) and p["char_count"] < threshold
    ]

    header_counts = Counter(p["header"] for p in page_stats if p["header"])
    footer_counts = Counter(p["footer"] for p in page_stats if p["footer"])
    repeated_headers = _repeated_lines(header_counts, min_repeat=3)
    repeated_footers = _repeated_lines(footer_counts, min_repeat=3)

    summary: dict[str, Any] = {
        "input": str(input_jsonl),
        "total_pages": len(page_stats),
        "empty_pages": empty_pages,
        "suspicious_low_text_pages": suspicious_pages,
        "low_text_threshold": threshold,
        "median_char_count_non_empty": median_len,
        "repeated_headers": repeated_headers,
        "repeated_footers": repeated_footers,
        "page_stats": page_stats,
    }
    write_qa_reports(summary=summary, report_dir=report_dir)
    return summary


def write_qa_reports(summary: dict[str, Any], report_dir: Path) -> None:
    ensure_dir(report_dir)
    json_path = report_dir / "qa_summary.json"
    md_path = report_dir / "qa_summary.md"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_format_md_summary(summary), encoding="utf-8")


def _repeated_lines(counter: Counter[str], min_repeat: int) -> list[dict[str, Any]]:
    return [
        {"line": line, "count": count}
        for line, count in sorted(counter.items(), key=lambda x: x[1], reverse=True)
        if count >= min_repeat
    ]


def _normalize_line(line: str) -> str:
    return " ".join(line.lower().strip().split())


def _format_md_summary(summary: dict[str, Any]) -> str:
    headers = ", ".join(f"'{x['line']}'({x['count']})" for x in summary["repeated_headers"]) or "None"
    footers = ", ".join(f"'{x['line']}'({x['count']})" for x in summary["repeated_footers"]) or "None"
    return (
        "# OCR QA Summary\n\n"
        f"- Input: `{summary['input']}`\n"
        f"- Total pages: {summary['total_pages']}\n"
        f"- Empty pages: {len(summary['empty_pages'])} -> {summary['empty_pages']}\n"
        f"- Suspicious low-text pages (< {summary['low_text_threshold']} chars): "
        f"{len(summary['suspicious_low_text_pages'])} -> {summary['suspicious_low_text_pages']}\n"
        f"- Median char count (non-empty): {summary['median_char_count_non_empty']}\n"
        f"- Repeated headers: {headers}\n"
        f"- Repeated footers: {footers}\n"
    )

