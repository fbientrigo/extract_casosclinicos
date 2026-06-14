#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

MANIFEST_JSON = PROJECT_ROOT / "data/curated/clean_rebuild_cleanup_manifest.json"
MANIFEST_MD = PROJECT_ROOT / "data/curated/clean_rebuild_cleanup_manifest.md"

TARGETS = [
    "book_corrected",
    "data/ocr_cases",
    "data/ocr_cases_global_summary.json",
    "data/ocr_cases_global_summary.md",
    "data/clinical_cases.db",
    "data/curated/case_registry.csv",
    "data/curated/case_registry.jsonl",
    "data/curated/clean_cases",
    "data/curated/database_build_report.json",
    "data/curated/database_build_report.md",
    "data/colab_exports",
]

PROTECTED_PREFIXES = [
    "book",
    "book_corrected_v2",
    "scripts",
    "tests",
    "data/curated/boundary_review/review_decisions_rule_v2.csv",
    "data/curated/boundary_review/review_decisions_rule_v2.json",
    "data/curated/boundary_review/corrected_validation_v2",
]


@dataclass
class Action:
    rel_path: str
    abs_path: str
    exists: bool
    kind: str
    deleted: bool
    reason: str


def _is_protected(rel: Path) -> bool:
    rel_s = rel.as_posix().strip("/")
    for p in PROTECTED_PREFIXES:
        pp = p.strip("/")
        if rel_s == pp or rel_s.startswith(pp + "/"):
            return True
    return False


def _resolve_target(rel: str) -> Path:
    p = (PROJECT_ROOT / rel).resolve()
    if PROJECT_ROOT.resolve() not in [p, *p.parents]:
        raise ValueError(f"Target escapes project root: {rel}")
    return p


def run_cleanup(execute: bool) -> dict:
    actions: list[Action] = []
    for rel in TARGETS:
        rel_path = Path(rel)
        if _is_protected(rel_path):
            raise ValueError(f"Refusing to target protected path: {rel}")
        abs_path = _resolve_target(rel)
        exists = abs_path.exists()
        kind = "directory" if abs_path.is_dir() else "file"

        deleted = False
        reason = "not_found"
        if exists:
            reason = "planned_delete"
            if execute:
                if abs_path.is_dir():
                    shutil.rmtree(abs_path)
                else:
                    abs_path.unlink()
                deleted = True
                reason = "deleted"

        actions.append(Action(rel, str(abs_path), exists, kind, deleted, reason))

    now = datetime.now(timezone.utc).isoformat()
    summary = {
        "timestamp_utc": now,
        "mode": "execute" if execute else "dry-run",
        "project_root": str(PROJECT_ROOT),
        "targets": TARGETS,
        "protected_prefixes": PROTECTED_PREFIXES,
        "actions": [a.__dict__ for a in actions],
        "counts": {
            "planned_existing": sum(1 for a in actions if a.exists),
            "deleted": sum(1 for a in actions if a.deleted),
            "missing": sum(1 for a in actions if not a.exists),
        },
    }

    MANIFEST_JSON.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Clean Rebuild Cleanup Manifest",
        "",
        f"- Mode: `{summary['mode']}`",
        f"- Timestamp (UTC): `{now}`",
        f"- Planned existing targets: `{summary['counts']['planned_existing']}`",
        f"- Deleted targets: `{summary['counts']['deleted']}`",
        f"- Missing targets: `{summary['counts']['missing']}`",
        "",
        "| rel_path | exists | kind | deleted | reason |",
        "|---|---:|---|---:|---|",
    ]
    for a in actions:
        lines.append(f"| `{a.rel_path}` | {a.exists} | {a.kind} | {a.deleted} | {a.reason} |")
    MANIFEST_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete obsolete generated artifacts for clean rebuild.")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    summary = run_cleanup(execute=args.execute)
    print(f"cleanup mode={summary['mode']} deleted={summary['counts']['deleted']}")
    print(MANIFEST_JSON)
    print(MANIFEST_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
