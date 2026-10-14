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
def no_production_artifact_writes() -> Iterator[None]:
    """Fail session if tests write to this repository's own artifacts tree."""
    guarded = ("cohorts", "cache", "document_planning")
    before = {
        sub: (
            {p.name for p in (DEFAULT_ARTIFACTS_ROOT / sub).iterdir()}
            if (DEFAULT_ARTIFACTS_ROOT / sub).is_dir()
            else set()
        )
        for sub in guarded
    }
    yield
    for sub in guarded:
        root = DEFAULT_ARTIFACTS_ROOT / sub
        after = {p.name for p in root.iterdir()} if root.is_dir() else set()
        leaked = sorted(after - before[sub])
        assert not leaked, (
            f"tests wrote production artifacts under {root}: {leaked}. "
            "Pass tmp_path as the artifacts_root when running operations in tests."
        )
