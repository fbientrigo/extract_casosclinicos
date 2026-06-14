#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRIM_DECISION_TO_PAGES = {
    "trim_1_leading_page": 1,
    "trim_2_leading_pages": 2,
}

NO_ACTION_DECISIONS = {"no_action", "inspect_manual", "uncertain", ""}


@dataclass
class DecisionRow:
    case_id: str
    section: str
    subsection: str
    severity: str
    suggested_trim_pages: int | None
    human_decision: str
    human_trim_pages: int | None
    confidence: str
    notes: str
    page1_previous_case: bool | None
    page2_previous_case: bool | None
    case_starts_correctly: bool | None
    render_ocr_mismatch: bool | None
    source_pdf: str


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text == "":
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


def _normalize_trim_from_decision(human_decision: str, human_trim_pages: int | None) -> int | None:
    if human_trim_pages is not None:
        return human_trim_pages
    return TRIM_DECISION_TO_PAGES.get(human_decision)


def _normalize_source_pdf(row: dict[str, Any]) -> str:
    source_pdf = str(row.get("source_pdf", "")).replace("\\", "/").strip()
    if source_pdf:
        if source_pdf.lower().startswith("book/"):
            return source_pdf[5:]
        return source_pdf

    section = str(row.get("section", "")).strip()
    subsection = str(row.get("subsection", "")).strip()
    case_id = str(row.get("case_id", "")).strip()
    if section and subsection and case_id:
        return f"{section}/{subsection}/{case_id}.pdf"
    return ""


def normalize_decision_row(row: dict[str, Any]) -> DecisionRow:
    human_decision = str(row.get("human_decision", "")).strip()
    human_trim_pages = _normalize_trim_from_decision(human_decision, _to_int(row.get("human_trim_pages")))
    return DecisionRow(
        case_id=str(row.get("case_id", "")).strip(),
        section=str(row.get("section", "")).strip(),
        subsection=str(row.get("subsection", "")).strip(),
        severity=str(row.get("severity", "")).strip(),
        suggested_trim_pages=_to_int(row.get("suggested_trim_pages")),
        human_decision=human_decision,
        human_trim_pages=human_trim_pages,
        confidence=str(row.get("confidence", "")).strip(),
        notes=str(row.get("notes", "")).strip(),
        page1_previous_case=_to_bool(row.get("page1_previous_case")),
        page2_previous_case=_to_bool(row.get("page2_previous_case")),
        case_starts_correctly=_to_bool(row.get("case_starts_correctly")),
        render_ocr_mismatch=_to_bool(row.get("render_ocr_mismatch")),
        source_pdf=_normalize_source_pdf(row),
    )


def load_decisions(decisions_path: Path) -> list[DecisionRow]:
    suffix = decisions_path.suffix.lower()
    if suffix == ".csv":
        with decisions_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [normalize_decision_row(row) for row in reader]

    payload = json.loads(decisions_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("decisions", [])
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError(f"Unsupported JSON decisions payload in {decisions_path}")
    return [normalize_decision_row(dict(row)) for row in rows]


def _parse_actionable_trim(row: DecisionRow) -> tuple[int | None, str | None]:
    expected_trim = TRIM_DECISION_TO_PAGES.get(row.human_decision)
    if expected_trim is None:
        return None, None
    if row.human_trim_pages not in {1, 2}:
        return None, f"{row.case_id}: human_trim_pages must be 1 or 2 for trim decisions."
    if row.human_trim_pages != expected_trim:
        return None, f"{row.case_id}: human_trim_pages mismatch with human_decision."
    return expected_trim, None


def _trim_pdf(input_pdf: Path, output_pdf: Path, trim_leading_pages: int) -> tuple[int, int]:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(input_pdf))
    total_pages = len(reader.pages)
    if trim_leading_pages < 1:
        raise ValueError("trim_leading_pages must be >= 1")
    if trim_leading_pages >= total_pages:
        raise ValueError(
            f"trim {trim_leading_pages} invalid for {input_pdf} with {total_pages} page(s)"
        )

    writer = PdfWriter()
    for i in range(trim_leading_pages, total_pages):
        writer.add_page(reader.pages[i])

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as f:
        writer.write(f)

    out_reader = PdfReader(str(output_pdf))
    out_pages = len(out_reader.pages)
    expected_pages = total_pages - trim_leading_pages
    if out_pages != expected_pages:
        raise RuntimeError(
            f"output page count mismatch for {output_pdf}: expected {expected_pages}, got {out_pages}"
        )
    return total_pages, out_pages


