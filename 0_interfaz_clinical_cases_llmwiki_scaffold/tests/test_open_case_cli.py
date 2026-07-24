#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CLI-mode tests for scripts/open_case.py.

The DB layer (_load_case) and the actual launches are mocked so these run
without duckdb, book PDFs, or a desktop. Verifies auto/pdf/text/both modes and
stable nonzero exit codes on failure.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import open_case as oc  # noqa: E402


@dataclass(frozen=True)
class FakePaths:
    collection_id: str
    data_updated_dir: Path


def _row():
    return pd.Series({
        "case_id": "452_x",
        "case_number": 452,
        "title_clean": "efectos adversos",
        "clean_text": "Texto completo.",
    })


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Wire open_case with a resolvable case and captured launches."""
    pdf = tmp_path / "452.pdf"
    pdf.write_bytes(b"%PDF fake")
    paths = FakePaths("lab", tmp_path / "du")
    events = {"pdf": [], "notepad": []}

    monkeypatch.setattr(oc, "_load_case", lambda args: (paths, _row(), pdf))
    monkeypatch.setattr(oc, "launch_pdf", lambda p, viewer=None: (
        events["pdf"].append(p) or {"status": "launch_requested", "mechanism": "os.startfile", "error": None, "path": str(p)}
    ))

    def fake_write(paths, row, sel, pdf_path=None):
        out = paths.data_updated_dir / "opened_cases" / "452_x.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("t", encoding="utf-8")
        return out

    monkeypatch.setattr(oc, "write_case_transcript", fake_write)
    monkeypatch.setattr(oc, "open_in_notepad", lambda p: (
        events["notepad"].append(p) or {"status": "launch_requested", "mechanism": "notepad.exe", "error": None, "path": str(p)}
    ))
    return events, pdf


def test_mode_pdf(monkeypatch, wired):
    events, pdf = wired
    monkeypatch.setattr(sys, "argv", ["open_case.py", "452", "--mode", "pdf", "--collection", "lab"])
    assert oc.main() == 0
    assert events["pdf"] and not events["notepad"]


def test_mode_text(monkeypatch, wired):
    events, _ = wired
    monkeypatch.setattr(sys, "argv", ["open_case.py", "452", "--mode", "text", "--collection", "lab"])
    assert oc.main() == 0
    assert events["notepad"] and not events["pdf"]


def test_mode_both(monkeypatch, wired):
    events, _ = wired
    monkeypatch.setattr(sys, "argv", ["open_case.py", "452", "--mode", "both", "--collection", "lab"])
    assert oc.main() == 0
    assert events["pdf"] and events["notepad"]


def test_mode_auto_success_no_notepad(monkeypatch, wired):
    events, _ = wired
    monkeypatch.setattr(sys, "argv", ["open_case.py", "452", "--mode", "auto", "--collection", "lab"])
    assert oc.main() == 0
    assert events["pdf"] and not events["notepad"]


def test_mode_auto_fallback_on_launch_failure(monkeypatch, wired):
    events, pdf = wired
    monkeypatch.setattr(oc, "launch_pdf", lambda p, viewer=None: {
        "status": "launch_failed", "mechanism": "os.startfile", "error": "OSError: boom", "path": str(p)})
    monkeypatch.setattr(sys, "argv", ["open_case.py", "452", "--mode", "auto", "--collection", "lab"])
    # launch failed but text fallback succeeds -> overall not a hard failure
    assert oc.main() == 0
    assert events["notepad"]


def test_mode_auto_fallback_text_flag(monkeypatch, wired):
    events, _ = wired
    monkeypatch.setattr(sys, "argv", ["open_case.py", "452", "--mode", "auto", "--fallback-text", "--collection", "lab"])
    assert oc.main() == 0
    assert events["pdf"] and events["notepad"]


def test_unresolvable_case_returns_nonzero(monkeypatch):
    def boom(args):
        raise ValueError("Case not found: 999")

    monkeypatch.setattr(oc, "_load_case", boom)
    monkeypatch.setattr(sys, "argv", ["open_case.py", "999", "--collection", "lab"])
    assert oc.main() == 2


def test_pdf_missing_and_no_text_returns_nonzero(monkeypatch, tmp_path):
    paths = FakePaths("lab", tmp_path / "du")
    row = pd.Series({"case_id": "1_x", "case_number": 1, "title_clean": "t"})  # no text fields
    monkeypatch.setattr(oc, "_load_case", lambda args: (paths, row, None))
    monkeypatch.setattr(sys, "argv", ["open_case.py", "1", "--mode", "both", "--collection", "lab"])
    assert oc.main() == 1


def test_diagnose_mode(monkeypatch, wired):
    events, _ = wired
    monkeypatch.setattr(oc, "pdf_association_info", lambda: {
        "platform": "Windows", "pdf_progid": "MSEdgePDF", "viewers": {"edge": "x", "acrobat": None}})
    monkeypatch.setattr(sys, "argv", ["open_case.py", "452", "--diagnose", "--collection", "lab"])
    assert oc.main() == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
