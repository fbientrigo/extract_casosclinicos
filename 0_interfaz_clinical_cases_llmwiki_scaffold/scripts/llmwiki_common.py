#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Common utilities for the local Clinical Cases LLMWiki interface.

Design goals:
- Support a single collection layout out of the box:
    book/<collection_book_dir>/
    data/<collection_data_dir>/
    llm_wiki/<collection_wiki_dir>/
- Support multiple collections without rewriting scripts.
- Never modify canonical data in data/, book/ or llm_wiki/.
- Write derived outputs only under data_updated/.

Collections are configured at runtime via an (optional) manifest:
    data/manifest.json   (see data/manifest.example.json)

Example:
{
  "default_collection": "demo_coleccion",
  "collections": {
    "demo_coleccion": {
      "display_name": "Colección de ejemplo",
      "domain": "clinical_cases",
      "wiki_dir": "llm_wiki/demo_coleccion",
      "book_dir": "book/demo_coleccion",
      "data_dir": "data/demo_coleccion",
      "explorer_db": "llm_wiki/demo_coleccion/clinical_cases_explorer_llmwiki.duckdb",
      "bundle_db": "data/demo_coleccion/clinical_cases_bundle.duckdb",
      "base_db": "data/demo_coleccion/clinical_cases.db"
    }
  }
}
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import re
import subprocess
import sys
import unicodedata
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Any

import duckdb
import numpy as np
import pandas as pd


SPANISH_STOPWORDS = {
    "a", "al", "algo", "algun", "alguna", "algunas", "alguno", "algunos",
    "ante", "antes", "como", "con", "contra", "cual", "cuando", "de", "del",
    "desde", "donde", "dos", "el", "ella", "ellas", "ellos", "en", "entre",
    "era", "es", "esa", "esas", "ese", "eso", "esos", "esta", "estas",
    "este", "esto", "estos", "fue", "ha", "hay", "la", "las", "le", "les",
    "lo", "los", "mas", "me", "mi", "mis", "muy", "no", "o", "para",
    "pero", "por", "que", "se", "si", "sin", "sobre", "son", "su", "sus",
    "tal", "tambien", "te", "tiene", "un", "una", "unas", "uno", "unos",
    "y", "ya",
    "caso", "casos", "clinico", "clinicos", "laboratorio", "clase",
    "alumno", "alumnos", "estudiante", "estudiantes", "necesito", "quiero",
    "buscar", "recomendar", "recomendados", "ver", "explorar",
}


