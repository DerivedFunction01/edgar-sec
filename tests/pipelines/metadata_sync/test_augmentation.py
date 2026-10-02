"""Delta augmentation against a published snapshot.

The augmentation contract under test: a snapshot holding N CIKs that receives K
new ones publishes N+K rows, the N base CIKs are never refetched, and the delta
plan is identified by its base as well as its cohort. That last property is the
one the old identity got wrong, so it is pinned directly rather than inferred.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.sec_urls import submissions_url
from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.pipelines.metadata_sync.augmentation import (
    augment,
    augment_from_manifest,
    augment_from_roster,
    base_snapshot_ciks,
    derive_delta_plan,
    preflight_augment,
    snapshot_cik_roster,
)
from edgar_sec.pipelines.metadata_sync.checkpoints import discover_completed_chunks
from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from edgar_sec.pipelines.metadata_sync.merger import (
    MergeError,
    merge_chunks,
    publish_snapshot,
)
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
from edgar_sec.pipelines.metadata_sync.snapshot import read_snapshot_parts
from edgar_sec.pipelines.metadata_sync.worker import run_chunk
from tests.support import (
    FakeSession,
    cik_payload,
    fixture_path,
    load_fixture,
)

# A live listing that names a registrant the curated seed does not cover.
SOURCE_TICKERS = {
    "0": {"cik_str": "37996", "ticker": "F", "title": "FORD MOTOR CO"},
    "1": {"cik_str": "20", "ticker": "KTC", "title": "K Tron International Inc"},
    "2": {"cik_str": "5555", "ticker": "NEW", "title": "NEWCO INC"},
}

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


def _snapshot_rows(metadata, snapshot_id: str) -> list[dict]:
    """Every row of a published snapshot, across all of its parts.

    A snapshot is a dataset, not a file, so tests read it the way a consumer
    does: through the part list its manifest declares.
    """
    parts = read_snapshot_parts(metadata.snapshot_manifest(snapshot_id))
    rows: list[dict] = []
    for path in parts.paths:
        rows.extend(pq.read_table(path).to_pylist())
    return rows


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
    # A merge is not a publication. The base of an augmentation must be a
    # published snapshot, so the manifest is the commit record that makes it one.
    publish_snapshot(report, metadata)
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

    table = pa.Table.from_pylist(
        _snapshot_rows(metadata, "next"), schema=SUBMISSION_METADATA_SCHEMA
    )
    ciks = table.column("cik").to_pylist()
    assert sorted(ciks) == sorted([*manifest.ciks, EXTRA])
    # An augmented snapshot is in part order (base parts, then delta chunks), not
    # globally CIK-sorted. Membership is the contract; the manifest records the
    # ordering as `sort_order`.
    parts = read_snapshot_parts(metadata.snapshot_manifest("next"))
    assert [
        part["source"].split(":")[0] for part in parts.layout.manifest["parts"]
    ] == [
        "base",
        "base",
        "chunk",
    ]
    assert parts.layout.manifest["sort_order"] == "chunk_order"

    pointer = json.loads(metadata.current_pointer.read_text())
    assert pointer["snapshot_id"] == "next"
    assert pointer["row_count"] == 5


# --------------------------------------------------------------- progress


def test_an_augmentation_reports_both_of_its_phases(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """An augmentation is the pipeline's longest silent wait without this.

    It does a rate-limited network fetch and then scans every input for null and
    duplicate CIKs, so it emits the same two event shapes ``run`` and ``merge``
    already emit. Asserting the whole sequence matters: a caller that renders a
    bar needs the delta size before the first fetch event, which is why
    ``delta_plan`` comes first.
    """
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)

    events: list[dict] = []
    augment(
        client,
        read_cik_manifest(widened),
        metadata,
        base_snapshot_id="base",
        chunk_size=2,
        workers=2,
        progress=events.append,
    )

    types = [event["type"] for event in events]
    assert types[0] == "delta_plan", (
        "the delta size must be known before any fetch event"
    )
    plan_event = events[0]
    assert plan_event["row_count"] == 1, "the delta is one CIK, not the base count"
    assert plan_event["plan_id"]
    # Per-CIK fetch events, so a bar advances per unit of real work.
    assert "cik_normalized" in types
    fetch_events = [event for event in events if event["type"] == "cik_normalized"]
    assert [event["cik"] for event in fetch_events] == [EXTRA]
    # Both merge stages, then the readback, so the merge bar can complete.
    stages = [event["stage"] for event in events if event["type"] == "merge_stage"]
    assert stages == ["validating", "publishing_parts"]
    assert events[-1]["type"] == "readback_done"
    assert events[-1]["rows"] == 5


def test_progress_comes_before_the_publish_so_a_bar_never_overruns(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """The readback event is the last thing, so it reports the verified total."""
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)

    events: list[dict] = []
    result = augment(
        client,
        read_cik_manifest(widened),
        metadata,
        base_snapshot_id="base",
        chunk_size=2,
        workers=2,
        progress=events.append,
    )
    assert events[-1] == {
        "type": "readback_done",
        "rows": result.total_row_count,
    }


def test_a_broken_progress_callback_cannot_fail_an_augmentation(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """Presentation must not be able to fail a fetch, same as a merge."""
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)

    def explode(event: dict) -> None:
        raise RuntimeError("bar went away")

    result = augment(
        client,
        read_cik_manifest(widened),
        metadata,
        base_snapshot_id="base",
        chunk_size=2,
        workers=2,
        progress=explode,
    )
    assert result.delta_row_count == 1


def test_omitting_progress_is_still_supported(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)
    result = augment(
        client,
        read_cik_manifest(widened),
        metadata,
        base_snapshot_id="base",
        chunk_size=2,
        workers=2,
    )
    assert result.delta_row_count == 1


# --------------------------------------------------- derived snapshot identity


def _widen(tmp_path: Path, session: FakeSession, *extra: str) -> Path:
    """Write a manifest adding CIKs to the baseline cohort, and register them."""
    rows = "cik,name\n1985,A\n1761,B\n20,C\n37996,FORD\n"
    rows += "".join(f"{cik},EXTRA {cik}\n" for cik in extra)
    path = tmp_path / "widened.csv"
    path.write_text(rows, encoding="utf-8")
    _seed(session, extra=bool(extra))
    return path


def test_an_omitted_snapshot_id_publishes_under_the_delta_plan_id(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """Every other Phase 1 identity is content-derived; this one now is too.

    The snapshot was the single hand-typed identifier on this surface while
    ``merge`` in the same pipeline already defaulted to the plan id. The delta plan
    id is a content address over the base snapshot, the delta cohort, and the chunk
    layout, so deriving it makes the operation idempotent.
    """
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)

    result = augment(
        client,
        read_cik_manifest(widened),
        metadata,
        base_snapshot_id="base",
        chunk_size=2,
        workers=2,
    )

    assert result.new_snapshot_id == result.report.plan_id
    assert result.new_snapshot_id
    # The derived id is what actually got written, not just what was reported.
    manifest = json.loads(
        metadata.snapshot_manifest(result.new_snapshot_id).read_text()
    )
    assert manifest["snapshot_id"] == result.report.plan_id
    assert manifest["parent_snapshot_id"] == "base"
    assert json.loads(metadata.current_pointer.read_text())["snapshot_id"] == (
        result.new_snapshot_id
    )


def test_the_derived_id_is_stable_for_the_same_base_and_cohort(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """Idempotency is the point: rerunning the same delta must resolve the same id."""
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)
    first = augment(
        client,
        read_cik_manifest(widened),
        metadata,
        base_snapshot_id="base",
        chunk_size=2,
        workers=2,
    )
    second = augment(
        client,
        read_cik_manifest(widened),
        metadata,
        base_snapshot_id="base",
        chunk_size=2,
        workers=2,
    )
    assert first.new_snapshot_id == second.new_snapshot_id


def test_a_different_base_or_chunk_layout_yields_a_different_id(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """The derivation is only meaningful if the bound inputs actually move it."""
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)
    manifest = read_cik_manifest(widened)

    chunk_size_two = augment(
        client,
        manifest,
        metadata,
        base_snapshot_id="base",
        chunk_size=2,
        workers=2,
    )
    chunk_size_one = augment(
        client,
        manifest,
        metadata,
        base_snapshot_id="base",
        chunk_size=1,
        workers=2,
    )
    assert chunk_size_two.new_snapshot_id != chunk_size_one.new_snapshot_id


def test_an_explicit_snapshot_id_still_overrides_the_derivation(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """The distribution path stamps rows with a chosen id, so the override stays."""
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)

    result = augment(
        client,
        read_cik_manifest(widened),
        metadata,
        base_snapshot_id="base",
        new_snapshot_id="chosen",
        chunk_size=2,
        workers=2,
    )
    assert result.new_snapshot_id == "chosen"
    assert result.report.plan_id != "chosen"
    rows = _snapshot_rows(metadata, "chosen")
    assert {row["snapshot_id"] for row in rows if row["cik"] == EXTRA} == {"chosen"}


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
        row["cik"]: row["snapshot_id"] for row in _snapshot_rows(metadata, "base")
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
    for row in _snapshot_rows(metadata, "next"):
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


def test_augment_is_a_no_op_when_the_base_already_covers_the_request(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """Re-requesting a fully-covered cohort is the ordinary case, not a failure.

    The seed this pipeline plans over is a file someone curated at a point in
    time. Re-augmenting it after it has been fully ingested is the *expected*
    outcome, and it used to raise "augmentation requested no work" from inside
    the run, after the operator had already answered the fetch-consent and
    worker-count questions.
    """
    metadata, manifest, _, _ = _publish_baseline(client, session, tmp_path)
    pointer_before = metadata.current_pointer.read_bytes()
    sessions_before = session.calls

    result = augment(
        client,
        manifest,
        metadata,
        base_snapshot_id="base",
        new_snapshot_id="next",
        chunk_size=2,
    )

    assert result.no_op is True
    assert result.report is None
    assert result.new_snapshot_id == ""
    assert result.delta_row_count == 0
    assert result.refetched_ciks == ()
    assert result.requested_cik_count == len(manifest.ciks)
    assert result.already_present_count == len(manifest.ciks)
    assert result.total_row_count == result.base_row_count
    # No request, no plan, no snapshot, no pointer movement.
    assert session.calls == sessions_before
    assert metadata.snapshot_manifest("next").exists() is False
    assert metadata.current_pointer.read_bytes() == pointer_before


def test_preflight_reports_the_work_before_anything_is_fetched(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """The arithmetic is answerable from published artifacts alone."""
    metadata, manifest, _, _ = _publish_baseline(client, session, tmp_path)
    requested = build_roster((*manifest.ciks, EXTRA))

    check = preflight_augment(requested, metadata, base_snapshot_id="base")

    assert check.is_empty is False
    assert check.requested_count == len(manifest.ciks) + 1
    assert check.already_present_count == len(manifest.ciks)
    assert check.delta.ciks == (EXTRA,)
    assert "to fetch" in check.describe()


def test_preflight_reports_an_empty_delta_without_raising(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest, _, _ = _publish_baseline(client, session, tmp_path)
    check = preflight_augment(
        roster_from_manifest(manifest), metadata, base_snapshot_id="base"
    )
    assert check.is_empty is True
    assert check.delta.is_empty is True
    assert check.already_present_count == check.requested_count


def test_a_delta_calling_itself_a_delta_is_still_reduced_against_the_base(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """A hand-supplied increment is a *request*, not a claim about what is missing.

    The operator may point augmentation at a file that already looks like the
    delta. Treating that file's contents as the work list would refetch CIKs the
    base already holds and then reject the merge for containing them, so every
    cohort is reduced against the base no matter what it is named.
    """
    metadata, manifest, _, _ = _publish_baseline(client, session, tmp_path)
    already_covered = build_roster(manifest.ciks)
    check = preflight_augment(already_covered, metadata, base_snapshot_id="base")
    assert check.is_empty is True


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
