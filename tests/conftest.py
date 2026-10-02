"""Fixtures shared across the whole test tree.

Only fixtures needed by more than one package live here. Anything a single test
package uses belongs in that package's own ``conftest.py``; see AGENTS.md §6.3.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support import catalog_fixture_path

SAMPLE_SUBMISSION_METADATA = "sample_submission_metadata.parquet"


@pytest.fixture
def sample_source() -> Path:
    """Path to the committed Phase 1 dataset the filing catalog consumes.

    Consumed by the catalog pipeline tests and by the company-family engine
    tests, which read the same materialized profiles, so it lives here rather
    than in either package.
    """
    return catalog_fixture_path(SAMPLE_SUBMISSION_METADATA)
