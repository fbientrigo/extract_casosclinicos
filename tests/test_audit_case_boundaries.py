from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from scripts.audit_case_boundaries import (  # noqa: E402
    audit_one_case,
    detect_footer_in_page,
    main,
    parse_expected_start,
    split_case_md_by_page,
)


def _write_case(
    ocr_root: Path,
    *,
    section: str,
    subsection: str,
    case_id: str,
    source_pdf: str,
    case_md: str,
    page_count: int,
) -> Path:
    case_dir = ocr_root / section / subsection / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "case_metadata.json").write_text(
        json.dumps(
            {
                "case_id": case_id,
                "section": section,
                "subsection": subsection,
                "source_pdf": source_pdf,
                "page_count": page_count,
                "status": "success",
            }
        ),
        encoding="utf-8",
    )
    (case_dir / "case.md").write_text(case_md, encoding="utf-8")
    return case_dir / "case_metadata.json"


def test_parse_expected_start() -> None:
    assert parse_expected_start("762_loxoscelismo") == 762
    assert parse_expected_start("100_some_case") == 100
    assert parse_expected_start("no_prefix") is None


def test_detect_footer_in_page() -> None:
    assert detect_footer_in_page("algo\n\n762\n") == 762
    assert detect_footer_in_page("algo\n\n9999\n") == 9999


def test_split_case_md_by_page() -> None:
    content = """---
case_id: 100_clean_case
---

## Page 1
Uno

## Page 2
Dos
"""
    pages = split_case_md_by_page(content)
    assert pages == [(1, "Uno"), (2, "Dos")]


def test_regression_762_loxoscelismo_confirmed_trim_2(tmp_path: Path) -> None:
    ocr_root = tmp_path / "data/ocr_cases"
    book_root = tmp_path / "book"
    audit_img_dir = tmp_path / "data/curated/boundary_audit"
    book_root.mkdir(parents=True)
    audit_img_dir.mkdir(parents=True, exist_ok=True)

    meta = _write_case(
        ocr_root,
        section="seccion6",
        subsection="artropodos",
        case_id="762_loxoscelismo",
        source_pdf="seccion6/artropodos/762_loxoscelismo.pdf",
        page_count=5,
        case_md="""---
printed_start_page: 762
---
## Page 1
Respuestas y comentarios
760
## Page 2
Lecturas sugeridas
761
## Page 3
Caso Problema 137
762
## Page 4
Preguntas
763
## Page 5
Respuestas y comentarios
764
""",
    )

    result = audit_one_case(meta, book_root, {}, audit_img_dir, render_flagged=False)
    assert result is not None
    assert result.severity == "confirmed_boundary_error"
    assert "leading_contamination" in result.footer_flags
    assert "previous_case_tail" in result.content_flags
    assert result.suggested_trim_pages == 2
    assert result.suggested_action == "trim_leading_pages"


def test_false_positive_numbers_not_footer(tmp_path: Path) -> None:
    ocr_root = tmp_path / "data/ocr_cases"
    book_root = tmp_path / "book"
    audit_img_dir = tmp_path / "data/curated/boundary_audit"
    book_root.mkdir(parents=True)
    audit_img_dir.mkdir(parents=True, exist_ok=True)

    meta = _write_case(
        ocr_root,
        section="seccion5",
        subsection="gastro",
        case_id="539_diarrea_por_rotavirus",
        source_pdf="seccion5/gastro/539_diarrea_por_rotavirus.pdf",
        page_count=2,
        case_md="""---
printed_start_page: 539
---
## Page 1
Caso Problema
Pregunta 1:
La opción correcta es:
a) texto
b) texto
c) texto
1
## Page 2
Preguntas
Pregunta 2:
""",
    )

    result = audit_one_case(meta, book_root, {}, audit_img_dir, render_flagged=False)
    assert result is not None
    assert result.footer_confidence == "low"
    assert "footer_unresolved" in result.footer_flags
    assert result.severity == "low_confidence_review"
    assert result.suggested_trim_pages is None
    assert result.suggested_action == "inspect_manual"


