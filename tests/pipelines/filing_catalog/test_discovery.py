"""Unit tests for manifest-only discovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.pipelines.filing_catalog.catalog_job import materialize
from edgar_sec.pipelines.filing_catalog.discovery import (
    current_catalog_id,
    discover_catalogs,
    discover_plans,
    resolve_catalog_manifest,
    status,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    PLAN_FILE_NAME,
    SNAPSHOT_MANIFEST_NAME,
    resolve_filing_catalog_paths,
    safe_identifier,
)
from edgar_sec.pipelines.filing_catalog.planner import plan


@pytest.fixture
def published(tmp_path: Path, sample_source: Path) -> tuple[Path, str]:
    root = tmp_path / "art"
    manifest = materialize(sample_source, root)
    plan(str(manifest["catalog_id"]), root, forms=("10-K",))
    return root, str(manifest["catalog_id"])


def _paths(root: Path):  # type: ignore[no-untyped-def]
    return resolve_filing_catalog_paths(root)


# --- empty state ----------------------------------------------------------


def test_discovery_on_an_empty_tree(tmp_path: Path) -> None:
    assert discover_catalogs(_paths(tmp_path)) == []
    assert discover_plans(_paths(tmp_path)) == []
    summary = status(_paths(tmp_path))
    assert summary["catalog_count"] == 0
    assert summary["plan_count"] == 0
    assert summary["current_catalog_id"] is None


# --- catalogs -------------------------------------------------------------


def test_discover_catalogs_reports_published_state(published: tuple[Path, str]) -> None:
    root, catalog_id = published
    found = discover_catalogs(_paths(root))
    assert len(found) == 1
    entry = found[0]
    assert entry["catalog_id"] == catalog_id
    assert entry["profile_row_count"] == 6
    assert entry["target_row_count"] == 13
    assert entry["part_count"] == 1
    assert sum(entry["form_counts"].values()) == 13


def test_discovery_ignores_the_current_pointer_directory(
    published: tuple[Path, str],
) -> None:
    root, _ = published
    pointer_dir = _paths(root).snapshots_root / "current"
    pointer_dir.mkdir(parents=True, exist_ok=True)
    assert len(discover_catalogs(_paths(root))) == 1


def test_a_damaged_manifest_is_skipped_not_fatal(published: tuple[Path, str]) -> None:
    root, catalog_id = published
    broken = _paths(root).snapshots_root / "aaaaaaaaaaaa"
    broken.mkdir()
    (broken / SNAPSHOT_MANIFEST_NAME).write_text("{ truncated", encoding="utf-8")
    found = discover_catalogs(_paths(root))
    assert [c["catalog_id"] for c in found] == [catalog_id]


def test_resolve_catalog_manifest_by_id(published: tuple[Path, str]) -> None:
    root, catalog_id = published
    manifest = resolve_catalog_manifest(_paths(root), catalog_id)
    assert manifest is not None
    assert manifest["manifest_kind"] == "filing_catalog_snapshot"


def test_resolve_current_requires_a_pointer(tmp_path: Path) -> None:
    assert resolve_catalog_manifest(_paths(tmp_path), "current") is None


def test_resolve_manifest_rejects_an_unsafe_identifier(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe identifier"):
        resolve_catalog_manifest(_paths(tmp_path), "../../etc")


def test_safe_identifier_allows_expected_shapes() -> None:
    assert safe_identifier("a3614dc68ad7603adbc95720") == "a3614dc68ad7603adbc95720"
    for bad in ("", "../x", "a/b", "a b", "a;b"):
        with pytest.raises(ValueError, match="unsafe identifier"):
            safe_identifier(bad)


# --- plans ----------------------------------------------------------------


def test_discover_plans_reports_published_state(published: tuple[Path, str]) -> None:
    root, catalog_id = published
    found = discover_plans(_paths(root))
    assert len(found) == 1
    entry = found[0]
    assert entry["catalog_id"] == catalog_id
    assert entry["forms"] == ["10-K"]
    assert entry["amendment"] == "both"
    assert entry["selected_rows"] == 4


def test_a_damaged_plan_is_skipped_not_fatal(published: tuple[Path, str]) -> None:
    root, _ = published
    broken = _paths(root).plans_root / "broken"
    broken.mkdir()
    (broken / PLAN_FILE_NAME).write_text("not json", encoding="utf-8")
    assert len(discover_plans(_paths(root))) == 1


# --- status ---------------------------------------------------------------


def test_status_aggregates_without_reading_parquet(published: tuple[Path, str]) -> None:
    root, _ = published
    summary = status(_paths(root))
    assert summary["catalog_count"] == 1
    assert summary["plan_count"] == 1
    assert summary["total_planned_rows"] == 4
    assert summary["artifacts_root"] == str(root)


def test_status_does_not_open_any_parquet(
    published: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The menu loop calls status constantly; it must stay manifest-only."""
    import pyarrow.parquet as pq

    root, _ = published
    opened: list[str] = []
    original = pq.read_table

    def tracking(path: object, *args: object, **kwargs: object) -> object:
        opened.append(str(path))
        return original(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pq, "read_table", tracking)
    status(_paths(root))
    assert opened == []


def test_current_pointer_is_read_when_durable(
    tmp_path: Path, sample_source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGAR_ARTIFACTS_DIR", str(tmp_path / "durable"))
    manifest = materialize(sample_source)
    paths = resolve_filing_catalog_paths()
    assert current_catalog_id(paths) == manifest["catalog_id"]
    assert resolve_catalog_manifest(paths, "current") is not None


def test_pointer_contents_are_authoritative(published: tuple[Path, str]) -> None:
    root, catalog_id = published
    paths = _paths(root)
    paths.current_pointer.parent.mkdir(parents=True, exist_ok=True)
    paths.current_pointer.write_text(
        json.dumps({"catalog_id": catalog_id}), encoding="utf-8"
    )
    assert current_catalog_id(paths) == catalog_id
