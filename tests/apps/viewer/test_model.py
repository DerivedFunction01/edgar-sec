"""Unit tests for apps.viewer.model."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.apps.viewer.model import (
    ArtifactSummary,
    DatasetError,
    artifact_id,
    artifact_path,
    artifact_table,
    compute_revision,
    compute_union_revision,
    decode_artifact_id,
    file_size,
    manifest_revision,
    mtime_iso,
    newest_mtime,
    summary_to_dict,
    walk_files,
)


def _summary(
    relative_path: str = "a/b.parquet", revision: str = "1:2"
) -> ArtifactSummary:
    return ArtifactSummary(
        id=artifact_id(relative_path),
        relative_path=relative_path,
        phase="metadata",
        run_id=None,
        kind="metadata_snapshot",
        format="parquet",
        size_bytes=10,
        mtime=None,
        revision=revision,
    )


def test_artifact_id_round_trips() -> None:
    assert decode_artifact_id(artifact_id("metadata/snapshots/abc")) == (
        "metadata/snapshots/abc",
        None,
    )


def test_artifact_id_carries_a_table_name() -> None:
    value = artifact_id("payload/store.db", "records")
    assert decode_artifact_id(value) == ("payload/store.db", "records")
    assert artifact_table(value) == "records"


def test_artifact_id_is_url_safe() -> None:
    value = artifact_id("metadata/snapshots/a b/c?.parquet")
    assert " " not in value and "?" not in value and "/" not in value


def test_artifact_path_resolves_inside_the_root(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b.parquet"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    assert artifact_path(artifact_id("a/b.parquet"), tmp_path) == target.resolve()


@pytest.mark.parametrize(
    "escape",
    ["../outside.parquet", "a/../../outside.parquet", "/etc/passwd"],
)
def test_artifact_path_refuses_to_escape_the_root(tmp_path: Path, escape: str) -> None:
    with pytest.raises(DatasetError, match="escapes"):
        artifact_path(artifact_id(escape), tmp_path)


def test_decode_refuses_garbage() -> None:
    with pytest.raises(DatasetError, match="invalid dataset id"):
        decode_artifact_id("!!! not base64 !!!")


def test_artifact_table_returns_none_for_a_plain_id() -> None:
    assert artifact_table(artifact_id("a/b.parquet")) is None


def test_manifest_revision_is_content_addressed(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text('{"a":1}', encoding="utf-8")
    first = manifest_revision(manifest)
    assert first == manifest_revision(manifest)
    manifest.write_text('{"a":2}', encoding="utf-8")
    assert manifest_revision(manifest) != first


def test_compute_revision_tracks_size_and_mtime() -> None:
    assert compute_revision(10, 20) == "10:20"


def test_union_revision_changes_when_a_file_is_added() -> None:
    before = compute_union_revision([_summary("c1", "1:1"), _summary("c2", "1:2")])
    after = compute_union_revision(
        [_summary("c1", "1:1"), _summary("c2", "1:2"), _summary("c3", "1:3")]
    )
    assert before != after


def test_union_revision_is_order_independent() -> None:
    items = [_summary("c1", "1:1"), _summary("c2", "1:2")]
    assert compute_union_revision(items) == compute_union_revision(
        list(reversed(items))
    )


def test_union_revision_changes_when_a_file_is_rewritten() -> None:
    before = compute_union_revision([_summary("c1", "1:1")])
    after = compute_union_revision([_summary("c1", "9:9")])
    assert before != after


def test_mtime_and_size_tolerate_a_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.parquet"
    assert mtime_iso(missing) is None
    assert file_size(missing) == 0
    assert newest_mtime([missing]) is None


def test_walk_files_skips_dot_directories(tmp_path: Path) -> None:
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "a.parquet").write_text("x", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "b.parquet").write_text("x", encoding="utf-8")
    (tmp_path / ".dotfile").write_text("x", encoding="utf-8")
    names = sorted(path.name for path in walk_files(tmp_path))
    assert names == ["a.parquet"]


def test_summary_to_dict_keeps_the_wire_field_names() -> None:
    """The compiled browser bundle reads these keys directly."""
    assert set(summary_to_dict(_summary())) == {
        "id",
        "relative_path",
        "phase",
        "run_id",
        "kind",
        "format",
        "size_bytes",
        "mtime",
        "revision",
        "source_paths",
        "table",
    }
