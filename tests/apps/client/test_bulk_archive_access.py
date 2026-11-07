"""Facade access to stored bulk archives: reference and member reads."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths

SOURCE_ID = "submissions_bulk"
SOURCE_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"


def _stored_archive(tmp_path: Path) -> BulkArchiveStore:
    metadata = resolve_metadata_paths(tmp_path)
    store = BulkArchiveStore(metadata.bulk_archives_root)
    zip_path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("CIK0000000020.json", b'{"name": "A"}')
        archive.writestr("CIK0000001761.json", b'{"name": "B"}')
    store.put_file(SOURCE_ID, zip_path, source_url=SOURCE_URL)
    return store


def test_bulk_archive_returns_the_stored_reference(tmp_path: Path) -> None:
    _stored_archive(tmp_path)
    reference = Edgar(artifacts_root=tmp_path).bulk_archive(SOURCE_ID)
    assert reference is not None
    assert reference.source_id == SOURCE_ID
    assert reference.path.is_file()
    assert reference.member_index_path.is_file()
    assert reference.manifest.source_url == SOURCE_URL
    assert reference.manifest.member_count == 2


def test_bulk_archive_member_reads_through_the_store(tmp_path: Path) -> None:
    _stored_archive(tmp_path)
    edgar = Edgar(artifacts_root=tmp_path)
    assert (
        edgar.bulk_archive_member(SOURCE_ID, "CIK0000000020.json") == b'{"name": "A"}'
    )
    with pytest.raises(ValueError, match="is not in archive"):
        edgar.bulk_archive_member(SOURCE_ID, "CIK9999999999.json")


def test_unstored_source_is_honest_absence(tmp_path: Path) -> None:
    edgar = Edgar(artifacts_root=tmp_path)
    assert edgar.bulk_archive(SOURCE_ID) is None
    assert edgar.bulk_archive_member(SOURCE_ID, "CIK0000000020.json") is None


def test_bulk_archive_opens_a_pinned_digest(tmp_path: Path) -> None:
    store = _stored_archive(tmp_path)
    stored = store.open(SOURCE_ID)
    assert stored is not None
    edgar = Edgar(artifacts_root=tmp_path)
    assert edgar.bulk_archive(SOURCE_ID, stored.sha256) == stored
    assert edgar.bulk_archive(SOURCE_ID, "0" * 64) is None
