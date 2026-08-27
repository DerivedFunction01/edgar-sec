"""Test bootstrap: make the non-identifier phase package importable and
register the repository root on sys.path."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def imp(name: str):
    return importlib.import_module(name)
