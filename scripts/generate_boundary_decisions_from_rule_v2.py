#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

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


def _load_json_rows(path: Path, key: str | None = None) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(x) for x in payload]
    if isinstance(payload, dict):
        if key is None:
            if "cases" in payload:
                return [dict(x) for x in payload["cases"]]
            if "flagged_cases" in payload:
                return [dict(x) for x in payload["flagged_cases"]]
            if "decisions" in payload:
                return [dict(x) for x in payload["decisions"]]
            return []
        return [dict(x) for x in payload.get(key, [])]
    raise ValueError(f"Unsupported JSON payload: {path}")


def _load_manifest_cases(path: Path) -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, dict[str, Any]] = {}
    for section in data.get("sections", []) or []:
        section_slug = str(section.get("slug", "")).strip()
        for subsection in section.get("subsections", []) or []:
            sub_slug = str(subsection.get("slug", "")).strip()
            for case in subsection.get("cases", []) or []:
                printed_start = _to_int(case.get("printed_start"))
                out_path = _normalize_path(case.get("output_path"))
                case_id = Path(out_path).stem if out_path else ""
                if not case_id:
                    continue
                out[case_id] = {
                    "case_id": case_id,
                    "section": section_slug,
                    "subsection": sub_slug,
                    "expected_start": printed_start,
                    "source_pdf": out_path,
                }
    return out


def _build_context(
    case_id: str,
    review_case: dict[str, Any] | None,
    audit_case: dict[str, Any] | None,
    plan_case: dict[str, Any] | None,
    manifest_case: dict[str, Any] | None,
    prior_decision: dict[str, Any] | None,
) -> dict[str, Any]:
    review_case = review_case or {}
    audit_case = audit_case or {}
    plan_case = plan_case or {}
    manifest_case = manifest_case or {}
    prior_decision = prior_decision or {}
    return {
        "case_id": case_id,
        "section": str(
            review_case.get("section")
            or audit_case.get("section")
            or manifest_case.get("section")
            or prior_decision.get("section")
            or ""
        ).strip(),
        "subsection": str(
            review_case.get("subsection")
            or audit_case.get("subsection")
            or manifest_case.get("subsection")
            or prior_decision.get("subsection")
            or ""
        ).strip(),
        "severity": str(
            review_case.get("severity")
            or audit_case.get("severity")
            or plan_case.get("severity")
            or prior_decision.get("severity")
            or ""
        ).strip(),
        "expected_start": _to_int(
            review_case.get("expected_start")
            or audit_case.get("expected_start")
            or manifest_case.get("expected_start")
        ),
        "source_pdf": _normalize_path(
            review_case.get("source_pdf")
            or audit_case.get("source_pdf")
            or manifest_case.get("source_pdf")
            or prior_decision.get("source_pdf")
        ),
        "suggested_action": str(
            audit_case.get("suggested_action") or plan_case.get("action") or review_case.get("correction_plan_action") or ""
        ).strip(),
        "suggested_trim_pages": _to_int(
            review_case.get("suggested_trim_pages")
            or audit_case.get("suggested_trim_pages")
            or plan_case.get("trim_leading_pages")
            or prior_decision.get("suggested_trim_pages")
        ),
        "prior_decision": str(prior_decision.get("human_decision", "")).strip(),
        "prior_trim_pages": _to_int(prior_decision.get("human_trim_pages")),
        "prior_confidence": str(prior_decision.get("confidence", "")).strip(),
        "prior_notes": str(prior_decision.get("notes", "")).strip(),
        "prior_page1_previous_case": _to_bool(prior_decision.get("page1_previous_case")),
        "prior_page2_previous_case": _to_bool(prior_decision.get("page2_previous_case")),
        "prior_case_starts_correctly": _to_bool(prior_decision.get("case_starts_correctly")),
        "prior_render_ocr_mismatch": _to_bool(prior_decision.get("render_ocr_mismatch")),
    }


