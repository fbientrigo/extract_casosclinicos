import json
import duckdb
from pathlib import Path

def main():
    bundle_path = Path("data/clinical_cases_bundle.duckdb")
    verification_path = Path("data/clinical_cases_bundle_verification.json")
    
    print("Checking bundle inputs before notebook execution...")
    
    if not bundle_path.exists():
        print(f"Error: Bundle not found at {bundle_path}")
        return 1
        
    if verification_path.exists():
        with open(verification_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        status = data.get("final_status")
        if status != "READY_FOR_COLAB_UPLOAD":
            print(f"Error: Verification status is {status}, expected READY_FOR_COLAB_UPLOAD")
            return 1
            
    con = duckdb.connect(str(bundle_path), read_only=True)
    
    cases_count = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    if cases_count != 139:
        print(f"Error: Expected 139 cases, found {cases_count}")
        return 1
        
    prefacio_count = con.execute("SELECT COUNT(*) FROM cases WHERE case_id = 'prefacio_27_28'").fetchone()[0]
    if prefacio_count != 0:
        print(f"Error: Expected prefacio_27_28 to be absent, found {prefacio_count}")
        return 1
        
    embeddings_count = con.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    if embeddings_count != 0:
        print(f"Error: Expected embeddings table to be empty, found {embeddings_count} rows")
        return 1
        
    con.close()
    
    print("Smoke checks passed. Bundle is ready for the notebook.")
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
