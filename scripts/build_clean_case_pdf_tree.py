#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DECISIONS_CSV = PROJECT_ROOT / "data/curated/boundary_review/review_decisions_rule_v2.csv"
CORRECTED_ROOT = PROJECT_ROOT / "book_corrected_v2"
ORIGINAL_ROOT = PROJECT_ROOT / "book"
CLEAN_ROOT = PROJECT_ROOT / "book_cases_clean"
RESOLUTION_CSV = PROJECT_ROOT / "data/curated/inspect_manual_resolution.csv"
NON_CASE_EXCLUSIONS_CSV = PROJECT_ROOT / "data/curated/non_case_exclusions.csv"
EXCLUDED_NON_CASES_JSON = PROJECT_ROOT / "data/curated/excluded_non_cases.json"
EXCLUDED_NON_CASES_MD = PROJECT_ROOT / "data/curated/excluded_non_cases.md"

BLOCKERS_MD = PROJECT_ROOT / "data/curated/inspect_manual_blockers.md"
BLOCKERS_JSON = PROJECT_ROOT / "data/curated/inspect_manual_blockers.json"

MANIFEST_CSV = PROJECT_ROOT / "data/curated/clean_case_pdf_manifest.csv"
MANIFEST_JSON = PROJECT_ROOT / "data/curated/clean_case_pdf_manifest.json"
MANIFEST_MD = PROJECT_ROOT / "data/curated/clean_case_pdf_manifest.md"

EXPECTED_COUNTS = {
    "total": 140,
    "trim_2_leading_pages": 92,
    "no_action": 46,
    "inspect_manual": 2,
}


@dataclass
class Row:
    case_id: str
    section: str
    subsection: str
    decision: str
    source_pdf: str


def _load_rows(path: Path) -> list[Row]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        out = []
        for r in reader:
            out.append(
                Row(
                    case_id=str(r["case_id"]).strip(),
                    section=str(r["section"]).strip(),
                    subsection=str(r["subsection"]).strip(),
                    decision=str(r["human_decision"]).strip(),
                    source_pdf=str(r["source_pdf"]).strip().replace("\\", "/").removeprefix("book/"),
                )
            )
    return out


