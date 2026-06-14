from __future__ import annotations

import csv
import json
import sys
from hashlib import sha256
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from scripts.apply_boundary_review_decisions import load_decisions, run_apply  # noqa: E402
from scripts.generate_boundary_decisions_from_rule_v2 import generate_rule_v2  # noqa: E402
from scripts.build_boundary_review_dashboard import (  # noqa: E402
    build_boundary_review_dashboard,
    write_dashboard_html,
    write_review_decisions_template_csv,
)


def _write_pdf(path: Path, pages: int) -> None:
    from pypdf import PdfWriter

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as f:
        writer.write(f)


def _pdf_pages(path: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(path)).pages)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_build_review_cases_json_generation(tmp_path: Path) -> None:
    audit_path = tmp_path / "data/curated/case_boundary_audit_v2.json"
    plan_path = tmp_path / "data/curated/case_boundary_correction_plan_v2.json"
    book_root = tmp_path / "book"
    output_dir = tmp_path / "data/curated/boundary_review"

    _write_pdf(book_root / "seccion1/suba/100_case_a.pdf", pages=5)
    _write_pdf(book_root / "seccion2/subb/200_case_b.pdf", pages=4)

    audit_payload = {
        "flagged_cases": [
            {
                "case_id": "100_case_a",
                "section": "seccion1",
                "subsection": "suba",
                "severity": "confirmed_boundary_error",
                "flags": ["leading_contamination"],
                "suggested_trim_pages": 1,
                "expected_start": 100,
                "first_detected_footer": 99,
                "source_pdf": "seccion1/suba/100_case_a.pdf",
                "first_caso_problema_page": 2,
            }
        ]
    }
    correction_payload = [
        {
            "case_id": "200_case_b",
            "severity": "clean",
            "action": "trim_leading_pages",
            "trim_leading_pages": 2,
            "affected_paths": ["seccion2/subb/200_case_b.pdf"],
        }
    ]
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit_payload), encoding="utf-8")
    plan_path.write_text(json.dumps(correction_payload), encoding="utf-8")

    cases = build_boundary_review_dashboard(
        audit_json_path=audit_path,
        correction_plan_path=plan_path,
        book_root=book_root,
        output_dir=output_dir,
        render_thumbnails=False,
    )

    assert len(cases) == 2
    assert {c["case_id"] for c in cases} == {"100_case_a", "200_case_b"}

    dataset_path = output_dir / "review_cases.json"
    assert dataset_path.exists()
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    assert dataset["total_cases"] == 2


def test_html_file_generation(tmp_path: Path) -> None:
    html_path = tmp_path / "index.html"
    write_dashboard_html(
        [
            {
                "case_id": "100_case",
                "section": "seccion1",
                "subsection": "sub",
                "severity": "confirmed_boundary_error",
                "flags": ["leading_contamination"],
                "suggested_trim_pages": 1,
                "expected_start": 100,
                "first_detected_footer": 99,
                "source_pdf": "seccion1/sub/100_case.pdf",
                "first_caso_problema_page": 3,
                "correction_plan_action": "trim_leading_pages",
                "thumbnails": [],
            }
        ],
        html_path,
    )
    content = html_path.read_text(encoding="utf-8")
    assert "Boundary Review Dashboard" in content
    assert "Export decisions (CSV)" in content
    assert "only undecided" in content


def test_csv_template_generation(tmp_path: Path) -> None:
    csv_path = tmp_path / "review_decisions_template.csv"
    write_review_decisions_template_csv(
        [
            {
                "case_id": "100_case",
                "section": "seccion1",
                "subsection": "sub",
                "severity": "confirmed_boundary_error",
                "suggested_trim_pages": 2,
            }
        ],
        csv_path,
    )
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["case_id"] == "100_case"
    assert rows[0]["suggested_trim_pages"] == "2"
    assert rows[0]["human_decision"] == ""


def test_decision_parser_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "review_decisions.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
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
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "100_case",
                "section": "seccion1",
                "subsection": "sub",
                "severity": "confirmed_boundary_error",
                "suggested_trim_pages": "1",
                "human_decision": "trim_1_leading_page",
                "human_trim_pages": "1",
                "confidence": "high",
                "notes": "ok",
                "page1_previous_case": "true",
                "page2_previous_case": "false",
                "case_starts_correctly": "",
                "render_ocr_mismatch": "0",
            }
        )

    rows = load_decisions(csv_path)
    assert len(rows) == 1
    row = rows[0]
    assert row.case_id == "100_case"
    assert row.human_trim_pages == 1
    assert row.page1_previous_case is True
    assert row.page2_previous_case is False
    assert row.render_ocr_mismatch is False
    assert row.source_pdf == "seccion1/sub/100_case.pdf"


