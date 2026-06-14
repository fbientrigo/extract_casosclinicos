#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTO_NOTES = (
    "Auto-filled from human-confirmed structural pattern: "
    "first_detected_footer = expected_start - 2 from 306_anafilaxia through 767_pediculosis."
)

CSV_COLUMNS = [
    "case_id",
    "section",
    "subsection",
    "severity",
    "suggested_trim_pages",
    "human_decision",
    "human_trim_pages",
    "confidence",
    "notes",
    "page1_previous_case",
    "page2_previous_case",
    "case_starts_correctly",
    "render_ocr_mismatch",
    "source",
    "source_pdf",
]

TRIM_DECISION_TO_PAGES = {
    "trim_1_leading_page": 1,
    "trim_2_leading_pages": 2,
}


@dataclass
class CaseContext:
    case_id: str
    section: str
    subsection: str
    severity: str
    expected_start: int | None
    first_detected_footer: int | None
    suggested_trim_pages: int | None
    source_pdf: str
    action_candidates: set[str]


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text == "":
        return None
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _normalize_path(path_text: Any) -> str:
    text = str(path_text or "").strip().replace("\\", "/")
    if text.lower().startswith("book/"):
        return text[5:]
    return text


def _normalize_trim_from_manual(row: dict[str, Any]) -> int | None:
    explicit = _to_int(row.get("human_trim_pages"))
    if explicit is not None:
        return explicit
    return TRIM_DECISION_TO_PAGES.get(str(row.get("human_decision", "")).strip())


def _case_order_key(case_id: str, expected_start: int | None) -> tuple[int, str]:
    if expected_start is not None:
        return (expected_start, case_id)
    prefix = case_id.split("_", 1)[0]
    prefix_num = _to_int(prefix)
    if prefix_num is not None:
        return (prefix_num, case_id)
    return (10**9, case_id)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_audit(path: Path) -> dict[str, dict[str, Any]]:
    payload = _read_json(path)
    rows: list[dict[str, Any]]
    if isinstance(payload, dict):
        rows = [dict(x) for x in payload.get("flagged_cases", [])]
    elif isinstance(payload, list):
        rows = [dict(x) for x in payload]
    else:
        raise ValueError(f"Unsupported audit payload in {path}")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("case_id", "")).strip()
        if case_id:
            out[case_id] = row
    return out


def _load_correction_plan(path: Path) -> dict[str, dict[str, Any]]:
    payload = _read_json(path)
    rows: list[dict[str, Any]]
    if isinstance(payload, list):
        rows = [dict(x) for x in payload]
    elif isinstance(payload, dict):
        rows = [dict(x) for x in payload.get("corrections", [])]
    else:
        raise ValueError(f"Unsupported correction plan payload in {path}")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("case_id", "")).strip()
        if case_id:
            out[case_id] = row
    return out


def _load_review_cases(path: Path) -> dict[str, dict[str, Any]]:
    payload = _read_json(path)
    rows: list[dict[str, Any]]
    if isinstance(payload, dict):
        rows = [dict(x) for x in payload.get("cases", [])]
    elif isinstance(payload, list):
        rows = [dict(x) for x in payload]
    else:
        raise ValueError(f"Unsupported review_cases payload in {path}")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("case_id", "")).strip()
        if case_id:
            out[case_id] = row
    return out


def _derive_case_context(
    case_id: str,
    audit_row: dict[str, Any],
    plan_row: dict[str, Any],
    review_row: dict[str, Any],
) -> CaseContext:
    section = str(review_row.get("section") or audit_row.get("section") or "").strip()
    subsection = str(review_row.get("subsection") or audit_row.get("subsection") or "").strip()
    severity = str(review_row.get("severity") or audit_row.get("severity") or plan_row.get("severity") or "").strip()

    expected_start = _to_int(review_row.get("expected_start"))
    if expected_start is None:
        expected_start = _to_int(audit_row.get("expected_start"))

    first_detected_footer = _to_int(review_row.get("first_detected_footer"))
    if first_detected_footer is None:
        first_detected_footer = _to_int(audit_row.get("first_detected_footer"))

    suggested_trim_pages = _to_int(review_row.get("suggested_trim_pages"))
    if suggested_trim_pages is None:
        suggested_trim_pages = _to_int(audit_row.get("suggested_trim_pages"))
    if suggested_trim_pages is None:
        suggested_trim_pages = _to_int(plan_row.get("trim_leading_pages"))

    source_pdf = _normalize_path(review_row.get("source_pdf") or audit_row.get("source_pdf"))
    if not source_pdf and section and subsection and case_id:
        source_pdf = f"{section}/{subsection}/{case_id}.pdf"

    action_candidates: set[str] = set()
    for value in (
        audit_row.get("suggested_action"),
        plan_row.get("action"),
        review_row.get("correction_plan_action"),
    ):
        text = str(value or "").strip()
        if text:
            action_candidates.add(text)

    return CaseContext(
        case_id=case_id,
        section=section,
        subsection=subsection,
        severity=severity,
        expected_start=expected_start,
        first_detected_footer=first_detected_footer,
        suggested_trim_pages=suggested_trim_pages,
        source_pdf=source_pdf,
        action_candidates=action_candidates,
    )


