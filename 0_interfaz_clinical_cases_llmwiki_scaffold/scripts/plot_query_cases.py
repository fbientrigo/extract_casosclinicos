#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import webbrowser

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from llmwiki_common import (
    add_collection_args,
    apply_filters,
    build_search_table,
    collect_neighbors,
    collection_from_args,
    collection_output_dir,
    load_explorer_tables,
    make_case_hover_fields,
    score_cases_for_query,
    slugify,
    write_markdown_summary,
)


def add_edge_trace(fig, edges_df: pd.DataFrame, coords_df: pd.DataFrame):
    if edges_df.empty or not {"umap2_x", "umap2_y"}.issubset(coords_df.columns):
        return fig

    coord = coords_df.set_index("case_id")[["umap2_x", "umap2_y"]]
    xs, ys = [], []
    for _, r in edges_df.iterrows():
        a = str(r["source_case_id"])
        b = str(r["neighbor_case_id"])
        if a not in coord.index or b not in coord.index:
            continue
        xs += [coord.loc[a, "umap2_x"], coord.loc[b, "umap2_x"], None]
        ys += [coord.loc[a, "umap2_y"], coord.loc[b, "umap2_y"], None]

    if xs:
        fig.add_trace(go.Scatter(
            x=xs,
            y=ys,
            mode="lines",
            line=dict(width=1),
            opacity=0.28,
            hoverinfo="skip",
            name="semantic neighbor links",
        ))
    return fig


def add_query_star_overlay(fig, df: pd.DataFrame, hover_cols: list[str]):
    top = df[df["query_selected"]].copy()
    if top.empty:
        return fig

    customdata = top[hover_cols].astype(object)
    hovertemplate = "<br>".join(
        f"{col}: %{{customdata[{i}]}}" for i, col in enumerate(hover_cols)
    ) + "<extra></extra>"

    labels = top["case_number"].fillna("").astype(str).str.replace(".0", "", regex=False)

    fig.add_trace(go.Scatter(
        x=top["umap2_x"],
        y=top["umap2_y"],
        mode="markers+text",
        marker=dict(size=22, symbol="star", line=dict(width=1)),
        text=labels,
        textposition="top center",
        customdata=customdata,
        hovertemplate=hovertemplate,
        name="★ query top cases",
    ))
    return fig


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Plotly 2D map from a natural-language case-search idea.")
    add_collection_args(parser)
    parser.add_argument("query", help="Natural-language case idea/search request.")
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--neighbors", type=int, default=5)
    parser.add_argument("--color-by", default="section_label")
    parser.add_argument("--network-only", action="store_true")
    parser.add_argument("--section", default=None)
    parser.add_argument("--subsection", default=None)
    parser.add_argument("--difficulty", default=None)
    parser.add_argument("--clinical-area", default=None)
    parser.add_argument("--case-type", default=None)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()

    paths = collection_from_args(args)
    out_dir = collection_output_dir(paths, "query_plots")

    tables = load_explorer_tables(paths)
    search_df = build_search_table(tables)
    filtered_df = apply_filters(search_df, args.section, args.subsection, args.difficulty, args.clinical_area, args.case_type)

    if filtered_df.empty:
        raise RuntimeError("No cases left after filters. Relax section/difficulty/area filters.")

    scored_df = score_cases_for_query(filtered_df, args.query)
    top_df = scored_df.head(args.top).copy()

    if top_df["query_score"].max() <= 0:
        print("WARNING: no strong lexical/metadata matches found. Showing best available cases by weak prior.")

    selected_ids = top_df["case_id"].astype(str).tolist()
    neighbor_edges = collect_neighbors(tables, selected_ids, args.neighbors)

    neighbor_ids = set(neighbor_edges["neighbor_case_id"].astype(str)) if not neighbor_edges.empty else set()
    network_ids = set(selected_ids) | neighbor_ids

    plot_df = search_df.copy()
    score_map = dict(zip(scored_df["case_id"].astype(str), scored_df["query_score"]))
    evidence_map = dict(zip(scored_df["case_id"].astype(str), scored_df["match_evidence"]))
    plot_df["query_score"] = plot_df["case_id"].astype(str).map(score_map).fillna(0.0)
    plot_df["match_evidence"] = plot_df["case_id"].astype(str).map(evidence_map).fillna("")
    plot_df["query_selected"] = plot_df["case_id"].astype(str).isin(selected_ids)
    plot_df["query_neighbor"] = plot_df["case_id"].astype(str).isin(neighbor_ids)
    plot_df["query_network"] = plot_df["case_id"].astype(str).isin(network_ids)

    plot_df["plot_role"] = "other case"
    plot_df.loc[plot_df["query_neighbor"], "plot_role"] = "neighbor"
    plot_df.loc[plot_df["query_selected"], "plot_role"] = "query top case"

    plot_df["marker_size"] = 6
    plot_df.loc[plot_df["query_neighbor"], "marker_size"] = 10
    plot_df.loc[plot_df["query_selected"], "marker_size"] = 18

    plot_used = plot_df[plot_df["query_network"]].copy() if args.network_only else plot_df.copy()

    required = {"umap2_x", "umap2_y"}
    if not required.issubset(plot_used.columns) or plot_used[list(required)].isna().all().any():
        raise RuntimeError("2D UMAP coordinates are missing. Rebuild llm_wiki explorer output first.")

    if args.color_by not in plot_used.columns:
        print(f"WARNING: color column {args.color_by!r} not found. Falling back to section_label.")
        args.color_by = "section_label"

    hover_cols = make_case_hover_fields(plot_used)

    fig = px.scatter(
        plot_used,
        x="umap2_x",
        y="umap2_y",
        color=args.color_by,
        symbol="plot_role",
        size="marker_size",
        size_max=20,
        hover_data=hover_cols,
        title=f"{paths.display_name} · query map: {args.query}",
    )

    fig = add_edge_trace(fig, neighbor_edges, plot_used)
    fig = add_query_star_overlay(fig, plot_used, hover_cols)

    subtitle = (
        f"Collection: {paths.collection_id} · Top cases: {len(selected_ids)} · "
        f"neighbors/case: {args.neighbors} · ranking: GPT-OSS metadata + curated fields · map: precomputed UMAP"
    )
    fig.update_layout(
        height=780,
        legend_title_text=args.color_by,
        annotations=[dict(text=subtitle, xref="paper", yref="paper", x=0, y=-0.10, showarrow=False, align="left")],
        margin=dict(b=90),
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"query_map_{stamp}_{slugify(args.query)}"
    html_path = out_dir / f"{stem}.html"
    matches_path = out_dir / f"{stem}_matches.csv"
    neighbors_path = out_dir / f"{stem}_neighbors.csv"
    summary_path = out_dir / f"{stem}_summary.md"

    fig.write_html(html_path, include_plotlyjs="cdn")
    top_df.to_csv(matches_path, index=False)
    neighbor_edges.to_csv(neighbors_path, index=False)
    write_markdown_summary(summary_path, f"{paths.display_name} · {args.query}", top_df, neighbor_edges)

    print("Wrote:", html_path)
    print("Wrote:", matches_path)
    print("Wrote:", neighbors_path)
    print("Wrote:", summary_path)

    show_cols = [
        "case_number", "case_id", "title_clean", "section_label", "subsection_short",
        "difficulty", "clinical_area", "query_score", "main_problem", "match_evidence",
    ]
    show_cols = [c for c in show_cols if c in top_df.columns]
    print("\nTop cases:")
    print(top_df[show_cols].to_string(index=False, max_colwidth=90))

    if args.open:
        webbrowser.open(html_path.resolve().as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
