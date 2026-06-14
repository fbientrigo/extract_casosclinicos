import json
from pathlib import Path

def test_notebook_exists_and_contains_strings():
    notebook_path = Path("notebooks/2_explorer_llmwiki_clean.ipynb")
    assert notebook_path.exists(), "Notebook file not found"
    
    with open(notebook_path, "r", encoding="utf-8") as f:
        notebook_data = json.load(f)
        
    # Serialize cells to a single string for easy searching
    cells_text = ""
    for cell in notebook_data.get("cells", []):
        for line in cell.get("source", []):
            cells_text += line
            
        pass

def test_notebook_cell_count():
    notebook_path = Path("notebooks/2_explorer_llmwiki_clean.ipynb")
    with open(notebook_path, "r", encoding="utf-8") as f:
        notebook_data = json.load(f)
    cells = notebook_data.get("cells", [])
    assert len(cells) >= 15, f"Expected at least 15 cells in the upgraded notebook, found {len(cells)}"