def _manual_decision_rows(path: Path, contexts: dict[str, CaseContext]) -> list[dict[str, Any]]:
    payload = _read_json(path)
    if isinstance(payload, dict):
        rows = payload.get("decisions", [])
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError(f"Unsupported manual decisions payload in {path}")
    normalized: list[dict[str, Any]] = []
    for item in rows:
        row = dict(item)
        case_id = str(row.get("case_id", "")).strip()
        if not case_id:
            continue
        human_decision = str(row.get("human_decision", "")).strip()
        human_trim_pages = _normalize_trim_from_manual(row)
        is_explicit_manual = bool(human_decision) or (human_trim_pages is not None)
        if not is_explicit_manual:
            continue

        ctx = contexts.get(
            case_id,
            CaseContext(
                case_id=case_id,
                section="",
                subsection="",
                severity="",
                expected_start=None,
                first_detected_footer=None,
                suggested_trim_pages=None,
                source_pdf="",
                action_candidates=set(),
            ),
        )
        normalized.append(
            {
                "case_id": case_id,
                "section": str(row.get("section", "")).strip() or ctx.section,
                "subsection": str(row.get("subsection", "")).strip() or ctx.subsection,
                "severity": str(row.get("severity", "")).strip() or ctx.severity,
                "suggested_trim_pages": _to_int(row.get("suggested_trim_pages"))
                if _to_int(row.get("suggested_trim_pages")) is not None
                else ctx.suggested_trim_pages,
                "human_decision": human_decision,
                "human_trim_pages": human_trim_pages,
                "confidence": str(row.get("confidence", "")).strip(),
                "notes": str(row.get("notes", "")).strip(),
                "page1_previous_case": _to_bool(row.get("page1_previous_case")),
                "page2_previous_case": _to_bool(row.get("page2_previous_case")),
                "case_starts_correctly": _to_bool(row.get("case_starts_correctly")),
                "render_ocr_mismatch": _to_bool(row.get("render_ocr_mismatch")),
                "source": "manual",
                "source_pdf": _normalize_path(row.get("source_pdf")) or ctx.source_pdf,
            }
        )
    return normalized


def _auto_decision_row(ctx: CaseContext) -> dict[str, Any]:
    return {
        "case_id": ctx.case_id,
        "section": ctx.section,
        "subsection": ctx.subsection,
        "severity": ctx.severity,
        "suggested_trim_pages": 2,
        "human_decision": "trim_2_leading_pages",
        "human_trim_pages": 2,
        "confidence": "high",
        "notes": AUTO_NOTES,
        "page1_previous_case": True,
        "page2_previous_case": True,
        "case_starts_correctly": False,
        "render_ocr_mismatch": False,
        "source": "auto_confirmed_rule",
        "source_pdf": ctx.source_pdf,
    }


def _to_json_safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        new_row = dict(row)
        for key in [
            "suggested_trim_pages",
            "human_trim_pages",
        ]:
            if new_row.get(key) is None:
                new_row[key] = None
        out.append(new_row)
    return out


def _csv_value(value: Any) -> Any:
    return "" if value is None else value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: _csv_value(row.get(col)) for col in CSV_COLUMNS})


