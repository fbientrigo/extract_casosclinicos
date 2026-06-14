from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "scripts" / "freeze_clean_rebuild_acceptance.py"

# This whole module is an acceptance test over locally built, copyrighted-derived
# artifacts under data/curated/ (never committed). Skip cleanly when absent.
pytestmark = pytest.mark.skipif(
    not (ROOT / "data" / "curated" / "clean_case_pdf_manifest.json").exists(),
    reason="Requires locally built data/curated artifacts (copyrighted-derived; not committed).",
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location("freeze_clean_rebuild_acceptance", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acceptance_artifact_generated() -> None:
    module = _load_script_module()
    payload = module.generate_acceptance(ROOT)

    out_json = ROOT / "data/curated/final_clean_rebuild_acceptance.json"
    out_md = ROOT / "data/curated/final_clean_rebuild_acceptance.md"

    assert out_json.exists()
    assert out_md.exists()
    assert payload["acceptance_status"] == "ACCEPTED_CLEAN_CANONICAL_BASELINE"


def test_acceptance_status_and_required_checks() -> None:
    module = _load_script_module()
    payload = module.generate_acceptance(ROOT)

    assert payload["acceptance_status"] == "ACCEPTED_CLEAN_CANONICAL_BASELINE"
    assert payload["absence_checks"]["prefacio_27_28_absent"] is True
    assert payload["checks"]["required_smoke_cases_present"] is True
    assert payload["checks"]["embedding_status_not_built"] is True


def test_required_smoke_cases_present() -> None:
    module = _load_script_module()
    payload = module.generate_acceptance(ROOT)

    expected = {
        "48_cetoacidosis_diabetica",
        "73_liquido_seminal",
        "306_anafilaxia",
        "762_loxoscelismo",
        "773_sarna",
        "117_anemia_de_enfermedades_cronicas",
        "296_sindrome_antifosfolipido",
    }
    present = {case_id for case_id, ok in payload["presence_checks"].items() if ok}
    assert expected.issubset(present)


def test_embedding_status_remains_not_built() -> None:
    module = _load_script_module()
    payload = module.generate_acceptance(ROOT)

    assert payload["embedding"]["status"] == "not_built"


def test_no_ocr_db_embedding_generation_triggered() -> None:
    module = _load_script_module()

    ocr_summary = ROOT / "data/ocr_cases_global_summary.json"
    db_file = ROOT / "data/clinical_cases.db"
    emb_manifest = ROOT / "data/colab_exports/embedding_manifest.json"

    before = {
        "ocr_summary_mtime": ocr_summary.stat().st_mtime_ns,
        "db_mtime": db_file.stat().st_mtime_ns,
        "embedding_manifest_mtime": emb_manifest.stat().st_mtime_ns,
    }

    payload = module.generate_acceptance(ROOT)
    assert payload["acceptance_status"] == "ACCEPTED_CLEAN_CANONICAL_BASELINE"

    after = {
        "ocr_summary_mtime": ocr_summary.stat().st_mtime_ns,
        "db_mtime": db_file.stat().st_mtime_ns,
        "embedding_manifest_mtime": emb_manifest.stat().st_mtime_ns,
    }

    assert before == after

    acceptance_json = ROOT / "data/curated/final_clean_rebuild_acceptance.json"
    parsed = json.loads(acceptance_json.read_text(encoding="utf-8"))
    assert parsed["acceptance_status"] == "ACCEPTED_CLEAN_CANONICAL_BASELINE"
