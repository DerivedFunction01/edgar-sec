"""The fixture source serves stored products by accession."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.pipelines.table_classification.fixture_store.source import (
    FixtureFilingSource,
)
from tests.pipelines.table_classification.fixture_store.test_capture_reader import (
    _capture,
)


def test_source_serves_primary_first_with_products(tmp_path: Path) -> None:
    _capture(tmp_path)
    source = FixtureFilingSource(tmp_path, "fx1")
    assert source.accessions() == ("0000000000-00-000000",)
    payloads = source.documents_for("0000000000-00-000000")
    assert len(payloads) == 1
    assert payloads[0].target_role == "primary"
    assert payloads[0].result.text
    assert payloads[0].stamps.normalize_version == "normalize-1"
    assert source.documents_for("9999999999-99-999999") == ()
