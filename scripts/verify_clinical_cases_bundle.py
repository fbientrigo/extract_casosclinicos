#!/usr/bin/env python3
import json
import hashlib
from pathlib import Path
import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_PATH = PROJECT_ROOT / "data" / "clinical_cases_bundle.duckdb"
VERIFICATION_JSON_PATH = PROJECT_ROOT / "data" / "clinical_cases_bundle_verification.json"
VERIFICATION_MD_PATH = PROJECT_ROOT / "data" / "clinical_cases_bundle_verification.md"

def get_sha256(file_path):
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def main():
    print(f"Verifying bundle: {BUNDLE_PATH}")
    
    results = {
        "checks": {},
        "bundle_info": {},
        "smoke_cases": {},
        "final_status": "FAILED"
    }
    
    # 1. File exists
    exists = BUNDLE_PATH.exists()
    results["checks"]["file_exists"] = exists
    if not exists:
        print("Error: Bundle file does not exist.")
        save_results(results)
        return 1
    
    results["bundle_info"]["path"] = str(BUNDLE_PATH.relative_to(PROJECT_ROOT))
    results["bundle_info"]["size_mb"] = round(BUNDLE_PATH.stat().st_size / (1024 * 1024), 2)
    results["bundle_info"]["sha256"] = get_sha256(BUNDLE_PATH)
    
    con = duckdb.connect(str(BUNDLE_PATH), read_only=True)
    
    try:
        # 2. Tables exist
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        required_tables = ["cases", "pages", "source_lineage", "acceptance", "embeddings", "clusters", "star_case_scores", "book_metadata", "section_metadata"]
        results["checks"]["tables_exist"] = all(t in tables for t in required_tables)
        results["bundle_info"]["tables"] = tables
        
        # 3. Row counts
        counts = {}
        for t in required_tables:
            counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        
        results["bundle_info"]["row_counts"] = counts
        results["checks"]["cases_count_139"] = (counts["cases"] == 139)
        results["checks"]["source_lineage_count_139"] = (counts["source_lineage"] == 139)
        results["checks"]["acceptance_count_1"] = (counts["acceptance"] == 1)
        results["checks"]["embeddings_count_0"] = (counts["embeddings"] == 0)
        results["checks"]["clusters_count_0"] = (counts["clusters"] == 0)
        results["checks"]["star_case_scores_count_0"] = (counts["star_case_scores"] == 0)
        
        # 4. Content checks
        prefacio_count = con.execute("SELECT COUNT(*) FROM cases WHERE case_id = 'prefacio_27_28'").fetchone()[0]
        results["checks"]["prefacio_absent"] = (prefacio_count == 0)
        
        ceto_count = con.execute("SELECT COUNT(*) FROM cases WHERE case_id = '48_cetoacidosis_diabetica'").fetchone()[0]
        results["checks"]["48_cetoacidosis_diabetica_present"] = (ceto_count == 1)
        
        liquido_count = con.execute("SELECT COUNT(*) FROM cases WHERE case_id = '73_liquido_seminal'").fetchone()[0]
        results["checks"]["73_liquido_seminal_present"] = (liquido_count == 1)
        
        unique_cases = con.execute("SELECT COUNT(DISTINCT case_id) FROM cases").fetchone()[0]
        results["checks"]["case_id_unique"] = (unique_cases == 139)
        
        # Foreign key-like checks
        orphan_pages = con.execute("SELECT COUNT(*) FROM pages WHERE case_id NOT IN (SELECT case_id FROM cases)").fetchone()[0]
        results["checks"]["no_orphan_pages"] = (orphan_pages == 0)
        
        orphan_lineage = con.execute("SELECT COUNT(*) FROM source_lineage WHERE case_id NOT IN (SELECT case_id FROM cases)").fetchone()[0]
        results["checks"]["no_orphan_lineage"] = (orphan_lineage == 0)
        
        # 5. Acceptance values
        acc = con.execute("SELECT acceptance_status, embedding_status FROM acceptance").fetchone()
        results["checks"]["acceptance_status_ok"] = (acc[0] == "ACCEPTED_CLEAN_CANONICAL_BASELINE")
        results["checks"]["embedding_status_not_built"] = (acc[1] == "not_built")
        
        # 6. Lineage smoke checks
        smoke_cases = {
            "306_anafilaxia": "book_corrected_v2",
            "762_loxoscelismo": "book_corrected_v2",
            "773_sarna": "book_corrected_v2",
            "117_anemia_de_enfermedades_cronicas": "book",
            "296_sindrome_antifosfolipido": "book"
        }
        
        lineage_pass = True
        for cid, expected_root in smoke_cases.items():
            observed = con.execute("SELECT source_root FROM source_lineage WHERE case_id = ?", [cid]).fetchone()
            if observed and observed[0] == expected_root:
                results["smoke_cases"][cid] = {"ok": True, "observed": observed[0]}
            else:
                results["smoke_cases"][cid] = {"ok": False, "expected": expected_root, "observed": observed[0] if observed else None}
                lineage_pass = False
        
        results["checks"]["lineage_smoke_checks_pass"] = lineage_pass
        
        # Final status
        all_checks_pass = all(v is True for k, v in results["checks"].items())
        if all_checks_pass:
            results["final_status"] = "READY_FOR_COLAB_UPLOAD"
        
    finally:
        con.close()
    
    save_results(results)
    print(f"Verification complete. Status: {results['final_status']}")
    return 0 if results["final_status"] == "READY_FOR_COLAB_UPLOAD" else 1

def save_results(results):
    # JSON
    VERIFICATION_JSON_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    
    # MD
    md = f"""# Clinical Cases Bundle Verification Report

- **Bundle Path:** `{results['bundle_info'].get('path')}`
- **Bundle Size:** {results['bundle_info'].get('size_mb')} MB
- **Bundle SHA256:** `{results['bundle_info'].get('sha256')}`
- **Final Status:** `{results['final_status']}`

## Table Row Counts

| Table | Count |
|-------|-------|
"""
    for t, c in results['bundle_info'].get('row_counts', {}).items():
        md += f"| {t} | {c} |\n"
    
    md += "\n## Check Results\n\n"
    for check, pass_status in results['checks'].items():
        emoji = "✅" if pass_status is True else "❌"
        md += f"- {emoji} {check}\n"
        
    md += "\n## Lineage Smoke Checks\n\n"
    for cid, info in results['smoke_cases'].items():
        emoji = "✅" if info['ok'] else "❌"
        md += f"- {emoji} {cid}: {info['observed']}\n"
        
    VERIFICATION_MD_PATH.write_text(md, encoding="utf-8")

if __name__ == "__main__":
    import sys
    sys.exit(main())