def _write_json_payload(path: Path, rows: list[dict[str, Any]], payload_name: str) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        payload_name: len(rows),
        "decisions": _to_json_safe_rows(rows),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _bool_rule_ok(ctx: CaseContext, range_min: int, range_max: int) -> tuple[bool, str]:
    if ctx.expected_start is None:
        return False, "missing_expected_start"
    if ctx.expected_start < range_min or ctx.expected_start > range_max:
        return False, "outside_range"
    if ctx.severity != "confirmed_boundary_error":
        return False, "severity_not_confirmed_boundary_error"
    if "trim_leading_pages" not in ctx.action_candidates:
        return False, "action_not_trim_leading_pages"
    if ctx.suggested_trim_pages != 2:
        return False, "suggested_trim_not_2"
    if ctx.first_detected_footer is None or ctx.expected_start - ctx.first_detected_footer != 2:
        return False, "first_detected_footer_not_expected_minus_2"
    return True, "selected"


def generate_from_rule(
    *,
    audit_path: Path,
    correction_plan_path: Path,
    review_cases_path: Path,
    review_decisions_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    audit = _load_audit(audit_path)
    plan = _load_correction_plan(correction_plan_path)
    review_cases = _load_review_cases(review_cases_path)

    all_case_ids = set(audit) | set(plan) | set(review_cases)
    contexts: dict[str, CaseContext] = {}
    for case_id in all_case_ids:
        contexts[case_id] = _derive_case_context(
            case_id=case_id,
            audit_row=audit.get(case_id, {}),
            plan_row=plan.get(case_id, {}),
            review_row=review_cases.get(case_id, {}),
        )

    start_case = contexts.get("306_anafilaxia")
    end_case = contexts.get("767_pediculosis")
    if start_case is None or end_case is None:
        raise ValueError("Required boundary cases not found: 306_anafilaxia or 767_pediculosis.")

    if (
        start_case.section != "seccion3"
        or start_case.subsection != "hipersensibilidad_tipo_i"
        or end_case.section != "seccion6"
        or end_case.subsection != "artropodos"
    ):
        raise ValueError("Boundary case section/subsection mismatch against confirmed human rule.")

    if start_case.expected_start is None or end_case.expected_start is None:
        raise ValueError("Boundary cases are missing expected_start; cannot compute printed-page range.")

    range_min = min(start_case.expected_start, end_case.expected_start)
    range_max = max(start_case.expected_start, end_case.expected_start)

    excluded_counts: Counter[str] = Counter()
    excluded_cases: list[dict[str, Any]] = []
    auto_selected_contexts: list[CaseContext] = []

    for case_id, ctx in contexts.items():
        is_selected, reason = _bool_rule_ok(ctx, range_min, range_max)
        if is_selected:
            auto_selected_contexts.append(ctx)
            continue
        excluded_counts[reason] += 1
        excluded_cases.append(
            {
                "case_id": case_id,
                "expected_start": ctx.expected_start,
                "reason": reason,
            }
        )

    auto_selected_contexts.sort(key=lambda c: _case_order_key(c.case_id, c.expected_start))
    auto_rows = [_auto_decision_row(ctx) for ctx in auto_selected_contexts]

    manual_rows: list[dict[str, Any]] = []
    if review_decisions_path.exists():
        manual_rows = _manual_decision_rows(review_decisions_path, contexts)

    manual_by_case = {row["case_id"]: row for row in manual_rows}
    auto_by_case = {row["case_id"]: row for row in auto_rows}

    merged_by_case = dict(auto_by_case)
    manual_overrides = 0
    for case_id, manual_row in manual_by_case.items():
        if case_id in merged_by_case:
            manual_overrides += 1
        merged_by_case[case_id] = manual_row

    merged_rows = list(merged_by_case.values())
    merged_rows.sort(
        key=lambda row: _case_order_key(
            str(row.get("case_id", "")),
            contexts.get(str(row.get("case_id", "")), CaseContext("", "", "", "", None, None, None, "", set())).expected_start,
        )
    )

    auto_json_path = output_dir / "review_decisions_auto_from_rule.json"
    auto_csv_path = output_dir / "review_decisions_auto_from_rule.csv"
    merged_json_path = output_dir / "review_decisions_merged.json"
    merged_csv_path = output_dir / "review_decisions_merged.csv"
    report_json_path = output_dir / "rule_application_report.json"
    report_md_path = output_dir / "rule_application_report.md"

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json_payload(auto_json_path, auto_rows, "total_auto_decisions")
    _write_csv(auto_csv_path, auto_rows)
    _write_json_payload(merged_json_path, merged_rows, "total_merged_decisions")
    _write_csv(merged_csv_path, merged_rows)

    final_trim_2_count = sum(
        1
        for row in merged_rows
        if str(row.get("human_decision", "")).strip() == "trim_2_leading_pages"
        and _to_int(row.get("human_trim_pages")) == 2
    )

    first_selected = auto_rows[0]["case_id"] if auto_rows else ""
    last_selected = auto_rows[-1]["case_id"] if auto_rows else ""
    report_payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rule_window": {
            "start_case_id": "306_anafilaxia",
            "start_section": "seccion3",
            "start_subsection": "hipersensibilidad_tipo_i",
            "end_case_id": "767_pediculosis",
            "end_section": "seccion6",
            "end_subsection": "artropodos",
            "printed_page_range": [range_min, range_max],
        },
        "totals": {
            "total_cases_considered": len(contexts),
            "total_selected_by_auto_rule": len(auto_rows),
            "manual_decisions_found": len(manual_rows),
            "manual_overrides": manual_overrides,
            "final_trim_2_count": final_trim_2_count,
        },
        "first_selected_case": first_selected,
        "last_selected_case": last_selected,
        "excluded_reason_counts": dict(sorted(excluded_counts.items())),
        "excluded_cases": sorted(excluded_cases, key=lambda x: _case_order_key(x["case_id"], _to_int(x["expected_start"]))),
        "warning": "Decisions are applied only to book_corrected/. Original book/ must remain unchanged.",
        "outputs": {
            "auto_csv": str(auto_csv_path).replace("\\", "/"),
            "auto_json": str(auto_json_path).replace("\\", "/"),
            "merged_csv": str(merged_csv_path).replace("\\", "/"),
            "merged_json": str(merged_json_path).replace("\\", "/"),
        },
    }
    report_json_path.write_text(json.dumps(report_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    md_lines = [
        "# Boundary Rule Application Report",
        "",
        "## Summary",
        "",
        f"- total selected by auto rule: {len(auto_rows)}",
        f"- manual decisions found: {len(manual_rows)}",
        f"- manual overrides: {manual_overrides}",
        f"- final trim_2 count: {final_trim_2_count}",
        f"- first selected case: {first_selected or '(none)'}",
        f"- last selected case: {last_selected or '(none)'}",
        "",
        "## Excluded Cases",
        "",
        "| reason | count |",
        "|---|---:|",
    ]
    for reason, count in sorted(excluded_counts.items()):
        md_lines.append(f"| {reason} | {count} |")
    md_lines.extend(
        [
            "",
            "## Safety Warning",
            "",
            "Decisions are applied only to `book_corrected/`. Original `book/` must remain unchanged.",
            "",
            "## Output Files",
            "",
            f"- `{auto_csv_path.as_posix()}`",
            f"- `{auto_json_path.as_posix()}`",
            f"- `{merged_csv_path.as_posix()}`",
            f"- `{merged_json_path.as_posix()}`",
            f"- `{report_md_path.as_posix()}`",
            f"- `{report_json_path.as_posix()}`",
        ]
    )
    report_md_path.write_text("\n".join(md_lines), encoding="utf-8")

    return report_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate boundary review decisions from the confirmed structural trim=2 rule."
    )
    parser.add_argument("--audit", default="data/curated/case_boundary_audit_v2.json")
    parser.add_argument("--correction-plan", default="data/curated/case_boundary_correction_plan_v2.json")
    parser.add_argument("--review-cases", default="data/curated/boundary_review/review_cases.json")
    parser.add_argument("--review-decisions", default="data/curated/boundary_review/review_decisions.json")
    parser.add_argument("--output-dir", default="data/curated/boundary_review")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = generate_from_rule(
        audit_path=Path(args.audit),
        correction_plan_path=Path(args.correction_plan),
        review_cases_path=Path(args.review_cases),
        review_decisions_path=Path(args.review_decisions),
        output_dir=Path(args.output_dir),
    )
    totals = report["totals"]
    print(
        "[Rule Decisions] "
        f"auto_selected={totals['total_selected_by_auto_rule']} "
        f"manual_found={totals['manual_decisions_found']} "
        f"manual_overrides={totals['manual_overrides']} "
        f"final_trim2={totals['final_trim_2_count']}"
    )
    print(
        "[Rule Decisions] first_selected="
        f"{report['first_selected_case'] or '(none)'} "
        f"last_selected={report['last_selected_case'] or '(none)'}"
    )
    print(
        "[Rule Decisions] outputs="
        f"{report['outputs']['merged_csv']} {report['outputs']['merged_json']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
