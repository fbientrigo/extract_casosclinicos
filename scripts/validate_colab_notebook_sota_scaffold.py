#!/usr/bin/env python3
import json
import sys
from pathlib import Path

NOTEBOOK_PATH = Path("notebooks/colab_clinical_cases_embeddings.ipynb")

def main():
    print(f"Validating notebook static scaffold at: {NOTEBOOK_PATH}")
    if not NOTEBOOK_PATH.exists():
        print(f"Error: Notebook not found at {NOTEBOOK_PATH}")
        return 1

    try:
        with open(NOTEBOOK_PATH, "r", encoding="utf-8") as f:
            nb = json.load(f)
    except Exception as e:
        print(f"Error parsing notebook JSON: {e}")
        return 1

    cells = nb.get("cells", [])
    code_cells = [c for c in cells if c.get("cell_type") == "code"]
    
    print(f"Found {len(cells)} cells, {len(code_cells)} code cells.")
    
    # Concatenate all code cells for search check
    full_code = ""
    syntax_errors = 0
    
    for idx, cell in enumerate(code_cells):
        lines = cell.get("source", [])
        code = "".join(lines)
        full_code += code + "\n"
        
        # Strip Jupyter magic commands before syntax check
        clean_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("!") or stripped.startswith("%"):
                # Replace with pass or comment to preserve line count
                clean_lines.append("# " + line)
            else:
                clean_lines.append(line)
        
        clean_code = "".join(clean_lines)
        try:
            compile(clean_code, f"Cell_{idx}", "exec")
        except SyntaxError as se:
            print(f"Syntax Error in Code Cell {idx} (lines {se.lineno} in cell):\n{se}")
            print("--- Cell Code Snippet ---")
            print(clean_code[:400])
            print("-------------------------")
            syntax_errors += 1

    if syntax_errors > 0:
        print(f"Validation FAILED with {syntax_errors} syntax errors in notebook code cells.")
        return 1

    # Check for required configurations, functions, tables, and assertions
    required_patterns = {
        "Configuration Variables": [
            "BUNDLE_PATH",
            "OUTPUT_BUNDLE_PATH",
            "RUN_MODE",
            "QUALITY_MODE",
            "EMBEDDING_BACKEND",
            "MODEL_REGISTRY",
            "CHUNK_TOKENS",
            "CHUNK_OVERLAP",
            "MIN_CHUNK_CHARS",
            "BATCH_SIZE",
            "RANDOM_SEED"
        ],
        "Model Registry Names": [
            "Qwen/Qwen3-Embedding-4B",
            "Qwen/Qwen3-Embedding-0.6B",
            "BAAI/bge-m3",
            "jinaai/jina-embeddings-v3",
            "intfloat/multilingual-e5-base"
        ],
        "Token Chunking": [
            "build_case_document",
            "chunk_text_by_tokens",
            "chunks_df",
            "case_id",
            "chunk_id",
            "chunk_index",
            "chunk_text",
            "chunk_char_count",
            "token_start",
            "token_end"
        ],
        "Embedding Implementations": [
            "embed_chunks_qwen3",
            "embed_chunks_sentence_transformers",
            "chunk_embeddings_df",
            "case_embeddings_df",
            "weighted"
        ],
        "Similarity & Neighbors": [
            "cosine_similarity",
            "nearest_neighbors_df",
            "neighbor_case_id",
            "same_section",
            "same_subsection",
            "cross_section_neighbor_rate",
            "same_subsection_neighbor_rate"
        ],
        "Clustering Suite": [
            "hdbscan",
            "KMeans",
            "AgglomerativeClustering",
            "silhouette_score",
            "cluster_model_report_df",
            "clusters_df"
        ],
        "UMAP & Visuals": [
            "umap_coordinates_df",
            "umap_x",
            "umap_y",
            "plt.scatter"
        ],
        "Rarity & Diversity Metrics": [
            "section_rarity_score",
            "subsection_rarity_score",
            "cluster_rarity_score",
            "neighbor_diversity_score",
            "length_balance_score",
            "semantic_centrality_score",
            "semantic_novelty_score",
            "curriculum_coverage_score",
            "diversity_metrics_df"
        ],
        "Star Case Scoring": [
            "teaching_score",
            "review_priority",
            "star_case_scores_df"
        ],
        "DuckDB Tables": [
            "chunk_embeddings",
            "case_embeddings",
            "embeddings",
            "clusters",
            "nearest_neighbors",
            "umap_coordinates",
            "cluster_model_report",
            "diversity_metrics",
            "star_case_scores",
            "model_run_metadata"
        ],
        "Verification Assertions": [
            "READY_FOR_STAR_CASE_REVIEW",
            "cases_count",
            "prefacio_27_28"
        ]
    }

    missing_elements = 0
    for category, elements in required_patterns.items():
        print(f"Checking category: {category}...")
        for elem in elements:
            if elem not in full_code:
                print(f"  [MISSING] Missing required element: '{elem}'")
                missing_elements += 1
            else:
                print(f"  [OK] Found: '{elem}'")

    if missing_elements > 0:
        print(f"Validation FAILED with {missing_elements} missing required elements.")
        return 1

    print("Static validation PASSED successfully!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
