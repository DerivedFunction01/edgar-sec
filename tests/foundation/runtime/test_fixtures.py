from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.fixtures import (
    FIXTURE_MANIFEST_NAME,
    FIXTURE_DATABASE_NAME,
    FixtureManifestEnvelope,
    FixtureManifestError,
    fixture_paths,
)
from edgar_sec.foundation.runtime.paths import validate_path_component


def test_fixture_paths_are_dataset_scoped(tmp_path: Path) -> None:
    paths = fixture_paths(tmp_path, "document_storage", "fixture-1")

    assert paths.root == tmp_path / "document_storage" / "fixtures" / "fixture-1"
    assert paths.manifest_path == paths.root / FIXTURE_MANIFEST_NAME
    assert paths.storage_path == paths.root / FIXTURE_DATABASE_NAME


@pytest.mark.parametrize(
    ("dataset", "fixture_id"),
    [
        ("../outside", "fixture-1"),
        ("document_storage", "../outside"),
    ],
)
def test_fixture_paths_reject_escaping_components(
    tmp_path: Path, dataset: str, fixture_id: str
) -> None:
    with pytest.raises(ValueError):
        fixture_paths(tmp_path, dataset, fixture_id)


def test_path_component_validation_is_owned_by_foundation_paths() -> None:
    assert validate_path_component("fixture-1", "fixture_id") == "fixture-1"


def test_fixture_manifest_envelope_round_trips_pipeline_details() -> None:
    envelope = FixtureManifestEnvelope(
        fixture_kind="document_inventory.index_pages",
        fixture_id="fixture-1",
        storage_format="sqlite",
        storage_path=FIXTURE_DATABASE_NAME,
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


@pytest.mark.parametrize("manifest_version", [True, 1.0])
def test_fixture_manifest_rejects_non_integer_version(
    manifest_version: bool | float,
) -> None:
    with pytest.raises(FixtureManifestError, match="must be an integer"):
        FixtureManifestEnvelope.from_mapping(
            {
                "fixture_kind": "document_storage.raw_payload",
                "manifest_version": manifest_version,
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
