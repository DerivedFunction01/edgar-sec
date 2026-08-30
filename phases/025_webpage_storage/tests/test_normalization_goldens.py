"""Cross-era DeepNormalizer golden tests for reviewed filing segments."""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from defs.runtime.paths import resolve_paths
from defs.testing.goldens import compare_golden

forms_base = importlib.import_module("phases.025_webpage_storage.processors.forms.base")
normalizer_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.normalizer"
)
PreprocessedDocument = forms_base.PreprocessedDocument
DeepNormalizer = normalizer_mod.DeepNormalizer

FIXTURES = Path(__file__).parent / "fixtures"


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


@pytest.mark.parametrize(
    "name",
    [
        "apple_2025_segment",
        "jpmorgan_2025_segment",
        "jnj_2025_segment",
        "berry_2008_segment",
        "kellogg_2003_segment",
    ],
)
def test_normalization_segment_golden(name: str) -> None:
    input_path = FIXTURES / "archetypes" / f"{name}.htm"
    expected_path = FIXTURES / "normalization" / f"{name}.expected"
    actual = DeepNormalizer().normalize(
        PreprocessedDocument(
            raw_text=input_path.read_text(encoding="utf-8"),
            cleaned_text=input_path.read_text(encoding="utf-8"),
            word_count=100,
            has_html_tags=True,
            detected_encoding="utf-8",
        )
    )
    report_root = (
        resolve_paths().test_run_root(
            "webpage_storage", "normalization-goldens", _run_id()
        )
        / name
    )
    assert compare_golden(
        actual,
        expected_path,
        report_root,
        name,
        {"input": str(input_path), "expected": str(expected_path)},
        update=os.environ.get("UPDATE_GOLDENS") == "1",
    )
