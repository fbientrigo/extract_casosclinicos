from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from scripts import build_clean_case_pdf_tree as tree
from scripts import clean_generated_artifacts as clean


def _write_pdf(path: Path, pages: int = 1) -> None:
    from pypdf import PdfWriter

    path.parent.mkdir(parents=True, exist_ok=True)
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=792)
    with path.open("wb") as f:
        w.write(f)


def test_cleanup_dry_run_does_not_delete(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "book_corrected").mkdir(parents=True)
    (tmp_path / "data/clinical_cases.db").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/clinical_cases.db").write_text("x", encoding="utf-8")

    monkeypatch.setattr(clean, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(clean, "MANIFEST_JSON", tmp_path / "data/curated/clean_rebuild_cleanup_manifest.json")
    monkeypatch.setattr(clean, "MANIFEST_MD", tmp_path / "data/curated/clean_rebuild_cleanup_manifest.md")

    summary = clean.run_cleanup(execute=False)
    assert summary["mode"] == "dry-run"
    assert (tmp_path / "book_corrected").exists()
    assert (tmp_path / "data/clinical_cases.db").exists()


def test_cleanup_never_targets_book_and_preserves_book_corrected_v2() -> None:
    assert "book" not in clean.TARGETS
    assert "book_corrected_v2" not in clean.TARGETS


def test_clean_tree_mapping_and_blockers(tmp_path: Path, monkeypatch) -> None:
    decisions = tmp_path / "data/curated/boundary_review/review_decisions_rule_v2.csv"
    decisions.parent.mkdir(parents=True, exist_ok=True)

    rows = [
        ["306_anafilaxia", "seccion3", "hipersensibilidad_tipo_i", "trim_2_leading_pages", "seccion3/hipersensibilidad_tipo_i/306_anafilaxia.pdf"],
        ["117_anemia_de_enfermedades_cronicas", "seccion2", "anemias_microciticas", "no_action", "seccion2/anemias_microciticas/117_anemia_de_enfermedades_cronicas.pdf"],
        ["48_cetoacidosis_diabetica", "seccion1", "equilibrio_electrolitico_y_acido_base", "inspect_manual", "seccion1/equilibrio_electrolitico_y_acido_base/48_cetoacidosis_diabetica.pdf"],
    ]
    with decisions.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "section", "subsection", "human_decision", "source_pdf"])
        for r in rows:
            w.writerow(r)

    corrected = tmp_path / "book_corrected_v2/seccion3/hipersensibilidad_tipo_i/306_anafilaxia.pdf"
    original = tmp_path / "book/seccion2/anemias_microciticas/117_anemia_de_enfermedades_cronicas.pdf"
    _write_pdf(corrected)
    _write_pdf(original)

    monkeypatch.setattr(tree, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tree, "DECISIONS_CSV", decisions)
    monkeypatch.setattr(tree, "CORRECTED_ROOT", tmp_path / "book_corrected_v2")
    monkeypatch.setattr(tree, "ORIGINAL_ROOT", tmp_path / "book")
    monkeypatch.setattr(tree, "CLEAN_ROOT", tmp_path / "book_cases_clean")
    monkeypatch.setattr(tree, "RESOLUTION_CSV", tmp_path / "data/curated/inspect_manual_resolution.csv")
    monkeypatch.setattr(tree, "BLOCKERS_MD", tmp_path / "data/curated/inspect_manual_blockers.md")
    monkeypatch.setattr(tree, "BLOCKERS_JSON", tmp_path / "data/curated/inspect_manual_blockers.json")
    monkeypatch.setattr(tree, "MANIFEST_CSV", tmp_path / "data/curated/clean_case_pdf_manifest.csv")
    monkeypatch.setattr(tree, "MANIFEST_JSON", tmp_path / "data/curated/clean_case_pdf_manifest.json")
    monkeypatch.setattr(tree, "MANIFEST_MD", tmp_path / "data/curated/clean_case_pdf_manifest.md")
    monkeypatch.setattr(tree, "EXPECTED_COUNTS", {"total": 3, "trim_2_leading_pages": 1, "no_action": 1, "inspect_manual": 1})

    code, _summary = tree.build_tree(allow_inspect_manual=False)
    assert code == 2
    assert (tmp_path / "data/curated/inspect_manual_blockers.json").exists()

    manifest = (tmp_path / "data/curated/clean_case_pdf_manifest.csv").read_text(encoding="utf-8")
    assert "306_anafilaxia" in manifest
    assert "117_anemia_de_enfermedades_cronicas" in manifest
    assert "48_cetoacidosis_diabetica" not in manifest


