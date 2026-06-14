#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRIM_DECISION_TO_PAGES = {
    "trim_1_leading_page": 1,
    "trim_2_leading_pages": 2,
}

KNOWN_DECISIONS = {
    "trim_1_leading_page",
    "trim_2_leading_pages",
    "no_action",
    "inspect_manual",
    "uncertain",
}

KNOWN_BOOL_FIELDS = {
    "page1_previous_case",
    "page2_previous_case",
    "case_starts_correctly",
    "render_ocr_mismatch",
}

CSV_COLUMNS = [
    "case_id",
    "section",
    "subsection",
    "severity",
    "audit_suggested_trim_pages",
    "inferred_human_trim_pages",
    "inferred_decision",
    "confidence",
    "inference_reason",
    "needs_manual_confirmation",
    "source",
    "notes",
]


@dataclass
class ReviewedCase:
    case_id: str
    section: str
    subsection: str
    severity: str
    suggested_trim_pages: int | None
    human_decision: str
    human_trim_pages: int | None
    confidence: str
    notes: str
    booleans: dict[str, bool | None]
    audit_flags: list[str]
    first_detected_footer: int | None
    expected_start: int | None
    first_caso_problema_page: int | None


@dataclass
class CandidateDecision:
    case_id: str
    section: str
    subsection: str
    severity: str
    audit_suggested_trim_pages: int | None
    inferred_human_trim_pages: int | None
    inferred_decision: str
    confidence: str
    inference_reason: str
    needs_manual_confirmation: bool
    source: str
    notes: str


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
    mapped = TRIM_DECISION_TO_PAGES.get(human_decision)
    return mapped


def _normalize_decision_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload]
    if isinstance(payload, dict):
        rows = payload.get("decisions", [])
        if not isinstance(rows, list):
            raise ValueError("review_decisions payload has non-list 'decisions'.")
        return [dict(row) for row in rows]
    raise ValueError("Unsupported review_decisions payload type.")


