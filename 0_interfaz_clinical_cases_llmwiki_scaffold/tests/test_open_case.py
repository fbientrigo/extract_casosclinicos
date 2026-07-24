#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Focused tests for the unified case opener helpers.

These use synthetic rows and temporary files, and mock os.startfile /
subprocess, so they run without duckdb, the book PDFs, or a real desktop.
Run with the working interpreter, e.g.:

    python -m pytest tests/test_open_case.py -q
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

import llmwiki_common as lc  # noqa: E402


@dataclass(frozen=True)
class FakePaths:
    collection_id: str
    data_updated_dir: Path


def make_row(**overrides):
    base = {
        "case_id": "452_efectos_adversos",
        "case_number": 452,
        "title_clean": "efectos adversos de la transfusion",
        "clean_text": "Texto clinico completo del caso 452.",
        "llmwiki_text": "# Markdown del caso",
        "text_preview": "Vista previa truncada...",
    }
    base.update(overrides)
    return pd.Series(base)


# --------------------------------------------------------------------------
# Text source precedence
# --------------------------------------------------------------------------

def test_text_precedence_prefers_clean_text():
    sel = lc.select_case_text(make_row())
    assert sel["source_field"] == "clean_text"
    assert sel["truncated"] is False
    assert "completo" in sel["text"]


def test_text_precedence_falls_back_to_llmwiki_then_preview():
    sel = lc.select_case_text(make_row(clean_text="   "))
    assert sel["source_field"] == "llmwiki_text"

    sel2 = lc.select_case_text(make_row(clean_text="", llmwiki_text=None))
    assert sel2["source_field"] == "text_preview"
    assert sel2["truncated"] is True


def test_text_precedence_none_available():
    sel = lc.select_case_text(make_row(clean_text="", llmwiki_text="", text_preview=""))
    assert sel["text"] == ""
    assert sel["source_field"] is None


# --------------------------------------------------------------------------
# Transcript writing: UTF-8, provenance header, stays under data_updated/
# --------------------------------------------------------------------------

def test_write_transcript_utf8_and_provenance(tmp_path):
    paths = FakePaths(collection_id="lab_ivan_palomo", data_updated_dir=tmp_path / "data_updated" / "lab")
    row = make_row(clean_text="Hemoglobina 8.0 g/dL — anemia ferropénica.")
    sel = lc.select_case_text(row)
    out = lc.write_case_transcript(paths, row, sel, pdf_path=Path("book/x/452.pdf"))

    assert out.exists()
    # Must live under data_updated/
    assert "data_updated" in out.parts
    assert out.parts[-2] == "opened_cases"
    content = out.read_text(encoding="utf-8")
    assert "collection : lab_ivan_palomo" in content
    assert "case_number: 452" in content
    assert "case_id    : 452_efectos_adversos" in content
    assert "source     : clean_text" in content
    assert "Hemoglobina 8.0 g/dL" in content
    assert "anemia ferropénica" in content  # UTF-8 round-trip


def test_write_transcript_marks_truncated(tmp_path):
    paths = FakePaths(collection_id="c", data_updated_dir=tmp_path / "du")
    row = make_row(clean_text="", llmwiki_text="")
    sel = lc.select_case_text(row)
    out = lc.write_case_transcript(paths, row, sel)
    assert "TRUNCADO" in out.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# launch_pdf: missing / requested / failed
# --------------------------------------------------------------------------

def test_launch_pdf_missing(tmp_path):
    res = lc.launch_pdf(tmp_path / "nope.pdf")
    assert res["status"] == "missing"
    assert res["mechanism"] is None


def test_launch_pdf_requested_windows(tmp_path, monkeypatch):
    pdf = tmp_path / "case.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(lc.platform, "system", lambda: "Windows")
    calls = {}
    # os.startfile only exists on Windows; inject a stub.
    monkeypatch.setattr(lc.os, "startfile", lambda p: calls.setdefault("path", p), raising=False)
    res = lc.launch_pdf(pdf)
    assert res["status"] == "launch_requested"
    assert res["mechanism"] == "os.startfile"
    assert calls["path"].endswith("case.pdf")


def test_launch_pdf_failed_when_startfile_raises(tmp_path, monkeypatch):
    pdf = tmp_path / "case.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(lc.platform, "system", lambda: "Windows")

    def boom(_):
        raise OSError("No application is associated")

    monkeypatch.setattr(lc.os, "startfile", boom, raising=False)
    res = lc.launch_pdf(pdf)
    assert res["status"] == "launch_failed"
    assert "OSError" in res["error"]


def test_launch_pdf_explicit_viewer(tmp_path, monkeypatch):
    pdf = tmp_path / "case.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    viewer = tmp_path / "msedge.exe"
    viewer.write_text("stub")
    recorded = {}
    monkeypatch.setattr(lc.subprocess, "Popen", lambda argv, *a, **k: recorded.setdefault("argv", argv))
    res = lc.launch_pdf(pdf, viewer=viewer)
    assert res["status"] == "launch_requested"
    assert recorded["argv"][0] == str(viewer)


# --------------------------------------------------------------------------
# Notepad invocation: explicit subprocess, mocked
# --------------------------------------------------------------------------

def test_open_in_notepad_uses_notepad_exe(tmp_path, monkeypatch):
    txt = tmp_path / "case.txt"
    txt.write_text("hola", encoding="utf-8")
    monkeypatch.setattr(lc.platform, "system", lambda: "Windows")
    recorded = {}
    monkeypatch.setattr(lc.subprocess, "Popen", lambda argv, *a, **k: recorded.setdefault("argv", argv))
    res = lc.open_in_notepad(txt)
    assert res["status"] == "launch_requested"
    assert recorded["argv"][0] == "notepad.exe"
    assert recorded["argv"][1].endswith("case.txt")


def test_open_in_notepad_missing(tmp_path):
    res = lc.open_in_notepad(tmp_path / "gone.txt")
    assert res["status"] == "missing"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
