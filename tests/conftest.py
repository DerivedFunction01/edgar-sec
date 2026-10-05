"""Fixtures needed by more than one test package; the rest live in their package."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.settings.paths import DEFAULT_ARTIFACTS_ROOT
from tests.support import catalog_fixture_path

SAMPLE_SUBMISSION_METADATA = "sample_submission_metadata.parquet"


@pytest.fixture
def sample_source() -> Path:
    """Consumed by the catalog pipeline and the company-family engine tests."""
    return catalog_fixture_path(SAMPLE_SUBMISSION_METADATA)


@pytest.fixture(scope="session", autouse=True)
def no_production_cohort_writes() -> Iterator[None]:
    """Fail the session if a test adds a cohort to this repository's own tree."""
    root = DEFAULT_ARTIFACTS_ROOT / "metadata" / "cohorts"
    before = {path.name for path in root.iterdir()} if root.is_dir() else set()
    yield
    after = {path.name for path in root.iterdir()} if root.is_dir() else set()
    leaked = sorted(after - before)
    assert not leaked, (
        f"tests wrote production cohorts under {root}: {leaked}. "
        "Pass artifacts_root=tmp_path to the options that compile one."
    )
