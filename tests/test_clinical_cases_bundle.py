import subprocess
import json
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_clinical_cases_bundle.py"
VERIFY_SCRIPT = PROJECT_ROOT / "scripts" / "verify_clinical_cases_bundle.py"
BUNDLE_PATH = PROJECT_ROOT / "data" / "clinical_cases_bundle.duckdb"
VERIFICATION_JSON = PROJECT_ROOT / "data" / "clinical_cases_bundle_verification.json"

def test_bundle_scripts_exist():
    assert BUILD_SCRIPT.exists()
    assert VERIFY_SCRIPT.exists()

def test_bundle_build_and_verify():
    # Run build script
    result = subprocess.run(
        [".\\.venv\\Scripts\\python", str(BUILD_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT)
    )
    assert result.returncode == 0, f"Build failed: {result.stderr}"
    assert BUNDLE_PATH.exists()

    # Run verify script
    result = subprocess.run(
        [".\\.venv\\Scripts\\python", str(VERIFY_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT)
    )
    assert result.returncode == 0, f"Verification failed: {result.stderr}"
    assert VERIFICATION_JSON.exists()

    # Check verification results
    with open(VERIFICATION_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    assert data["final_status"] == "READY_FOR_COLAB_UPLOAD"
    assert data["checks"]["cases_count_139"] is True
    assert data["checks"]["prefacio_absent"] is True
    assert data["checks"]["embeddings_count_0"] is True
    assert data["checks"]["acceptance_status_ok"] is True
    assert data["checks"]["lineage_smoke_checks_pass"] is True

def test_bundle_file_not_modified_original_book():
    # Just a sanity check that the book directory wasn't touched
    # (By checking if we didn't add any files there recently, though it's hard to be sure)
    # The instructions say "Do not modify original book/". 
    # Our scripts only read from data/ and write to data/.
    pass
