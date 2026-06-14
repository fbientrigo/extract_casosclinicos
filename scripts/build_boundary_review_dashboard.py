#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

REVIEW_SEVERITIES = {
    "confirmed_boundary_error",
    "probable_boundary_error",
    "low_confidence_review",
}

TEMPLATE_COLUMNS = [
    "case_id",
    "section",
    "subsection",
    "severity",
    "suggested_trim_pages",
    "human_decision",
    "human_trim_pages",
    "confidence",
    "notes",
    "page1_previous_case",
    "page2_previous_case",
    "case_starts_correctly",
    "render_ocr_mismatch",
]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_relpath(path_str: str) -> str:
    return path_str.replace("\\", "/").strip()


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _parse_section_subsection_from_source(source_pdf: str) -> tuple[str, str]:
    parts = [p for p in PurePosixPath(_normalize_relpath(source_pdf)).parts if p]
    if len(parts) >= 3:
        return parts[0], parts[1]
    return "", ""


def _path_from_plan_item(plan_item: dict[str, Any]) -> str:
    for item in plan_item.get("affected_paths", []):
        candidate = str(item)
        if candidate.lower().endswith(".pdf"):
            return _normalize_relpath(candidate)
    return ""


def _is_trim_suggested(audit_case: dict[str, Any], plan_item: dict[str, Any] | None) -> bool:
    suggested_trim = _to_int(audit_case.get("suggested_trim_pages"))
    if suggested_trim is not None and suggested_trim > 0:
        return True
    if not plan_item:
        return False
    plan_trim = _to_int(plan_item.get("trim_leading_pages"))
    if plan_trim is not None and plan_trim > 0:
        return True
    return str(plan_item.get("action", "")).strip() == "trim_leading_pages"


