#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Dynamically prepend the virtual environment's Scripts directory to PATH
# This ensures ocrmypdf and tesseract executables are discoverable
sys_path = Path(sys.executable).parent
os.environ["PATH"] = str(sys_path) + os.pathsep + os.environ.get("PATH", "")

from scanbook.ocr.ocrmypdf_backend import OcrmypdfBackend
from scanbook.qa import run_qa
from scanbook.utils import ensure_dir, sha256_file, read_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch OCR and text extraction for split clinical case PDFs."
    )
    parser.add_argument(
        "--book-id",
        required=True,
        help="ID of the book to process (mandatory)."
    )
    parser.add_argument(
        "--input-root",
        help="Root directory containing split case PDFs (defaults to book/<book_id>)."
    )
    parser.add_argument(
        "--output-root",
        help="Directory where OCR outputs will be written (defaults to data/ocr_cases/<book_id>)."
    )
    parser.add_argument(
        "--section",
        help="Optional section subdirectory to process (e.g. seccion2)."
    )
    parser.add_argument(
        "--subsection",
        help="Optional subsection subdirectory to process (e.g. anemias_microciticas)."
    )
    parser.add_argument(
        "--case-glob",
        default="*.pdf",
        help="Glob pattern to match case PDFs (default: *.pdf)."
    )
    parser.add_argument(
        "--lang",
        action="append",
        help="OCR languages (can be specified multiple times, default: ['spa', 'eng'])."
    )
    parser.add_argument(
        "--profile",
        default="balanced",
        help="OCR profile to use (default: balanced)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional maximum number of cases to process."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run: scan files and print planned operations without executing."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute OCR processing."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-processing of already completed cases."
    )
    return parser.parse_args()


def discover_cases(
    input_root: Path,
    output_root: Path,
    section_filter: str | None,
    subsection_filter: str | None,
    case_glob: str,
    force: bool
) -> list[dict]:
    discovered = []
    
    # Resolve section directories
    if section_filter and section_filter != "all":
        sections = [input_root / section_filter]
    else:
        sections = [d for d in input_root.iterdir() if d.is_dir() and d.name.startswith("seccion")]
        
    for sec_dir in sections:
        if not sec_dir.exists():
            continue
        sec_name = sec_dir.name
        
        # Resolve subsection directories
        if subsection_filter:
            subsections = [sec_dir / subsection_filter]
        else:
            subsections = [d for d in sec_dir.iterdir() if d.is_dir()]
            
        for subsec_dir in subsections:
            if not subsec_dir.exists():
                continue
            subsec_name = subsec_dir.name
            
            # Find PDF files matching glob
            for pdf_path in subsec_dir.glob(case_glob):
                if not pdf_path.is_file():
                    continue
                if pdf_path.suffix.lower() != ".pdf":
                    continue
                
                # Exclude section-level PDFs (which live in sec_dir, not subsec_dir)
                if pdf_path.parent != subsec_dir:
                    continue
                
                case_file_stem = pdf_path.stem
                
                # Exclude section-level or generated PDFs (e.g. sectionN.pdf, ocr.pdf)
                if case_file_stem.startswith("section") or case_file_stem == "ocr":
                    continue
                
                # Parse printed_start_page and title_slug
                match = re.match(r"^(\d+)_(.*)$", case_file_stem)
                if match:
                    printed_start_page = int(match.group(1))
                    title_slug = match.group(2)
                else:
                    printed_start_page = None
                    title_slug = case_file_stem
                
                # Check completeness
                output_dir = output_root / sec_name / subsec_name / case_file_stem
                expected_files = [
                    output_dir / "ocr.pdf",
                    output_dir / "sidecar.txt",
                    output_dir / "pages.jsonl",
                    output_dir / "case.md",
                    output_dir / "case_metadata.json",
                    output_dir / "qa.json",
                    output_dir / "qa.md"
                ]
                
                is_completed = False
                meta_file = output_dir / "case_metadata.json"
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                        if meta.get("status") == "success":
                            is_completed = all((output_dir / f.name).exists() for f in expected_files)
                    except Exception:
                        pass
                
                will_skip = is_completed and (not force)
                skip_reason = "already_completed" if will_skip else ""
                
                discovered.append({
                    "path": pdf_path,
                    "section": sec_name,
                    "subsection": subsec_name,
                    "case_file_stem": case_file_stem,
                    "printed_start_page": printed_start_page,
                    "title_slug": title_slug,
                    "output_dir": output_dir,
                    "is_completed": is_completed,
                    "will_skip": will_skip,
                    "skip_reason": skip_reason
                })
                
    discovered.sort(key=lambda x: (x["section"], x["subsection"], x["case_file_stem"]))
    return discovered


