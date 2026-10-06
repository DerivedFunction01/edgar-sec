from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.fixtures import (
    FIXTURE_MANIFEST_NAME,
    FixtureManifestEnvelope,
    FixtureManifestError,
    fixture_paths,
)


def test_fixture_paths_are_dataset_scoped(tmp_path: Path) -> None:
    paths = fixture_paths(tmp_path, "document_storage", "fixture-1", "fixture.sqlite")

    assert paths.root == tmp_path / "document_storage" / "fixtures" / "fixture-1"
    assert paths.manifest_path == paths.root / FIXTURE_MANIFEST_NAME
    assert paths.storage_path == paths.root / "fixture.sqlite"


@pytest.mark.parametrize(
    ("dataset", "fixture_id", "filename"),
    [
        ("../outside", "fixture-1", "data.sqlite"),
        ("document_storage", "../outside", "data.sqlite"),
        ("document_storage", "fixture-1", "../outside.sqlite"),
        ("document_storage", "fixture-1", "data/file.sqlite"),
    ],
)
def test_fixture_paths_reject_escaping_components(
    tmp_path: Path, dataset: str, fixture_id: str, filename: str
) -> None:
    with pytest.raises(ValueError):
        fixture_paths(tmp_path, dataset, fixture_id, filename)


def test_fixture_manifest_envelope_round_trips_pipeline_details() -> None:
    envelope = FixtureManifestEnvelope(
        fixture_kind="document_inventory.index_pages",
        fixture_id="fixture-1",
        storage_format="sqlite",
        storage_path="index_fixtures.sqlite",
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-02T00:00:00+00:00",
        details={"store_schema_version": 2, "capture_state": "complete"},
    )

    decoded = FixtureManifestEnvelope.from_mapping(envelope.to_mapping())
    assert decoded == envelope


def test_fixture_manifest_rejects_unsupported_version() -> None:
    with pytest.raises(FixtureManifestError, match="unsupported"):
        FixtureManifestEnvelope.from_mapping(
            {
                "fixture_kind": "document_storage.raw_payload",
                "manifest_version": 7,
                "fixture_id": "fixture-1",
                "storage": {"format": "sqlite", "path": "fixture.sqlite"},
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "details": {},
            }
        )


def test_fixture_manifest_rejects_unsafe_storage_path() -> None:
    with pytest.raises(FixtureManifestError):
        FixtureManifestEnvelope.from_mapping(
            {
                "fixture_kind": "document_storage.raw_payload",
                "manifest_version": 1,
                "fixture_id": "fixture-1",
                "storage": {"format": "sqlite", "path": "../fixture.sqlite"},
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "details": {},
            }
        )