def _select_case_ids(
    audit_cases_by_id: dict[str, dict[str, Any]],
    plan_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    selected: set[str] = set()
    for case_id, audit_case in audit_cases_by_id.items():
        severity = str(audit_case.get("severity", "")).strip()
        if severity in REVIEW_SEVERITIES or _is_trim_suggested(audit_case, plan_by_id.get(case_id)):
            selected.add(case_id)
    for case_id, plan_item in plan_by_id.items():
        action = str(plan_item.get("action", "")).strip()
        plan_trim = _to_int(plan_item.get("trim_leading_pages"))
        if action == "trim_leading_pages" or (plan_trim is not None and plan_trim > 0):
            selected.add(case_id)
    return sorted(selected)


def _resolve_pdf_path(book_root: Path, source_pdf: str, case_id: str) -> Path | None:
    normalized = _normalize_relpath(source_pdf)
    direct = book_root / normalized
    if direct.exists():
        return direct

    if normalized.lower().startswith("book/"):
        candidate = book_root / normalized[5:]
        if candidate.exists():
            return candidate

    by_name = list(book_root.rglob(f"{case_id}.pdf"))
    if by_name:
        return by_name[0]
    return None


def _open_doc(pdf_path: Path) -> tuple[str, Any, int] | tuple[None, None, None]:
    try:
        import fitz  # type: ignore

        doc = fitz.open(str(pdf_path))
        return "fitz", doc, int(doc.page_count)
    except Exception:
        pass

    try:
        import pypdfium2 as pdfium  # type: ignore

        doc = pdfium.PdfDocument(str(pdf_path))
        return "pdfium", doc, int(len(doc))
    except Exception:
        pass
    return None, None, None


def _close_doc(engine: str | None, doc: Any) -> None:
    if doc is None:
        return
    try:
        doc.close()
    except Exception:
        if engine == "fitz":
            pass


def _render_doc_page(engine: str, doc: Any, page_number: int, out_path: Path) -> bool:
    if engine == "fitz":
        import fitz  # type: ignore

        page = doc.load_page(page_number - 1)
        matrix = fitz.Matrix(150 / 72.0, 150 / 72.0)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        pix.save(str(out_path))
        return True

    if engine == "pdfium":
        page = doc[page_number - 1]
        bitmap = page.render(scale=150 / 72.0)
        image = bitmap.to_pil()
        image.save(str(out_path))
        return True

    return False


def _thumbnail_targets(first_caso_page: int | None, page_count: int) -> list[tuple[int, str, str]]:
    targets: list[tuple[int, str, str]] = []
    for page in range(1, min(page_count, 4) + 1):
        targets.append((page, f"page_{page}.png", f"Page {page}"))

    if first_caso_page is not None and 1 <= first_caso_page <= page_count and first_caso_page > 4:
        targets.append(
            (
                first_caso_page,
                "page_where_caso_problema_appears.png",
                f"Caso Problema page (Page {first_caso_page})",
            )
        )

    targets.append((page_count, "last_page.png", f"Last page (Page {page_count})"))
    return targets


def render_case_thumbnails(
    *,
    pdf_path: Path,
    case_id: str,
    first_caso_page: int | None,
    assets_root: Path,
) -> tuple[int | None, list[dict[str, Any]]]:
    engine, doc, page_count = _open_doc(pdf_path)
    if engine is None or doc is None or page_count is None or page_count < 1:
        return None, []

    case_assets_dir = assets_root / case_id
    case_assets_dir.mkdir(parents=True, exist_ok=True)

    thumbnails: list[dict[str, Any]] = []
    try:
        for page_number, file_name, label in _thumbnail_targets(first_caso_page, page_count):
            out_path = case_assets_dir / file_name
            try:
                rendered = _render_doc_page(engine, doc, page_number, out_path)
            except Exception:
                rendered = False
            if not rendered:
                continue
            thumbnails.append(
                {
                    "page_number": page_number,
                    "label": label,
                    "path": f"assets/{case_id}/{file_name}",
                }
            )
    finally:
        _close_doc(engine, doc)

    return page_count, thumbnails


def build_review_cases(
    *,
    audit_json_path: Path,
    correction_plan_path: Path,
    book_root: Path,
    assets_root: Path,
    render_thumbnails: bool = True,
) -> list[dict[str, Any]]:
    audit_payload = _load_json(audit_json_path)
    correction_plan_payload = _load_json(correction_plan_path)

    flagged_cases = audit_payload.get("flagged_cases", [])
    audit_cases_by_id = {str(item.get("case_id")): item for item in flagged_cases if item.get("case_id")}
    plan_by_id = {
        str(item.get("case_id")): item for item in correction_plan_payload if item.get("case_id")
    }
    selected_ids = _select_case_ids(audit_cases_by_id, plan_by_id)

    review_cases: list[dict[str, Any]] = []
    for case_id in selected_ids:
        audit_case = audit_cases_by_id.get(case_id, {})
        plan_item = plan_by_id.get(case_id, {})

        severity = str(audit_case.get("severity", plan_item.get("severity", "low_confidence_review")))
        source_pdf = str(audit_case.get("source_pdf", _path_from_plan_item(plan_item)))
        section = str(audit_case.get("section", "")).strip()
        subsection = str(audit_case.get("subsection", "")).strip()
        if not section or not subsection:
            section_guess, subsection_guess = _parse_section_subsection_from_source(source_pdf)
            section = section or section_guess
            subsection = subsection or subsection_guess

        first_caso_page = _to_int(audit_case.get("first_caso_problema_page"))
        suggested_trim_pages = _to_int(audit_case.get("suggested_trim_pages"))
        if suggested_trim_pages is None:
            suggested_trim_pages = _to_int(plan_item.get("trim_leading_pages"))

        flags = audit_case.get("flags")
        if not flags:
            footer_flags = list(audit_case.get("footer_flags", []))
            content_flags = list(audit_case.get("content_flags", []))
            flags = sorted(set([*footer_flags, *content_flags]))

        pdf_path = _resolve_pdf_path(book_root, source_pdf, case_id)
        pdf_path_resolved = str(pdf_path) if pdf_path else ""
        pdf_page_count: int | None = _to_int(audit_case.get("pdf_page_count"))
        thumbnails: list[dict[str, Any]] = []

        if render_thumbnails and pdf_path is not None and pdf_path.exists():
            rendered_page_count, thumbnails = render_case_thumbnails(
                pdf_path=pdf_path,
                case_id=case_id,
                first_caso_page=first_caso_page,
                assets_root=assets_root,
            )
            if rendered_page_count is not None:
                pdf_page_count = rendered_page_count

        review_cases.append(
            {
                "case_id": case_id,
                "section": section,
                "subsection": subsection,
                "severity": severity,
                "flags": list(flags or []),
                "suggested_trim_pages": suggested_trim_pages,
                "expected_start": _to_int(audit_case.get("expected_start")),
                "first_detected_footer": _to_int(audit_case.get("first_detected_footer")),
                "source_pdf": source_pdf,
                "source_pdf_resolved": pdf_path_resolved,
                "first_caso_problema_page": first_caso_page,
                "correction_plan_action": str(plan_item.get("action", "")),
                "correction_plan_trim_leading_pages": _to_int(plan_item.get("trim_leading_pages")),
                "pdf_page_count": pdf_page_count,
                "thumbnails": thumbnails,
            }
        )

    return review_cases


def write_review_cases_json(review_cases: list[dict[str, Any]], output_path: Path) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_cases": len(review_cases),
        "cases": review_cases,
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_review_decisions_template_csv(review_cases: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TEMPLATE_COLUMNS)
        writer.writeheader()
        for case in review_cases:
            writer.writerow(
                {
                    "case_id": case["case_id"],
                    "section": case["section"],
                    "subsection": case["subsection"],
                    "severity": case["severity"],
                    "suggested_trim_pages": (
                        "" if case["suggested_trim_pages"] is None else case["suggested_trim_pages"]
                    ),
                    "human_decision": "",
                    "human_trim_pages": "",
                    "confidence": "",
                    "notes": "",
                    "page1_previous_case": "",
                    "page2_previous_case": "",
                    "case_starts_correctly": "",
                    "render_ocr_mismatch": "",
                }
            )


def write_review_instructions(output_path: Path) -> None:
    content = """# Boundary Review Instructions

1. Open `data/curated/boundary_review/index.html` in your browser.
2. Inspect only the first 2-4 pages first.
3. Key question:
   "Does this case include pages from the previous case before the real case starts?"
4. Use decisions:
   - `no_action`: Page 1 is the correct case start.
   - `trim_1_leading_page`: Page 1 belongs to the previous case and Page 2 starts the case.
   - `trim_2_leading_pages`: Pages 1-2 belong to the previous case and Page 3 starts the case.
   - `inspect_manual`: unclear after first-pass inspection.
5. Export decisions as JSON or CSV from the dashboard.
6. Do not apply corrections until exported decisions are reviewed.
"""
    output_path.write_text(content, encoding="utf-8")


def _html_template(embedded_cases_json: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Boundary Review Dashboard</title>
  <style>
    :root {{
      --bg: #f4f7f9;
      --panel: #ffffff;
      --text: #102a43;
      --muted: #5c6f82;
      --line: #d9e2ec;
      --accent: #0b7285;
      --bad: #b02a37;
      --warn: #b08900;
      --ok: #2b8a3e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Tahoma, sans-serif;
      color: var(--text);
      background: linear-gradient(180deg, #ecf2f7 0%, #f7fafc 240px);
    }}
    .wrap {{ max-width: 1500px; margin: 0 auto; padding: 20px; }}
    .top {{
      position: sticky;
      top: 0;
      z-index: 3;
      background: rgba(244, 247, 249, 0.96);
      backdrop-filter: blur(6px);
      border-bottom: 1px solid var(--line);
      padding: 12px 0;
      margin-bottom: 14px;
    }}
    .top h1 {{ margin: 0 0 10px 0; font-size: 20px; }}
    .filters {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      align-items: end;
    }}
    label {{ display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }}
    select, input[type="text"] {{
      width: 100%;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }}
    .checks {{
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      font-size: 13px;
      color: var(--text);
      align-items: center;
    }}
    .row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 10px;
      align-items: center;
    }}
    .btn {{
      border: 1px solid #0b7285;
      background: #0b7285;
      color: #fff;
      border-radius: 8px;
      padding: 8px 12px;
      cursor: pointer;
      font-weight: 600;
    }}
    .btn.secondary {{
      background: #fff;
      color: #0b7285;
    }}
    .progress {{ font-weight: 600; color: var(--accent); }}
    .cards {{
      display: grid;
      gap: 14px;
      grid-template-columns: 1fr;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      box-shadow: 0 1px 0 rgba(16, 42, 67, 0.03);
    }}
    .card-head {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }}
    .pill {{
      padding: 3px 9px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid var(--line);
      background: #fff;
    }}
    .sev-confirmed_boundary_error {{ color: var(--bad); border-color: #f1aeb5; background: #fff5f6; }}
    .sev-probable_boundary_error {{ color: var(--warn); border-color: #f5d977; background: #fff8dd; }}
    .sev-low_confidence_review {{ color: #495057; border-color: #ced4da; background: #f8f9fa; }}
    .meta {{ color: var(--muted); font-size: 12px; margin-bottom: 8px; }}
    .flags {{ margin: 0 0 8px 0; padding-left: 16px; font-size: 12px; color: #334e68; }}
    .thumbs {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      margin-bottom: 10px;
    }}
    figure {{
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: #fff;
    }}
    figure img {{
      width: 100%;
      height: 250px;
      object-fit: contain;
      background: #f8fafc;
      display: block;
    }}
    figcaption {{
      font-size: 12px;
      padding: 6px 8px;
      border-top: 1px solid var(--line);
      color: #334e68;
      background: #f9fbfd;
    }}
    .controls {{
      display: grid;
      gap: 10px;
      grid-template-columns: 1.5fr 1fr;
      align-items: start;
    }}
    .radios {{ display: grid; gap: 4px; font-size: 13px; }}
    textarea {{
      width: 100%;
      min-height: 74px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      font-family: inherit;
    }}
    .checklist {{ display: grid; gap: 4px; font-size: 13px; }}
    .source {{ font-family: Consolas, monospace; font-size: 12px; color: #486581; }}
    @media (max-width: 980px) {{
      .controls {{ grid-template-columns: 1fr; }}
      figure img {{ height: 220px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap top">
    <h1>Boundary Review Dashboard</h1>
    <div class="filters">
      <div>
        <label for="filterSection">Section</label>
        <select id="filterSection"></select>
      </div>
      <div>
        <label for="filterSeverity">Severity</label>
        <select id="filterSeverity"></select>
      </div>
      <div>
        <label for="filterSuggestedTrim">Suggested Trim</label>
        <select id="filterSuggestedTrim"></select>
      </div>
      <div class="checks">
        <label><input type="checkbox" id="onlyUndecided" /> only undecided</label>
        <label><input type="checkbox" id="onlyConfirmed" /> only confirmed_boundary_error</label>
      </div>
    </div>
    <div class="row">
      <span class="progress" id="progressText">Reviewed 0 / 0</span>
      <button class="btn" id="exportJsonBtn">Export decisions (JSON)</button>
      <button class="btn secondary" id="exportCsvBtn">Export decisions (CSV)</button>
    </div>
  </div>
  <div class="wrap">
    <div id="cards" class="cards"></div>
  </div>

  <script>
    const embeddedCases = {embedded_cases_json};
    let cases = embeddedCases;
    const decisions = Object.create(null);

    const DECISION_OPTIONS = [
      "no_action",
      "trim_1_leading_page",
      "trim_2_leading_pages",
      "inspect_manual",
      "uncertain",
    ];

    function sanitizeId(value) {{
      return String(value).replace(/[^a-zA-Z0-9_-]/g, "_");
    }}

    function esc(value) {{
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }}

    async function loadCases() {{
      try {{
        const response = await fetch("./review_cases.json");
        if (!response.ok) throw new Error("fetch not ok");
        const payload = await response.json();
        if (Array.isArray(payload.cases)) {{
          cases = payload.cases;
        }}
      }} catch (_err) {{
      }}
    }}

    function initFilters() {{
      const sectionSelect = document.getElementById("filterSection");
      const severitySelect = document.getElementById("filterSeverity");
      const suggestedSelect = document.getElementById("filterSuggestedTrim");

      const sections = [...new Set(cases.map(c => c.section || "(unknown)"))].sort();
      const severities = [...new Set(cases.map(c => c.severity || "(unknown)"))].sort();

      sectionSelect.innerHTML = `<option value="all">all</option>${{sections.map(s => `<option value="${{esc(s)}}">${{esc(s)}}</option>`).join("")}}`;
      severitySelect.innerHTML = `<option value="all">all</option>${{severities.map(s => `<option value="${{esc(s)}}">${{esc(s)}}</option>`).join("")}}`;
      suggestedSelect.innerHTML = `
        <option value="all">all</option>
        <option value="1">1</option>
        <option value="2">2</option>
        <option value="0">0</option>
        <option value="unknown">unknown</option>
      `;

      sectionSelect.addEventListener("change", render);
      severitySelect.addEventListener("change", render);
      suggestedSelect.addEventListener("change", render);
      document.getElementById("onlyUndecided").addEventListener("change", render);
      document.getElementById("onlyConfirmed").addEventListener("change", render);
    }}

    function getDecision(caseId) {{
      return decisions[caseId] || {{}};
    }}

    function renderProgress() {{
      const reviewed = cases.filter(c => (getDecision(c.case_id).human_decision || "").trim() !== "").length;
      document.getElementById("progressText").textContent = `Reviewed ${{reviewed}} / ${{cases.length}}`;
    }}

    function filteredCases() {{
      const section = document.getElementById("filterSection").value;
      const severity = document.getElementById("filterSeverity").value;
      const suggestedTrim = document.getElementById("filterSuggestedTrim").value;
      const onlyUndecided = document.getElementById("onlyUndecided").checked;
      const onlyConfirmed = document.getElementById("onlyConfirmed").checked;

      return cases.filter((c) => {{
        if (section !== "all" && (c.section || "(unknown)") !== section) return false;
        if (severity !== "all" && (c.severity || "(unknown)") !== severity) return false;
        if (onlyConfirmed && c.severity !== "confirmed_boundary_error") return false;

        const suggested = c.suggested_trim_pages;
        if (suggestedTrim === "unknown" && suggested != null) return false;
        if (suggestedTrim === "0" && suggested !== 0) return false;
        if (suggestedTrim === "1" && suggested !== 1) return false;
        if (suggestedTrim === "2" && suggested !== 2) return false;

        const d = getDecision(c.case_id);
        if (onlyUndecided && (d.human_decision || "").trim() !== "") return false;
        return true;
      }});
    }}

    function updateDecision(caseId, patch) {{
      decisions[caseId] = {{ ...(decisions[caseId] || {{}}), ...patch }};
      renderProgress();
    }}

    function render() {{
      renderProgress();
      const list = filteredCases();
      const cards = document.getElementById("cards");
      cards.innerHTML = "";

      for (const c of list) {{
        const caseDomId = sanitizeId(c.case_id);
        const d = getDecision(c.case_id);
        const flags = Array.isArray(c.flags) ? c.flags : [];
        const thumbs = Array.isArray(c.thumbnails) ? c.thumbnails : [];
        const cpPage = c.first_caso_problema_page;

        const thumbHtml = thumbs.map((t) => {{
          const cpTag = (cpPage != null && Number(cpPage) === Number(t.page_number)) ? " | Caso Problema page" : "";
          return `
            <figure>
              <img loading="lazy" src="${{esc(t.path)}}" alt="${{esc(t.label)}}" />
              <figcaption>${{esc(t.label)}}${{cpTag}}</figcaption>
            </figure>
          `;
        }}).join("");

        const radios = DECISION_OPTIONS.map((opt) => {{
          const checked = (d.human_decision || "") === opt ? "checked" : "";
          return `<label><input type="radio" name="decision_${{caseDomId}}" value="${{opt}}" ${{checked}} /> ${{opt}}</label>`;
        }}).join("");

        const element = document.createElement("article");
        element.className = "card";
        element.innerHTML = `
          <div class="card-head">
            <div><strong>${{esc(c.case_id)}}</strong> <span class="meta">${{esc(c.section)}} / ${{esc(c.subsection)}}</span></div>
            <span class="pill sev-${{esc(c.severity)}}">${{esc(c.severity)}}</span>
          </div>
          <div class="meta">expected_start=${{esc(c.expected_start)}} | first_detected_footer=${{esc(c.first_detected_footer)}} | suggested_trim_pages=${{esc(c.suggested_trim_pages)}} | plan_action=${{esc(c.correction_plan_action)}}</div>
          <ul class="flags">${{flags.map(f => `<li>${{esc(f)}}</li>`).join("") || "<li>(no flags)</li>"}}</ul>
          <div class="source">source_pdf: ${{esc(c.source_pdf)}}</div>
          <div class="thumbs">${{thumbHtml || "<div class='meta'>No thumbnails rendered</div>"}}</div>
          <div class="controls">
            <div>
              <div class="radios">${{radios}}</div>
              <div style="margin-top:8px;">
                <label for="trim_${{caseDomId}}">human_trim_pages</label>
                <select id="trim_${{caseDomId}}">
                  <option value="">(empty)</option>
                  <option value="1" ${{String(d.human_trim_pages||"")==="1" ? "selected" : ""}}>1</option>
                  <option value="2" ${{String(d.human_trim_pages||"")==="2" ? "selected" : ""}}>2</option>
                </select>
              </div>
              <div style="margin-top:8px;">
                <label for="confidence_${{caseDomId}}">confidence</label>
                <select id="confidence_${{caseDomId}}">
                  <option value="">(empty)</option>
                  <option value="low" ${{(d.confidence||"")==="low" ? "selected" : ""}}>low</option>
                  <option value="medium" ${{(d.confidence||"")==="medium" ? "selected" : ""}}>medium</option>
                  <option value="high" ${{(d.confidence||"")==="high" ? "selected" : ""}}>high</option>
                </select>
              </div>
            </div>
            <div>
              <div class="checklist">
                <label><input type="checkbox" id="p1_${{caseDomId}}" ${{d.page1_previous_case ? "checked" : ""}} /> page 1 clearly belongs to previous case</label>
                <label><input type="checkbox" id="p2_${{caseDomId}}" ${{d.page2_previous_case ? "checked" : ""}} /> page 2 clearly belongs to previous case</label>
                <label><input type="checkbox" id="startok_${{caseDomId}}" ${{d.case_starts_correctly ? "checked" : ""}} /> case starts correctly</label>
                <label><input type="checkbox" id="mismatch_${{caseDomId}}" ${{d.render_ocr_mismatch ? "checked" : ""}} /> render/OCR mismatch suspected</label>
              </div>
              <div style="margin-top:8px;">
                <label for="notes_${{caseDomId}}">notes</label>
                <textarea id="notes_${{caseDomId}}" placeholder="optional notes">${{esc(d.notes || "")}}</textarea>
              </div>
            </div>
          </div>
        `;
        cards.appendChild(element);

        element.querySelectorAll(`input[name="decision_${{caseDomId}}"]`).forEach((input) => {{
          input.addEventListener("change", (e) => updateDecision(c.case_id, {{ human_decision: e.target.value }}));
        }});
        document.getElementById(`trim_${{caseDomId}}`).addEventListener("change", (e) => {{
          updateDecision(c.case_id, {{ human_trim_pages: e.target.value }});
        }});
        document.getElementById(`confidence_${{caseDomId}}`).addEventListener("change", (e) => {{
          updateDecision(c.case_id, {{ confidence: e.target.value }});
        }});
        document.getElementById(`notes_${{caseDomId}}`).addEventListener("input", (e) => {{
          updateDecision(c.case_id, {{ notes: e.target.value }});
        }});
        document.getElementById(`p1_${{caseDomId}}`).addEventListener("change", (e) => {{
          updateDecision(c.case_id, {{ page1_previous_case: e.target.checked }});
        }});
        document.getElementById(`p2_${{caseDomId}}`).addEventListener("change", (e) => {{
          updateDecision(c.case_id, {{ page2_previous_case: e.target.checked }});
        }});
        document.getElementById(`startok_${{caseDomId}}`).addEventListener("change", (e) => {{
          updateDecision(c.case_id, {{ case_starts_correctly: e.target.checked }});
        }});
        document.getElementById(`mismatch_${{caseDomId}}`).addEventListener("change", (e) => {{
          updateDecision(c.case_id, {{ render_ocr_mismatch: e.target.checked }});
        }});
      }}
    }}

    function collectDecisionRows() {{
      return cases.map((c) => {{
        const d = getDecision(c.case_id);
        return {{
          case_id: c.case_id,
          section: c.section || "",
          subsection: c.subsection || "",
          severity: c.severity || "",
          suggested_trim_pages: c.suggested_trim_pages == null ? "" : c.suggested_trim_pages,
          human_decision: d.human_decision || "",
          human_trim_pages: d.human_trim_pages || "",
          confidence: d.confidence || "",
          notes: d.notes || "",
          page1_previous_case: d.page1_previous_case === true,
          page2_previous_case: d.page2_previous_case === true,
          case_starts_correctly: d.case_starts_correctly === true,
          render_ocr_mismatch: d.render_ocr_mismatch === true,
        }};
      }});
    }}

    function toCsv(rows) {{
      const cols = [
        "case_id",
        "section",
        "subsection",
        "severity",
        "suggested_trim_pages",
        "human_decision",
        "human_trim_pages",
        "confidence",
        "notes",
        "page1_previous_case",
        "page2_previous_case",
        "case_starts_correctly",
        "render_ocr_mismatch",
      ];

      const escapeCell = (v) => {{
        const text = String(v ?? "");
        if (text.includes(",") || text.includes("\\"") || text.includes("\\n")) {{
          return `"${{text.replace(/"/g, '""')}}"`;
        }}
        return text;
      }};

      const lines = [cols.join(",")];
      for (const row of rows) {{
        lines.push(cols.map((col) => escapeCell(row[col])).join(","));
      }}
      return lines.join("\\n");
    }}

    function download(name, content, mimeType) {{
      const blob = new Blob([content], {{ type: mimeType }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }}

    document.getElementById("exportJsonBtn").addEventListener("click", () => {{
      const rows = collectDecisionRows();
      const payload = {{
        exported_at: new Date().toISOString(),
        total_cases: rows.length,
        decisions: rows,
      }};
      download("review_decisions.json", JSON.stringify(payload, null, 2), "application/json");
    }});

    document.getElementById("exportCsvBtn").addEventListener("click", () => {{
      const rows = collectDecisionRows();
      download("review_decisions.csv", toCsv(rows), "text/csv;charset=utf-8");
    }});

    (async function init() {{
      await loadCases();
      initFilters();
      render();
    }})();
  </script>
</body>
</html>
"""


def write_dashboard_html(review_cases: list[dict[str, Any]], output_path: Path) -> None:
    html = _html_template(json.dumps(review_cases, ensure_ascii=False))
    output_path.write_text(html, encoding="utf-8")


def build_boundary_review_dashboard(
    *,
    audit_json_path: Path,
    correction_plan_path: Path,
    book_root: Path,
    output_dir: Path,
    render_thumbnails: bool = True,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_root = output_dir / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    review_cases = build_review_cases(
        audit_json_path=audit_json_path,
        correction_plan_path=correction_plan_path,
        book_root=book_root,
        assets_root=assets_root,
        render_thumbnails=render_thumbnails,
    )

    write_review_cases_json(review_cases, output_dir / "review_cases.json")
    write_dashboard_html(review_cases, output_dir / "index.html")
    write_review_decisions_template_csv(review_cases, output_dir / "review_decisions_template.csv")
    write_review_instructions(output_dir / "review_instructions.md")
    return review_cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local boundary-review dashboard artifacts.")
    parser.add_argument("--audit-json", default="data/curated/case_boundary_audit_v2.json")
    parser.add_argument("--correction-plan-json", default="data/curated/case_boundary_correction_plan_v2.json")
    parser.add_argument("--book-root", default="book")
    parser.add_argument("--output-dir", default="data/curated/boundary_review")
    parser.add_argument("--no-thumbnails", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit_json_path = Path(args.audit_json)
    correction_plan_path = Path(args.correction_plan_json)
    book_root = Path(args.book_root)
    output_dir = Path(args.output_dir)

    review_cases = build_boundary_review_dashboard(
        audit_json_path=audit_json_path,
        correction_plan_path=correction_plan_path,
        book_root=book_root,
        output_dir=output_dir,
        render_thumbnails=not args.no_thumbnails,
    )

    print(f"[Boundary Review] cases selected: {len(review_cases)}")
    print(f"[Boundary Review] dashboard: {output_dir / 'index.html'}")
    print(f"[Boundary Review] dataset: {output_dir / 'review_cases.json'}")
    print(f"[Boundary Review] template: {output_dir / 'review_decisions_template.csv'}")
    print(f"[Boundary Review] instructions: {output_dir / 'review_instructions.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
