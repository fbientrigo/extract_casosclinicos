from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return data


def get_chapters(config: dict[str, Any]) -> list[dict[str, Any]]:
    chapters = config.get("chapters", [])
    if not isinstance(chapters, list):
        raise ValueError("'chapters' must be a list.")
    for item in chapters:
        if not isinstance(item, dict):
            raise ValueError("Each chapter entry must be an object.")
        if "chapter_id" not in item:
            raise ValueError("Each chapter entry must include chapter_id.")
        if "start_page" not in item or "end_page" not in item:
            raise ValueError("Each chapter entry must include start_page and end_page.")
    return chapters