@dataclass(frozen=True)
class CollectionPaths:
    collection_id: str
    display_name: str
    domain: str
    root: Path
    wiki_dir: Path
    book_dir: Path
    data_dir: Path
    explorer_db: Path
    bundle_db: Optional[Path]
    base_db: Optional[Path]
    data_updated_dir: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "collection_id": self.collection_id,
            "display_name": self.display_name,
            "domain": self.domain,
            "root": str(self.root),
            "wiki_dir": str(self.wiki_dir),
            "book_dir": str(self.book_dir),
            "data_dir": str(self.data_dir),
            "explorer_db": str(self.explorer_db),
            "bundle_db": str(self.bundle_db) if self.bundle_db else "",
            "base_db": str(self.base_db) if self.base_db else "",
            "data_updated_dir": str(self.data_updated_dir),
        }


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def normalize_text(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(value: str, max_len: int = 80) -> str:
    text = normalize_text(value)
    text = re.sub(r"\s+", "_", text).strip("_")
    return (text[:max_len].strip("_") or "query")


def query_tokens(query: str) -> list[str]:
    toks = normalize_text(query).split()
    return [t for t in toks if len(t) >= 3 and t not in SPANISH_STOPWORDS]


def compact(value: object, max_chars: int = 260) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def parse_json_list(value: object) -> list[str]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return [str(x) for x in obj if str(x).strip()]
        if isinstance(obj, dict):
            return [json.dumps(obj, ensure_ascii=False)]
        return [str(obj)]
    except Exception:
        return [text]


def list_to_inline(value: object, max_items: int = 5) -> str:
    items = parse_json_list(value)
    return "; ".join(items[:max_items])


def list_to_bullets(value: object, max_items: Optional[int] = None) -> str:
    items = parse_json_list(value)
    if max_items is not None:
        items = items[:max_items]
    return "\n".join(f"- {x}" for x in items)


def first_existing(cols: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    cols = list(cols)
    for c in candidates:
        if c in cols:
            return c
    return None


def table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return name in {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def read_table(con: duckdb.DuckDBPyConnection, name: str) -> pd.DataFrame:
    if not table_exists(con, name):
        return pd.DataFrame()
    return con.execute(f"SELECT * FROM {name}").df()


def read_manifest(root: Optional[Path] = None) -> dict[str, Any]:
    root = root or project_root()
    manifest_path = root / "data" / "manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _resolve_path(root: Path, value: Optional[str | Path]) -> Optional[Path]:
    if not value:
        return None
    p = Path(value)
    return p if p.is_absolute() else root / p


def _discover_wiki_dirs(root: Path) -> list[Path]:
    llm_wiki_root = root / "llm_wiki"
    if not llm_wiki_root.exists():
        return []
    return sorted({
        p.parent
        for p in llm_wiki_root.rglob("clinical_cases_explorer_llmwiki.duckdb")
        if p.is_file()
    })


def _discover_data_dirs(root: Path) -> list[Path]:
    data_root = root / "data"
    if not data_root.exists():
        return []
    dirs = set()
    for pattern in ["*sota*gptoss*.duckdb", "clinical_cases.db", "*.duckdb"]:
        for p in data_root.rglob(pattern):
            if p.is_file():
                dirs.add(p.parent)
    return sorted(dirs)


def _discover_book_dirs(root: Path) -> list[Path]:
    book_root = root / "book"
    if not book_root.exists():
        return []
    return sorted([p for p in book_root.iterdir() if p.is_dir()])


def _pick_by_collection(candidates: list[Path], collection: Optional[str], label: str) -> Optional[Path]:
    if not candidates:
        return None
    if collection:
        needle = normalize_text(collection)
        exact = [p for p in candidates if normalize_text(p.name) == needle]
        if exact:
            return exact[0]
        contains = [p for p in candidates if needle in normalize_text(str(p.relative_to(project_root())))]
        if len(contains) == 1:
            return contains[0]
        if len(contains) > 1:
            names = "\n".join(f"- {p}" for p in contains)
            raise RuntimeError(f"Ambiguous {label} candidates for collection {collection!r}:\n{names}")
    if len(candidates) == 1:
        return candidates[0]
    return None


def discover_collections(root: Optional[Path] = None) -> pd.DataFrame:
    root = root or project_root()
    manifest = read_manifest(root)
    rows = []

    collections = manifest.get("collections", {}) if isinstance(manifest, dict) else {}
    for cid, cfg in collections.items():
        wiki_dir = _resolve_path(root, cfg.get("wiki_dir"))
        data_dir = _resolve_path(root, cfg.get("data_dir"))
        book_dir = _resolve_path(root, cfg.get("book_dir"))
        explorer_db = _resolve_path(root, cfg.get("explorer_db"))
        bundle_db = _resolve_path(root, cfg.get("bundle_db"))
        base_db = _resolve_path(root, cfg.get("base_db"))
        rows.append({
            "collection_id": cid,
            "source": "manifest",
            "display_name": cfg.get("display_name", cid),
            "domain": cfg.get("domain", "unknown"),
            "wiki_dir": str(wiki_dir or ""),
            "data_dir": str(data_dir or ""),
            "book_dir": str(book_dir or ""),
            "explorer_db": str(explorer_db or ""),
            "bundle_db": str(bundle_db or ""),
            "base_db": str(base_db or ""),
            "explorer_db_exists": bool(explorer_db and explorer_db.exists()),
            "book_dir_exists": bool(book_dir and book_dir.exists()),
        })

    for wiki_dir in _discover_wiki_dirs(root):
        cid = wiki_dir.name
        explorer_db = wiki_dir / "clinical_cases_explorer_llmwiki.duckdb"
        if cid not in {r["collection_id"] for r in rows}:
            rows.append({
                "collection_id": cid,
                "source": "auto_wiki",
                "display_name": cid,
                "domain": "unknown",
                "wiki_dir": str(wiki_dir),
                "data_dir": "",
                "book_dir": "",
                "explorer_db": str(explorer_db),
                "bundle_db": "",
                "base_db": "",
                "explorer_db_exists": explorer_db.exists(),
                "book_dir_exists": False,
            })

    return pd.DataFrame(rows)


def resolve_collection(
    collection: Optional[str] = None,
    root: Optional[Path] = None,
    wiki_dir: Optional[str | Path] = None,
    data_dir: Optional[str | Path] = None,
    book_dir: Optional[str | Path] = None,
    explorer_db: Optional[str | Path] = None,
    bundle_db: Optional[str | Path] = None,
    base_db: Optional[str | Path] = None,
) -> CollectionPaths:
    root = root or project_root()
    manifest = read_manifest(root)

    if not collection and isinstance(manifest, dict):
        collection = manifest.get("default_collection")

    cfg = {}
    if collection and isinstance(manifest, dict):
        cfg = manifest.get("collections", {}).get(collection, {}) or {}

    display_name = cfg.get("display_name", collection or "auto_collection")
    domain = cfg.get("domain", "unknown")

    # Explicit args override manifest; manifest overrides autodiscovery.
    wiki_dir_p = _resolve_path(root, wiki_dir) or _resolve_path(root, cfg.get("wiki_dir"))
    data_dir_p = _resolve_path(root, data_dir) or _resolve_path(root, cfg.get("data_dir"))
    book_dir_p = _resolve_path(root, book_dir) or _resolve_path(root, cfg.get("book_dir"))
    explorer_db_p = _resolve_path(root, explorer_db) or _resolve_path(root, cfg.get("explorer_db"))
    bundle_db_p = _resolve_path(root, bundle_db) or _resolve_path(root, cfg.get("bundle_db"))
    base_db_p = _resolve_path(root, base_db) or _resolve_path(root, cfg.get("base_db"))

    if explorer_db_p and not wiki_dir_p:
        wiki_dir_p = explorer_db_p.parent

    if not wiki_dir_p:
        wiki_dir_p = _pick_by_collection(_discover_wiki_dirs(root), collection, "llm_wiki")
    if not wiki_dir_p:
        candidates = _discover_wiki_dirs(root)
        names = "\n".join(f"- {p}" for p in candidates) or "(none)"
        raise RuntimeError(
            "Could not resolve wiki_dir. Use --collection or --wiki-dir.\n"
            f"Discovered wiki dirs:\n{names}"
        )

    if not explorer_db_p:
        explorer_db_p = wiki_dir_p / "clinical_cases_explorer_llmwiki.duckdb"

    if not data_dir_p:
        data_dir_p = _pick_by_collection(_discover_data_dirs(root), collection, "data")
        if data_dir_p is None:
            data_dir_p = root / "data"

    if not bundle_db_p:
        matches = sorted(data_dir_p.glob("*sota*gptoss*.duckdb")) if data_dir_p.exists() else []
        if len(matches) == 1:
            bundle_db_p = matches[0]
        elif len(matches) > 1:
            # Prefer clinical_cases_bundle_sota_gptoss20b if present.
            preferred = [p for p in matches if p.name == "clinical_cases_bundle_sota_gptoss20b.duckdb"]
            bundle_db_p = preferred[0] if preferred else matches[0]

    if not base_db_p:
        for candidate in ["clinical_cases.db", "clinical_cases_bundle.duckdb"]:
            p = data_dir_p / candidate
            if p.exists():
                base_db_p = p
                break

    if not book_dir_p:
        book_dir_p = _pick_by_collection(_discover_book_dirs(root), collection, "book")
        if book_dir_p is None:
            # Last-resort fuzzy matching between wiki/data names and book dirs.
            books = _discover_book_dirs(root)
            keys = [wiki_dir_p.name, data_dir_p.name if data_dir_p else ""]
            scores = []
            for b in books:
                bnorm = normalize_text(b.name)
                score = sum(1 for k in keys if k and normalize_text(k) in bnorm or bnorm in normalize_text(k))
                scores.append((score, b))
            scores = sorted(scores, key=lambda x: (-x[0], str(x[1])))
            if scores and scores[0][0] > 0:
                book_dir_p = scores[0][1]
            elif len(books) == 1:
                book_dir_p = books[0]
            else:
                book_dir_p = root / "book"

    collection_id = collection or wiki_dir_p.name
    data_updated_dir = root / "data_updated" / collection_id
    return CollectionPaths(
        collection_id=collection_id,
        display_name=display_name,
        domain=domain,
        root=root,
        wiki_dir=wiki_dir_p,
        book_dir=book_dir_p,
        data_dir=data_dir_p,
        explorer_db=explorer_db_p,
        bundle_db=bundle_db_p,
        base_db=base_db_p,
        data_updated_dir=data_updated_dir,
    )


def add_collection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--collection", default=None, help="Collection id, e.g. demo_coleccion. Optional if only one wiki DB exists.")
    parser.add_argument("--wiki-dir", default=None, help="Override llm_wiki/<collection> directory.")
    parser.add_argument("--data-dir", default=None, help="Override data/<collection> directory.")
    parser.add_argument("--book-dir", default=None, help="Override book/<collection> directory.")
    parser.add_argument("--explorer-db", "--db", dest="explorer_db", default=None, help="Override explorer DuckDB path.")
    parser.add_argument("--bundle-db", default=None, help="Override SOTA/GPT-OSS full bundle DuckDB path.")
    parser.add_argument("--base-db", default=None, help="Override base clinical_cases DB path.")


def collection_from_args(args: argparse.Namespace) -> CollectionPaths:
    return resolve_collection(
        collection=getattr(args, "collection", None),
        wiki_dir=getattr(args, "wiki_dir", None),
        data_dir=getattr(args, "data_dir", None),
        book_dir=getattr(args, "book_dir", None),
        explorer_db=getattr(args, "explorer_db", None),
        bundle_db=getattr(args, "bundle_db", None),
        base_db=getattr(args, "base_db", None),
    )


def load_explorer_tables(paths: CollectionPaths) -> dict[str, pd.DataFrame]:
    if not paths.explorer_db.exists():
        raise FileNotFoundError(f"Explorer DB not found: {paths.explorer_db}")
    con = duckdb.connect(str(paths.explorer_db), read_only=True)
    names = [
        "case_catalog",
        "plot_cases",
        "llmwiki_cases",
        "star_cases",
        "star_neighbors",
        "coverage_by_section",
        "source_cases",
        "source_pages",
        "source_consensus_neighbors",
        "source_nearest_neighbors",
        "source_case_llm_annotations",
        "source_case_llm_star_scores",
    ]
    out = {name: read_table(con, name) for name in names}
    con.close()
    for df in out.values():
        if not df.empty and "case_id" in df.columns:
            df["case_id"] = df["case_id"].astype(str)
    return out


def build_search_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    plot = tables.get("plot_cases", pd.DataFrame()).copy()
    wiki = tables.get("llmwiki_cases", pd.DataFrame()).copy()

    if plot.empty and not wiki.empty:
        plot = wiki.copy()
    if plot.empty:
        raise RuntimeError("No plot_cases or llmwiki_cases available in explorer DB.")

    if "case_id" not in plot.columns:
        raise RuntimeError("Search table requires case_id.")

    plot["case_id"] = plot["case_id"].astype(str)

    if not wiki.empty and "case_id" in wiki.columns:
        wiki["case_id"] = wiki["case_id"].astype(str)
        wiki_extra = [c for c in wiki.columns if c not in plot.columns or c == "case_id"]
        plot = plot.merge(wiki[wiki_extra], on="case_id", how="left", suffixes=("", "_wiki"))

    for col in [
        "case_number", "title_clean", "section_label", "subsection_short",
        "difficulty", "case_type", "clinical_area", "main_problem",
        "key_concepts_json", "learning_objectives_json", "laboratory_methods_json",
        "star_case_rationale", "text_preview", "llmwiki_text",
        "combined_star_score", "sota_score", "llm_star_score",
        "umap2_x", "umap2_y", "umap3_x", "umap3_y", "umap3_z",
    ]:
        if col not in plot.columns:
            plot[col] = "" if col.endswith("_json") or col in {
                "title_clean", "section_label", "subsection_short", "difficulty",
                "case_type", "clinical_area", "main_problem", "star_case_rationale",
                "text_preview", "llmwiki_text"
            } else np.nan

    return plot


def apply_filters(
    df: pd.DataFrame,
    section: Optional[str] = None,
    subsection: Optional[str] = None,
    difficulty: Optional[str] = None,
    clinical_area: Optional[str] = None,
    case_type: Optional[str] = None,
) -> pd.DataFrame:
    out = df.copy()
    filters = {
        "section_label": section,
        "subsection_short": subsection,
        "difficulty": difficulty,
        "clinical_area": clinical_area,
        "case_type": case_type,
    }
    for col, value in filters.items():
        if value and col in out.columns:
            needle = normalize_text(value)
            out = out[out[col].map(normalize_text).str.contains(re.escape(needle), na=False)]
    return out


def score_cases_for_query(df: pd.DataFrame, query: str) -> pd.DataFrame:
    tokens = query_tokens(query)
    norm_query = normalize_text(query)
    if not tokens and not norm_query:
        raise ValueError("Empty query after normalization.")

    field_weights = {
        "key_concepts_json": 3.2,
        "learning_objectives_json": 3.0,
        "main_problem": 2.8,
        "clinical_area": 2.2,
        "laboratory_methods_json": 2.0,
        "subsection_short": 1.8,
        "title_clean": 1.6,
        "case_type": 1.0,
        "difficulty": 0.9,
        "section_label": 0.8,
        "star_case_rationale": 0.8,
        "text_preview": 0.7,
        "llmwiki_text": 0.35,
    }

    rows = []
    for _, row in df.iterrows():
        raw_score = 0.0
        evidence = []

        for col, weight in field_weights.items():
            text = normalize_text(row.get(col, ""))
            if not text:
                continue

            hits = [t for t in tokens if t in text]
            if hits:
                token_score = weight * (len(set(hits)) / max(1.0, math.sqrt(len(tokens))))
                raw_score += token_score
                evidence.append(f"{col}: " + ", ".join(sorted(set(hits))[:8]))

            if norm_query and len(norm_query) >= 5 and norm_query in text:
                raw_score += 2.5 * weight
                evidence.append(f"{col}: exact phrase")

        try:
            raw_score += 0.20 * float(row.get("combined_star_score", 0.0))
        except Exception:
            pass

        rows.append({
            "case_id": str(row.get("case_id")),
            "query_score": raw_score,
            "match_evidence": "; ".join(evidence[:8]),
        })

    scored = df.merge(pd.DataFrame(rows), on="case_id", how="left")
    scored["query_score"] = pd.to_numeric(scored["query_score"], errors="coerce").fillna(0.0)
    scored["combined_star_score"] = pd.to_numeric(scored.get("combined_star_score", 0.0), errors="coerce").fillna(0.0)
    scored["case_number_sort"] = pd.to_numeric(scored.get("case_number", np.nan), errors="coerce")
    scored = scored.sort_values(["query_score", "combined_star_score", "case_number_sort"], ascending=[False, False, True])
    return scored.drop(columns=["case_number_sort"], errors="ignore")


def _standardize_neighbor_table(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["source_case_id", "neighbor_case_id", "neighbor_rank", "similarity", "source_table"])

    cols = list(df.columns)
    src_col = first_existing(cols, ["source_case_id", "query_case_id", "anchor_case_id", "case_id", "star_case_id"])
    dst_col = first_existing(cols, ["neighbor_case_id", "target_case_id", "matched_case_id", "case_id_neighbor", "neighbor_id"])
    rank_col = first_existing(cols, ["neighbor_rank", "rank", "consensus_rank", "rank_in_model"])
    sim_col = first_existing(cols, ["similarity", "consensus_similarity", "mean_similarity", "cosine_similarity", "score"])

    if src_col is None or dst_col is None:
        return pd.DataFrame(columns=["source_case_id", "neighbor_case_id", "neighbor_rank", "similarity", "source_table"])

    out = pd.DataFrame({
        "source_case_id": df[src_col].astype(str),
        "neighbor_case_id": df[dst_col].astype(str),
        "neighbor_rank": pd.to_numeric(df[rank_col], errors="coerce") if rank_col else np.nan,
        "similarity": pd.to_numeric(df[sim_col], errors="coerce") if sim_col else np.nan,
        "source_table": table_name,
    })
    out = out[out["source_case_id"] != out["neighbor_case_id"]].copy()
    out["neighbor_rank"] = out["neighbor_rank"].fillna(999999).astype(int)
    return out


def collect_neighbors(tables: dict[str, pd.DataFrame], source_case_ids: list[str], neighbors_per_case: int) -> pd.DataFrame:
    source_case_ids = [str(x) for x in source_case_ids]
    candidates = []
    for table_name in ["source_consensus_neighbors", "source_nearest_neighbors", "star_neighbors"]:
        std = _standardize_neighbor_table(tables.get(table_name, pd.DataFrame()), table_name)
        if not std.empty:
            candidates.append(std)

    if not candidates:
        return pd.DataFrame(columns=["source_case_id", "neighbor_case_id", "neighbor_rank", "similarity", "source_table"])

    all_edges = pd.concat(candidates, ignore_index=True)
    all_edges = all_edges[all_edges["source_case_id"].isin(source_case_ids)].copy()
    if all_edges.empty:
        return all_edges

    source_priority = {"source_consensus_neighbors": 0, "source_nearest_neighbors": 1, "star_neighbors": 2}
    all_edges["source_priority"] = all_edges["source_table"].map(source_priority).fillna(9)
    all_edges = all_edges.sort_values(
        ["source_case_id", "source_priority", "neighbor_rank", "similarity"],
        ascending=[True, True, True, False],
    )
    all_edges = all_edges.drop_duplicates(["source_case_id", "neighbor_case_id"], keep="first")

    kept = []
    for _, group in all_edges.groupby("source_case_id"):
        kept.append(group.head(neighbors_per_case))
    return pd.concat(kept, ignore_index=True) if kept else all_edges.iloc[0:0]


def resolve_case_id(df: pd.DataFrame, case_ref: str) -> str:
    ref = str(case_ref).strip()
    ids = set(df["case_id"].astype(str))
    if ref in ids:
        return ref

    if re.fullmatch(r"\d+", ref):
        n = int(ref)
        matches = df[pd.to_numeric(df.get("case_number"), errors="coerce") == n]
        if len(matches) == 1:
            return str(matches.iloc[0]["case_id"])
        if len(matches) > 1:
            raise ValueError(f"Ambiguous case number {n}: {matches['case_id'].tolist()}")

    norm_ref = normalize_text(ref)
    matches = df[df["case_id"].map(normalize_text).str.contains(re.escape(norm_ref), na=False)]
    if len(matches) == 1:
        return str(matches.iloc[0]["case_id"])
    if len(matches) > 1:
        raise ValueError(f"Ambiguous case reference {case_ref!r}: {matches['case_id'].head(10).tolist()}")

    raise ValueError(f"Case not found: {case_ref}")


def find_pdf_for_case(paths: CollectionPaths, row_or_case_id: Any, case_number: Optional[int] = None) -> Optional[Path]:
    if isinstance(row_or_case_id, pd.Series):
        case_id = str(row_or_case_id.get("case_id"))
        if case_number is None:
            try:
                case_number = int(float(row_or_case_id.get("case_number")))
            except Exception:
                case_number = None
    else:
        case_id = str(row_or_case_id)

    if not paths.book_dir.exists():
        return None

    candidates = []
    if case_id:
        safe = re.escape(case_id)
        candidates.extend(paths.book_dir.rglob(f"{case_id}.pdf"))
        candidates.extend([p for p in paths.book_dir.rglob("*.pdf") if re.search(safe, p.name)])

    if case_number is not None:
        prefix = str(case_number)
        candidates.extend([p for p in paths.book_dir.rglob("*.pdf") if p.name.startswith(prefix + "_") or p.name.startswith(prefix + "-") or p.stem == prefix])

    # Deduplicate and prefer shortest path/name.
    unique = []
    seen = set()
    for p in candidates:
        if p not in seen and p.exists():
            unique.append(p)
            seen.add(p)

    if not unique:
        return None
    return sorted(unique, key=lambda p: (len(str(p)), str(p)))[0]


def open_path(path: Path) -> None:
    path = path.resolve()
    system = platform.system().lower()
    if system == "windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif system == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def case_summary_row(row: pd.Series, include_pdf: Optional[Path] = None) -> dict[str, Any]:
    return {
        "case_number": row.get("case_number"),
        "case_id": row.get("case_id"),
        "title": row.get("title_clean"),
        "section": row.get("section_label"),
        "subsection": row.get("subsection_short"),
        "difficulty": row.get("difficulty"),
        "case_type": row.get("case_type"),
        "clinical_area": row.get("clinical_area"),
        "main_problem": compact(row.get("main_problem"), 300),
        "key_concepts": list_to_inline(row.get("key_concepts_json")),
        "learning_objectives": list_to_inline(row.get("learning_objectives_json")),
        "combined_star_score": row.get("combined_star_score"),
        "query_score": row.get("query_score"),
        "pdf_path": str(include_pdf) if include_pdf else "",
    }


def make_case_hover_fields(df: pd.DataFrame) -> list[str]:
    fields = [
        "case_number", "case_id", "title_clean", "section_label", "subsection_short",
        "difficulty", "case_type", "clinical_area", "main_problem",
        "query_score", "combined_star_score", "match_evidence",
    ]
    return [c for c in fields if c in df.columns]


def print_table(df: pd.DataFrame, cols: list[str], max_colwidth: int = 100) -> None:
    cols = [c for c in cols if c in df.columns]
    if not cols:
        print(df.to_string(index=False, max_colwidth=max_colwidth))
    else:
        print(df[cols].to_string(index=False, max_colwidth=max_colwidth))


def write_markdown_summary(path: Path, title: str, top_df: pd.DataFrame, neighbors_df: Optional[pd.DataFrame] = None) -> None:
    lines = [f"# {title}", ""]
    lines += ["## Top cases", ""]
    for _, r in top_df.iterrows():
        n = r.get("case_number", "")
        cid = r.get("case_id", "")
        name = r.get("title_clean", cid)
        score = r.get("query_score", "")
        area = r.get("clinical_area", "")
        diff = r.get("difficulty", "")
        main = compact(r.get("main_problem", ""), 220)
        ev = compact(r.get("match_evidence", ""), 260)
        lines += [
            f"### {n} · {name}",
            f"- case_id: `{cid}`",
            f"- score: {score}",
            f"- clinical_area: {area}",
            f"- difficulty: {diff}",
            f"- main_problem: {main}",
            f"- match_evidence: {ev}",
            "",
        ]

    if neighbors_df is not None and not neighbors_df.empty:
        lines += ["## Neighbor edges", ""]
        for _, r in neighbors_df.iterrows():
            lines.append(
                f"- `{r.get('source_case_id')}` → `{r.get('neighbor_case_id')}` "
                f"(rank={r.get('neighbor_rank')}, similarity={r.get('similarity')}, source={r.get('source_table')})"
            )
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def collection_output_dir(paths: CollectionPaths, kind: str) -> Path:
    out = paths.data_updated_dir / kind
    out.mkdir(parents=True, exist_ok=True)
    return out
