"""Family-index cache lifecycle: content identity, reuse, and refusal to trust a
damaged payload.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.pipelines.metadata_sync.family_index import (
    FamilyIndexArtifact,
    _reusable,
    build_family_index,
    family_index_id,
    published_universe_roster,
)
from edgar_sec.pipelines.metadata_sync.paths import MetadataPaths
from edgar_sec.pipelines.metadata_sync.roster import (
    ROSTER_FILE_NAME,
    write_roster_rows,
)

_ROWS = [
    ("0000019617", "JPMorgan Chase & Co"),
    (
        "0001319760",
        "JPMorgan Chase Commercial Mortgage Securities Corp Series 2005-LDP3",
    ),
    ("0001600001", "Wells Fargo & Co"),
    ("0001600002", "Wells Fargo Mortgage Backed Securities Trust 2005-1"),
    ("0001566139", "Honda Motor Co Ltd"),
]


@pytest.fixture
def roster(tmp_path: Path) -> tuple[Path, str]:
    dataset = tmp_path / "cohorts" / ROSTER_FILE_NAME
    dataset.parent.mkdir(parents=True)
    _roster, roster_id = write_roster_rows(_ROWS, dataset)
    return dataset, roster_id


def _artifact(tmp_path: Path, roster: tuple[Path, str]) -> FamilyIndexArtifact:
    dataset, roster_id = roster
    index_id = family_index_id(roster_id=roster_id, dataset_sha256=file_sha256(dataset))
    paths = MetadataPaths(artifacts_root=tmp_path / "artifacts")
    return build_family_index(
        dataset=dataset,
        roster_id=roster_id,
        dataset_sha256=file_sha256(dataset),
        output_path=paths.family_index_file(index_id),
        manifest_path=paths.family_index_manifest(index_id),
    )


def test_a_built_index_publishes_one_row_per_registrant(
    tmp_path: Path, roster: tuple[Path, str]
) -> None:
    artifact = _artifact(tmp_path, roster)
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT count(*), count(DISTINCT cik) FROM read_parquet('{artifact.assignment_path}')"
    ).fetchone()
    assert rows == (len(_ROWS), len(_ROWS))


def test_the_manifest_records_the_roster_and_the_rule_fingerprint(
    tmp_path: Path, roster: tuple[Path, str]
) -> None:
    artifact = _artifact(tmp_path, roster)
    recorded = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
    assert recorded["manifest_kind"] == "company_family_index"
    assert recorded["roster_id"] == roster[1]
    assert recorded["dataset_sha256"] == file_sha256(roster[0])
    assert recorded["assignment_sha256"] == file_sha256(artifact.assignment_path)
    assert recorded["registrants"] == len(_ROWS)
    assert recorded["rules_fingerprint"]


def test_no_staging_file_survives_a_build(
    tmp_path: Path, roster: tuple[Path, str]
) -> None:
    artifact = _artifact(tmp_path, roster)
    assert not list(artifact.assignment_path.parent.glob("*.staging"))


def test_the_identity_changes_with_the_roster_and_with_the_rules() -> None:
    base = family_index_id(roster_id="roster-a", dataset_sha256="sha-a")
    assert base == family_index_id(roster_id="roster-a", dataset_sha256="sha-a")
    assert base != family_index_id(roster_id="roster-b", dataset_sha256="sha-a")
    assert base != family_index_id(roster_id="roster-a", dataset_sha256="sha-b")


def test_a_matching_verified_artifact_is_reused(
    tmp_path: Path, roster: tuple[Path, str]
) -> None:
    """Reuse is what makes the index cheap enough to keep across every plan."""
    artifact = _artifact(tmp_path, roster)
    index_id = artifact.family_index_id
    assert _reusable(
        artifact.manifest_path,
        artifact.assignment_path,
        index_id,
        file_sha256(roster[0]),
    )


def test_a_damaged_payload_is_not_trusted_as_a_cache_hit(
    tmp_path: Path, roster: tuple[Path, str]
) -> None:
    """A truncated Parquet file would otherwise pass as a hit and yield empty joins."""
    artifact = _artifact(tmp_path, roster)
    index_id = artifact.family_index_id
    artifact.assignment_path.write_bytes(b"not parquet")
    assert not _reusable(
        artifact.manifest_path,
        artifact.assignment_path,
        index_id,
        file_sha256(roster[0]),
    )


def test_an_unreadable_manifest_is_not_a_cache_hit(
    tmp_path: Path, roster: tuple[Path, str]
) -> None:
    artifact = _artifact(tmp_path, roster)
    artifact.manifest_path.write_text("{ not json", encoding="utf-8")
    assert not _reusable(
        artifact.manifest_path,
        artifact.assignment_path,
        artifact.family_index_id,
        file_sha256(roster[0]),
    )


def test_ensure_refuses_when_the_universe_was_never_published(
    tmp_path: Path,
) -> None:
    paths = MetadataPaths(artifacts_root=tmp_path / "artifacts")
    with pytest.raises(FileNotFoundError, match="cik_lookup"):
        published_universe_roster(paths)
