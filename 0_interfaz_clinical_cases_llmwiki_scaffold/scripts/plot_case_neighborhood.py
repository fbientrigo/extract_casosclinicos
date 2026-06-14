#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from datetime import datetime
import webbrowser

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from llmwiki_common import (
    add_collection_args,
    build_search_table,
    collect_neighbors,
    collection_from_args,
    collection_output_dir,
    load_explorer_tables,
    make_case_hover_fields,
    resolve_case_id,
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
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(width=2), opacity=0.35, hoverinfo="skip", name="semantic neighbor links"))
    return fig


def add_focus_overlay(fig, df: pd.DataFrame, focus_case_id: str, hover_cols: list[str]):
    focus = df[df["case_id"].astype(str) == str(focus_case_id)].copy()
    if focus.empty:
        return fig
    customdata = focus[hover_cols].astype(object)
    hovertemplate = "<br>".join(f"{col}: %{{customdata[{i}]}}" for i, col in enumerate(hover_cols)) + "<extra></extra>"
    label = focus["case_number"].fillna("").astype(str).str.replace(".0", "", regex=False)
    fig.add_trace(go.Scatter(
        x=focus["umap2_x"],
        y=focus["umap2_y"],
        mode="markers+text",
        marker=dict(size=25, symbol="star", line=dict(width=2)),
        text=label,
        textposition="top center",
        customdata=customdata,
        hovertemplate=hovertemplate,
        name="★ focus case",
    ))
    return fig


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Plotly 2D neighborhood map for one case.")
    add_collection_args(parser)
    parser.add_argument("case", help="Case number or case_id.")
    parser.add_argument("--neighbors", type=int, default=10)
    parser.add_argument("--color-by", default="section_label")
    parser.add_argument("--network-only", action="store_true")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()

    paths = collection_from_args(args)
    out_dir = collection_output_dir(paths, "query_plots")
    tables = load_explorer_tables(paths)
    search_df = build_search_table(tables)

    focus_case_id = resolve_case_id(search_df, args.case)
    focus_row = search_df[search_df["case_id"].astype(str) == focus_case_id].iloc[0]

    neighbor_edges = collect_neighbors(tables, [focus_case_id], args.neighbors)
    neighbor_ids = set(neighbor_edges["neighbor_case_id"].astype(str)) if not neighbor_edges.empty else set()
    network_ids = {focus_case_id} | neighbor_ids

    plot_df = search_df.copy()
    plot_df["focus_case"] = plot_df["case_id"].astype(str) == focus_case_id
    plot_df["focus_neighbor"] = plot_df["case_id"].astype(str).isin(neighbor_ids)
    plot_df["focus_network"] = plot_df["case_id"].astype(str).isin(network_ids)

    plot_df["plot_role"] = "other case"
    plot_df.loc[plot_df["focus_neighbor"], "plot_role"] = "neighbor"
    plot_df.loc[plot_df["focus_case"], "plot_role"] = "focus case"

    plot_df["marker_size"] = 6
    plot_df.loc[plot_df["focus_neighbor"], "marker_size"] = 11
    plot_df.loc[plot_df["focus_case"], "marker_size"] = 20

    plot_used = plot_df[plot_df["focus_network"]].copy() if args.network_only else plot_df.copy()

    if args.color_by not in plot_used.columns:
        print(f"WARNING: color column {args.color_by!r} not found. Falling back to section_label.")
        args.color_by = "section_label"

    hover_cols = make_case_hover_fields(plot_used)
    title = f"{paths.display_name} · Neighborhood for case {focus_row.get('case_number')} · {focus_row.get('title_clean')}"

    fig = px.scatter(
        plot_used,
        x="umap2_x",
        y="umap2_y",
        color=args.color_by,
        symbol="plot_role",
        size="marker_size",
        size_max=22,
        hover_data=hover_cols,
        title=title,
    )

    fig = add_edge_trace(fig, neighbor_edges, plot_used)
    fig = add_focus_overlay(fig, plot_used, focus_case_id, hover_cols)

    fig.update_layout(
        height=780,
        legend_title_text=args.color_by,
        annotations=[dict(text=f"Collection: {paths.collection_id} · neighbors from precomputed semantic tables · map: precomputed UMAP", xref="paper", yref="paper", x=0, y=-0.10, showarrow=False, align="left")],
        margin=dict(b=90),
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"case_neighborhood_{stamp}_{slugify(str(focus_row.get('case_id')))}"
    html_path = out_dir / f"{stem}.html"
    neighbors_path = out_dir / f"{stem}_neighbors.csv"
    summary_path = out_dir / f"{stem}_summary.md"

    fig.write_html(html_path, include_plotlyjs="cdn")
    neighbor_edges.to_csv(neighbors_path, index=False)

    top_df = search_df[search_df["case_id"].astype(str).isin([focus_case_id] + list(neighbor_ids))].copy()
    top_df["query_score"] = top_df["case_id"].astype(str).map(lambda x: 999 if x == focus_case_id else 1)
    top_df["match_evidence"] = top_df["case_id"].astype(str).map(lambda x: "focus case" if x == focus_case_id else "semantic neighbor")
    write_markdown_summary(summary_path, title, top_df, neighbor_edges)

    print("Wrote:", html_path)
    print("Wrote:", neighbors_path)
    print("Wrote:", summary_path)
    print("\nFocus case:")
    print(search_df[search_df["case_id"].astype(str) == focus_case_id][[
        c for c in ["case_number", "case_id", "title_clean", "section_label", "subsection_short", "difficulty", "clinical_area", "main_problem"]
        if c in search_df.columns
    ]].to_string(index=False, max_colwidth=100))

    if args.open:
        webbrowser.open(html_path.resolve().as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
