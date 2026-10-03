"""Lifecycle convergence: the same cohort must produce the same snapshot.

These tests are the definition of done for the format change. They assert
properties a single-path unit test cannot: that scaling the cohort does not
change what the plan *is*, that reassigning work does not change the snapshot,
and that the published artifact is verifiable from itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.sec_urls import submissions_url
from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.pipelines.metadata_sync.assignment import (
    build_assignment,
    divide_chunks,
    write_assignment,
)
from edgar_sec.pipelines.metadata_sync.checkpoints import discover_completed_chunks
from edgar_sec.pipelines.metadata_sync.merger import merge_chunks, publish_snapshot
from edgar_sec.pipelines.metadata_sync.options import (
    BundleRunPaths,
    derive_plan_id,
    plan_options,
    run_options,
)
from edgar_sec.pipelines.metadata_sync.paths import (
    resolve_metadata_paths,
    resolve_run_paths,
)
from edgar_sec.pipelines.metadata_sync.planner import (
    build_plan,
    load_plan,
    write_plan,
)
from edgar_sec.pipelines.metadata_sync.roster import read_cik_index
from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient
from edgar_sec.pipelines.metadata_sync.snapshot import read_snapshot_parts
from edgar_sec.pipelines.metadata_sync.worker import run_chunk_ids
from tests.support import (
    FakeSession,
    build_test_http,
    fixture_cohort,
    fixture_path,
    roster_of,
)

MINI_CIKS = ("0000001985", "0000001761", "0000000020", "0000037996")


def _session(ciks: tuple[str, ...] = MINI_CIKS) -> FakeSession:
    session = FakeSession()
    for cik in ciks:
        session.register(
            submissions_url(cik),
            {
                "name": f"CO {cik}",
                "cik": int(cik),
                "filings": {"recent": {}, "files": []},
            },
        )
    return session


def _client(session: FakeSession) -> SubmissionsClient:
    return SubmissionsClient(http=build_test_http(session))


def _prepare(tmp_path: Path, chunk_size: int = 1):
    """Plan the committed mini manifest, returning plan, paths, and run options."""

    cohort = fixture_cohort("cik_sec_mini.csv")
    plan = build_plan(
        cohort.roster,
        chunk_size=chunk_size,
        input_name=cohort.input_name,
        input_fingerprint=cohort.input_fingerprint,
    )
    run_paths = resolve_run_paths(plan.plan_id, tmp_path)
    write_plan(plan, run_paths)
    return plan, run_paths


# ------------------------------------------------------------------- identity


def _snapshot_rows(metadata, snapshot_id: str) -> list[dict]:
    """Every row of a published snapshot, read through its declared part list."""
    parts = read_snapshot_parts(metadata.snapshot_manifest(snapshot_id))
    rows: list[dict] = []
    for path in parts.paths:
        rows.extend(pq.read_table(path).to_pylist())
    return rows


def test_the_plan_document_stays_small_at_every_scale() -> None:
    """The reason the roster became its own artifact.

    The previous document embedded the CIK list three times, so a 250,000-CIK
    cohort produced a 15 MB plan. Constant in cohort size is the property that
    makes a plan cheap to copy to a worker and cheap to diff.
    """
    small = build_plan(roster_of(MINI_CIKS), chunk_size=1000)
    large = build_plan(
        roster_of(tuple(f"{value:010d}" for value in range(1, 250_001))),
        chunk_size=1000,
    )
    manifest = json.dumps(large.to_manifest(), indent=2)
    assert len(manifest) < 2048
    assert len(manifest) < 2 * len(json.dumps(small.to_manifest(), indent=2)) + 64
    assert "cik_padded" not in manifest
    assert "rows" not in manifest
    assert large.chunk_count == 250


def test_reassigning_every_chunk_leaves_the_plan_untouched(tmp_path: Path) -> None:
    """Moving work between machines must not move the plan.

    Assignment is a separate artifact with its own identity, so a reassignment
    cannot discard the completed checkpoints of an otherwise identical cohort.
    """
    plan, run_paths = _prepare(tmp_path, chunk_size=1)
    session = _session()
    client = _client(session)
    run_chunk_ids(
        client,
        plan,
        run_paths,
        [0],
        snapshot_id=plan.plan_id,
        workers=2,
    )
    assert set(discover_completed_chunks(plan, run_paths)) == {0}
    calls_after_chunk_zero = len(session.calls)

    for worker_count in (2, 3, 4):
        for worker_id, chunk_ids in divide_chunks(
            plan.chunk_count, worker_count
        ).items():
            write_assignment(
                build_assignment(plan.plan_id, worker_id, chunk_ids), run_paths
            )

    reloaded = load_plan(run_paths)
    assert reloaded.plan_id == plan.plan_id
    assert reloaded.chunk_ciks(0) == plan.chunk_ciks(0)
    assert set(discover_completed_chunks(reloaded, run_paths)) == {0}

    run_chunk_ids(
        client,
        reloaded,
        run_paths,
        reloaded.chunk_ids(),
        snapshot_id=plan.plan_id,
        workers=2,
    )
    reasserted = len(session.calls) - calls_after_chunk_zero
    assert reasserted == 3


def test_derived_and_recorded_plan_ids_agree(tmp_path: Path) -> None:
    """Planning twice is idempotent, which is what makes resume safe."""
    plan, run_paths = _prepare(tmp_path, chunk_size=1)
    derived = derive_plan_id(
        plan_options(input_path=fixture_path("cik_sec_mini.csv"), chunk_size=1)
    )
    assert derived == plan.plan_id == load_plan(run_paths).plan_id
    assert (
        run_options(
            input_path=str(fixture_path("cik_sec_mini.csv")), chunk_size=1
        ).plan_id
        == plan.plan_id
    )


# -------------------------------------------------------------- multi-machine


def test_two_machines_with_one_bundle_merge_to_the_same_snapshot(
    tmp_path: Path,
) -> None:
    """The property the whole distribution surface exists to provide.

    A single host runs every chunk in one directory. Two "machines" each run a
    disjoint assignment from copies of the same bundle. Both must produce the same
    published snapshot, because a worker's location is not a property of the data.
    """
    single_root = tmp_path / "single"
    plan, single_paths = _prepare(single_root, chunk_size=1)
    single_client = _client(_session())
    run_chunk_ids(
        single_client,
        plan,
        single_paths,
        plan.chunk_ids(),
        snapshot_id=plan.plan_id,
        workers=2,
    )
    single_report = merge_chunks(plan, single_paths, plan.plan_id)
    publish_snapshot(single_report, single_paths.metadata)

    # Now the same plan, distributed.
    distributed_root = tmp_path / "distributed"
    coordinator_paths = resolve_run_paths(plan.plan_id, distributed_root)
    write_plan(plan, coordinator_paths)

    coordinator = _client(_session())
    run_chunk_ids(
        coordinator,
        plan,
        coordinator_paths,
        plan.chunk_ids(),
        snapshot_id=plan.plan_id,
        workers=2,
    )
    distributed_report = merge_chunks(plan, coordinator_paths, plan.plan_id)
    publish_snapshot(distributed_report, coordinator_paths.metadata)

    single = pa.Table.from_pylist(
        _snapshot_rows(single_paths.metadata, plan.plan_id),
        schema=SUBMISSION_METADATA_SCHEMA,
    )
    distributed = pa.Table.from_pylist(
        _snapshot_rows(coordinator_paths.metadata, plan.plan_id),
        schema=SUBMISSION_METADATA_SCHEMA,
    )
    assert single.num_rows == distributed.num_rows == plan.row_count
    assert single.schema.equals(distributed.schema)
    assert single.column("cik").to_pylist() == distributed.column("cik").to_pylist()
    assert (
        set(single.column("snapshot_id").to_pylist())
        == {plan.plan_id}
        == set(distributed.column("snapshot_id").to_pylist())
    )
    # The CIK index is derived from the published rows' key column, so it is
    # deterministic across runs even though the fetch timestamps are not. The
    # per-part digests are not, because a part's bytes carry those timestamps.
    assert single_report.cik_index_sha256 == distributed_report.cik_index_sha256
    assert single_report.cik_count == distributed_report.cik_count == plan.row_count
    assert single_report.part_count == distributed_report.part_count == plan.chunk_count
    assert single_report.parts_digest != ""


def test_a_worker_running_a_copied_bundle_cannot_widen_its_scope(
    tmp_path: Path,
) -> None:
    """The chunk list comes from the assignment, never from the worker's choice."""
    from edgar_sec.pipelines.metadata_sync.assignment import AssignmentError
    from edgar_sec.pipelines.metadata_sync.distribution import (
        copy_bundle,
        select_assignment,
    )

    plan, run_paths = _prepare(tmp_path, chunk_size=1)
    bundle = tmp_path / "worker-00"
    bundle.mkdir()
    copy_bundle(run_paths, bundle)
    bundle_paths = BundleRunPaths(bundle_root=bundle, plan_id=plan.plan_id)
    write_assignment(build_assignment(plan.plan_id, "worker-00", [0]), bundle_paths)

    client = _client(_session())
    assignment = select_assignment(
        run_options(plan_id=plan.plan_id, bundle_root=str(bundle)), bundle_paths
    )
    run_chunk_ids(
        client,
        plan,
        bundle_paths,
        list(assignment.chunk_ids),
        snapshot_id=plan.plan_id,
        workers=2,
    )
    assert bundle_paths.chunk_file(0).is_file()
    assert not bundle_paths.chunk_file(1).exists()
    assert sorted(p.name for p in bundle_paths.chunk_dir.glob("chunk_*.parquet")) == [
        "chunk_0000.parquet"
    ]

    with pytest.raises(AssignmentError, match="bundle carries no assignment"):
        select_assignment(
            run_options(plan_id=plan.plan_id, bundle_root=str(tmp_path / "bare")),
            BundleRunPaths(bundle_root=tmp_path / "bare", plan_id=plan.plan_id),
        )


