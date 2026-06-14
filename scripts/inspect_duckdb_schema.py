import duckdb
import sys

def print_schema(db_path):
    print(f"=== SCHEMA FOR {db_path} ===")
    try:
        con = duckdb.connect(db_path, read_only=True)
        tables = con.execute("SHOW TABLES").fetchall()
        for t in tables:
            table_name = t[0]
            print(f"\nTable: {table_name}")
            count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            print(f"Row count: {count}")
            columns = con.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            for col in columns:
                print(f"  {col[1]}: {col[2]}")
        con.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        for p in sys.argv[1:]:
            print_schema(p)
    else:
        # Pass one or more DuckDB paths as arguments, e.g.:
        #   python scripts/inspect_duckdb_schema.py data/<book_id>.duckdb
        print_schema("data/clinical_cases_bundle.duckdb")
