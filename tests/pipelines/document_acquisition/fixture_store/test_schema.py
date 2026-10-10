import json
import sqlite3

import pytest

from edgar_sec.foundation.runtime.fixtures import (
    FIXTURE_DATABASE_NAME,
    FixtureManifestEnvelope,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import (
    FIXTURE_KIND,
    SCHEMA_VERSION,
    open_fixture,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    initialize_fixture,
)


def test_initialize_writes_shared_manifest_and_schema(acquisition_paths) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_schema")
    envelope = FixtureManifestEnvelope.from_mapping(
        json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
    )

    assert envelope.fixture_kind == FIXTURE_KIND
    assert envelope.fixture_id == "fixture_schema"
    assert envelope.storage_format == "sqlite"
    assert envelope.storage_path == FIXTURE_DATABASE_NAME
    assert envelope.created_at == envelope.updated_at
    assert envelope.details == {"store_schema_version": SCHEMA_VERSION}
    with sqlite3.connect(fixture.storage_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
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
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(FixtureStoreError, match="unsupported.*schema version"):
        open_fixture(acquisition_paths, "fixture_invalid_schema", readonly=True)
    with pytest.raises(FixtureStoreError, match="already exists or is incomplete"):
        initialize_fixture(acquisition_paths, "fixture_invalid_schema")
