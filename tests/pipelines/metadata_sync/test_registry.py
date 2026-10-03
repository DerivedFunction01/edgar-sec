"""Curated-versus-source comparison and effective-input projection, over immutable
inputs only, so every assertion is a pure function of snapshot plus curated CSV.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.metadata_sync.manifest import compile_cik_cohort
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.registry import (
    EFFECTIVE_INPUT_MANIFEST_KIND,
    REGISTRY_MANIFEST_KIND,
    REGISTRY_SCHEMA,
    WORKLIST_SCHEMA,
    RegistryError,
    compare_sources,
    ensure_registry,
    load_registry_manifest,
    load_registry_roster,
    registry_id_for,
)
from edgar_sec.pipelines.metadata_sync.roster import write_roster
from edgar_sec.pipelines.metadata_sync.source_registry import (
    SOURCE_NAME,
    SOURCE_URL,
    SourceRegistryError,
    load_source_snapshot,
    refresh_company_tickers,
)
from tests.support import (
    FakeSession,
    build_test_http,
    fixture_ciks,
    fixture_path,
    roster_of,
)

TICKERS = {
    "0": {"cik_str": "37996", "ticker": "F", "title": "FORD MOTOR CO"},
    "1": {"cik_str": "20", "ticker": "KTC", "title": "K Tron International Inc"},
    "2": {"cik_str": "5555", "ticker": "NEW", "title": "NEWCO INC"},
}


@pytest.fixture()
def published_source(session: FakeSession, tmp_path: Path) -> tuple[Path, object]:
    """Refresh a source snapshot and return its manifest path."""
    session.register_bytes(SOURCE_URL, json.dumps(TICKERS).encode("utf-8"))
    metadata = resolve_metadata_paths(tmp_path)
    manifest = refresh_company_tickers(
        metadata_paths=metadata, client=build_test_http(session)
    )
    return metadata.source_manifest_file(SOURCE_NAME, manifest["snapshot_id"]), metadata


def _read(path: Path) -> list[dict]:
    return pq.read_table(path).to_pylist()


def test_registry_id_is_content_derived() -> None:
    assert registry_id_for("snap", "fp") == registry_id_for("snap", "fp")
    assert registry_id_for("snap", "fp") != registry_id_for("other", "fp")
    assert registry_id_for("snap", "fp") != registry_id_for("snap", "other")
    assert len(registry_id_for("snap", "fp")) == 32


def test_compare_writes_every_declared_artifact(published_source, tmp_path) -> None:
    manifest_path, metadata = published_source
    result = compare_sources(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_manifest_path=manifest_path,
        metadata_paths=metadata,
    )

    assert result["validation_status"] == "ok"
    assert result["source"] == SOURCE_NAME
    assert result["registry_id"] == registry_id_for(
        result["source_snapshot_id"], result["curated_input_fingerprint"]
    )
    assert set(result["artifact_sha256"]) == {
        "listing_observations",
        "registrant_registry",
        "new_ciks",
        "augmentation_worklist",
    }
    for dataset in (
        "listing_observations",
        "registrant_registry",
        "new_ciks",
        "augmentation_worklist",
    ):
        assert metadata.registry_dataset(result["registry_id"], dataset).is_file()
        sidecar = metadata.registry_dataset(result["registry_id"], dataset).with_name(
            metadata.registry_dataset(result["registry_id"], dataset).name
            + ".manifest.json"
        )
        published = json.loads(sidecar.read_text(encoding="utf-8"))
        assert published["manifest_kind"] == REGISTRY_MANIFEST_KIND
        assert published["registry_id"] == result["registry_id"]
        assert published["source_snapshot_id"] == result["source_snapshot_id"]
        assert published["schema_version"] == "1.0.0"
        assert published["row_count"] == len(
            _read(metadata.registry_dataset(result["registry_id"], dataset))
        )


def test_compare_derives_new_ciks_and_worklist(published_source) -> None:
    """The curated manifest covers four CIKs; the source adds one upstream."""
    manifest_path, metadata = published_source
    result = compare_sources(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_manifest_path=manifest_path,
        metadata_paths=metadata,
    )
    registry_id = result["registry_id"]
    curated = set(fixture_ciks("cik_sec_mini.csv"))

    registry_rows = _read(metadata.registry_dataset(registry_id, "registrant_registry"))
    assert [row["cik_padded"] for row in registry_rows] == sorted(
        curated | {"0000005555"}
    )
    assert result["new_cik_count"] == 1

    delta_rows = _read(metadata.registry_dataset(registry_id, "new_ciks"))
    assert [row["cik_padded"] for row in delta_rows] == ["0000005555"]
    assert delta_rows[0]["curated_membership"] is False
    assert delta_rows[0]["active_listing_membership"] is True
    assert delta_rows[0]["canonical_name"] == "NEWCO INC"
    assert delta_rows[0]["tickers"] == ["NEW"]
    assert delta_rows[0]["activity_class"] == "active_listing"
    assert delta_rows[0]["source_snapshot_ids"] == [result["source_snapshot_id"]]

    worklist = _read(metadata.registry_dataset(registry_id, "augmentation_worklist"))
    assert [row["cik_padded"] for row in worklist] == ["0000005555"]
    assert worklist[0]["work_reason"] == "active_source_only"
    assert worklist[0]["name"] == "NEWCO INC"
    assert worklist[0]["source_snapshot_id"] == result["source_snapshot_id"]


def test_compare_preserves_curated_only_ciks(published_source) -> None:
    manifest_path, metadata = published_source
    result = compare_sources(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_manifest_path=manifest_path,
        metadata_paths=metadata,
    )
    rows = {
        row["cik_padded"]: row
        for row in _read(
            metadata.registry_dataset(result["registry_id"], "registrant_registry")
        )
    }
    curated_only = rows["0000001985"]
    assert curated_only["curated_membership"] is True
    assert curated_only["active_listing_membership"] is False
    assert curated_only["activity_class"] == "curated_only"
    assert curated_only["source_snapshot_ids"] == []
    assert curated_only["refresh_cadence"] == "unknown"


def test_the_effective_roster_is_published_as_a_loadable_dataset(
    published_source,
) -> None:
    """Without the roster dataset, the datasets a comparison publishes are read by nothing."""
    manifest_path, metadata = published_source
    result = compare_sources(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_manifest_path=manifest_path,
        metadata_paths=metadata,
    )
    registry_id = result["registry_id"]
    roster = load_registry_roster(registry_id, metadata)
    assert roster.row_count == result["registry_row_count"]
    assert result["roster_id"] == roster.roster_id
    assert roster.name_map()["0000005555"] == "NEWCO INC"

    sidecar = metadata.effective_cik_roster(registry_id).with_name(
        "effective_ciks.parquet.manifest.json"
    )
    published = json.loads(sidecar.read_text(encoding="utf-8"))
    assert published["roster_id"] == roster.roster_id
    assert published["registry_id"] == registry_id
    assert published["row_count"] == roster.row_count


def test_the_roster_and_the_csv_describe_the_same_union(
    published_source,
) -> None:
    manifest_path, metadata = published_source
    result = compare_sources(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_manifest_path=manifest_path,
        metadata_paths=metadata,
    )
    roster = load_registry_roster(result["registry_id"], metadata)
    round_tripped = compile_cik_cohort(
        metadata.effective_input_file(result["registry_id"]),
        metadata_paths=metadata,
    )
    assert sorted(
        round_tripped.roster.range_ciks(0, round_tripped.row_count)
    ) == sorted(roster.range_ciks(0, roster.row_count))


def test_load_registry_roster_refuses_a_swapped_dataset(published_source) -> None:
    """A cohort replaced after publication must not drive a fetch."""
    manifest_path, metadata = published_source
    result = compare_sources(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_manifest_path=manifest_path,
        metadata_paths=metadata,
    )
    registry_id = result["registry_id"]
    write_roster(roster_of(("0000099999",)), metadata.effective_cik_roster(registry_id))
    with pytest.raises(RegistryError, match="digest does not match"):
        load_registry_roster(registry_id, metadata)


def test_load_registry_roster_reports_a_missing_manifest(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_registry_roster("deadbeef", resolve_metadata_paths(tmp_path))


def test_effective_csv_covers_the_union_and_is_usable_as_input(
    published_source, tmp_path
) -> None:
    manifest_path, metadata = published_source
    result = compare_sources(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_manifest_path=manifest_path,
        metadata_paths=metadata,
    )
    effective = metadata.effective_input_file(result["registry_id"])
    assert effective.is_file()
    lines = effective.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "cik,name"
    assert lines[1] == "0000000020,K Tron International Inc"
    assert "0000005555,NEWCO INC" in lines
    assert len(lines) == 1 + result["registry_row_count"]

    sidecar = effective.with_name(effective.name + ".manifest.json")
    published = json.loads(sidecar.read_text(encoding="utf-8"))
    assert published["manifest_kind"] == EFFECTIVE_INPUT_MANIFEST_KIND
    assert published["row_count"] == result["registry_row_count"]
    assert published["columns"] == ["cik", "name"]

    parsed = compile_cik_cohort(effective, metadata_paths=metadata)
    assert parsed.row_count == result["registry_row_count"]
    assert parsed.roster.range_ciks(0, parsed.row_count)[0] == "0000000020"
    names = parsed.roster.name_map()
    assert names["0000000020"] == "K Tron International Inc"
    assert names["0000005555"] == "NEWCO INC"


def test_compare_is_deterministic_for_unchanged_inputs(published_source) -> None:
    manifest_path, metadata = published_source
    kwargs = {
        "curated_input_path": fixture_path("cik_sec_mini.csv"),
        "source_manifest_path": manifest_path,
        "metadata_paths": metadata,
    }
    first = compare_sources(**kwargs)
    second = compare_sources(**kwargs)
    assert first == second
    registries = list((metadata.metadata_root / "registries").iterdir())
    assert len(registries) == 1


def test_comparing_against_a_different_curated_input_changes_identity(
    published_source, tmp_path
) -> None:
    manifest_path, metadata = published_source
    other = tmp_path / "other.csv"
    other.write_text("cik,name\n20,IBM\n", encoding="utf-8")

    first = compare_sources(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_manifest_path=manifest_path,
        metadata_paths=metadata,
    )
    second = compare_sources(
        curated_input_path=other,
        source_manifest_path=manifest_path,
        metadata_paths=metadata,
    )
    assert first["registry_id"] != second["registry_id"]
    assert second["registry_row_count"] == 3


def test_compare_performs_no_network_access(
    published_source, session: FakeSession
) -> None:
    manifest_path, metadata = published_source
    calls_after_refresh = len(session.calls)
    compare_sources(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_manifest_path=manifest_path,
        metadata_paths=metadata,
    )
    assert len(session.calls) == calls_after_refresh


def test_compare_rejects_a_tampered_source_snapshot(published_source) -> None:
    manifest_path, metadata = published_source
    published = json.loads(manifest_path.read_text(encoding="utf-8"))
    Path(published["raw_path"]).write_text("{}", encoding="utf-8")

    with pytest.raises(SourceRegistryError, match="hash does not match"):
        compare_sources(
            curated_input_path=fixture_path("cik_sec_mini.csv"),
            source_manifest_path=manifest_path,
            metadata_paths=metadata,
        )


def test_compare_reports_a_missing_source_manifest(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        compare_sources(
            curated_input_path=fixture_path("cik_sec_mini.csv"),
            source_manifest_path=tmp_path / "absent.json",
            metadata_paths=resolve_metadata_paths(tmp_path),
        )


def test_load_registry_manifest_verifies_the_digest(published_source) -> None:
    manifest_path, metadata = published_source
    result = compare_sources(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_manifest_path=manifest_path,
        metadata_paths=metadata,
    )
    assert load_registry_manifest(result["registry_id"], metadata)["row_count"] == 5

    metadata.effective_input_file(result["registry_id"]).write_text(
        "cik,name\n", encoding="utf-8"
    )
    with pytest.raises(RegistryError, match="digest does not match"):
        load_registry_manifest(result["registry_id"], metadata)


def test_load_registry_manifest_reports_a_missing_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_registry_manifest("deadbeef", resolve_metadata_paths(tmp_path))


def test_dataset_schemas_match_the_declared_contracts(published_source) -> None:
    manifest_path, metadata = published_source
    result = compare_sources(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_manifest_path=manifest_path,
        metadata_paths=metadata,
    )
    registry_id = result["registry_id"]
    for dataset in ("registrant_registry", "new_ciks"):
        assert pq.read_schema(metadata.registry_dataset(registry_id, dataset)).equals(
            REGISTRY_SCHEMA, check_metadata=False
        )
    assert pq.read_schema(
        metadata.registry_dataset(registry_id, "augmentation_worklist")
    ).equals(WORKLIST_SCHEMA, check_metadata=False)


def test_a_stale_manifest_is_detected_on_load(tmp_path) -> None:
    """A hand-edited effective-input manifest cannot masquerade as verified."""
    metadata = resolve_metadata_paths(tmp_path)
    registry_id = "abc123"
    effective = metadata.effective_input_file(registry_id)
    effective.parent.mkdir(parents=True)
    effective.write_text("cik,name\n", encoding="utf-8")
    atomic_write_json(
        effective.with_name("effective_cik_input.csv.manifest.json"),
        {
            "manifest_kind": EFFECTIVE_INPUT_MANIFEST_KIND,
            "registry_id": registry_id,
            "artifact_path": str(metadata.effective_input_file(registry_id)),
            "artifact_sha256": "0" * 64,
        },
        canonical=False,
    )
    with pytest.raises(RegistryError, match="digest does not match"):
        load_registry_manifest(registry_id, metadata)


# ------------------------------------------------------------- ensure_registry


def test_ensure_registry_projects_the_seed_against_the_source(
    published_source,
) -> None:
    """The curated CSV is a seed, so it cannot describe who files now."""
    manifest_path, metadata = published_source
    result = ensure_registry(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_snapshot_id=load_source_snapshot(manifest_path).manifest["snapshot_id"],
        metadata_paths=metadata,
    )
    roster = load_registry_roster(result["registry_id"], metadata)
    # The seed's four CIKs, plus NEWCO from the live listing.
    assert roster.range_ciks(0, roster.row_count) == (
        "0000000020",
        "0000001761",
        "0000001985",
        "0000005555",
        "0000037996",
    )
    assert result["reused"] is False


def test_ensure_registry_reuses_an_already_computed_projection(
    published_source,
) -> None:
    """An unnoticed re-comparison would republish a registry on every invocation."""
    manifest_path, metadata = published_source
    source_id = load_source_snapshot(manifest_path).manifest["snapshot_id"]
    first = ensure_registry(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_snapshot_id=source_id,
        metadata_paths=metadata,
    )
    second = ensure_registry(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_snapshot_id=source_id,
        metadata_paths=metadata,
    )
    assert second["registry_id"] == first["registry_id"]
    assert second["roster_id"] == first["roster_id"]
    assert first["reused"] is False
    assert second["reused"] is True


def test_ensure_registry_answers_the_same_questions_either_way(
    published_source,
) -> None:
    """The two paths answer from different sources, so their key sets must match."""
    manifest_path, metadata = published_source
    source_id = load_source_snapshot(manifest_path).manifest["snapshot_id"]
    fresh = ensure_registry(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_snapshot_id=source_id,
        metadata_paths=metadata,
    )
    reused = ensure_registry(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_snapshot_id=source_id,
        metadata_paths=metadata,
    )
    for key in (
        "registry_id",
        "roster_id",
        "source_snapshot_id",
        "curated_input_path",
        "curated_input_fingerprint",
        "curated_cik_count",
        "active_cik_count",
        "row_count",
    ):
        assert key in fresh, key
        assert key in reused, key
    assert fresh["row_count"] == reused["row_count"] == 5


def test_ensure_registry_recomputes_when_the_roster_digest_is_wrong(
    published_source,
) -> None:
    """A swapped roster is not reused; the comparison republishes the truth."""
    manifest_path, metadata = published_source
    source_id = load_source_snapshot(manifest_path).manifest["snapshot_id"]
    first = ensure_registry(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_snapshot_id=source_id,
        metadata_paths=metadata,
    )
    metadata.effective_cik_roster(first["registry_id"]).write_bytes(b"corrupted")
    second = ensure_registry(
        curated_input_path=fixture_path("cik_sec_mini.csv"),
        source_snapshot_id=source_id,
        metadata_paths=metadata,
    )
    assert second["reused"] is False
    assert second["registry_id"] == first["registry_id"]


def test_ensure_registry_names_a_missing_seed(tmp_path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    with pytest.raises(FileNotFoundError, match="curated CIK manifest"):
        ensure_registry(
            curated_input_path=tmp_path / "absent.csv",
            source_snapshot_id="src-1",
            metadata_paths=metadata,
        )
