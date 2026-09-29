"""Delta augmentation against a published snapshot.

The augmentation contract under test: a snapshot holding N CIKs that receives K
new ones publishes N+K rows, the N base CIKs are never refetched, and the delta
plan is identified by its base as well as its cohort. That last property is the
one the old identity got wrong, so it is pinned directly rather than inferred.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.sec_urls import submissions_url
from edgar_sec.pipelines.metadata_sync.augmentation import (
    augment,
    augment_from_manifest,
    augment_from_roster,
    base_snapshot_ciks,
    derive_delta_plan,
    snapshot_cik_roster,
)
from edgar_sec.pipelines.metadata_sync.checkpoints import discover_completed_chunks
from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from edgar_sec.pipelines.metadata_sync.merger import MergeError, merge_chunks
from edgar_sec.pipelines.metadata_sync.paths import (
    resolve_metadata_paths,
    resolve_run_paths,
)
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from edgar_sec.pipelines.metadata_sync.roster import (
    build_roster,
    read_cik_index,
    roster_from_manifest,
)
from edgar_sec.pipelines.metadata_sync.worker import run_chunk
from tests.support import FakeSession, cik_payload, fixture_path, load_fixture

FORD = "0000037996"
EXTRA = "0000005555"
HIST_URL = f"https://data.sec.gov/submissions/CIK{FORD}-submissions-001.json"


def _seed(session: FakeSession, extra: bool = False) -> None:
    session.register(submissions_url(FORD), load_fixture("recent_submissions.json"))
    session.register(HIST_URL, load_fixture("historical_submissions.json"))
    for cik, name in (
        ("0000001985", "ACCEL"),
        ("0000001761", "TRANZONIC"),
        ("0000000020", "K TRON"),
    ):
        session.register(submissions_url(cik), cik_payload(cik, name))
    if extra:
        session.register(submissions_url(EXTRA), cik_payload(EXTRA, "EXTRA CO"))


def _publish_baseline(client, session: FakeSession, tmp_path: Path):
    _seed(session)
    metadata = resolve_metadata_paths(tmp_path)
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    plan = build_plan(
        roster_from_manifest(manifest),
        chunk_size=2,
        input_name=manifest.input_name,
        input_fingerprint=manifest.input_fingerprint,
    )
    run_paths = resolve_run_paths(plan.plan_id, metadata.artifacts_root)
    write_plan(plan, run_paths)
    for chunk_id in plan.chunk_ids():
        run_chunk(client, plan, run_paths, chunk_id, snapshot_id="base", workers=2)
    report = merge_chunks(plan, run_paths, "base")
    return metadata, manifest, plan, report


# ------------------------------------------------------------------ delta plan


def test_plan_delta_excludes_base_ciks() -> None:
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    plan = derive_delta_plan(
        roster_from_manifest(manifest),
        build_roster(("0000001985", "0000001761")),
        chunk_size=2,
        base_snapshot_id="base",
    )
    assert plan.roster.ciks == ("0000000020", FORD)
    assert plan.kind == "delta"
    assert plan.parent_id == "base"


def test_an_empty_delta_is_refused_rather_than_planned() -> None:
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    with pytest.raises(MergeError, match="no work"):
        derive_delta_plan(
            roster_from_manifest(manifest),
            build_roster(manifest.ciks),
            chunk_size=2,
            base_snapshot_id="base",
        )


def test_one_requested_list_against_two_bases_is_two_plans() -> None:
    """The identity defect this work exists to close.

    The delta plan used to be identified by the request file's digest, so the
    same requested CIKs against two different bases resolved to one plan
    directory and one chunk namespace, and the second run overwrote the first
    plan's record.
    """
    requested = roster_from_manifest(
        read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    )
    against_a = derive_delta_plan(
        requested,
        build_roster(("0000001985", "0000001761", "0000000020")),
        chunk_size=2,
        base_snapshot_id="base-a",
    )
    against_b = derive_delta_plan(
        requested,
        build_roster((FORD,)),
        chunk_size=2,
        base_snapshot_id="base-b",
    )
    assert against_a.plan_id != against_b.plan_id
    assert against_a.roster.ciks == (FORD,)
    assert against_b.roster.ciks == ("0000001985", "0000001761", "0000000020")


def test_a_delta_plan_never_shares_a_directory_with_a_full_plan(tmp_path: Path) -> None:
    """The two plan kinds over one cohort must not collide on disk."""
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    roster = roster_from_manifest(manifest)
    full = build_plan(roster, chunk_size=2)
    delta = derive_delta_plan(
        roster,
        build_roster(roster.ciks[:2]),
        chunk_size=2,
        base_snapshot_id="base",
    )
    assert full.plan_id != delta.plan_id
    full_paths = resolve_run_paths(full.plan_id, tmp_path)
    delta_paths = resolve_run_paths(delta.plan_id, tmp_path)
    assert full_paths.plan_bundle != delta_paths.plan_bundle
    assert full_paths.chunk_dir != delta_paths.chunk_dir


def test_delta_refuses_an_empty_cohort() -> None:
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    with pytest.raises(MergeError, match="no work"):
        derive_delta_plan(
            roster_from_manifest(manifest),
            build_roster(manifest.ciks),
            chunk_size=2,
            base_snapshot_id="base",
        )


# ----------------------------------------------------------------- base lookup


def test_base_membership_is_read_from_the_published_index(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest, _, _ = _publish_baseline(client, session, tmp_path)
    assert base_snapshot_ciks(metadata, "base") == set(manifest.ciks)
    assert snapshot_cik_roster(metadata, "base").ciks == tuple(sorted(manifest.ciks))


def test_base_membership_falls_back_to_the_payload(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """A snapshot published before the index existed is still readable.

    Falling back is what makes the index an addition rather than a migration; a
    missing base is still an error, because an unreadable base must never be
    mistaken for an empty one.
    """
    metadata, manifest, _, _ = _publish_baseline(client, session, tmp_path)
    metadata.snapshot_cik_index("base").unlink()
    assert base_snapshot_ciks(metadata, "base") == set(manifest.ciks)


def test_a_missing_base_is_never_read_as_empty(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    with pytest.raises(FileNotFoundError):
        base_snapshot_ciks(metadata, "absent")


# ---------------------------------------------------------------- augmentation


def test_augment_merges_base_and_delta_without_refetching_base(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest, _, base_report = _publish_baseline(client, session, tmp_path)
    assert base_report.row_count == 4
    calls_after_base = len(session.calls)

    widened = tmp_path / "widened.csv"
    widened.write_text(
        "cik,name\n1985,A\n1761,B\n20,C\n37996,FORD\n5555,EXTRA CO\n", encoding="utf-8"
    )
    _seed(session, extra=True)

    result = augment(
        client,
        read_cik_manifest(widened),
        metadata,
        base_snapshot_id="base",
        new_snapshot_id="next",
        chunk_size=2,
        workers=2,
    )

    assert result.base_row_count == 4
    assert result.delta_row_count == 1
    assert result.total_row_count == 5
    assert result.refetched_ciks == (EXTRA,)

    base_urls = {
        submissions_url(cik) for cik in ("0000001985", "0000001761", "0000000020", FORD)
    }
    refetched_urls = {url for url in session.calls[calls_after_base:]}
    assert not (refetched_urls & base_urls)
    assert submissions_url(EXTRA) in refetched_urls

    table = pq.read_table(metadata.snapshot_file("next"))
    ciks = table.column("cik").to_pylist()
    assert sorted(ciks) == sorted([*manifest.ciks, EXTRA])
    assert ciks == sorted(ciks)

    pointer = json.loads(metadata.current_pointer.read_text())
    assert pointer["snapshot_id"] == "next"
    assert pointer["row_count"] == 5


def test_augmented_index_is_the_union_of_base_and_delta(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest, _, _ = _publish_baseline(client, session, tmp_path)
    widened = tmp_path / "widened.csv"
    widened.write_text("cik,name\n5555,EXTRA CO\n", encoding="utf-8")
    _seed(session, extra=True)

    result = augment(
        client,
        read_cik_manifest(widened),
        metadata,
        base_snapshot_id="base",
        new_snapshot_id="next",
        chunk_size=2,
        workers=2,
    )
    index = read_cik_index(metadata.snapshot_cik_index("next"))
    assert list(index) == sorted([*manifest.ciks, EXTRA])
    assert result.report.cik_count == len(index)
    assert result.report.cik_index_sha256


def test_augmented_manifest_records_its_lineage(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """The published artifact says which base and which delta produced it."""
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = tmp_path / "widened.csv"
    widened.write_text("cik,name\n5555,EXTRA CO\n", encoding="utf-8")
    _seed(session, extra=True)

    result = augment(
        client,
        read_cik_manifest(widened),
        metadata,
        base_snapshot_id="base",
        new_snapshot_id="next",
        chunk_size=2,
        workers=2,
    )
    manifest = json.loads(
        metadata.snapshot_manifest("next").read_text(encoding="utf-8")
    )
    assert manifest["kind"] == "delta"
    assert manifest["parent_snapshot_id"] == "base"
    assert manifest["delta_roster_id"] == result.report.roster_id
    assert manifest["plan_id"] == result.report.plan_id


def test_augment_preserves_base_row_provenance(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """Row-level ``snapshot_id`` is provenance, not the containing artifact's id.

    Augmentation copies base rows verbatim, so an augmented snapshot legitimately
    contains rows stamped with the base's identity. Rewriting them to the new
    artifact's id would misstate where the data came from.
    """
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    base_stamps = {
        row["cik"]: row["snapshot_id"]
        for row in pq.read_table(metadata.snapshot_file("base")).to_pylist()
    }
    widened = tmp_path / "widened.csv"
    widened.write_text("cik,name\n5555,EXTRA CO\n", encoding="utf-8")
    _seed(session, extra=True)
    augment(
        client,
        read_cik_manifest(widened),
        metadata,
        base_snapshot_id="base",
        new_snapshot_id="next",
        chunk_size=2,
        workers=2,
    )
    for row in pq.read_table(metadata.snapshot_file("next")).to_pylist():
        if row["cik"] in base_stamps:
            assert row["snapshot_id"] == base_stamps[row["cik"]]
        else:
            assert row["snapshot_id"] == "next"


def test_augment_from_manifest_reads_the_csv_and_matches_augment(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """The documented wrapper is the path the CLI takes, so it must agree."""
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = tmp_path / "widened.csv"
    widened.write_text("cik,name\n5555,EXTRA CO\n", encoding="utf-8")
    _seed(session, extra=True)

    result = augment_from_manifest(
        client,
        str(widened),
        metadata,
        base_snapshot_id="base",
        new_snapshot_id="next",
        chunk_size=2,
        workers=2,
    )
    assert result.base_row_count == 4
    assert result.delta_row_count == 1
    assert result.refetched_ciks == (EXTRA,)


def test_augment_from_roster_agrees_with_the_csv_wrapper(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """A published registry roster and a CSV describe the same delta."""
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    roster = build_roster((EXTRA,), ("EXTRA CO",))
    _seed(session, extra=True)
    result = augment_from_roster(
        client,
        roster,
        metadata,
        base_snapshot_id="base",
        new_snapshot_id="next",
        chunk_size=2,
        input_name="registry:demo",
        input_fingerprint=roster.roster_id,
        workers=2,
    )
    assert result.delta_row_count == 1
    assert result.refetched_ciks == (EXTRA,)
    assert result.report.input_fingerprint == roster.roster_id


def test_augment_rejects_when_nothing_new(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest, _, _ = _publish_baseline(client, session, tmp_path)
    with pytest.raises(MergeError, match="no work"):
        augment(
            client,
            manifest,
            metadata,
            base_snapshot_id="base",
            new_snapshot_id="next",
            chunk_size=2,
        )


def test_augment_requires_an_existing_base(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    with pytest.raises(FileNotFoundError):
        augment(
            client,
            manifest,
            metadata,
            base_snapshot_id="missing",
            new_snapshot_id="next",
            chunk_size=2,
        )


def test_base_checkpoints_are_still_discoverable(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, _manifest, plan, _ = _publish_baseline(client, session, tmp_path)
    completed = discover_completed_chunks(
        plan, resolve_run_paths(plan.plan_id, metadata.artifacts_root)
    )
    assert set(completed) == {0, 1}
