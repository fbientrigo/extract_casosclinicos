import os
from pathlib import Path

import duckdb
import pytest

# Acceptance test for a locally built case bundle. The bundle is derived from a
# (potentially copyrighted) source book and is never committed, so this whole
# module is skipped unless a bundle is present. Point it at your own bundle via
# the SCANBOOK_BUNDLE_DB env var, or drop one at the default path below.
BUNDLE_PATH = os.environ.get(
    "SCANBOOK_BUNDLE_DB", "data/bundles/clinical_cases_bundle.duckdb"
)

pytestmark = pytest.mark.skipif(
    not Path(BUNDLE_PATH).exists(),
    reason=(
        f"No case bundle at {BUNDLE_PATH}; set SCANBOOK_BUNDLE_DB to run "
        "this acceptance test against your locally built bundle."
    ),
)


@pytest.fixture
def conn():
    con = duckdb.connect(BUNDLE_PATH, read_only=True)
    yield con
    con.close()

def test_tables_exist(conn):
    tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
    expected_tables = ["acceptance", "cases", "clusters", "embeddings", "pages", "source_lineage", "star_case_scores"]
    for expected in expected_tables:
        assert expected in tables, f"Missing table {expected}"

def test_acceptance_row_count(conn):
    count = conn.execute("SELECT COUNT(*) FROM acceptance").fetchone()[0]
    assert count == 1, f"Expected 1 row in acceptance, got {count}"

def test_source_lineage_row_count(conn):
    cases_count = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    lineage_count = conn.execute("SELECT COUNT(*) FROM source_lineage").fetchone()[0]
    assert lineage_count == cases_count, "source_lineage row count must equal cases row count"

def test_cases_columns(conn):
    cols = [col[1] for col in conn.execute("PRAGMA table_info('cases')").fetchall()]
    expected_cols = [
        "case_id", "title", "section", "subsection", "printed_start_page",
        "printed_end_page", "page_count", "char_count", "clean_text",
        "source_pdf_path", "clean_pdf_path", "boundary_decision",
        "boundary_source", "ocr_version"
    ]
    for expected in expected_cols:
        assert expected in cols, f"Missing column {expected} in cases"

def test_embeddings_exists(conn):
    count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    assert count >= 0

def test_clusters_exists(conn):
    count = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
    assert count >= 0

def test_star_case_scores_exists(conn):
    count = conn.execute("SELECT COUNT(*) FROM star_case_scores").fetchone()[0]
    assert count >= 0
