from __future__ import annotations

import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from scripts.analyze_boundary_review_decisions import (  # noqa: E402
    detect_audit_human_disagreements,
    infer_candidates,
    load_review_decisions,
    merge_case_context,
    summarize_reviewed_decisions,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _minimal_context() -> tuple[list[dict], list[dict], list[dict]]:
    review_cases = [
        {
            "case_id": "100_case_a",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "flags": ["leading_contamination"],
            "suggested_trim_pages": 1,
            "expected_start": 100,
            "first_detected_footer": 99,
            "first_caso_problema_page": 3,
        },
        {
            "case_id": "101_case_b",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "flags": ["leading_contamination"],
            "suggested_trim_pages": 1,
            "expected_start": 101,
            "first_detected_footer": 100,
            "first_caso_problema_page": 3,
        },
        {
            "case_id": "102_case_c",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "flags": ["leading_contamination"],
            "suggested_trim_pages": 1,
            "expected_start": 102,
            "first_detected_footer": 101,
            "first_caso_problema_page": 3,
        },
    ]

    audit_cases = [
        {
            "case_id": "100_case_a",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "flags": ["leading_contamination"],
            "suggested_trim_pages": 1,
            "expected_start": 100,
            "first_detected_footer": 99,
            "first_caso_problema_page": 3,
        },
        {
            "case_id": "101_case_b",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "flags": ["leading_contamination"],
            "suggested_trim_pages": 1,
            "expected_start": 101,
            "first_detected_footer": 100,
            "first_caso_problema_page": 3,
        },
        {
            "case_id": "102_case_c",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "flags": ["leading_contamination"],
            "suggested_trim_pages": 1,
            "expected_start": 102,
            "first_detected_footer": 101,
            "first_caso_problema_page": 3,
        },
    ]

    correction_plan = []
    return review_cases, audit_cases, correction_plan


def test_parse_browser_exported_review_decisions_json(tmp_path: Path) -> None:
    payload = {
        "exported_at": "2026-05-27T00:00:00Z",
        "total_cases": 1,
        "decisions": [
            {
                "case_id": "100_case_a",
                "section": "seccionX",
                "subsection": "subA",
                "severity": "confirmed_boundary_error",
                "suggested_trim_pages": 1,
                "human_decision": "trim_2_leading_pages",
                "human_trim_pages": "",
                "confidence": "high",
                "notes": "separator then intro",
                "page1_previous_case": "false",
                "page2_previous_case": "false",
                "case_starts_correctly": "false",
                "render_ocr_mismatch": "false",
            }
        ],
    }
    path = tmp_path / "review_decisions.json"
    _write_json(path, payload)

    rows = load_review_decisions(path)
    assert len(rows) == 1
    assert rows[0]["human_decision"] == "trim_2_leading_pages"
    assert rows[0]["human_trim_pages"] == 2
    assert rows[0]["booleans"]["case_starts_correctly"] is False


def test_summarize_reviewed_decisions() -> None:
    decisions = [
        {
            "case_id": "100_case_a",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "suggested_trim_pages": 1,
            "human_decision": "trim_2_leading_pages",
            "human_trim_pages": 2,
            "confidence": "high",
            "notes": "",
            "booleans": {},
        },
        {
            "case_id": "101_case_b",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "suggested_trim_pages": None,
            "human_decision": "no_action",
            "human_trim_pages": None,
            "confidence": "high",
            "notes": "",
            "booleans": {},
        },
        {
            "case_id": "102_case_c",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "suggested_trim_pages": 1,
            "human_decision": "",
            "human_trim_pages": None,
            "confidence": "",
            "notes": "",
            "booleans": {},
        },
    ]
    review_cases, audit_cases, correction_plan = _minimal_context()
    reviewed_cases, _, _ = merge_case_context(decisions, review_cases, audit_cases, correction_plan)

    summary = summarize_reviewed_decisions(reviewed_cases)
    assert summary["total_reviewed_cases"] == 2
    assert summary["reviewed_trim_0"] == 1
    assert summary["reviewed_trim_2"] == 1


def test_detect_audit_human_disagreement() -> None:
    decisions = [
        {
            "case_id": "100_case_a",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "suggested_trim_pages": 1,
            "human_decision": "trim_2_leading_pages",
            "human_trim_pages": 2,
            "confidence": "high",
            "notes": "",
            "booleans": {},
        }
    ]
    review_cases, audit_cases, correction_plan = _minimal_context()
    reviewed_cases, _, _ = merge_case_context(decisions, review_cases, audit_cases, correction_plan)
    disagreements = detect_audit_human_disagreements(reviewed_cases)
    assert len(disagreements) == 1
    assert disagreements[0]["delta"] == 1


def test_infer_same_subsection_candidate() -> None:
    decisions = [
        {
            "case_id": "100_case_a",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "suggested_trim_pages": 1,
            "human_decision": "trim_2_leading_pages",
            "human_trim_pages": 2,
            "confidence": "high",
            "notes": "",
            "booleans": {},
        },
        {
            "case_id": "101_case_b",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "suggested_trim_pages": 1,
            "human_decision": "trim_2_leading_pages",
            "human_trim_pages": 2,
            "confidence": "high",
            "notes": "",
            "booleans": {},
        },
    ]
    review_cases, audit_cases, correction_plan = _minimal_context()
    reviewed_cases, merged_cases, _ = merge_case_context(decisions, review_cases, audit_cases, correction_plan)
    candidates = infer_candidates(reviewed_cases, merged_cases)
    inferred = {c.case_id: c for c in candidates}
    assert inferred["102_case_c"].inferred_decision == "trim_2_leading_pages"
    assert inferred["102_case_c"].confidence == "high"


def test_prevent_overwrite_human_reviewed_decisions() -> None:
    decisions = [
        {
            "case_id": "100_case_a",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "suggested_trim_pages": 1,
            "human_decision": "trim_2_leading_pages",
            "human_trim_pages": 2,
            "confidence": "high",
            "notes": "",
            "booleans": {},
        },
        {
            "case_id": "101_case_b",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "suggested_trim_pages": 1,
            "human_decision": "",
            "human_trim_pages": None,
            "confidence": "",
            "notes": "",
            "booleans": {},
        },
    ]
    review_cases, audit_cases, correction_plan = _minimal_context()
    reviewed_cases, merged_cases, _ = merge_case_context(decisions, review_cases, audit_cases, correction_plan)
    candidates = infer_candidates(reviewed_cases, merged_cases)
    candidate_ids = {c.case_id for c in candidates}
    assert "100_case_a" not in candidate_ids


def test_conflicting_reviewed_cases_produce_inspect_manual() -> None:
    decisions = [
        {
            "case_id": "100_case_a",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "suggested_trim_pages": 1,
            "human_decision": "trim_2_leading_pages",
            "human_trim_pages": 2,
            "confidence": "high",
            "notes": "",
            "booleans": {},
        },
        {
            "case_id": "101_case_b",
            "section": "seccionX",
            "subsection": "subA",
            "severity": "confirmed_boundary_error",
            "suggested_trim_pages": None,
            "human_decision": "no_action",
            "human_trim_pages": None,
            "confidence": "high",
            "notes": "",
            "booleans": {},
        },
    ]
    review_cases, audit_cases, correction_plan = _minimal_context()
    reviewed_cases, merged_cases, _ = merge_case_context(decisions, review_cases, audit_cases, correction_plan)
    candidates = infer_candidates(reviewed_cases, merged_cases)
    inferred = {c.case_id: c for c in candidates}
    assert inferred["102_case_c"].inferred_decision == "inspect_manual"
    assert inferred["102_case_c"].confidence == "manual"
