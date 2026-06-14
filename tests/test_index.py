from __future__ import annotations

import builtins
import json
from pathlib import Path

from scanbook.build_index import build_index
from scanbook.query import query_index


def _write_cases(path: Path) -> None:
    rows = [
        {"case_id": "a1", "text": "adult patient with chest pain and dyspnea"},
        {"case_id": "a2", "text": "child with fever and rash"},
        {"case_id": "a3", "text": "adult with abdominal pain and nausea"},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_build_and_query_lexical(tmp_path: Path) -> None:
    input_jsonl = tmp_path / "cases.jsonl"
    index_dir = tmp_path / "index"
    _write_cases(input_jsonl)
    meta = build_index(input_jsonl=input_jsonl, output_dir=index_dir, vector_store="lexical")
    assert meta["vector_store"] == "lexical"
    assert (index_dir / "chunks.jsonl").exists()
    assert (index_dir / "lexical_index.json").exists()
    hits = query_index(index_dir=index_dir, question="adult chest pain", top_k=2)
    assert hits
    assert hits[0]["chunk_id"] in {"a1", "a3"}


def test_build_index_none_does_not_import_sentence_transformers(tmp_path: Path, monkeypatch) -> None:
    input_jsonl = tmp_path / "cases.jsonl"
    index_dir = tmp_path / "index_none"
    _write_cases(input_jsonl)

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "sentence_transformers" or name.startswith("sentence_transformers."):
            raise AssertionError("sentence_transformers should not be imported for vector_store=none")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    meta = build_index(input_jsonl=input_jsonl, output_dir=index_dir, vector_store="none")
    assert meta["vector_store"] == "none"
    assert (index_dir / "chunks.jsonl").exists()
    assert not (index_dir / "embeddings.npy").exists()
