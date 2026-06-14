from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from scanbook.errors import MissingDependencyError
from scanbook.utils import read_jsonl


def query_index(
    index_dir: Path,
    question: str,
    top_k: int = 5,
    model_name: str | None = None,
) -> list[dict[str, Any]]:
    meta = _load_meta(index_dir)
    chunks = read_jsonl(index_dir / "chunks.jsonl")
    if not chunks:
        return []

    used_store = str(meta.get("vector_store", "none")).lower()
    if used_store == "lexical":
        scores, indices = _search_lexical(index_dir=index_dir, chunks=chunks, question=question, top_k=top_k)
    else:
        model_name = model_name or meta.get("model_name", "sentence-transformers/all-MiniLM-L6-v2")
        q_emb = _encode_query(question, model_name=model_name)
        scores, indices = _search(index_dir=index_dir, query_embedding=q_emb, top_k=top_k)
    out: list[dict[str, Any]] = []
    for score, idx in zip(scores, indices):
        if idx < 0 or idx >= len(chunks):
            continue
        item = dict(chunks[idx])
        item["score"] = float(score)
        out.append(item)
    return out


def _load_meta(index_dir: Path) -> dict[str, Any]:
    meta_path = index_dir / "index_meta.json"
    if not meta_path.exists():
        return {}
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _encode_query(question: str, model_name: str):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise MissingDependencyError("sentence-transformers is required for query.") from exc
    model = SentenceTransformer(model_name)
    return model.encode([question], normalize_embeddings=True)[0]


def _search(index_dir: Path, query_embedding: Any, top_k: int):
    faiss_path = index_dir / "index.faiss"
    if faiss_path.exists():
        try:
            import faiss
            import numpy as np
        except ImportError as exc:
            raise MissingDependencyError("faiss-cpu and numpy are required to query FAISS index.") from exc
        idx = faiss.read_index(str(faiss_path))
        q = np.asarray([query_embedding], dtype="float32")
        scores, ids = idx.search(q, top_k)
        return scores[0].tolist(), ids[0].tolist()

    raise FileNotFoundError(
        f"Missing FAISS index at {faiss_path}. Rebuild with --vector-store lexical or faiss."
    )


TOKEN_RE = re.compile(r"[a-z0-9]{2,}", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in TOKEN_RE.findall(text)]


def _search_lexical(index_dir: Path, chunks: list[dict[str, Any]], question: str, top_k: int):
    lexical_path = index_dir / "lexical_index.json"
    if not lexical_path.exists():
        raise FileNotFoundError(f"Missing lexical index at {lexical_path}. Rebuild with --vector-store lexical.")
    lexical = json.loads(lexical_path.read_text(encoding="utf-8"))
    postings: dict[str, list[int]] = lexical.get("postings", {})
    doc_len: list[int] = lexical.get("doc_len", [])
    idf: dict[str, float] = lexical.get("idf", {})
    avg_doc_len = float(lexical.get("avg_doc_len", 0.0)) or 1.0

    q_terms = _tokenize(question)
    term_counts: dict[str, int] = {}
    for term in q_terms:
        term_counts[term] = term_counts.get(term, 0) + 1

    k1 = 1.2
    b = 0.75
    scores: dict[int, float] = {}
    for term, qtf in term_counts.items():
        docs = postings.get(term, [])
        term_idf = float(idf.get(term, math.log(1.1)))
        for doc_id in docs:
            if doc_id >= len(chunks):
                continue
            tf = _tokenize(str(chunks[doc_id].get("text", ""))).count(term)
            if tf <= 0:
                continue
            dl = doc_len[doc_id] if doc_id < len(doc_len) else 1
            denom = tf + k1 * (1 - b + b * (dl / avg_doc_len))
            score = term_idf * ((tf * (k1 + 1)) / denom) * qtf
            scores[doc_id] = scores.get(doc_id, 0.0) + score

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [score for _, score in ranked], [idx for idx, _ in ranked]