def _copy_clean_case(input_pdf: Path, output_pdf: Path) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_pdf, output_pdf)


def _resolve_and_validate_path(path: Path, root: Path, *, label: str) -> Path:
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    try:
        path_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"{label} escapes allowed root: {path_resolved} not under {root_resolved}") from exc
    return path_resolved


def _validate_roots(input_root: Path, output_root: Path) -> tuple[Path, Path]:
    input_resolved = input_root.resolve()
    output_resolved = output_root.resolve()

    out_name = output_resolved.name.lower()
    if not (out_name == "book_corrected" or out_name.startswith("book_corrected_")):
        raise ValueError(
            f"output_root must be 'book_corrected' or 'book_corrected_*', got: {output_resolved}"
        )
    if out_name == "book":
        raise ValueError("output_root cannot be book/.")
    if input_resolved == output_resolved:
        raise ValueError("input_root and output_root must be different to protect original book/.")

    try:
        output_resolved.relative_to(input_resolved)
    except ValueError:
        pass
    else:
        raise ValueError("output_root cannot be inside input_root.")

    return input_resolved, output_resolved


def run_apply(
    *,
    decisions_path: Path,
    input_root: Path,
    output_root: Path,
    report_dir: Path,
    execute: bool = False,
    copy_clean: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    input_root_resolved, output_root_resolved = _validate_roots(input_root, output_root)
    rows = load_decisions(decisions_path)

    summary: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "execute" if execute else "dry-run",
        "decisions_path": str(decisions_path),
        "input_root": str(input_root),
        "output_root": str(output_root),
        "total_rows": len(rows),
        "planned_actions": [],
        "skipped_invalid": [],
        "skipped_missing_source": [],
        "skipped_existing_output": [],
        "executed_trims": [],
        "copied_clean": [],
        "decision_counts": {
            "no_action": 0,
            "trim_1": 0,
            "trim_2": 0,
            "inspect_manual": 0,
        },
        "contains_case_ids": {
            "306_anafilaxia": False,
            "773_sarna": False,
        },
    }

    for row in rows:
        if not row.case_id:
            summary["skipped_invalid"].append("row with empty case_id")
            continue
        if not row.source_pdf:
            summary["skipped_invalid"].append(f"{row.case_id}: missing source_pdf/section/subsection")
            continue
        if row.human_decision not in set(TRIM_DECISION_TO_PAGES.keys()) | NO_ACTION_DECISIONS:
            summary["skipped_invalid"].append(f"{row.case_id}: unknown human_decision '{row.human_decision}'")
            continue
        if row.human_decision == "no_action":
            summary["decision_counts"]["no_action"] += 1
        elif row.human_decision == "inspect_manual":
            summary["decision_counts"]["inspect_manual"] += 1
        elif row.human_decision == "trim_1_leading_page":
            summary["decision_counts"]["trim_1"] += 1
        elif row.human_decision == "trim_2_leading_pages":
            summary["decision_counts"]["trim_2"] += 1
        if row.case_id in summary["contains_case_ids"]:
            summary["contains_case_ids"][row.case_id] = True

        source_pdf = input_root / row.source_pdf
        output_pdf = output_root / row.source_pdf
        try:
            _resolve_and_validate_path(source_pdf, input_root_resolved, label=f"{row.case_id}: source_pdf")
            _resolve_and_validate_path(output_pdf, output_root_resolved, label=f"{row.case_id}: output_pdf")
        except ValueError as e:
            summary["skipped_invalid"].append(str(e))
            continue

        trim_pages, trim_error = _parse_actionable_trim(row)
        if trim_error:
            summary["skipped_invalid"].append(trim_error)
            continue

        if trim_pages is not None:
            action_payload = {
                "case_id": row.case_id,
                "action": "trim",
                "trim_leading_pages": trim_pages,
                "source_pdf": str(source_pdf),
                "output_pdf": str(output_pdf),
            }
            summary["planned_actions"].append(action_payload)

            if not execute:
                continue
            if not source_pdf.exists():
                summary["skipped_missing_source"].append(str(source_pdf))
                continue
            if output_pdf.exists() and not overwrite:
                summary["skipped_existing_output"].append(str(output_pdf))
                continue

            in_pages, out_pages = _trim_pdf(source_pdf, output_pdf, trim_pages)
            entry = {**action_payload, "input_page_count": in_pages, "output_page_count": out_pages}
            summary["executed_trims"].append(entry)
            continue

        if execute and copy_clean and row.human_decision == "no_action":
            if not source_pdf.exists():
                summary["skipped_missing_source"].append(str(source_pdf))
                continue
            if output_pdf.exists() and not overwrite:
                summary["skipped_existing_output"].append(str(output_pdf))
                continue
            _copy_clean_case(source_pdf, output_pdf)
            summary["copied_clean"].append(
                {
                    "case_id": row.case_id,
                    "action": "copy_clean",
                    "source_pdf": str(source_pdf),
                    "output_pdf": str(output_pdf),
                }
            )

    if execute:
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "applied_review_decisions.json"
        md_path = report_dir / "applied_review_decisions.md"
        json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        md_lines = [
            "# Applied Boundary Review Decisions",
            "",
            f"- mode: {summary['mode']}",
            f"- total_rows: {summary['total_rows']}",
            f"- planned_actions: {len(summary['planned_actions'])}",
            f"- executed_trims: {len(summary['executed_trims'])}",
            f"- copied_clean: {len(summary['copied_clean'])}",
            f"- skipped_invalid: {len(summary['skipped_invalid'])}",
            f"- skipped_missing_source: {len(summary['skipped_missing_source'])}",
            f"- skipped_existing_output: {len(summary['skipped_existing_output'])}",
            "",
            "## Executed Trims",
            "",
            "| case_id | trim | input_pages | output_pages | source | output |",
            "|---|---:|---:|---:|---|---|",
        ]
        for item in summary["executed_trims"]:
            md_lines.append(
                f"| {item['case_id']} | {item['trim_leading_pages']} | "
                f"{item['input_page_count']} | {item['output_page_count']} | "
                f"{item['source_pdf']} | {item['output_pdf']} |"
            )
        md_lines.append("")
        md_path.write_text("\n".join(md_lines), encoding="utf-8")

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply human-reviewed boundary corrections to PDFs.")
    parser.add_argument("--decisions", default="data/curated/boundary_review/review_decisions.csv")
    parser.add_argument("--input-root", default="book")
    parser.add_argument("--output-root", default="book_corrected")
    parser.add_argument("--report-dir", default="data/curated/boundary_review")
    parser.add_argument("--dry-run", action="store_true", help="Force dry-run mode.")
    parser.add_argument("--execute", action="store_true", help="Apply trimming and write corrected PDFs.")
    parser.add_argument("--copy-clean", action="store_true", help="Copy no_action cases in execute mode.")
    parser.add_argument("--overwrite", action="store_true", help="Allow overwrite in output-root.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.execute and args.dry_run:
        raise SystemExit("Use either --dry-run or --execute, not both.")

    execute_mode = bool(args.execute) and not bool(args.dry_run)
    decisions_path = Path(args.decisions)
    if not decisions_path.exists():
        fallback = decisions_path.with_name("review_decisions_template.csv")
        if fallback.exists():
            decisions_path = fallback
            print(f"[Apply Review] using fallback decisions file: {fallback}")

    summary = run_apply(
        decisions_path=decisions_path,
        input_root=Path(args.input_root),
        output_root=Path(args.output_root),
        report_dir=Path(args.report_dir),
        execute=execute_mode,
        copy_clean=bool(args.copy_clean),
        overwrite=bool(args.overwrite),
    )

    print(f"[Apply Review] mode={summary['mode']}")
    print(f"[Apply Review] total rows={summary['total_rows']}")
    print(f"[Apply Review] no_action={summary['decision_counts']['no_action']}")
    print(f"[Apply Review] trim_1={summary['decision_counts']['trim_1']}")
    print(f"[Apply Review] trim_2={summary['decision_counts']['trim_2']}")
    print(f"[Apply Review] inspect_manual={summary['decision_counts']['inspect_manual']}")
    print(f"[Apply Review] planned trims={len(summary['planned_actions'])}")
    print(f"[Apply Review] executed trims={len(summary['executed_trims'])}")
    print(f"[Apply Review] skipped invalid={len(summary['skipped_invalid'])}")
    print(f"[Apply Review] skipped missing source={len(summary['skipped_missing_source'])}")
    print(f"[Apply Review] skipped existing output={len(summary['skipped_existing_output'])}")
    print(f"[Apply Review] includes_306_anafilaxia={summary['contains_case_ids']['306_anafilaxia']}")
    print(f"[Apply Review] includes_773_sarna={summary['contains_case_ids']['773_sarna']}")
    print(f"[Apply Review] output_root={summary['output_root']}")
    if execute_mode:
        print(f"[Apply Review] applied report JSON: {Path(args.report_dir) / 'applied_review_decisions.json'}")
        print(f"[Apply Review] applied report MD: {Path(args.report_dir) / 'applied_review_decisions.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
