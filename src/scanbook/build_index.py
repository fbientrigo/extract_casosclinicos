from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from scanbook.errors import MissingDependencyError
from scanbook.utils import ensure_dir, read_jsonl, write_jsonl


def build_index(
    input_jsonl: Path,
    output_dir: Path,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    vector_store: str = "none",
    batch_size: int = 8,
) -> dict[str, Any]:
    rows = read_jsonl(input_jsonl)
    chunks = [_row_to_chunk(r, i) for i, r in enumerate(rows)]
    texts = [c["text"] for c in chunks]
    if not texts:
        raise ValueError("No text chunks found for indexing.")

    ensure_dir(output_dir)
    chunks_path = output_dir / "chunks.jsonl"
    write_jsonl(chunks, chunks_path)

    used_store = vector_store.lower()
    if used_store == "none":
        pass
    elif used_store == "lexical":
        lexical_index = _build_lexical_index(chunks)
        (output_dir / "lexical_index.json").write_text(
            json.dumps(lexical_index, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    elif used_store == "faiss":
        embeddings = _embed_texts(texts=texts, model_name=model_name, batch_size=batch_size)
        _build_faiss(output_dir, embeddings)
    elif used_store == "chroma":
        embeddings = _embed_texts(texts=texts, model_name=model_name, batch_size=batch_size)
        _build_chroma(output_dir, chunks, embeddings)
    else:
        embeddings = _embed_texts(texts=texts, model_name=model_name, batch_size=batch_size)
        _save_numpy(output_dir, embeddings)
        used_store = "none"

    summary = {
        "input_jsonl": str(input_jsonl),
        "output_dir": str(output_dir),
        "model_name": model_name,
        "vector_store": used_store,
        "records": len(chunks),
    }
    (output_dir / "index_meta.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


TOKEN_RE = re.compile(r"[a-z0-9]{2,}", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in TOKEN_RE.findall(text)]


def _build_lexical_index(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    postings: dict[str, list[int]] = {}
    doc_len: list[int] = []
    for i, chunk in enumerate(chunks):
        tokens = _tokenize(str(chunk.get("text", "")))
        doc_len.append(len(tokens))
        seen: set[str] = set()
        for token in tokens:
            if token in seen:
                continue
            seen.add(token)
            postings.setdefault(token, []).append(i)
    n_docs = len(chunks)
    avg_doc_len = (sum(doc_len) / n_docs) if n_docs else 0.0
    df = {token: len(ids) for token, ids in postings.items()}
    idf = {token: math.log(1.0 + (n_docs - freq + 0.5) / (freq + 0.5)) for token, freq in df.items()}
    return {
        "n_docs": n_docs,
        "avg_doc_len": avg_doc_len,
        "doc_len": doc_len,
        "postings": postings,
        "idf": idf,
    }


def _row_to_chunk(row: dict[str, Any], i: int) -> dict[str, Any]:
    text = str(row.get("text", "")).strip()
    if not text:
        text = str(row.get("title", "")).strip()
    return {
        "chunk_id": str(row.get("case_id") or row.get("chunk_id") or f"chunk-{i:06d}"),
        "text": text,
        "chapter_id": row.get("chapter_id"),
        "page_start": row.get("page_start"),
        "page_end": row.get("page_end"),
        "extractor": row.get("extractor"),
        "ocr_quality": row.get("ocr_quality"),
        "source_file": row.get("source_file"),
        "title": row.get("title"),
    }


def _embed_texts(texts: list[str], model_name: str, batch_size: int) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise MissingDependencyError(
            "sentence-transformers is required for build-index. Install extras: rag."
        ) from exc
    model = SentenceTransformer(model_name)
    return model.encode(texts, batch_size=batch_size, show_progress_bar=False, normalize_embeddings=True)


def _save_numpy(output_dir: Path, embeddings: Any) -> None:
    try:
        import numpy as np
    except ImportError as exc:
        raise MissingDependencyError("numpy is required to save embeddings.") from exc
    np.save(output_dir / "embeddings.npy", np.asarray(embeddings, dtype="float32"))


def _build_faiss(output_dir: Path, embeddings: Any) -> None:
    try:
        import faiss
        import numpy as np
    except ImportError as exc:
        raise MissingDependencyError("faiss-cpu and numpy are required for FAISS indexing.") from exc
    arr = np.asarray(embeddings, dtype="float32")
    index = faiss.IndexFlatIP(arr.shape[1])
    index.add(arr)
    faiss.write_index(index, str(output_dir / "index.faiss"))
    np.save(output_dir / "embeddings.npy", arr)


def _build_chroma(output_dir: Path, chunks: list[dict[str, Any]], embeddings: Any) -> None:
    try:
        import chromadb
    except ImportError as exc:
        raise MissingDependencyError("chromadb is required for Chroma indexing.") from exc
    client = chromadb.PersistentClient(path=str(output_dir / "chroma"))
    collection = client.get_or_create_collection("scanbook_chunks")
    ids = [c["chunk_id"] for c in chunks]
    docs = [c["text"] for c in chunks]
    metas = [{k: v for k, v in c.items() if k not in {"text"}} for c in chunks]
    collection.add(ids=ids, documents=docs, embeddings=embeddings.tolist(), metadatas=metas)