def build_global_summary(input_root: Path, output_root: Path) -> tuple[dict, str]:
    # 1. Discover all cases under the input root
    all_cases = discover_cases(
        input_root=input_root,
        output_root=output_root,
        section_filter=None,
        subsection_filter=None,
        case_glob="*.pdf",
        force=False
    )
    
    total_discovered = len(all_cases)
    
    # Load execute manifest to get newly processed case IDs
    newly_processed_ids = set()
    manifest_path = output_root / "ocr_cases_execute_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            newly_processed_ids = set(manifest.get("newly_processed_case_ids", []))
        except Exception:
            pass
            
    completed_count = 0
    failed_count = 0
    total_pages = 0
    total_chars = 0
    cases_with_empty = 0
    cases_with_suspicious = 0
    
    per_section = {}
    per_subsection = {}
    failed_cases = []
    successful_cases_data = []
    
    # Initialize per-section structures
    for c in all_cases:
        sec = c["section"]
        sub = c["subsection"]
        if sec not in per_section:
            per_section[sec] = {
                "discovered": 0, "completed": 0, "failed": 0, "pending": 0,
                "total_pages": 0, "total_characters": 0
            }
        per_section[sec]["discovered"] += 1
        
        sub_key = f"{sec}/{sub}"
        if sub_key not in per_subsection:
            per_subsection[sub_key] = {
                "section": sec, "subsection": sub,
                "discovered": 0, "completed": 0, "failed": 0, "pending": 0,
                "total_pages": 0, "total_characters": 0
            }
        per_subsection[sub_key]["discovered"] += 1
        
    for c in all_cases:
        case_id = c["case_file_stem"]
        sec = c["section"]
        sub = c["subsection"]
        sub_key = f"{sec}/{sub}"
        
        output_dir = c["output_dir"]
        meta_path = output_dir / "case_metadata.json"
        
        status = "pending"
        err_msg = None
        
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                status = meta.get("status", "pending")
                err_msg = meta.get("error")
            except Exception as e:
                err_msg = str(e)
                status = "failed"
                
        if status == "success":
            completed_count += 1
            per_section[sec]["completed"] += 1
            per_subsection[sub_key]["completed"] += 1
            
            # Read page count
            page_count = 0
            if meta_path.exists():
                try:
                    page_count = meta.get("page_count", 0)
                except Exception:
                    pass
            total_pages += page_count
            per_section[sec]["total_pages"] += page_count
            per_subsection[sub_key]["total_pages"] += page_count
            
            # Read character count from sidecar
            char_count = 0
            sidecar_path = output_dir / "sidecar.txt"
            if sidecar_path.exists():
                try:
                    char_count = len(sidecar_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            total_chars += char_count
            per_section[sec]["total_characters"] += char_count
            per_subsection[sub_key]["total_characters"] += char_count
            
            # Read QA details
            qa_json_path = output_dir / "qa.json"
            has_empty = False
            has_suspicious = False
            if qa_json_path.exists():
                try:
                    qa = json.loads(qa_json_path.read_text(encoding="utf-8"))
                    if qa.get("empty_pages"):
                        has_empty = True
                    if qa.get("suspicious_low_text_pages"):
                        has_suspicious = True
                except Exception:
                    pass
            if has_empty:
                cases_with_empty += 1
            if has_suspicious:
                cases_with_suspicious += 1
                
            successful_cases_data.append({
                "case_id": case_id,
                "section": sec,
                "subsection": sub,
                "page_count": page_count,
                "character_count": char_count,
                "has_empty_pages": has_empty,
                "has_suspicious_low_text_pages": has_suspicious
            })
            
        elif status == "failed":
            failed_count += 1
            per_section[sec]["failed"] += 1
            per_subsection[sub_key]["failed"] += 1
            
            retry_cmd = f'.\\.venv\\Scripts\\python scripts\\ocr_split_cases.py --execute --force --section {sec} --subsection {sub} --case-glob "{case_id}.pdf"'
            failed_cases.append({
                "case_id": case_id,
                "section": sec,
                "subsection": sub,
                "error": err_msg or "Unknown error",
                "retry_command": retry_cmd
            })
        else:
            per_section[sec]["pending"] += 1
            per_subsection[sub_key]["pending"] += 1
            
    # Calculate skipped vs newly processed
    newly_processed_count = sum(1 for c in successful_cases_data if c["case_id"] in newly_processed_ids)
    already_completed_count = completed_count - newly_processed_count
    
    # Sort successful cases for top 20 lowest character-count
    successful_cases_data.sort(key=lambda x: x["character_count"])
    top_20_lowest = successful_cases_data[:20]
    
    summary_data = {
        "generated_at": datetime.now().isoformat(),
        "total_discovered_cases": total_discovered,
        "already_completed_skipped_cases": already_completed_count,
        "newly_processed_cases": newly_processed_count,
        "failed_cases": failed_count,
        "total_pages_processed": total_pages,
        "total_ocr_characters": total_chars,
        "cases_with_empty_pages": cases_with_empty,
        "cases_with_suspicious_low_text_pages": cases_with_suspicious,
        "top_20_lowest_character_count_cases": top_20_lowest,
        "per_section_counts": per_section,
        "per_subsection_counts": per_subsection,
        "failed_case_list": failed_cases
    }
    
    # Generate Markdown Summary
    md_lines = [
        "# Clinical Cases OCR Global Summary\n",
        f"**Report Generated At:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        "## Overall Metrics\n",
        "| Metric | Count |",
        "| --- | --- |",
        f"| **Total Discovered Cases** | {total_discovered} |",
        f"| **Already Completed / Skipped Cases** | {already_completed_count} |",
        f"| **Newly Processed Cases** | {newly_processed_count} |",
        f"| **Failed Cases** | {failed_count} |",
        f"| **Total Pages Processed** | {total_pages} |",
        f"| **Total OCR Characters** | {total_chars:,} |",
        f"| **Cases with Empty Pages** | {cases_with_empty} |",
        f"| **Cases with Suspicious Low-Text Pages** | {cases_with_suspicious} |\n",
        "## Per-Section Breakdown\n",
        "| Section | Discovered | Completed | Failed | Pending | Pages | Characters |",
        "| --- | --- | --- | --- | --- | --- | --- |"
    ]
    for sec_name, counts in sorted(per_section.items()):
        md_lines.append(
            f"| {sec_name} | {counts['discovered']} | {counts['completed']} | {counts['failed']} | {counts['pending']} | {counts['total_pages']} | {counts['total_characters']:,} |"
        )
    md_lines.append("\n## Per-Subsection Breakdown\n")
    md_lines.append("| Section | Subsection | Discovered | Completed | Failed | Pending | Pages | Characters |")
    md_lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for _, counts in sorted(per_subsection.items(), key=lambda x: x[0]):
        md_lines.append(
            f"| {counts['section']} | {counts['subsection']} | {counts['discovered']} | {counts['completed']} | {counts['failed']} | {counts['pending']} | {counts['total_pages']} | {counts['total_characters']:,} |"
        )
        
    md_lines.append("\n## Top 20 Lowest Character-Count Cases\n")
    md_lines.append("| Rank | Case ID | Section | Subsection | Pages | Characters | Empty | Suspicious |")
    md_lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for i, c in enumerate(top_20_lowest, 1):
        md_lines.append(
            f"| {i} | {c['case_id']} | {c['section']} | {c['subsection']} | {c['page_count']} | {c['character_count']:,} | {'Yes' if c['has_empty_pages'] else 'No'} | {'Yes' if c['has_suspicious_low_text_pages'] else 'No'} |"
        )
        
    md_lines.append("\n## Failed Case Details & Retries\n")
    if failed_cases:
        md_lines.append("| Case ID | Section | Subsection | Error Message | Recommended Retry Command |")
        md_lines.append("| --- | --- | --- | --- | --- |")
        for fc in failed_cases:
            md_lines.append(
                f"| {fc['case_id']} | {fc['section']} | {fc['subsection']} | {fc['error']} | `{fc['retry_command']}` |"
            )
    else:
        md_lines.append("*No failed cases found! All executed clinical cases processed successfully.*")
        
    md_summary = "\n".join(md_lines)
    return summary_data, md_summary


def main() -> int:
    args = parse_args()
    
    book_id = args.book_id
    input_root = Path(args.input_root) if args.input_root else (Path("book") / book_id)
    output_root = Path(args.output_root) if args.output_root else (Path("data") / "ocr_cases" / book_id)
    
    if not input_root.exists():
        print(f"Error: input root '{input_root}' does not exist.")
        return 1
        
    languages = args.lang if args.lang else ["spa", "eng"]
    is_dry_run = args.dry_run or (not args.execute)
    
    # Pre-creation check of output_root
    ensure_dir(output_root)
    
    print("Discovering split cases...")
    cases = discover_cases(
        input_root=input_root,
        output_root=output_root,
        section_filter=args.section,
        subsection_filter=args.subsection,
        case_glob=args.case_glob,
        force=args.force
    )
    
    if is_dry_run:
        print("\n=== DRY RUN SUMMARY ===")
        print(f"Input root: {input_root}")
        print(f"Output root: {output_root}")
        print(f"Languages: {languages}")
        print(f"Profile: {args.profile}")
        print(f"Total discovered cases: {len(cases)}")
        print("\n" + "=" * 115)
        print(f"{'Section':<10} | {'Subsection':<22} | {'Case PDF':<40} | {'Will Skip':<10} | {'Skip Reason':<20}")
        print("=" * 115)
        
        for c in cases:
            pdf_rel = str(c["path"].relative_to(input_root)).replace("\\", "/")
            print(f"{c['section']:<10} | {c['subsection']:<22} | {pdf_rel:<40} | {str(c['will_skip']):<10} | {c['skip_reason']:<20}")
        print("=" * 115)
        
        # Write dry-run manifest
        manifest_data = {
            "generated_at": datetime.now().isoformat(),
            "input_root": str(input_root).replace("\\", "/"),
            "output_root": str(output_root).replace("\\", "/"),
            "languages": languages,
            "profile": args.profile,
            "cases": [
                {
                    "section": c["section"],
                    "subsection": c["subsection"],
                    "case_id": c["case_file_stem"],
                    "case_pdf": str(c["path"].relative_to(input_root)).replace("\\", "/"),
                    "output_dir": str(c["output_dir"].relative_to(output_root.parent.parent if len(output_root.parts) >= 2 else output_root)).replace("\\", "/"),
                    "printed_start_page": c["printed_start_page"],
                    "title_slug": c["title_slug"],
                    "will_skip": c["will_skip"],
                    "skip_reason": c["skip_reason"]
                }
                for c in cases
            ]
        }
        dryrun_manifest_path = output_root / "ocr_cases_dryrun_manifest.json"
        dryrun_manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nDry-run manifest written to: {dryrun_manifest_path}")
        return 0

    # EXECUTE MODE
    print("\n=== EXECUTING BATCH OCR ===")
    print(f"Languages: {languages}")
    print(f"Profile: {args.profile}")
    if args.limit is not None:
        print(f"Limit: {args.limit} cases")
        
    execute_results = []
    processed_count = 0
    
    project_root = Path(__file__).resolve().parent.parent
    
    for c in cases:
        case_id = c["case_file_stem"]
        output_dir = c["output_dir"]
        
        # Apply Limit check
        if args.limit is not None and processed_count >= args.limit:
            # We record remaining un-run cases as skipped
            execute_results.append({
                "case_id": case_id,
                "section": c["section"],
                "subsection": c["subsection"],
                "status": "skipped",
                "error": "limit_reached"
            })
            continue
            
        if c["will_skip"]:
            print(f"Skipping case '{case_id}' (already completed)...")
            execute_results.append({
                "case_id": case_id,
                "section": c["section"],
                "subsection": c["subsection"],
                "status": "skipped",
                "error": None
            })
            continue
            
        print(f"\n[{processed_count + 1}] Processing case: {case_id} ({c['section']}/{c['subsection']})")
        processed_count += 1
        
        ensure_dir(output_dir)
        
        try:
            # 1. Compute SHA256 of source PDF
            pdf_sha256 = sha256_file(c["path"])
            source_manifest = {
                "source_pdf": str(c["path"].relative_to(input_root)).replace("\\", "/"),
                "sha256": pdf_sha256,
                "file_size_bytes": c["path"].stat().st_size
            }
            (output_dir / "source_manifest.json").write_text(
                json.dumps(source_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            
            # 2. Run OCRmyPDF Backend
            backend = OcrmypdfBackend()
            print("  Running OCRmyPDF backend...")
            backend.run(
                input_pdf=c["path"],
                output_jsonl=output_dir / "pages.jsonl",
                language=languages,
                profile=args.profile,
                chapter_id=case_id,
                output_pdf=output_dir / "ocr.pdf",
                sidecar_txt=output_dir / "sidecar.txt"
            )
            
            # 3. Run QA
            print("  Running QA checks...")
            qa_summary = run_qa(
                input_jsonl=output_dir / "pages.jsonl",
                report_dir=output_dir
            )
            
            # Rename QA files to match layout
            if (output_dir / "qa_summary.json").exists():
                shutil.move(str(output_dir / "qa_summary.json"), str(output_dir / "qa.json"))
            if (output_dir / "qa_summary.md").exists():
                shutil.move(str(output_dir / "qa_summary.md"), str(output_dir / "qa.md"))
                
            # 4. Generate case.md from pages.jsonl
            pages_data = read_jsonl(output_dir / "pages.jsonl")
            
            # Formulate Title
            parts = case_id.split('_')
            if parts[0].isdigit():
                num = parts[0]
                rest = " ".join(parts[1:])
                title = f"{num} {rest.capitalize()}"
            else:
                title = case_id.replace('_', ' ').capitalize()
                
            yaml_langs = "[" + ", ".join(languages) + "]"
            rel_source_pdf = str(c["path"].relative_to(input_root)).replace("\\", "/")
            frontmatter = (
                "---\n"
                f"section: {c['section']}\n"
                f"subsection: {c['subsection']}\n"
                f"case_id: {case_id}\n"
                f"source_pdf: {rel_source_pdf}\n"
                f"ocr_engine: ocrmypdf\n"
                f"languages: {yaml_langs}\n"
                f"printed_start_page: {c['printed_start_page'] if c['printed_start_page'] is not None else 'null'}\n"
                "---\n\n"
                f"# {title}\n\n"
            )
            
            md_body = []
            for p in sorted(pages_data, key=lambda x: x["page_num"]):
                page_num = p["page_num"]
                page_text = p.get("text", "")
                md_body.append(f"## Page {page_num}\n{page_text}\n")
                
            case_md_content = frontmatter + "\n".join(md_body)
            (output_dir / "case.md").write_text(case_md_content, encoding="utf-8")
            
            # 5. Extract detailed QA metrics for case_metadata.json
            page_count = len(pages_data)
            
            # Write case_metadata.json
            try:
                output_dir_rel = str(output_dir.resolve().relative_to(project_root.resolve())).replace("\\", "/")
            except ValueError:
                output_dir_rel = str(output_dir).replace("\\", "/")

            case_metadata = {
                "case_id": case_id,
                "section": c["section"],
                "subsection": c["subsection"],
                "source_pdf": str(c["path"].relative_to(input_root)).replace("\\", "/"),
                "output_dir": output_dir_rel,
                "source_sha256": pdf_sha256,
                "page_count": page_count,
                "ocr_pdf": "ocr.pdf",
                "sidecar_txt": "sidecar.txt",
                "pages_jsonl": "pages.jsonl",
                "case_md": "case.md",
                "qa_json": "qa.json",
                "qa_md": "qa.md",
                "languages": languages,
                "profile": args.profile,
                "status": "success",
                "error": None
            }
            (output_dir / "case_metadata.json").write_text(
                json.dumps(case_metadata, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            
            execute_results.append({
                "case_id": case_id,
                "section": c["section"],
                "subsection": c["subsection"],
                "status": "success",
                "error": None
            })
            print(f"  Finished {case_id} successfully.")
            
        except Exception as err:
            print(f"  FAILED {case_id}: {err}")
            # Try to write failed metadata
            try:
                try:
                    output_dir_rel = str(output_dir.resolve().relative_to(project_root.resolve())).replace("\\", "/")
                except ValueError:
                    output_dir_rel = str(output_dir).replace("\\", "/")

                case_metadata = {
                    "case_id": case_id,
                    "section": c["section"],
                    "subsection": c["subsection"],
                    "source_pdf": str(c["path"].relative_to(input_root)).replace("\\", "/"),
                    "output_dir": output_dir_rel,
                    "status": "failed",
                    "error": str(err)
                }
                (output_dir / "case_metadata.json").write_text(
                    json.dumps(case_metadata, indent=2, ensure_ascii=False), encoding="utf-8"
                )
            except Exception:
                pass
                
            execute_results.append({
                "case_id": case_id,
                "section": c["section"],
                "subsection": c["subsection"],
                "status": "failed",
                "error": str(err)
            })
            
    # Load existing manifest for cumulative merging
    existing_cases = {}
    batch_manifest_path = output_root / "ocr_cases_execute_manifest.json"
    if batch_manifest_path.exists():
        try:
            old_manifest = json.loads(batch_manifest_path.read_text(encoding="utf-8"))
            for c_entry in old_manifest.get("cases", []):
                existing_cases[c_entry["case_id"]] = c_entry
        except Exception:
            pass
            
    # Merge execute_results into existing cases
    for r in execute_results:
        cid = r["case_id"]
        if cid in existing_cases:
            existing = existing_cases[cid]
            # Keep existing success status if we skipped in this run
            if r["status"] == "skipped" and existing.get("status") == "success":
                pass
            else:
                existing_cases[cid] = r
        else:
            existing_cases[cid] = r
            
    newly_processed_ids = [r["case_id"] for r in execute_results if r["status"] == "success"]
    
    # Write cumulative batch execution manifest
    batch_manifest = {
        "generated_at": datetime.now().isoformat(),
        "input_root": str(input_root).replace("\\", "/"),
        "output_root": str(output_root).replace("\\", "/"),
        "languages": languages,
        "profile": args.profile,
        "newly_processed_case_ids": newly_processed_ids,
        "cases": list(existing_cases.values())
    }
    batch_manifest_path.write_text(
        json.dumps(batch_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nBatch execution manifest updated: {batch_manifest_path}")
    
    # Generate and write global summaries
    print("Generating global summary...")
    summary_data, md_summary = build_global_summary(input_root, output_root)
    
    summary_json_path = output_root / "ocr_cases_global_summary.json"
    summary_md_path = output_root / "ocr_cases_global_summary.md"
    
    summary_json_path.write_text(
        json.dumps(summary_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    summary_md_path.write_text(md_summary, encoding="utf-8")
    print(f"Global summary JSON written to: {summary_json_path}")
    print(f"Global summary Markdown written to: {summary_md_path}")
    
    # Print compact section summary
    success_in_run = len([r for r in execute_results if r["status"] == "success"])
    failed_in_run = len([r for r in execute_results if r["status"] == "failed"])
    skipped_in_run = len([r for r in execute_results if r["status"] == "skipped"])
    print(f"\nSection/Batch execution summary:")
    print(f"  - Newly processed successfully: {success_in_run}")
    print(f"  - Newly failed: {failed_in_run}")
    print(f"  - Skipped: {skipped_in_run}")
    
    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())

