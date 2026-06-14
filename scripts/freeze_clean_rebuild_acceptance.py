#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ACCEPTANCE_JSON = PROJECT_ROOT / "data/curated/final_clean_rebuild_acceptance.json"
ACCEPTANCE_MD = PROJECT_ROOT / "data/curated/final_clean_rebuild_acceptance.md"

REQUIRED_CASES = [
    "48_cetoacidosis_diabetica",
    "73_liquido_seminal",
    "306_anafilaxia",
    "762_loxoscelismo",
    "773_sarna",
    "117_anemia_de_enfermedades_cronicas",
    "296_sindrome_antifosfolipido",
]

LINEAGE_EXPECTED = {
    "306_anafilaxia": "book_corrected_v2",
    "762_loxoscelismo": "book_corrected_v2",
    "773_sarna": "book_corrected_v2",
    "117_anemia_de_enfermedades_cronicas": "book",
    "296_sindrome_antifosfolipido": "book",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _jsonl_count(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def _csv_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def _build_inputs(project_root: Path) -> dict[str, Path]:
    return {
        "clean_manifest": project_root / "data/curated/clean_case_pdf_manifest.json",
        "ocr_summary": project_root / "data/ocr_cases_global_summary.json",
        "db_report": project_root / "data/curated/database_build_report.json",
        "case_registry": project_root / "data/curated/case_registry.csv",
        "colab_jsonl": project_root / "data/colab_exports/clinical_cases.jsonl",
        "colab_parquet": project_root / "data/colab_exports/clinical_cases.parquet",
        "embedding_manifest": project_root / "data/colab_exports/embedding_manifest.json",
        "clinical_db": project_root / "data/clinical_cases.db",
    }


def generate_acceptance(project_root: Path = PROJECT_ROOT) -> dict:
    paths = _build_inputs(project_root)
    required_inputs = list(paths.values())
    missing_inputs = [str(p) for p in required_inputs if not p.exists()]
    if missing_inputs:
        raise FileNotFoundError(f"Missing required input artifacts: {missing_inputs}")

    clean_manifest = _load_json(paths["clean_manifest"])
    ocr_summary = _load_json(paths["ocr_summary"])
    db_report = _load_json(paths["db_report"])
    embedding_manifest = _load_json(paths["embedding_manifest"])

    clean_summary = clean_manifest.get("summary", {})
    clean_cases = clean_manifest.get("cases", [])
    by_case = {row.get("case_id"): row for row in clean_cases}

    clean_pdf_count = int(clean_summary.get("included_cases", len(clean_cases)))
    ocr_case_count = int(ocr_summary.get("total_discovered_cases", 0))
    db_case_count = int(db_report.get("total_cases_inserted", 0))
    section_count = int(db_report.get("sections_count", 0))
    subsection_count = int(db_report.get("subsections_count", 0))
    case_registry_count = _csv_count(paths["case_registry"])
    colab_jsonl_row_count = _jsonl_count(paths["colab_jsonl"])
    colab_parquet_row_count = int(len(pd.read_parquet(paths["colab_parquet"])))

    prefacio_absent = "prefacio_27_28" not in by_case
    required_presence = {case_id: case_id in by_case for case_id in REQUIRED_CASES}

    lineage_checks = {}
    for case_id, expected_source in LINEAGE_EXPECTED.items():
        observed = (by_case.get(case_id) or {}).get("source_root")
        lineage_checks[case_id] = {
            "expected_source_root": expected_source,
            "observed_source_root": observed,
            "ok": observed == expected_source,
        }

    explicit_decisions = {
        "48_cetoacidosis_diabetica": (by_case.get("48_cetoacidosis_diabetica") or {}).get("decision"),
        "73_liquido_seminal": (by_case.get("73_liquido_seminal") or {}).get("decision"),
    }

    embedding_status = embedding_manifest.get("status")

    file_sizes = {
        "data/clinical_cases.db": paths["clinical_db"].stat().st_size,
        "data/colab_exports/clinical_cases.jsonl": paths["colab_jsonl"].stat().st_size,
        "data/colab_exports/clinical_cases.parquet": paths["colab_parquet"].stat().st_size,
        "data/colab_exports/embedding_manifest.json": paths["embedding_manifest"].stat().st_size,
    }

    hashes = {
        "data/clinical_cases.db": _sha256(paths["clinical_db"]),
        "data/colab_exports/clinical_cases.jsonl": _sha256(paths["colab_jsonl"]),
        "data/colab_exports/clinical_cases.parquet": _sha256(paths["colab_parquet"]),
    }

    checks = {
        "counts_match_clean_ocr_db": clean_pdf_count == ocr_case_count == db_case_count,
        "count_matches_case_registry": db_case_count == case_registry_count,
        "count_matches_colab_jsonl": db_case_count == colab_jsonl_row_count,
        "count_matches_colab_parquet": db_case_count == colab_parquet_row_count,
        "sections_expected_6": section_count == 6,
        "subsections_expected_45": subsection_count == 45,
        "prefacio_27_28_absent": prefacio_absent,
        "required_smoke_cases_present": all(required_presence.values()),
        "lineage_checks_pass": all(item["ok"] for item in lineage_checks.values()),
        "use_original_no_action_48": explicit_decisions["48_cetoacidosis_diabetica"] == "use_original_no_action",
        "use_original_no_action_73": explicit_decisions["73_liquido_seminal"] == "use_original_no_action",
        "embedding_status_not_built": embedding_status == "not_built",
    }

    acceptance_status = (
        "ACCEPTED_CLEAN_CANONICAL_BASELINE"
        if all(checks.values())
        else "REJECTED_CLEAN_CANONICAL_BASELINE"
    )

    payload = {
        "acceptance_status": acceptance_status,
        "counts": {
            "clean_pdf_count": clean_pdf_count,
            "ocr_case_count": ocr_case_count,
            "db_case_count": db_case_count,
            "case_registry_count": case_registry_count,
            "colab_jsonl_row_count": colab_jsonl_row_count,
            "colab_parquet_row_count": colab_parquet_row_count,
            "section_count": section_count,
            "subsection_count": subsection_count,
        },
        "absence_checks": {
            "prefacio_27_28_absent": prefacio_absent,
        },
        "presence_checks": required_presence,
        "lineage_checks": lineage_checks,
        "explicit_decisions": explicit_decisions,
        "embedding": {
            "status": embedding_status,
            "manifest": embedding_manifest,
        },
        "export_file_sizes_bytes": file_sizes,
        "sha256": hashes,
        "checks": checks,
        "inputs": {
            "clean_case_pdf_manifest": str(paths["clean_manifest"].relative_to(project_root)),
            "ocr_cases_global_summary": str(paths["ocr_summary"].relative_to(project_root)),
            "database_build_report": str(paths["db_report"].relative_to(project_root)),
            "case_registry": str(paths["case_registry"].relative_to(project_root)),
            "clinical_cases_jsonl": str(paths["colab_jsonl"].relative_to(project_root)),
            "clinical_cases_parquet": str(paths["colab_parquet"].relative_to(project_root)),
            "embedding_manifest": str(paths["embedding_manifest"].relative_to(project_root)),
        },
    }

    acceptance_json = project_root / "data/curated/final_clean_rebuild_acceptance.json"
    acceptance_md = project_root / "data/curated/final_clean_rebuild_acceptance.md"
    acceptance_json.parent.mkdir(parents=True, exist_ok=True)
    acceptance_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md_lines = [
        "# Final Clean Rebuild Acceptance",
        "",
        f"- acceptance_status: `{acceptance_status}`",
        "",
        "## Counts",
        f"- clean PDF count: {clean_pdf_count}",
        f"- OCR case count: {ocr_case_count}",
        f"- DB case count: {db_case_count}",
        f"- case registry count: {case_registry_count}",
        f"- Colab JSONL row count: {colab_jsonl_row_count}",
        f"- Colab Parquet row count: {colab_parquet_row_count}",
        f"- section count: {section_count}",
        f"- subsection count: {subsection_count}",
        "",
        "## Absence/Presence",
        f"- prefacio_27_28 absent: {prefacio_absent}",
    ]
    for case_id in REQUIRED_CASES:
        md_lines.append(f"- {case_id} present: {required_presence[case_id]}")

    md_lines.extend(
        [
            "",
            "## Lineage",
        ]
    )
    for case_id in LINEAGE_EXPECTED:
        entry = lineage_checks[case_id]
        md_lines.append(
            f"- {case_id}: expected={entry['expected_source_root']} observed={entry['observed_source_root']} ok={entry['ok']}"
        )

    md_lines.extend(
        [
            "",
            "## Decisions",
            f"- 48_cetoacidosis_diabetica decision: {explicit_decisions['48_cetoacidosis_diabetica']}",
            f"- 73_liquido_seminal decision: {explicit_decisions['73_liquido_seminal']}",
            "",
            "## Embeddings",
            f"- embedding status: {embedding_status}",
            "",
            "## Export File Sizes (bytes)",
        ]
    )
    for path, size in file_sizes.items():
        md_lines.append(f"- {path}: {size}")

    md_lines.extend(["", "## SHA256"])
    for path, digest in hashes.items():
        md_lines.append(f"- {path}: `{digest}`")

    md_lines.extend(["", "## Checks"])
    for name, ok in checks.items():
        md_lines.append(f"- {name}: {ok}")

    acceptance_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    payload = generate_acceptance(PROJECT_ROOT)
    print(f"acceptance_status={payload['acceptance_status']}")
    print(f"db_case_count={payload['counts']['db_case_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