def _row_with_defaults(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": ctx["case_id"],
        "section": ctx["section"],
        "subsection": ctx["subsection"],
        "severity": ctx["severity"],
        "suggested_trim_pages": ctx["suggested_trim_pages"],
        "human_decision": "",
        "human_trim_pages": None,
        "confidence": "",
        "notes": "",
        "page1_previous_case": None,
        "page2_previous_case": None,
        "case_starts_correctly": None,
        "render_ocr_mismatch": None,
        "source": "",
        "source_pdf": ctx["source_pdf"],
    }


def _csv_val(v: Any) -> Any:
    return "" if v is None else v


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: _csv_val(r.get(k)) for k in CSV_COLUMNS})


def _write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_decisions": len(rows),
        "decisions": rows,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def generate_rule_v2(
    *,
    audit_path: Path,
    correction_plan_path: Path,
    review_cases_path: Path,
    review_decisions_path: Path,
    manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    audit_rows = _load_json_rows(audit_path, key="flagged_cases")
    plan_rows = _load_json_rows(correction_plan_path)
    review_rows = _load_json_rows(review_cases_path, key="cases")
    prior_rows = _load_json_rows(review_decisions_path, key="decisions")
    manifest_cases = _load_manifest_cases(manifest_path)

    audit_by_case = {str(r.get("case_id", "")).strip(): r for r in audit_rows if str(r.get("case_id", "")).strip()}
    plan_by_case = {str(r.get("case_id", "")).strip(): r for r in plan_rows if str(r.get("case_id", "")).strip()}
    review_by_case = {str(r.get("case_id", "")).strip(): r for r in review_rows if str(r.get("case_id", "")).strip()}
    prior_by_case = {str(r.get("case_id", "")).strip(): r for r in prior_rows if str(r.get("case_id", "")).strip()}

    all_case_ids = set(manifest_cases) | set(audit_by_case) | set(plan_by_case) | set(review_by_case) | set(prior_by_case)
    decisions: list[dict[str, Any]] = []
    excluded_reason_counts: Counter[str] = Counter()

    for case_id in sorted(all_case_ids, key=lambda c: (_to_int(c.split("_", 1)[0]) or 10**9, c)):
        ctx = _build_context(
            case_id,
            review_by_case.get(case_id),
            audit_by_case.get(case_id),
            plan_by_case.get(case_id),
            manifest_cases.get(case_id),
            prior_by_case.get(case_id),
        )
        row = _row_with_defaults(ctx)
        ps = ctx["expected_start"]

        if ps is not None and 117 <= ps <= 296:
            row.update(
                {
                    "human_decision": "no_action",
                    "human_trim_pages": 0,
                    "confidence": "high",
                    "source": "human_validated_clean_range",
                    "notes": "Human validated: seccion2 from 117 to 296 is correctly cut.",
                }
            )
        elif ps is not None and 306 <= ps <= 773:
            row.update(
                {
                    "human_decision": "trim_2_leading_pages",
                    "human_trim_pages": 2,
                    "confidence": "high",
                    "source": "human_confirmed_range_rule_v2",
                    "notes": "Human confirmed structural offset: blank/intermediate page pattern from 306_anafilaxia through 773_sarna; remove 2 leading pages.",
                }
            )
        elif ctx["prior_decision"] or (ctx["prior_trim_pages"] is not None):
            row.update(
                {
                    "human_decision": ctx["prior_decision"],
                    "human_trim_pages": ctx["prior_trim_pages"],
                    "confidence": ctx["prior_confidence"],
                    "notes": ctx["prior_notes"],
                    "page1_previous_case": ctx["prior_page1_previous_case"],
                    "page2_previous_case": ctx["prior_page2_previous_case"],
                    "case_starts_correctly": ctx["prior_case_starts_correctly"],
                    "render_ocr_mismatch": ctx["prior_render_ocr_mismatch"],
                    "source": "prior_manual_decision",
                }
            )
        else:
            # Preserve conservative behavior outside human-confirmed ranges.
            if ctx["suggested_action"] == "inspect_manual":
                row.update(
                    {
                        "human_decision": "inspect_manual",
                        "human_trim_pages": 0,
                        "confidence": "medium",
                        "source": "fallback_from_audit_status",
                        "notes": "No explicit manual decision; preserved inspect_manual from prior audit status.",
                    }
                )
                excluded_reason_counts["fallback_inspect_manual"] += 1
            else:
                row.update(
                    {
                        "human_decision": "no_action",
                        "human_trim_pages": 0,
                        "confidence": "low",
                        "source": "fallback_no_action_outside_confirmed_ranges",
                        "notes": "Outside human-confirmed ranges and no explicit manual decision.",
                    }
                )
                excluded_reason_counts["fallback_no_action"] += 1

        decisions.append(row)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_csv = output_dir / "review_decisions_rule_v2.csv"
    out_json = output_dir / "review_decisions_rule_v2.json"
    report_md = output_dir / "rule_v2_application_report.md"
    report_json = output_dir / "rule_v2_application_report.json"

    _write_csv(out_csv, decisions)
    _write_json(out_json, decisions)

    by_case = {r["case_id"]: r for r in decisions}
    counts = Counter(r["human_decision"] for r in decisions)
    explicit_cases = [
        "306_anafilaxia",
        "773_sarna",
        "117_anemia_de_enfermedades_cronicas",
        "296_sindrome_antifosfolipido",
    ]
    explicit_status = {cid: by_case.get(cid, {"missing": True}) for cid in explicit_cases}

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "total_decisions_generated": len(decisions),
            "no_action_count": counts.get("no_action", 0),
            "trim_2_count": counts.get("trim_2_leading_pages", 0),
            "inspect_manual_count": counts.get("inspect_manual", 0),
        },
        "explicit_case_status": explicit_status,
        "excluded_cases_reason_counts": dict(sorted(excluded_reason_counts.items())),
        "warning": "Original book/ must not be modified. Apply only to book_corrected_v2/ (or another book_corrected_* root).",
        "outputs": {
            "csv": out_csv.as_posix(),
            "json": out_json.as_posix(),
        },
    }
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [
        "# Rule v2 Application Report",
        "",
        f"- total decisions generated: {report['totals']['total_decisions_generated']}",
        f"- no_action count: {report['totals']['no_action_count']}",
        f"- trim_2 count: {report['totals']['trim_2_count']}",
        f"- inspect_manual count: {report['totals']['inspect_manual_count']}",
        "",
        "## Explicit Cases",
        "",
    ]
    for cid in explicit_cases:
        s = explicit_status.get(cid, {})
        md.append(
            f"- `{cid}`: decision={s.get('human_decision', 'missing')} trim={s.get('human_trim_pages', 'missing')} source={s.get('source', 'missing')}"
        )
    md.extend(
        [
            "",
            "## Excluded/Fallback Reason Counts",
            "",
        ]
    )
    if excluded_reason_counts:
        for k, v in sorted(excluded_reason_counts.items()):
            md.append(f"- `{k}`: {v}")
    else:
        md.append("- none")
    md.extend(
        [
            "",
            "## Warning",
            "",
            "Original `book/` must not be modified.",
        ]
    )
    report_md.write_text("\n".join(md) + "\n", encoding="utf-8")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate boundary review decisions from human range rule v2.")
    parser.add_argument("--audit", default="data/curated/case_boundary_audit_v2.json")
    parser.add_argument("--correction-plan", default="data/curated/case_boundary_correction_plan_v2.json")
    parser.add_argument("--review-cases", default="data/curated/boundary_review/review_cases.json")
    parser.add_argument("--review-decisions", default="data/curated/boundary_review/review_decisions.json")
    parser.add_argument("--manifest", default="book/book_split_manifest.yaml")
    parser.add_argument("--output-dir", default="data/curated/boundary_review")
    args = parser.parse_args()

    report = generate_rule_v2(
        audit_path=Path(args.audit),
        correction_plan_path=Path(args.correction_plan),
        review_cases_path=Path(args.review_cases),
        review_decisions_path=Path(args.review_decisions),
        manifest_path=Path(args.manifest),
        output_dir=Path(args.output_dir),
    )
    totals = report["totals"]
    print(
        "[Rule v2] "
        f"total={totals['total_decisions_generated']} "
        f"no_action={totals['no_action_count']} "
        f"trim_2={totals['trim_2_count']} "
        f"inspect_manual={totals['inspect_manual_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
