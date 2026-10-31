"""Content-addressed family-index publication and refusal behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.domain.taxonomy.family_vocab import rule_fingerprint_payload
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from edgar_sec.pipelines.cohort.sources import resolve_active_source
from edgar_sec.pipelines.cohort.family_index import (
    _family_index_id,
    publish_family_index,
)
from tests.support import published_universe


def _published_catalog(tmp_path: Path) -> tuple[CohortPaths, CohortCatalog]:
    published_universe(tmp_path)
    paths = CohortPaths(tmp_path)
    return paths, CohortCatalog(paths)


def test_publish_registers_and_reuses_an_intact_family_index(tmp_path: Path) -> None:
    paths, catalog = _published_catalog(tmp_path)

    artifact, stats = publish_family_index(catalog=catalog, paths=paths)
    repeated, repeated_stats = publish_family_index(catalog=catalog, paths=paths)

    assert artifact.record == repeated.record
    assert artifact.dataset_path == paths.family_index_file(
        artifact.record.family_index_id
    )
    assert file_sha256(artifact.dataset_path) == artifact.record.dataset_sha256
    assert stats == repeated_stats
    assert stats.registrants > 0
    assert catalog.get_active_family_index(artifact.record.universe_cohort_id) == (
        artifact.record
    )


def test_publish_verifies_universe_digest_before_reading(tmp_path: Path) -> None:
    paths, catalog = _published_catalog(tmp_path)
    source = resolve_active_source("cik_lookup", catalog=catalog)
    assert source is not None
    dataset = paths.resolve_relative_path(source.dataset_path)
    dataset.write_bytes(b"corrupt")

    with pytest.raises(ValueError, match="dataset digest"):
        publish_family_index(catalog=catalog, paths=paths)


def test_orphan_family_index_directory_is_never_overwritten(tmp_path: Path) -> None:
    paths, catalog = _published_catalog(tmp_path)
    source = resolve_active_source("cik_lookup", catalog=catalog)
    assert source is not None
    fingerprint = canonical_hash(rule_fingerprint_payload())
    index_id = _family_index_id(source.roster_id, source.dataset_sha256, fingerprint)
    orphan = paths.family_index_dir(index_id)
    orphan.mkdir(parents=True)

    with pytest.raises(FileExistsError):
        publish_family_index(catalog=catalog, paths=paths)

    assert not paths.family_index_file(index_id).exists()


def test_corrupt_active_artifact_is_not_rebuilt(tmp_path: Path) -> None:
    paths, catalog = _published_catalog(tmp_path)
    artifact, _stats = publish_family_index(catalog=catalog, paths=paths)
    artifact.dataset_path.write_bytes(b"corrupt")

    with pytest.raises(ValueError, match="missing or corrupt"):
        publish_family_index(catalog=catalog, paths=paths)