def _load_manual_resolutions(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {str(r["case_id"]).strip(): r for r in reader}


def _load_non_case_exclusions(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {str(r["case_id"]).strip(): r for r in reader}


def _write_excluded_non_cases(exclusions: dict[str, dict], excluded_case_ids: list[str]) -> None:
    rows = []
    for case_id in sorted(excluded_case_ids):
        row = dict(exclusions.get(case_id, {}))
        row["case_id"] = case_id
        rows.append(row)
    payload = {"excluded_non_cases_count": len(rows), "excluded_non_cases": rows}
    EXCLUDED_NON_CASES_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md = [
        "# Excluded Non-Case Entries",
        "",
        f"- Excluded count: `{len(rows)}`",
        "",
        "| case_id | exclusion_type | reason | reviewer |",
        "|---|---|---|---|",
    ]
    for r in rows:
        md.append(
            f"| `{r.get('case_id','')}` | `{r.get('exclusion_type','')}` | `{r.get('reason','')}` | `{r.get('reviewer','')}` |"
        )
    EXCLUDED_NON_CASES_MD.write_text("\n".join(md) + "\n", encoding="utf-8")


def _resolve_source(row: Row, resolution: dict | None) -> tuple[str, Path, str] | tuple[None, None, None]:
    canonical_rel = f"{row.section}/{row.subsection}/{row.case_id}.pdf"
    if row.decision == "trim_2_leading_pages":
        canonical_abs = CORRECTED_ROOT / canonical_rel
        if canonical_abs.exists():
            return canonical_rel, canonical_abs, "book_corrected_v2"
        rel = row.source_pdf
        return rel, CORRECTED_ROOT / rel, "book_corrected_v2"
    if row.decision == "no_action":
        canonical_abs = ORIGINAL_ROOT / canonical_rel
        if canonical_abs.exists():
            return canonical_rel, canonical_abs, "book"
        rel = row.source_pdf
        return rel, ORIGINAL_ROOT / rel, "book"

    if resolution is None:
        return None, None, None

    mode = str(resolution.get("resolution", "")).strip()
    src = str(resolution.get("source_pdf_path", "")).strip().replace("\\", "/")
    src = src.removeprefix("book/").removeprefix("book_corrected_v2/")
    if mode == "exclude_until_reviewed":
        return "", Path(""), ""
    if mode == "use_corrected_trimmed":
        return src, CORRECTED_ROOT / src, "book_corrected_v2"
    if mode == "use_original_no_action":
        return src, ORIGINAL_ROOT / src, "book"
    return None, None, None


def _write_blockers(rows: list[Row]) -> None:
    payload = {
        "unresolved_count": len(rows),
        "unresolved_case_ids": [r.case_id for r in rows],
        "cases": [r.__dict__ for r in rows],
    }
    BLOCKERS_JSON.parent.mkdir(parents=True, exist_ok=True)
    BLOCKERS_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# Inspect Manual Blockers", "", f"- unresolved_count: `{len(rows)}`", "", "| case_id | section | subsection | source_pdf |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| `{r.case_id}` | `{r.section}` | `{r.subsection}` | `{r.source_pdf}` |")
    BLOCKERS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_tree(allow_inspect_manual: bool, decisions_csv: Path | None = None) -> tuple[int, dict]:
    decisions_path = decisions_csv or DECISIONS_CSV
    rows = _load_rows(decisions_path)
    cnt = Counter(r.decision for r in rows)
    if len(rows) != EXPECTED_COUNTS["total"]:
        raise ValueError("Unexpected decision row count")
    for k, v in EXPECTED_COUNTS.items():
        if k == "total":
            continue
        if cnt.get(k, 0) != v:
            raise ValueError(f"Unexpected count for {k}: {cnt.get(k, 0)} != {v}")

    resolutions = _load_manual_resolutions(RESOLUTION_CSV)
    non_case_exclusions = _load_non_case_exclusions(NON_CASE_EXCLUSIONS_CSV)
    excluded_non_case_ids: list[str] = []
    unresolved = [r for r in rows if r.decision == "inspect_manual" and r.case_id not in resolutions]

    if CLEAN_ROOT.exists():
        shutil.rmtree(CLEAN_ROOT)
    CLEAN_ROOT.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    excluded = []
    missing_sources = []

    for r in rows:
        if r.case_id in non_case_exclusions:
            excluded_non_case_ids.append(r.case_id)
            continue
        res = resolutions.get(r.case_id)
        rel_source, source_abs, source_root = _resolve_source(r, res)
        if r.decision == "inspect_manual" and not allow_inspect_manual and r.case_id not in resolutions:
            continue
        if rel_source is None:
            raise ValueError(f"Unresolved source for {r.case_id}")
        if rel_source == "":
            excluded.append(r.case_id)
            continue

        clean_pdf_rel = f"{r.section}/{r.subsection}/{r.case_id}.pdf"
        clean_pdf_abs = CLEAN_ROOT / clean_pdf_rel
        clean_pdf_abs.parent.mkdir(parents=True, exist_ok=True)
        if not source_abs.exists():
            missing_sources.append(
                {
                    "case_id": r.case_id,
                    "section": r.section,
                    "subsection": r.subsection,
                    "source_pdf_path": rel_source,
                    "missing_abs_path": str(source_abs),
                }
            )
            continue
        shutil.copy2(source_abs, clean_pdf_abs)

        manifest_rows.append(
            {
                "case_id": r.case_id,
                "section": r.section,
                "subsection": r.subsection,
                "printed_start_page": int(r.case_id.split("_", 1)[0]),
                "printed_end_page": "",
                "decision": r.decision if r.decision != "inspect_manual" else str(res["resolution"]),
                "source_pdf_path": rel_source,
                "source_root": source_root,
                "clean_pdf_path": clean_pdf_rel,
                "boundary_source": "review_decisions_rule_v2.csv",
            }
        )

    MANIFEST_CSV.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()) if manifest_rows else ["case_id", "section", "subsection", "printed_start_page", "printed_end_page", "decision", "source_pdf_path", "clean_pdf_path", "boundary_source"])
        w.writeheader()
        w.writerows(manifest_rows)

    blocker_rows = unresolved + [
        Row(
            case_id=m["case_id"],
            section=m["section"],
            subsection=m["subsection"],
            decision="missing_source_pdf",
            source_pdf=m["source_pdf_path"],
        )
        for m in missing_sources
    ]
    _write_blockers(blocker_rows)
    _write_excluded_non_cases(non_case_exclusions, excluded_non_case_ids)

    summary = {
        "total_rows": len(rows),
        "decision_counts": dict(cnt),
        "included_cases": len(manifest_rows),
        "excluded_cases": excluded,
        "excluded_non_cases": sorted(excluded_non_case_ids),
        "unresolved_inspect_manual": [r.case_id for r in unresolved],
        "missing_source_cases": [m["case_id"] for m in missing_sources],
        "allow_inspect_manual": allow_inspect_manual,
    }
    MANIFEST_JSON.write_text(json.dumps({"summary": summary, "cases": manifest_rows}, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [
        "# Clean Case PDF Manifest",
        "",
        f"- Included: `{len(manifest_rows)}`",
        f"- Unresolved inspect_manual: `{len(unresolved)}`",
        f"- Excluded by resolution: `{len(excluded)}`",
        "",
        "| case_id | decision | source_pdf_path | clean_pdf_path |",
        "|---|---|---|---|",
    ]
    for c in manifest_rows:
        md.append(f"| `{c['case_id']}` | `{c['decision']}` | `{c['source_pdf_path']}` | `{c['clean_pdf_path']}` |")
    MANIFEST_MD.write_text("\n".join(md) + "\n", encoding="utf-8")

    checks = {
        "306_anafilaxia": "book_corrected_v2",
        "311_toxicodermia": "book_corrected_v2",
        "762_loxoscelismo": "book_corrected_v2",
        "767_pediculosis": "book_corrected_v2",
        "773_sarna": "book_corrected_v2",
        "117_anemia_de_enfermedades_cronicas": "book/",
        "296_sindrome_antifosfolipido": "book/",
    }
    by_case = {c["case_id"]: c for c in manifest_rows}
    for case_id, expect in checks.items():
        if case_id not in by_case:
            continue
        src = by_case[case_id]["source_pdf_path"]
        if expect == "book_corrected_v2" and not (CORRECTED_ROOT / src).exists():
            raise ValueError(f"{case_id} not sourced from corrected")
        if expect == "book/" and not (ORIGINAL_ROOT / src).exists():
            raise ValueError(f"{case_id} not sourced from original")

    if (unresolved and not allow_inspect_manual) or missing_sources:
        return 2, summary
    return 0, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build canonical clean case PDF tree from validated v2 decisions.")
    parser.add_argument("--decisions-csv", default=str(DECISIONS_CSV))
    parser.add_argument("--allow-inspect-manual", action="store_true")
    args = parser.parse_args()

    code, summary = build_tree(
        allow_inspect_manual=args.allow_inspect_manual,
        decisions_csv=Path(args.decisions_csv),
    )
    print(json.dumps(summary, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