@pytest.mark.skipif(
    not (Path(__file__).resolve().parent.parent / "data/curated/clean_case_pdf_manifest.csv").exists(),
    reason="Requires locally built data/curated artifacts (copyrighted-derived; not committed).",
)
def test_clean_rebuild_artifacts_counts_and_exclusions() -> None:
    root = Path(__file__).resolve().parent.parent
    manifest_csv = root / "data/curated/clean_case_pdf_manifest.csv"
    ocr_summary = root / "data/ocr_cases_global_summary.json"
    db_path = root / "data/clinical_cases.db"
    colab_jsonl = root / "data/colab_exports/clinical_cases.jsonl"
    embedding_manifest = root / "data/colab_exports/embedding_manifest.json"
    exclusions_csv = root / "data/curated/non_case_exclusions.csv"
    resolution_csv = root / "data/curated/inspect_manual_resolution.csv"

    assert manifest_csv.exists()
    rows = list(csv.DictReader(manifest_csv.open("r", encoding="utf-8", newline="")))
    assert len(rows) == 139
    by_case = {r["case_id"]: r for r in rows}
    assert "prefacio_27_28" not in by_case
    assert by_case["48_cetoacidosis_diabetica"]["decision"] == "use_original_no_action"
    assert by_case["73_liquido_seminal"]["decision"] == "use_original_no_action"
    assert by_case["48_cetoacidosis_diabetica"]["source_root"] == "book"
    assert by_case["73_liquido_seminal"]["source_root"] == "book"
    assert by_case["306_anafilaxia"]["source_root"] == "book_corrected_v2"
    assert by_case["762_loxoscelismo"]["source_root"] == "book_corrected_v2"
    assert by_case["773_sarna"]["source_root"] == "book_corrected_v2"

    exclusions = list(csv.DictReader(exclusions_csv.open("r", encoding="utf-8", newline="")))
    assert any(r["case_id"] == "prefacio_27_28" and r["exclusion_type"] == "front_matter" for r in exclusions)
    resolutions = list(csv.DictReader(resolution_csv.open("r", encoding="utf-8", newline="")))
    resolved_ids = {r["case_id"] for r in resolutions}
    assert "48_cetoacidosis_diabetica" in resolved_ids
    assert "73_liquido_seminal" in resolved_ids

    summary = json.loads(ocr_summary.read_text(encoding="utf-8"))
    assert summary["total_discovered_cases"] == 139

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM cases")
    assert cur.fetchone()[0] == 139
    cur.execute("SELECT COUNT(*) FROM sections")
    assert cur.fetchone()[0] == 6
    cur.execute("SELECT COUNT(*) FROM subsections")
    assert cur.fetchone()[0] == 45
    cur.execute("SELECT COUNT(*) FROM cases WHERE case_id='prefacio_27_28'")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM embeddings")
    assert cur.fetchone()[0] == 0
    conn.close()

    assert colab_jsonl.exists()
    lines = [ln for ln in colab_jsonl.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 139
    assert not any(json.loads(ln)["case_id"] == "prefacio_27_28" for ln in lines)

    emb = json.loads(embedding_manifest.read_text(encoding="utf-8"))
    assert emb["status"] == "not_built"
