from __future__ import annotations

from pathlib import Path

from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureOperationError,
    FixturePlanPin,
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    initialize_fixture,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths


def create_fixture(
    fixture_id: str, plan_pin: FixturePlanPin, *, paths: AcquisitionPaths
) -> Path:
    try:
        return initialize_fixture(paths, fixture_id, plan_pin).root
    except (FixtureStoreError, OSError, ValueError) as error:
        raise FixtureOperationError(str(error)) from error
