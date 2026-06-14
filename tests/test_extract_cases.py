from __future__ import annotations

from pathlib import Path

from scanbook.extract_cases import extract_case_candidates


def test_extract_case_candidates(tmp_path: Path) -> None:
    src = tmp_path / "cases.md"
    src.write_text(
        "# Intro\n\n"
        "No candidate here.\n\n"
        "## Caso clinico 1\n"
        "Paciente de 50 anos con dolor abdominal y nauseas.\n"
        "Se documenta anamnesis y examen fisico.\n\n"
        "## Clinical Case 2\n"
        "Patient with dyspnea and chest discomfort.\n"
        "Findings and progression are recorded.\n",
        encoding="utf-8",
    )
    out = tmp_path / "cases.jsonl"
    rows = extract_case_candidates(inputs=[src], output_jsonl=out, schema_path=None)

    assert out.exists()
    assert len(rows) == 2
    assert any("paciente" in " ".join(r["keywords"]) for r in rows)
    assert all(r["text"] for r in rows)

