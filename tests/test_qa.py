from __future__ import annotations

import json
from pathlib import Path

from scanbook.qa import run_qa


def test_run_qa_outputs_reports(tmp_path: Path) -> None:
    src = tmp_path / "ocr.jsonl"
    src.write_text(
        "\n".join(
            [
                json.dumps({"page_num": 1, "text": "Header\nlong enough text body\nFooter", "extractor": "x"}),
                json.dumps({"page_num": 2, "text": "Header\nshort\nFooter", "extractor": "x"}),
                json.dumps({"page_num": 3, "text": "", "extractor": "x"}),
                json.dumps({"page_num": 4, "text": "Header\nanother text body\nFooter", "extractor": "x"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    report_dir = tmp_path / "reports"
    summary = run_qa(input_jsonl=src, report_dir=report_dir, low_text_threshold=20)

    assert summary["total_pages"] == 4
    assert summary["empty_pages"] == [3]
    assert 2 in summary["suspicious_low_text_pages"]
    assert (report_dir / "qa_summary.json").exists()
    assert (report_dir / "qa_summary.md").exists()