def test_normal_case_clean(tmp_path: Path) -> None:
    ocr_root = tmp_path / "data/ocr_cases"
    book_root = tmp_path / "book"
    audit_img_dir = tmp_path / "data/curated/boundary_audit"
    book_root.mkdir(parents=True)
    audit_img_dir.mkdir(parents=True, exist_ok=True)

    meta = _write_case(
        ocr_root,
        section="seccion2",
        subsection="sub",
        case_id="112_anemia_ferropriva",
        source_pdf="seccion2/sub/112_anemia_ferropriva.pdf",
        page_count=1,
        case_md="""---
printed_start_page: 112
---
## Page 1
Caso Problema
112
""",
    )

    result = audit_one_case(meta, book_root, {}, audit_img_dir, render_flagged=False)
    assert result is not None
    assert result.severity == "clean"
    assert result.footer_confidence == "high"
    assert result.first_reliable_footer == 112
    assert result.suggested_trim_pages is None
    assert result.suggested_action == "no_action"


def test_extreme_trim_prevention(tmp_path: Path) -> None:
    ocr_root = tmp_path / "data/ocr_cases"
    book_root = tmp_path / "book"
    audit_img_dir = tmp_path / "data/curated/boundary_audit"
    book_root.mkdir(parents=True)
    audit_img_dir.mkdir(parents=True, exist_ok=True)

    meta = _write_case(
        ocr_root,
        section="seccion6",
        subsection="artropodos",
        case_id="773_sarna",
        source_pdf="seccion6/artropodos/773_sarna.pdf",
        page_count=1,
        case_md="""---
printed_start_page: 773
---
## Page 1
Caso Problema
11
""",
    )

    result = audit_one_case(meta, book_root, {}, audit_img_dir, render_flagged=False)
    assert result is not None
    assert "unreliable_footer_detection" in result.footer_flags
    assert result.severity == "low_confidence_review"
    assert result.suggested_trim_pages is None
    assert result.suggested_action == "inspect_manual"


def test_main_generates_expected_outputs_v2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ocr_root = tmp_path / "data/ocr_cases"
    book_root = tmp_path / "book"
    output_dir = tmp_path / "data/curated"
    ocr_root.mkdir(parents=True)
    book_root.mkdir(parents=True)

    _write_case(
        ocr_root,
        section="seccion6",
        subsection="artropodos",
        case_id="762_loxoscelismo",
        source_pdf="seccion6/artropodos/762_loxoscelismo.pdf",
        page_count=5,
        case_md="""---
printed_start_page: 762
---
## Page 1
Respuestas y comentarios
760
## Page 2
Lecturas sugeridas
761
## Page 3
Caso Problema
762
## Page 4
Preguntas
763
## Page 5
Respuestas y comentarios
764
""",
    )

    monkeypatch.setattr(
        "scripts.audit_case_boundaries.load_manifest_expected_page_counts",
        lambda _: ({}, None),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_case_boundaries.py",
            "--ocr-root",
            str(ocr_root),
            "--book-root",
            str(book_root),
            "--output-dir",
            str(output_dir),
            "--no-thumbnails",
        ],
    )

    assert main() == 0

    audit_json = output_dir / "case_boundary_audit_v2.json"
    audit_md = output_dir / "case_boundary_audit_v2.md"
    plan_json = output_dir / "case_boundary_correction_plan_v2.json"
    assert audit_json.exists()
    assert audit_md.exists()
    assert plan_json.exists()

    audit_payload = json.loads(audit_json.read_text(encoding="utf-8"))
    flagged = audit_payload["flagged_cases"]
    assert audit_payload["total_cases_audited"] == 1
    assert audit_payload["total_clean_boundaries"] == 0
    assert audit_payload["total_flagged"] == 1
    assert flagged[0]["case_id"] == "762_loxoscelismo"
    assert flagged[0]["severity"] == "confirmed_boundary_error"
    assert "leading_contamination" in flagged[0]["footer_flags"]
    assert "previous_case_tail" in flagged[0]["content_flags"]
    assert flagged[0]["suggested_trim_pages"] == 2