def test_dry_run_apply_only_lists_actions(tmp_path: Path) -> None:
    input_root = tmp_path / "book"
    output_root = tmp_path / "book_corrected"
    report_dir = tmp_path / "reports"
    decisions_path = tmp_path / "decisions.csv"

    _write_pdf(input_root / "seccion1/sub/100_case.pdf", pages=4)

    with decisions_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
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
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "100_case",
                "section": "seccion1",
                "subsection": "sub",
                "severity": "confirmed_boundary_error",
                "suggested_trim_pages": "1",
                "human_decision": "trim_1_leading_page",
                "human_trim_pages": "1",
            }
        )

    summary = run_apply(
        decisions_path=decisions_path,
        input_root=input_root,
        output_root=output_root,
        report_dir=report_dir,
        execute=False,
    )
    assert summary["mode"] == "dry-run"
    assert len(summary["planned_actions"]) == 1
    assert len(summary["executed_trims"]) == 0
    assert not (output_root / "seccion1/sub/100_case.pdf").exists()


def test_execute_trim_synthetic_pdf_and_keep_original(tmp_path: Path) -> None:
    input_root = tmp_path / "book"
    output_root = tmp_path / "book_corrected"
    report_dir = tmp_path / "reports"
    decisions_path = tmp_path / "decisions.csv"
    src_pdf = input_root / "seccion1/sub/100_case.pdf"

    _write_pdf(src_pdf, pages=5)
    original_pages = _pdf_pages(src_pdf)

    with decisions_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
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
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "100_case",
                "section": "seccion1",
                "subsection": "sub",
                "severity": "confirmed_boundary_error",
                "suggested_trim_pages": "2",
                "human_decision": "trim_2_leading_pages",
                "human_trim_pages": "2",
            }
        )

    summary = run_apply(
        decisions_path=decisions_path,
        input_root=input_root,
        output_root=output_root,
        report_dir=report_dir,
        execute=True,
    )

    out_pdf = output_root / "seccion1/sub/100_case.pdf"
    assert out_pdf.exists()
    assert len(summary["executed_trims"]) == 1
    assert _pdf_pages(out_pdf) == 3
    assert _pdf_pages(src_pdf) == original_pages
    assert (report_dir / "applied_review_decisions.json").exists()
    assert (report_dir / "applied_review_decisions.md").exists()


def test_execute_does_not_overwrite_original_pdf(tmp_path: Path) -> None:
    input_root = tmp_path / "book"
    output_root = tmp_path / "book_corrected"
    report_dir = tmp_path / "reports"
    decisions_path = tmp_path / "decisions.csv"
    src_pdf = input_root / "seccion6/artropodos/762_loxoscelismo.pdf"

    _write_pdf(src_pdf, pages=4)
    original_hash = _sha256(src_pdf)

    with decisions_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
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
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "762_loxoscelismo",
                "section": "seccion6",
                "subsection": "artropodos",
                "severity": "confirmed_boundary_error",
                "suggested_trim_pages": "1",
                "human_decision": "trim_1_leading_page",
                "human_trim_pages": "1",
            }
        )

    run_apply(
        decisions_path=decisions_path,
        input_root=input_root,
        output_root=output_root,
        report_dir=report_dir,
        execute=True,
    )

    assert _sha256(src_pdf) == original_hash


