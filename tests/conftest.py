from __future__ import annotations

import importlib.util

import pytest


@pytest.fixture
def has_pikepdf() -> bool:
    return importlib.util.find_spec("pikepdf") is not None

