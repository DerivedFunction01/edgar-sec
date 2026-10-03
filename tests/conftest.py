"""Fixtures needed by more than one test package; the rest live in their package."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support import catalog_fixture_path

SAMPLE_SUBMISSION_METADATA = "sample_submission_metadata.parquet"


@pytest.fixture
def sample_source() -> Path:
    """Consumed by the catalog pipeline and the company-family engine tests."""
    return catalog_fixture_path(SAMPLE_SUBMISSION_METADATA)
