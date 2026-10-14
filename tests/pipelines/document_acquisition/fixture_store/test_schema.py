import json
import sqlite3

import pytest

from edgar_sec.foundation.runtime.fixtures import (
    FIXTURE_DATABASE_NAME,
    FIXTURE_MANIFEST_VERSION,
    FixtureManifestEnvelope,
)
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import (
    FIXTURE_KIND,
    SCHEMA_VERSION,
    fixture_plan_pin,
    open_fixture,
)
from .fixture_helpers import initialize_test_fixture as initialize_fixture


def test_initialize_writes_shared_manifest_and_schema(acquisition_paths) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_schema")
    envelope = FixtureManifestEnvelope.from_mapping(
        json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
    )

    assert envelope.fixture_kind == FIXTURE_KIND
    assert envelope.manifest_version == FIXTURE_MANIFEST_VERSION == 1
    assert envelope.fixture_id == "fixture_schema"
    assert envelope.storage_format == "sqlite"
    assert envelope.storage_path == FIXTURE_DATABASE_NAME
    assert envelope.created_at == envelope.updated_at
    assert SCHEMA_VERSION == 2
    assert envelope.details == {
        "store_schema_version": 2,
        "target_plan_id": "plan_fixture_test",
        "target_plan_digest": "a" * 64,
        "target_plan_schema_version": 1,
    }
    with sqlite3.connect(fixture.storage_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    _, connection = open_fixture(acquisition_paths, "fixture_schema", readonly=True)
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()
    assert sorted(item.name for item in fixture.root.iterdir()) == [
        FIXTURE_DATABASE_NAME,
        "manifest.json",
    ]


def test_open_refuses_incompatible_schema_and_existing_fixture(
    acquisition_paths,
) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_invalid_schema")
    with sqlite3.connect(fixture.storage_path) as connection:
        connection.execute("PRAGMA user_version = 3")
    with pytest.raises(FixtureStoreError, match="unsupported.*schema version"):
        open_fixture(acquisition_paths, "fixture_invalid_schema", readonly=True)
    with pytest.raises(FixtureStoreError, match="already exists or is incomplete"):
        initialize_fixture(acquisition_paths, "fixture_invalid_schema")


def test_fixture_plan_pin_is_immutable_in_manifest_and_database(
    acquisition_paths,
) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_plan_pin")

    assert fixture_plan_pin(acquisition_paths, "fixture_plan_pin").target_plan_id == (
        "plan_fixture_test"
    )
    with sqlite3.connect(fixture.storage_path) as connection:
        with pytest.raises(
            sqlite3.IntegrityError, match="fixture metadata is immutable"
        ):
            connection.execute(
                "UPDATE fixture_meta SET value = ? WHERE key = ?",
                ("plan-other", "target_plan_id"),
            )


@pytest.mark.parametrize(
    ("manifest_version", "database_version", "message"),
    (
        (2, 1, "unsupported acquisition fixture schema version"),
        (1, 1, "invalid fixture manifest"),
        (4, 4, "invalid fixture manifest"),
        (2, 4, "unsupported acquisition fixture schema version"),
    ),
)
def test_open_rejects_version_mismatch_and_unknown_versions(
    acquisition_paths, manifest_version, database_version, message
) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_version_mismatch")
    manifest = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
    manifest["details"]["store_schema_version"] = manifest_version
    if manifest_version == 1:
        manifest["fixture_kind"] = "document_acquisition.source_responses"
    fixture.manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
    with sqlite3.connect(fixture.storage_path) as connection:
        connection.execute(f"PRAGMA user_version = {database_version}")

    with pytest.raises(FixtureStoreError, match=message):
        open_fixture(acquisition_paths, "fixture_version_mismatch", readonly=True)