def load_review_decisions(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = _normalize_decision_payload(payload)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        human_decision = str(row.get("human_decision", "")).strip()
        if human_decision and human_decision not in KNOWN_DECISIONS:
            human_decision = "inspect_manual"

        booleans: dict[str, bool | None] = {}
        for key, value in row.items():
            if key in KNOWN_BOOL_FIELDS:
                booleans[key] = _to_bool(value)
                continue
            candidate_bool = _to_bool(value)
            if candidate_bool is not None and key not in {
                "case_id",
                "section",
                "subsection",
                "severity",
                "suggested_trim_pages",
                "human_decision",
                "human_trim_pages",
                "confidence",
                "notes",
            }:
                booleans[key] = candidate_bool

        normalized.append(
            {
                "case_id": str(row.get("case_id", "")).strip(),
                "section": str(row.get("section", "")).strip(),
                "subsection": str(row.get("subsection", "")).strip(),
                "severity": str(row.get("severity", "")).strip(),
                "suggested_trim_pages": _to_int(row.get("suggested_trim_pages")),
                "human_decision": human_decision,
                "human_trim_pages": _normalize_trim_from_decision(
                    human_decision, _to_int(row.get("human_trim_pages"))
                ),
                "confidence": str(row.get("confidence", "")).strip(),
                "notes": str(row.get("notes", "")).strip(),
                "booleans": booleans,
            }
        )
    return normalized


def _load_review_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return [dict(x) for x in payload.get("cases", [])]
    if isinstance(payload, list):
        return [dict(x) for x in payload]
    raise ValueError("Unsupported review_cases payload type.")


def _load_audit_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return [dict(x) for x in payload.get("flagged_cases", [])]
    if isinstance(payload, list):
        return [dict(x) for x in payload]
    raise ValueError("Unsupported audit payload type.")


def _load_correction_plan(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(x) for x in payload]
    if isinstance(payload, dict):
        return [dict(x) for x in payload.get("corrections", [])]
    raise ValueError("Unsupported correction plan payload type.")


def _index_by_case(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("case_id", "")).strip()
        if case_id:
            out[case_id] = row
    return out


def merge_case_context(
    decisions: list[dict[str, Any]],
    review_cases: list[dict[str, Any]],
    audit_cases: list[dict[str, Any]],
    correction_plan: list[dict[str, Any]],
) -> tuple[list[ReviewedCase], list[dict[str, Any]], dict[str, Any]]:
    review_idx = _index_by_case(review_cases)
    audit_idx = _index_by_case(audit_cases)
    plan_idx = _index_by_case(correction_plan)

    all_case_ids = set(review_idx) | set(audit_idx) | {d["case_id"] for d in decisions if d["case_id"]}

    merged_cases: list[dict[str, Any]] = []
    for case_id in sorted(all_case_ids):
        r = review_idx.get(case_id, {})
        a = audit_idx.get(case_id, {})
        p = plan_idx.get(case_id, {})

        section = str(r.get("section") or a.get("section") or "").strip()
        subsection = str(r.get("subsection") or a.get("subsection") or "").strip()
        severity = str(r.get("severity") or a.get("severity") or p.get("severity") or "").strip()
        flags = r.get("flags") or a.get("flags") or []
        if not isinstance(flags, list):
            flags = []

        merged_cases.append(
            {
                "case_id": case_id,
                "section": section,
                "subsection": subsection,
                "severity": severity,
                "suggested_trim_pages": _to_int(
                    r.get("suggested_trim_pages")
                    if r.get("suggested_trim_pages") is not None
                    else a.get("suggested_trim_pages")
                ),
                "flags": [str(x) for x in flags],
                "first_detected_footer": _to_int(
                    r.get("first_detected_footer")
                    if r.get("first_detected_footer") is not None
                    else a.get("first_detected_footer")
                ),
                "expected_start": _to_int(
                    r.get("expected_start") if r.get("expected_start") is not None else a.get("expected_start")
                ),
                "first_caso_problema_page": _to_int(
                    r.get("first_caso_problema_page")
                    if r.get("first_caso_problema_page") is not None
                    else a.get("first_caso_problema_page")
                ),
                "correction_plan_action": str(p.get("action", "")).strip(),
                "correction_plan_trim_leading_pages": _to_int(p.get("trim_leading_pages")),
            }
        )

    merged_idx = _index_by_case(merged_cases)
    reviewed: list[ReviewedCase] = []

    for d in decisions:
        case_id = d["case_id"]
        if not case_id:
            continue
        ctx = merged_idx.get(case_id, {})
        reviewed.append(
            ReviewedCase(
                case_id=case_id,
                section=d["section"] or str(ctx.get("section", "")).strip(),
                subsection=d["subsection"] or str(ctx.get("subsection", "")).strip(),
                severity=d["severity"] or str(ctx.get("severity", "")).strip(),
                suggested_trim_pages=(
                    d["suggested_trim_pages"]
                    if d["suggested_trim_pages"] is not None
                    else _to_int(ctx.get("suggested_trim_pages"))
                ),
                human_decision=d["human_decision"],
                human_trim_pages=d["human_trim_pages"],
                confidence=d["confidence"],
                notes=d["notes"],
                booleans=d["booleans"],
                audit_flags=[str(x) for x in ctx.get("flags", [])],
                first_detected_footer=_to_int(ctx.get("first_detected_footer")),
                expected_start=_to_int(ctx.get("expected_start")),
                first_caso_problema_page=_to_int(ctx.get("first_caso_problema_page")),
            )
        )

    return reviewed, merged_cases, merged_idx


def _is_reviewed_case(row: ReviewedCase) -> bool:
    return bool(row.human_decision.strip())


def summarize_reviewed_decisions(reviewed_cases: list[ReviewedCase]) -> dict[str, Any]:
    reviewed = [r for r in reviewed_cases if _is_reviewed_case(r)]

    trim_counter = Counter()
    by_section = Counter()
    by_subsection = Counter()
    decision_counter = Counter()

    agreement = {
        "agree": 0,
        "disagree": 0,
        "not_comparable": 0,
    }

    for r in reviewed:
        by_section[r.section] += 1
        by_subsection[f"{r.section}/{r.subsection}"] += 1
        decision_counter[r.human_decision] += 1

        trim_value = r.human_trim_pages if r.human_decision.startswith("trim_") else 0
        if trim_value in {0, 1, 2}:
            trim_counter[trim_value] += 1

        if r.human_decision.startswith("trim_") and r.human_trim_pages is not None and r.suggested_trim_pages is not None:
            if r.human_trim_pages == r.suggested_trim_pages:
                agreement["agree"] += 1
            else:
                agreement["disagree"] += 1
        else:
            agreement["not_comparable"] += 1

    return {
        "total_reviewed_cases": len(reviewed),
        "reviewed_trim_0": trim_counter[0],
        "reviewed_trim_1": trim_counter[1],
        "reviewed_trim_2": trim_counter[2],
        "inspect_manual": decision_counter["inspect_manual"],
        "uncertain": decision_counter["uncertain"],
        "by_section": dict(sorted(by_section.items())),
        "by_subsection": dict(sorted(by_subsection.items())),
        "agreement_with_audit": agreement,
    }


def detect_audit_human_disagreements(reviewed_cases: list[ReviewedCase]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in reviewed_cases:
        if not _is_reviewed_case(r):
            continue
        if not r.human_decision.startswith("trim_"):
            continue
        if r.human_trim_pages is None or r.suggested_trim_pages is None:
            continue
        if r.human_trim_pages == r.suggested_trim_pages:
            continue
        out.append(
            {
                "case_id": r.case_id,
                "section": r.section,
                "subsection": r.subsection,
                "audit_suggested_trim_pages": r.suggested_trim_pages,
                "human_trim_pages": r.human_trim_pages,
                "delta": r.human_trim_pages - r.suggested_trim_pages,
                "notes": r.notes,
            }
        )
    return out


def _build_reviewed_group_stats(reviewed_cases: list[ReviewedCase]) -> dict[str, Any]:
    reviewed = [r for r in reviewed_cases if _is_reviewed_case(r)]

    by_subsection: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "trim_counts": Counter(),
            "decision_counts": Counter(),
            "plus_one": 0,
            "total": 0,
        }
    )
    by_section: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "trim_counts": Counter(),
            "decision_counts": Counter(),
            "plus_one": 0,
            "total": 0,
        }
    )

    global_trim_counts = Counter()
    global_plus_one = 0

    for r in reviewed:
        subkey = f"{r.section}/{r.subsection}"
        seckey = r.section
        for target in (by_subsection[subkey], by_section[seckey]):
            target["decision_counts"][r.human_decision] += 1
            target["total"] += 1

        if r.human_decision.startswith("trim_") and r.human_trim_pages is not None:
            by_subsection[subkey]["trim_counts"][r.human_trim_pages] += 1
            by_section[seckey]["trim_counts"][r.human_trim_pages] += 1
            global_trim_counts[r.human_trim_pages] += 1

            if r.suggested_trim_pages is not None and r.human_trim_pages == r.suggested_trim_pages + 1:
                by_subsection[subkey]["plus_one"] += 1
                by_section[seckey]["plus_one"] += 1
                global_plus_one += 1

    return {
        "by_subsection": by_subsection,
        "by_section": by_section,
        "global_trim_counts": global_trim_counts,
        "global_plus_one": global_plus_one,
    }