def test_generate_rule_v2_enforces_human_ranges(tmp_path: Path) -> None:
    data_dir = tmp_path / "data/curated"
    review_dir = data_dir / "boundary_review"
    book_dir = tmp_path / "book"
    manifest = book_dir / "book_split_manifest.yaml"
    review_dir.mkdir(parents=True, exist_ok=True)
    book_dir.mkdir(parents=True, exist_ok=True)

    audit = {
        "flagged_cases": [
            {
                "case_id": "306_anafilaxia",
                "section": "seccion3",
                "subsection": "hipersensibilidad_tipo_i",
                "expected_start": 306,
                "suggested_trim_pages": 1,
                "suggested_action": "trim_leading_pages",
                "source_pdf": "seccion3/hipersensibilidad_tipo_i/306_anafilaxia.pdf",
            },
            {
                "case_id": "773_sarna",
                "section": "seccion6",
                "subsection": "artropodos",
                "expected_start": 773,
                "suggested_action": "inspect_manual",
                "source_pdf": "seccion6/artropodos/773_sarna.pdf",
            },
            {
                "case_id": "117_anemia_de_enfermedades_cronicas",
                "section": "seccion2",
                "subsection": "anemias_microciticas",
                "expected_start": 117,
                "source_pdf": "seccion2/anemias_microciticas/117_anemia_de_enfermedades_cronicas.pdf",
            },
            {
                "case_id": "296_sindrome_antifosfolipido",
                "section": "seccion2",
                "subsection": "trombofilias",
                "expected_start": 296,
                "source_pdf": "seccion2/trombofilias/296_sindrome_antifosfolipido.pdf",
            },
        ]
    }
    plan = [{"case_id": "773_sarna", "action": "inspect_manual"}]
    review_cases = {"cases": audit["flagged_cases"], "total_cases": 4}
    prior = {"decisions": []}
    manifest.write_text(
        "sections:\n"
        "- slug: seccion2\n"
        "  subsections:\n"
        "  - slug: anemias_microciticas\n"
        "    cases:\n"
        "    - printed_start: 117\n"
        "      output_path: book/seccion2/anemias_microciticas/117_anemia_de_enfermedades_cronicas.pdf\n"
        "  - slug: trombofilias\n"
        "    cases:\n"
        "    - printed_start: 296\n"
        "      output_path: book/seccion2/trombofilias/296_sindrome_antifosfolipido.pdf\n"
        "- slug: seccion3\n"
        "  subsections:\n"
        "  - slug: hipersensibilidad_tipo_i\n"
        "    cases:\n"
        "    - printed_start: 306\n"
        "      output_path: book/seccion3/hipersensibilidad_tipo_i/306_anafilaxia.pdf\n"
        "- slug: seccion6\n"
        "  subsections:\n"
        "  - slug: artropodos\n"
        "    cases:\n"
        "    - printed_start: 773\n"
        "      output_path: book/seccion6/artropodos/773_sarna.pdf\n",
        encoding="utf-8",
    )

    (data_dir / "case_boundary_audit_v2.json").write_text(json.dumps(audit), encoding="utf-8")
    (data_dir / "case_boundary_correction_plan_v2.json").write_text(json.dumps(plan), encoding="utf-8")
    (review_dir / "review_cases.json").write_text(json.dumps(review_cases), encoding="utf-8")
    (review_dir / "review_decisions.json").write_text(json.dumps(prior), encoding="utf-8")

    report = generate_rule_v2(
        audit_path=data_dir / "case_boundary_audit_v2.json",
        correction_plan_path=data_dir / "case_boundary_correction_plan_v2.json",
        review_cases_path=review_dir / "review_cases.json",
        review_decisions_path=review_dir / "review_decisions.json",
        manifest_path=manifest,
        output_dir=review_dir,
    )

    decisions = json.loads((review_dir / "review_decisions_rule_v2.json").read_text(encoding="utf-8"))["decisions"]
    by_case = {r["case_id"]: r for r in decisions}
    assert by_case["306_anafilaxia"]["human_decision"] == "trim_2_leading_pages"
    assert by_case["306_anafilaxia"]["human_trim_pages"] == 2
    assert by_case["773_sarna"]["human_decision"] == "trim_2_leading_pages"
    assert by_case["773_sarna"]["human_trim_pages"] == 2
    assert by_case["117_anemia_de_enfermedades_cronicas"]["human_decision"] == "no_action"
    assert by_case["117_anemia_de_enfermedades_cronicas"]["human_trim_pages"] == 0
    assert by_case["296_sindrome_antifosfolipido"]["human_decision"] == "no_action"
    assert by_case["296_sindrome_antifosfolipido"]["human_trim_pages"] == 0
    assert report["totals"]["trim_2_count"] == 2
    assert report["totals"]["no_action_count"] == 2


def test_apply_accepts_book_corrected_v2_and_never_modifies_book(tmp_path: Path) -> None:
    input_root = tmp_path / "book"
    output_root = tmp_path / "book_corrected_v2"
    report_dir = tmp_path / "reports"
    decisions_path = tmp_path / "decisions.csv"
    src_pdf = input_root / "seccion3/hipersensibilidad_tipo_i/306_anafilaxia.pdf"
    _write_pdf(src_pdf, pages=5)
    src_hash = _sha256(src_pdf)

    with decisions_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
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
                "source_pdf",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "306_anafilaxia",
                "section": "seccion3",
                "subsection": "hipersensibilidad_tipo_i",
                "severity": "confirmed_boundary_error",
                "human_decision": "trim_2_leading_pages",
                "human_trim_pages": "2",
                "source_pdf": "seccion3/hipersensibilidad_tipo_i/306_anafilaxia.pdf",
            }
        )

    summary = run_apply(
        decisions_path=decisions_path,
        input_root=input_root,
        output_root=output_root,
        report_dir=report_dir,
        execute=True,
    )
    out_pdf = output_root / "seccion3/hipersensibilidad_tipo_i/306_anafilaxia.pdf"
    assert out_pdf.exists()
    assert _pdf_pages(out_pdf) == 3
    assert summary["output_root"].endswith("book_corrected_v2")
    assert _sha256(src_pdf) == src_hash