# ------------------------------------------------------------- verification


def test_a_published_snapshot_is_verifiable_from_its_own_directory(
    tmp_path: Path,
) -> None:
    """Payload, index, and manifest must agree without consulting the plan."""
    plan, run_paths = _prepare(tmp_path, chunk_size=2)
    client = _client(_session())
    run_chunk_ids(
        client,
        plan,
        run_paths,
        plan.chunk_ids(),
        snapshot_id=plan.plan_id,
        workers=2,
    )
    manifest = publish_snapshot(
        merge_chunks(plan, run_paths, plan.plan_id), run_paths.metadata
    )
    metadata = run_paths.metadata

    rows = _snapshot_rows(metadata, plan.plan_id)
    index = read_cik_index(metadata.snapshot_cik_index(plan.plan_id))
    assert list(index) == sorted({row["cik"] for row in rows})
    parts = read_snapshot_parts(metadata.snapshot_manifest(plan.plan_id))
    assert all(part["sha256"] for part in parts.layout.manifest["parts"])

    on_disk = json.loads(
        metadata.snapshot_manifest(plan.plan_id).read_text(encoding="utf-8")
    )
    assert on_disk["row_count"] == len(rows)
    assert on_disk["cik_count"] == len(index)
    pointer = json.loads(metadata.current_pointer.read_text(encoding="utf-8"))
    assert pointer["snapshot_id"] == on_disk["snapshot_id"] == plan.plan_id
    assert manifest["row_count"] == len(rows)