def _first_case_sets(merged_cases: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    by_section: dict[str, tuple[int, str]] = {}
    by_subsection: dict[str, tuple[int, str]] = {}

    for case in merged_cases:
        case_id = case["case_id"]
        expected = case.get("expected_start")
        if expected is None:
            prefix = case_id.split("_", 1)[0]
            expected = _to_int(prefix)
        if expected is None:
            continue

        section = case.get("section", "")
        subsection = case.get("subsection", "")

        if section and (section not in by_section or expected < by_section[section][0]):
            by_section[section] = (expected, case_id)

        subkey = f"{section}/{subsection}"
        if subsection and (subkey not in by_subsection or expected < by_subsection[subkey][0]):
            by_subsection[subkey] = (expected, case_id)

    section_first = {v[1] for v in by_section.values()}
    subsection_first = {v[1] for v in by_subsection.values()}
    return section_first, subsection_first


def infer_candidates(reviewed_cases: list[ReviewedCase], merged_cases: list[dict[str, Any]]) -> list[CandidateDecision]:
    reviewed_map = {r.case_id: r for r in reviewed_cases if _is_reviewed_case(r)}
    stats = _build_reviewed_group_stats(reviewed_cases)
    section_first, subsection_first = _first_case_sets(merged_cases)

    candidates: list[CandidateDecision] = []

    for case in merged_cases:
        case_id = case["case_id"]
        if case_id in reviewed_map:
            continue

        section = str(case.get("section", ""))
        subsection = str(case.get("subsection", ""))
        subkey = f"{section}/{subsection}"

        severity = str(case.get("severity", ""))
        flags = set(str(x) for x in (case.get("flags") or []))
        audit_trim = _to_int(case.get("suggested_trim_pages"))
        first_caso = _to_int(case.get("first_caso_problema_page"))

        sub_stats = stats["by_subsection"].get(subkey)
        sec_stats = stats["by_section"].get(section)

        option_trims: list[tuple[int, str, str, str]] = []

        if sub_stats and sub_stats["total"] > 0:
            decision_counts = sub_stats["decision_counts"]
            trim_counts = sub_stats["trim_counts"]
            nonzero_decisions = [k for k, v in decision_counts.items() if v > 0]

            if len(nonzero_decisions) > 1 and trim_counts:
                candidates.append(
                    CandidateDecision(
                        case_id=case_id,
                        section=section,
                        subsection=subsection,
                        severity=severity,
                        audit_suggested_trim_pages=audit_trim,
                        inferred_human_trim_pages=None,
                        inferred_decision="inspect_manual",
                        confidence="manual",
                        inference_reason="conflicting reviewed decisions in same subsection",
                        needs_manual_confirmation=True,
                        source="subsection_conflict",
                        notes="",
                    )
                )
                continue

            if trim_counts:
                dominant_trim, dominant_count = trim_counts.most_common(1)[0]
                if dominant_trim == 2 and dominant_count >= 1 and len(trim_counts) == 1:
                    option_trims.append((2, "high", "same subsection reviewed trim=2", "candidate_trim_2"))

            if sub_stats["plus_one"] >= 1 and audit_trim is not None:
                option_trims.append(
                    (
                        audit_trim + 1,
                        "high",
                        "same subsection shows audit underestimation by +1",
                        "candidate_trim_plus_one",
                    )
                )

        if sec_stats and sec_stats["trim_counts"]:
            sec_trim_counts = sec_stats["trim_counts"]
            sec_dominant_trim, sec_dominant_count = sec_trim_counts.most_common(1)[0]
            if sec_dominant_trim == 2 and sec_dominant_count >= 2 and len(sec_trim_counts) == 1:
                option_trims.append((2, "medium", "same section reviewed trim=2 pattern", "candidate_trim_2"))

            if sec_stats["plus_one"] >= 2 and audit_trim is not None:
                option_trims.append(
                    (
                        audit_trim + 1,
                        "medium",
                        "same section shows audit underestimation by +1",
                        "candidate_trim_plus_one",
                    )
                )

        if (
            (case_id in section_first or case_id in subsection_first)
            and ("leading_contamination" in flags or (first_caso is not None and first_caso >= 3))
        ):
            structural_trim = max(2, audit_trim or 0)
            option_trims.append(
                (
                    structural_trim,
                    "low",
                    "first case structural intro candidate",
                    "structural_intro_candidate",
                )
            )

        if severity == "confirmed_boundary_error" and audit_trim in {1, 2}:
            option_trims.append((audit_trim, "low", "preserve audit suggested trim", "audit_preserve"))

        if stats["global_plus_one"] >= 1 and audit_trim is not None:
            option_trims.append(
                (
                    audit_trim + 1,
                    "low",
                    "global reviewed pattern suggests audit +1 in some cases",
                    "candidate_trim_plus_one",
                )
            )

        if severity == "low_confidence_review" or "unclear_sequence" in flags:
            candidates.append(
                CandidateDecision(
                    case_id=case_id,
                    section=section,
                    subsection=subsection,
                    severity=severity,
                    audit_suggested_trim_pages=audit_trim,
                    inferred_human_trim_pages=None,
                    inferred_decision="inspect_manual",
                    confidence="manual",
                    inference_reason="high uncertainty in audit severity/flags",
                    needs_manual_confirmation=True,
                    source="uncertainty_rule",
                    notes="",
                )
            )
            continue

        if not option_trims:
            candidates.append(
                CandidateDecision(
                    case_id=case_id,
                    section=section,
                    subsection=subsection,
                    severity=severity,
                    audit_suggested_trim_pages=audit_trim,
                    inferred_human_trim_pages=None,
                    inferred_decision="inspect_manual",
                    confidence="manual",
                    inference_reason="insufficient pattern support",
                    needs_manual_confirmation=True,
                    source="no_pattern_support",
                    notes="",
                )
            )
            continue

        rank = {"high": 0, "medium": 1, "low": 2}
        sorted_options = sorted(option_trims, key=lambda x: rank[x[1]])
        best_rank = rank[sorted_options[0][1]]
        top_options = [x for x in sorted_options if rank[x[1]] == best_rank]
        top_trims = {x[0] for x in top_options}

        if len(top_trims) > 1:
            candidates.append(
                CandidateDecision(
                    case_id=case_id,
                    section=section,
                    subsection=subsection,
                    severity=severity,
                    audit_suggested_trim_pages=audit_trim,
                    inferred_human_trim_pages=None,
                    inferred_decision="inspect_manual",
                    confidence="manual",
                    inference_reason="conflicting inferred trim values",
                    needs_manual_confirmation=True,
                    source="conflicting_rules",
                    notes="; ".join(sorted({r[2] for r in top_options})),
                )
            )
            continue

        best = sorted_options[0]
        inferred_trim = best[0]
        inferred_decision = "trim_2_leading_pages" if inferred_trim == 2 else "trim_1_leading_page"
        if inferred_trim not in {1, 2}:
            inferred_decision = "inspect_manual"

        if inferred_decision == "inspect_manual":
            candidates.append(
                CandidateDecision(
                    case_id=case_id,
                    section=section,
                    subsection=subsection,
                    severity=severity,
                    audit_suggested_trim_pages=audit_trim,
                    inferred_human_trim_pages=None,
                    inferred_decision="inspect_manual",
                    confidence="manual",
                    inference_reason="inferred trim out of supported range",
                    needs_manual_confirmation=True,
                    source=best[3],
                    notes=best[2],
                )
            )
            continue

        candidates.append(
            CandidateDecision(
                case_id=case_id,
                section=section,
                subsection=subsection,
                severity=severity,
                audit_suggested_trim_pages=audit_trim,
                inferred_human_trim_pages=inferred_trim,
                inferred_decision=inferred_decision,
                confidence=best[1],
                inference_reason=best[2],
                needs_manual_confirmation=best[1] == "manual",
                source=best[3],
                notes="",
            )
        )

    return sorted(candidates, key=lambda x: (x.confidence, x.section, x.subsection, x.case_id))


def _reviewed_to_dict(r: ReviewedCase) -> dict[str, Any]:
    return {
        "case_id": r.case_id,
        "section": r.section,
        "subsection": r.subsection,
        "severity": r.severity,
        "suggested_trim_pages": r.suggested_trim_pages,
        "human_decision": r.human_decision,
        "human_trim_pages": r.human_trim_pages,
        "confidence": r.confidence,
        "notes": r.notes,
        "booleans": r.booleans,
        "audit_flags": r.audit_flags,
        "first_detected_footer": r.first_detected_footer,
        "expected_start": r.expected_start,
        "first_caso_problema_page": r.first_caso_problema_page,
    }


def _candidate_to_dict(c: CandidateDecision) -> dict[str, Any]:
    return {
        "case_id": c.case_id,
        "section": c.section,
        "subsection": c.subsection,
        "severity": c.severity,
        "audit_suggested_trim_pages": c.audit_suggested_trim_pages,
        "inferred_human_trim_pages": c.inferred_human_trim_pages,
        "inferred_decision": c.inferred_decision,
        "confidence": c.confidence,
        "inference_reason": c.inference_reason,
        "needs_manual_confirmation": c.needs_manual_confirmation,
        "source": c.source,
        "notes": c.notes,
    }


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
    return "\n".join(lines)


def _html_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _html_table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{_html_escape(h)}</th>" for h in headers)
    body_rows = []
    for row in rows:
        body_rows.append("<tr>" + "".join(f"<td>{_html_escape(v)}</td>" for v in row) + "</tr>")
    return (
        "<table><thead><tr>"
        + head
        + "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table>"
    )


def write_outputs(
    output_dir: Path,
    summary: dict[str, Any],
    reviewed_cases: list[ReviewedCase],
    disagreements: list[dict[str, Any]],
    candidates: list[CandidateDecision],
    pattern_notes: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates_dicts = [_candidate_to_dict(c) for c in candidates]
    reviewed_dicts = [_reviewed_to_dict(r) for r in reviewed_cases if _is_reviewed_case(r)]

    report_json = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_summary": summary,
        "reviewed_cases": reviewed_dicts,
        "audit_human_disagreements": disagreements,
        "inferred_patterns": pattern_notes,
        "candidate_decisions": candidates_dicts,
        "warning": "These are candidate decisions only. They must not be applied without user approval.",
    }

    (output_dir / "decision_pattern_report.json").write_text(
        json.dumps(report_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    (output_dir / "inferred_review_decisions_candidates.json").write_text(
        json.dumps(candidates_dicts, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    with (output_dir / "inferred_review_decisions_candidates.csv").open(
        "w", encoding="utf-8", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in candidates_dicts:
            writer.writerow(row)

    reviewed_rows = [
        [
            r["case_id"],
            r["section"],
            r["subsection"],
            r["severity"],
            r["suggested_trim_pages"],
            r["human_decision"],
            r["human_trim_pages"],
            r["confidence"],
        ]
        for r in reviewed_dicts
    ]

    disagreement_rows = [
        [
            d["case_id"],
            d["section"],
            d["subsection"],
            d["audit_suggested_trim_pages"],
            d["human_trim_pages"],
            d["delta"],
        ]
        for d in disagreements
    ]

    grouped = defaultdict(list)
    for c in candidates_dicts:
        grouped[c["confidence"]].append(c)

    md_lines = [
        "# Boundary Review Decision Pattern Report",
        "",
        "**Warning:** These are candidate decisions only. They must not be applied without user approval.",
        "",
        "## Reviewed Decisions Summary",
        "",
        f"- Total reviewed cases: {summary['total_reviewed_cases']}",
        f"- Reviewed trim=0: {summary['reviewed_trim_0']}",
        f"- Reviewed trim=1: {summary['reviewed_trim_1']}",
        f"- Reviewed trim=2: {summary['reviewed_trim_2']}",
        f"- inspect_manual: {summary['inspect_manual']}",
        f"- uncertain: {summary['uncertain']}",
        "",
        "## Reviewed Cases",
        "",
        _markdown_table(
            [
                "case_id",
                "section",
                "subsection",
                "severity",
                "audit_suggested_trim",
                "human_decision",
                "human_trim",
                "confidence",
            ],
            reviewed_rows,
        ),
        "",
        "## Audit vs Human Disagreement",
        "",
        _markdown_table(
            ["case_id", "section", "subsection", "audit_trim", "human_trim", "delta"],
            disagreement_rows,
        )
        if disagreement_rows
        else "No audit-human trim disagreements among reviewed trim decisions.",
        "",
        "## Inferred Patterns",
        "",
        f"- subsection_trim2_patterns: {pattern_notes.get('subsection_trim2_patterns', 0)}",
        f"- section_trim2_patterns: {pattern_notes.get('section_trim2_patterns', 0)}",
        f"- plus_one_patterns: {pattern_notes.get('plus_one_patterns', 0)}",
        "",
    ]

    def _candidate_rows(items: list[dict[str, Any]]) -> list[list[Any]]:
        return [
            [
                x["case_id"],
                x["section"],
                x["subsection"],
                x["severity"],
                x["audit_suggested_trim_pages"],
                x["inferred_human_trim_pages"],
                x["inferred_decision"],
                x["inference_reason"],
            ]
            for x in items
        ]

    for bucket, title in [
        ("high", "High Confidence"),
        ("medium", "Medium Confidence"),
        ("low", "Low Confidence"),
        ("manual", "Inspect Manual"),
    ]:
        md_lines.extend(
            [
                f"## Candidate Corrections - {title}",
                "",
                _markdown_table(
                    [
                        "case_id",
                        "section",
                        "subsection",
                        "severity",
                        "audit_trim",
                        "inferred_trim",
                        "inferred_decision",
                        "reason",
                    ],
                    _candidate_rows(grouped.get(bucket, [])),
                )
                if grouped.get(bucket)
                else "No cases.",
                "",
            ]
        )

    (output_dir / "decision_pattern_report.md").write_text("\n".join(md_lines), encoding="utf-8")

    html_sections: list[str] = []
    html_sections.append(
        f"""
<h1>Boundary Review Decision Pattern Report</h1>
<p class="warning"><strong>Warning:</strong> These are candidate decisions only. They must not be applied without user approval.</p>
<h2>Reviewed Decisions Summary</h2>
<ul>
  <li>Total reviewed cases: {_html_escape(summary['total_reviewed_cases'])}</li>
  <li>Reviewed trim=0: {_html_escape(summary['reviewed_trim_0'])}</li>
  <li>Reviewed trim=1: {_html_escape(summary['reviewed_trim_1'])}</li>
  <li>Reviewed trim=2: {_html_escape(summary['reviewed_trim_2'])}</li>
  <li>inspect_manual: {_html_escape(summary['inspect_manual'])}</li>
  <li>uncertain: {_html_escape(summary['uncertain'])}</li>
</ul>
"""
    )

    html_sections.append("<h2>Reviewed Cases</h2>")
    html_sections.append(
        _html_table(
            [
                "case_id",
                "section",
                "subsection",
                "severity",
                "audit_suggested_trim",
                "human_decision",
                "human_trim",
                "confidence",
            ],
            reviewed_rows,
        )
    )

    html_sections.append("<h2>Audit vs Human Disagreement</h2>")
    if disagreement_rows:
        html_sections.append(
            _html_table(
                ["case_id", "section", "subsection", "audit_trim", "human_trim", "delta"],
                disagreement_rows,
            )
        )
    else:
        html_sections.append("<p>No audit-human trim disagreements among reviewed trim decisions.</p>")

    html_sections.append("<h2>Inferred Patterns</h2>")
    html_sections.append(
        f"""
<ul>
  <li>subsection_trim2_patterns: {_html_escape(pattern_notes.get('subsection_trim2_patterns', 0))}</li>
  <li>section_trim2_patterns: {_html_escape(pattern_notes.get('section_trim2_patterns', 0))}</li>
  <li>plus_one_patterns: {_html_escape(pattern_notes.get('plus_one_patterns', 0))}</li>
</ul>
"""
    )

    for bucket, title in [
        ("high", "High Confidence"),
        ("medium", "Medium Confidence"),
        ("low", "Low Confidence"),
        ("manual", "Inspect Manual"),
    ]:
        html_sections.append(f"<h2>Candidate Corrections - {title}</h2>")
        items = grouped.get(bucket, [])
        if not items:
            html_sections.append("<p>No cases.</p>")
            continue
        html_sections.append(
            _html_table(
                [
                    "case_id",
                    "section",
                    "subsection",
                    "severity",
                    "audit_trim",
                    "inferred_trim",
                    "inferred_decision",
                    "reason",
                ],
                _candidate_rows(items),
            )
        )

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Boundary Decision Pattern Report</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; line-height: 1.4; }}
    h1, h2 {{ margin-top: 1.2rem; }}
    .warning {{ background: #fff4e5; border: 1px solid #ffcc80; padding: 10px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px 0; font-size: 14px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 6px 8px; text-align: left; vertical-align: top; }}
    thead {{ background: #f6f8fa; }}
    tr:nth-child(even) td {{ background: #fbfdff; }}
  </style>
</head>
<body>
{''.join(html_sections)}
</body>
</html>
"""
    (output_dir / "decision_pattern_report.html").write_text(html_doc, encoding="utf-8")


def analyze(
    *,
    review_decisions_path: Path,
    review_cases_path: Path,
    audit_path: Path,
    correction_plan_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    decisions = load_review_decisions(review_decisions_path)
    review_cases = _load_review_cases(review_cases_path)
    audit_cases = _load_audit_cases(audit_path)
    correction_plan = _load_correction_plan(correction_plan_path)

    reviewed_cases, merged_cases, _ = merge_case_context(decisions, review_cases, audit_cases, correction_plan)
    summary = summarize_reviewed_decisions(reviewed_cases)
    disagreements = detect_audit_human_disagreements(reviewed_cases)
    candidates = infer_candidates(reviewed_cases, merged_cases)

    group_stats = _build_reviewed_group_stats(reviewed_cases)
    pattern_notes = {
        "subsection_trim2_patterns": sum(
            1
            for _, stats in group_stats["by_subsection"].items()
            if stats["trim_counts"].get(2, 0) >= 1 and len(stats["trim_counts"]) == 1
        ),
        "section_trim2_patterns": sum(
            1
            for _, stats in group_stats["by_section"].items()
            if stats["trim_counts"].get(2, 0) >= 2 and len(stats["trim_counts"]) == 1
        ),
        "plus_one_patterns": group_stats["global_plus_one"],
    }

    write_outputs(output_dir, summary, reviewed_cases, disagreements, candidates, pattern_notes)

    confidence_counts = Counter(c.confidence for c in candidates)

    return {
        "summary": summary,
        "disagreements": disagreements,
        "candidates": candidates,
        "confidence_counts": dict(confidence_counts),
        "output_dir": str(output_dir),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze manual boundary review decisions and infer candidate patterns.")
    parser.add_argument(
        "--review-decisions",
        default="data/curated/boundary_review/review_decisions.json",
    )
    parser.add_argument(
        "--review-cases",
        default="data/curated/boundary_review/review_cases.json",
    )
    parser.add_argument(
        "--audit",
        default="data/curated/case_boundary_audit_v2.json",
    )
    parser.add_argument(
        "--correction-plan",
        default="data/curated/case_boundary_correction_plan_v2.json",
    )
    parser.add_argument(
        "--output-dir",
        default="data/curated/boundary_review",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = analyze(
        review_decisions_path=Path(args.review_decisions),
        review_cases_path=Path(args.review_cases),
        audit_path=Path(args.audit),
        correction_plan_path=Path(args.correction_plan),
        output_dir=Path(args.output_dir),
    )

    summary = result["summary"]
    counts = result["confidence_counts"]
    print(f"[Decision Analysis] reviewed={summary['total_reviewed_cases']}")
    print(
        "[Decision Analysis] human trims: "
        f"trim0={summary['reviewed_trim_0']} trim1={summary['reviewed_trim_1']} trim2={summary['reviewed_trim_2']}"
    )
    print(f"[Decision Analysis] disagreements={len(result['disagreements'])}")
    print(
        "[Decision Analysis] inferred candidates: "
        f"high={counts.get('high', 0)} medium={counts.get('medium', 0)} "
        f"low={counts.get('low', 0)} manual={counts.get('manual', 0)}"
    )
    print(f"[Decision Analysis] output_dir={result['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