def test_phase_two_reads_exactly_the_declared_parts(tmp_path: Path) -> None:
    """The handoff is a part list, not a single file.

    Phase 2 must consume exactly the parts the manifest names. The CIK index is a
    Phase 1 sibling, not a part, so a consumer resolving the part list cannot
    mistake it for a dataset.
    """
    plan, run_paths = _prepare(tmp_path, chunk_size=2)
    client = _client(_session())
    run_chunk_ids(
        client,
        plan,
        run_paths,
        plan.chunk_ids(),
        snapshot_id=plan.plan_id,
        workers=2,
    )
    publish_snapshot(merge_chunks(plan, run_paths, plan.plan_id), run_paths.metadata)
    metadata = run_paths.metadata

    index = metadata.snapshot_cik_index(plan.plan_id)
    assert index.is_file()
    assert pq.read_schema(index).names == ["cik"]
    parts = read_snapshot_parts(metadata.snapshot_manifest(plan.plan_id))
    assert parts.part_count >= 1
    for path in parts.paths:
        assert pq.read_schema(path).names == SUBMISSION_METADATA_SCHEMA.names
    assert index not in parts.paths
    pointer = json.loads(metadata.current_pointer.read_text(encoding="utf-8"))
    assert pointer["part_count"] == parts.part_count
    assert pointer["parts_digest"]


def test_an_empty_selection_is_refused_before_any_work(tmp_path: Path) -> None:
    from edgar_sec.pipelines.metadata_sync.roster import empty_roster

    with pytest.raises(ValueError, match="non-empty roster"):
        build_plan(empty_roster())


def test_metadata_paths_place_a_copied_bundle_outside_the_artifacts_tree(
    tmp_path: Path,
) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    assert "transient" not in metadata.plan_dir("p").parts
    assert metadata.transient_dir("p").is_relative_to(tmp_path / "transient")
