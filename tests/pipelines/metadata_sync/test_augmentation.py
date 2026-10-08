"""Delta augmentation: a delta plan is identified by its base as well as its cohort."""

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
    base_cik_sources,
    delta_roster_path,
    derive_delta_plan,
    preflight_augment,
)
from edgar_sec.pipelines.metadata_sync.checkpoints import discover_completed_chunks
from edgar_sec.pipelines.metadata_sync.discovery import current_snapshot_id
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
from edgar_sec.pipelines.metadata_sync.roster import read_cik_index
from edgar_sec.pipelines.metadata_sync.snapshot import read_snapshot_parts
from edgar_sec.pipelines.metadata_sync.worker import run_chunk
from tests.pipelines.metadata_sync.cohort_support import publish_test_cohort
from tests.support import (
    FakeSession,
    cik_payload,
    fixture_cohort,
    load_fixture,
    roster_of,
)

FORD = "0000037996"
EXTRA = "0000005555"
HIST_URL = f"https://data.sec.gov/submissions/CIK{FORD}-submissions-001.json"


def _published_roster(source: Path, metadata):
    return publish_test_cohort(source, metadata.artifacts_root)[2]


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
    """Read a snapshot the way a consumer does: every part its manifest declares."""
    parts = read_snapshot_parts(metadata.snapshot_manifest(snapshot_id))
    rows: list[dict] = []
    for path in parts.paths:
        rows.extend(pq.read_table(path).to_pylist())
    return rows


def _publish_baseline(client, session: FakeSession, tmp_path: Path):
    _seed(session)
    metadata = resolve_metadata_paths(tmp_path)
    cohort = fixture_cohort("cik_sec_mini.csv")
    plan = build_plan(
        cohort.roster,
        chunk_size=2,
        input_name=cohort.input_name,
        input_fingerprint=cohort.input_fingerprint,
    )
    run_paths = resolve_run_paths(plan.plan_id, metadata.artifacts_root)
    write_plan(plan, run_paths)
    for chunk_id in plan.chunk_ids():
        run_chunk(client, plan, run_paths, chunk_id, snapshot_id="base", workers=2)
    report = merge_chunks(plan, run_paths, "base")
    # A merge is not a publication; the manifest is the commit record.
    publish_snapshot(report, metadata)
    return metadata, cohort, plan, report


# ------------------------------------------------------------------ delta plan


def test_plan_delta_excludes_base_ciks(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """The base is read from published artifacts, so it must have been published."""
    metadata = _publish_partial_base(
        client, session, tmp_path, ("0000001985", "0000001761"), "base"
    )
    plan = derive_delta_plan(
        fixture_cohort("cik_sec_mini.csv").roster,
        metadata,
        chunk_size=2,
        base_snapshot_id="base",
    )
    assert plan.roster.range_ciks(0, plan.row_count) == ("0000000020", FORD)
    assert plan.kind == "delta"
    assert plan.parent_id == "base"


def test_an_empty_delta_is_refused_rather_than_planned(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, _cohort, _plan, _report = _publish_baseline(client, session, tmp_path)
    requested = fixture_cohort("cik_sec_mini.csv").roster
    with pytest.raises(MergeError, match="no work"):
        derive_delta_plan(
            requested,
            metadata,
            chunk_size=2,
            base_snapshot_id="base",
        )


def _publish_partial_base(
    client, session: FakeSession, tmp_path: Path, ciks, base_id: str
):
    """A base covering everything would leave an empty delta, the no-op case instead."""
    _seed(session)
    metadata = resolve_metadata_paths(tmp_path)
    plan = build_plan(roster_of(tuple(ciks)), chunk_size=1000)
    run_paths = resolve_run_paths(plan.plan_id, metadata.artifacts_root)
    write_plan(plan, run_paths)
    for chunk_id in plan.chunk_ids():
        run_chunk(client, plan, run_paths, chunk_id, snapshot_id=base_id, workers=2)
    report = merge_chunks(plan, run_paths, base_id)
    publish_snapshot(report, metadata)
    return metadata


def test_one_requested_list_against_two_bases_is_two_plans(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """One plan directory per base, or the second run overwrites the first plan."""
    requested = fixture_cohort("cik_sec_mini.csv").roster
    metadata_a = _publish_partial_base(
        client, session, tmp_path, ("0000001985",), "base-a"
    )
    metadata_b = _publish_partial_base(
        client, session, tmp_path, ("0000001985", "0000001761"), "base-b"
    )

    against_a = derive_delta_plan(
        requested, metadata_a, chunk_size=2, base_snapshot_id="base-a"
    )
    against_b = derive_delta_plan(
        requested, metadata_b, chunk_size=2, base_snapshot_id="base-b"
    )

    assert against_a.plan_id != against_b.plan_id
    assert against_a.roster.range_ciks(0, against_a.row_count) == (
        "0000000020",
        "0000001761",
        "0000037996",
    )
    assert against_b.roster.range_ciks(0, against_b.row_count) == (
        "0000000020",
        "0000037996",
    )


def test_a_delta_plan_never_shares_a_directory_with_a_full_plan(
    client, session: FakeSession, tmp_path: Path
) -> None:
    requested = fixture_cohort("cik_sec_mini.csv").roster
    metadata = _publish_partial_base(client, session, tmp_path, ("0000001985",), "base")
    full = build_plan(requested, chunk_size=2)
    delta = derive_delta_plan(
        requested, metadata, chunk_size=2, base_snapshot_id="base"
    )
    assert full.plan_id != delta.plan_id
    full_paths = resolve_run_paths(full.plan_id, tmp_path)
    delta_paths = resolve_run_paths(delta.plan_id, tmp_path)
    assert full_paths.plan_bundle != delta_paths.plan_bundle
    assert full_paths.chunk_dir != delta_paths.chunk_dir


def test_delta_refuses_an_empty_cohort(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, _cohort, _plan, _report = _publish_baseline(client, session, tmp_path)
    with pytest.raises(MergeError, match="no work"):
        derive_delta_plan(
            fixture_cohort("cik_sec_mini.csv").roster,
            metadata,
            chunk_size=2,
            base_snapshot_id="base",
        )


def test_the_delta_is_numbered_from_zero_and_is_reproducible(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """An ordinal is a position within a cohort, so a delta numbers from zero."""
    metadata = _publish_partial_base(client, session, tmp_path, ("0000001985",), "base")
    requested = fixture_cohort("cik_sec_mini.csv").roster

    first = derive_delta_plan(
        requested, metadata, chunk_size=2, base_snapshot_id="base"
    )
    second = derive_delta_plan(
        requested, metadata, chunk_size=2, base_snapshot_id="base"
    )
    delta_path = delta_roster_path(requested, metadata, "base")

    assert first.roster.roster_id == second.roster.roster_id
    assert delta_path.is_file()
    assert delta_path.is_relative_to(metadata.transient_dir("probe").parent)
    assert first.plan_id == second.plan_id
    assert first.row_count == 3
    assert first.chunk_start(0) == 0
    assert first.chunk_ciks(0) == ("0000000020", "0000001761")
    assert first.chunk_ciks(1) == (FORD,)


# ----------------------------------------------------------------- base lookup


def test_base_membership_is_read_from_the_published_index(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, _cohort, _plan, _report = _publish_baseline(client, session, tmp_path)
    sources, from_parts = base_cik_sources(metadata, "base")
    assert not from_parts, "a published base carries an index"
    assert sources == [str(metadata.snapshot_cik_index("base"))]


def test_base_membership_falls_back_to_the_payload(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """An index-less base still resolves; a missing base is never read as empty."""
    metadata, _cohort, _plan, _report = _publish_baseline(client, session, tmp_path)
    metadata.snapshot_cik_index("base").unlink()
    sources, from_parts = base_cik_sources(metadata, "base")
    assert from_parts
    assert sources, "the parts of a published base stand in for its index"


def test_a_missing_base_is_never_read_as_empty(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    with pytest.raises(FileNotFoundError):
        base_cik_sources(metadata, "absent")


# ---------------------------------------------------------------- augmentation


def test_augment_merges_base_and_delta_without_refetching_base(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, cohort, _, base_report = _publish_baseline(client, session, tmp_path)
    assert base_report.row_count == 4
    calls_after_base = len(session.calls)

    widened = tmp_path / "widened.csv"
    widened.write_text(
        "cik,name\n1985,A\n1761,B\n20,C\n37996,FORD\n5555,EXTRA CO\n", encoding="utf-8"
    )
    _seed(session, extra=True)

    result = augment(
        client,
        _published_roster(widened, metadata),
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
    assert sorted(ciks) == sorted(
        [*cohort.roster.range_ciks(0, cohort.row_count), EXTRA]
    )
    # Part order (base parts, then delta chunks), not global CIK sort.
    parts = read_snapshot_parts(metadata.snapshot_manifest("next"))
    assert [
        part["source"].split(":")[0] for part in parts.layout.manifest["parts"]
    ] == [
        "base",
        "base",
        "chunk",
    ]
    assert parts.layout.manifest["sort_order"] == "chunk_order"

    assert current_snapshot_id(metadata) == "next"


# --------------------------------------------------------------- progress


def test_an_augmentation_reports_both_of_its_phases(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """A bar needs the delta size before the first fetch event, hence `delta_plan`."""
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)

    events: list[dict] = []
    augment(
        client,
        _published_roster(widened, metadata),
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
    stages = [event["stage"] for event in events if event["type"] == "merge_stage"]
    assert stages == ["validating", "publishing_parts"]
    assert events[-1]["type"] == "readback_done"
    assert events[-1]["rows"] == 5


def test_progress_comes_before_the_publish_so_a_bar_never_overruns(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)

    events: list[dict] = []
    result = augment(
        client,
        _published_roster(widened, metadata),
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
    """Consistency: a merge also survives a raising progress callback."""
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)

    def explode(event: dict) -> None:
        raise RuntimeError("bar went away")

    result = augment(
        client,
        _published_roster(widened, metadata),
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
        _published_roster(widened, metadata),
        metadata,
        base_snapshot_id="base",
        chunk_size=2,
        workers=2,
    )
    assert result.delta_row_count == 1


# --------------------------------------------------- derived snapshot identity


def _widen(tmp_path: Path, session: FakeSession, *extra: str) -> Path:
    rows = "cik,name\n1985,A\n1761,B\n20,C\n37996,FORD\n"
    rows += "".join(f"{cik},EXTRA {cik}\n" for cik in extra)
    path = tmp_path / "widened.csv"
    path.write_text(rows, encoding="utf-8")
    _seed(session, extra=bool(extra))
    return path


def test_an_omitted_snapshot_id_publishes_under_the_delta_plan_id(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """Deriving it from the plan id is what makes a rerun idempotent."""
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)

    result = augment(
        client,
        _published_roster(widened, metadata),
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
    assert current_snapshot_id(metadata) == result.new_snapshot_id


def test_the_derived_id_is_stable_for_the_same_base_and_cohort(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)
    first = augment(
        client,
        _published_roster(widened, metadata),
        metadata,
        base_snapshot_id="base",
        chunk_size=2,
        workers=2,
    )
    second = augment(
        client,
        _published_roster(widened, metadata),
        metadata,
        base_snapshot_id="base",
        chunk_size=2,
        workers=2,
    )
    assert first.new_snapshot_id == second.new_snapshot_id


def test_a_different_base_or_chunk_layout_yields_a_different_id(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = _widen(tmp_path, session, EXTRA)
    _record, _paths, cohort_roster = publish_test_cohort(
        widened, metadata.artifacts_root
    )

    chunk_size_two = augment(
        client,
        cohort_roster,
        metadata,
        base_snapshot_id="base",
        chunk_size=2,
        workers=2,
    )
    chunk_size_one = augment(
        client,
        cohort_roster,
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
        _published_roster(widened, metadata),
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
    metadata, cohort, _, _ = _publish_baseline(client, session, tmp_path)
    widened = tmp_path / "widened.csv"
    widened.write_text("cik,name\n5555,EXTRA CO\n", encoding="utf-8")
    _seed(session, extra=True)

    result = augment(
        client,
        _published_roster(widened, metadata),
        metadata,
        base_snapshot_id="base",
        new_snapshot_id="next",
        chunk_size=2,
        workers=2,
    )
    index = read_cik_index(metadata.snapshot_cik_index("next"))
    assert list(index) == sorted(
        [*cohort.roster.range_ciks(0, cohort.row_count), EXTRA]
    )
    assert result.report.cik_count == len(index)
    assert result.report.cik_index_sha256


def test_augmented_manifest_records_its_lineage(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    widened = tmp_path / "widened.csv"
    widened.write_text("cik,name\n5555,EXTRA CO\n", encoding="utf-8")
    _seed(session, extra=True)

    result = augment(
        client,
        _published_roster(widened, metadata),
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
    """Base rows are copied verbatim; rewriting their stamp would misstate origin."""
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    base_stamps = {
        row["cik"]: row["snapshot_id"] for row in _snapshot_rows(metadata, "base")
    }
    widened = tmp_path / "widened.csv"
    widened.write_text("cik,name\n5555,EXTRA CO\n", encoding="utf-8")
    _seed(session, extra=True)
    augment(
        client,
        _published_roster(widened, metadata),
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


def test_augment_is_a_no_op_when_the_base_already_covers_the_request(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """Re-augmenting a fully ingested seed settles as a no-op rather than raising."""
    metadata, cohort, _, _ = _publish_baseline(client, session, tmp_path)
    pointer_before = current_snapshot_id(metadata)
    sessions_before = session.calls

    result = augment(
        client,
        cohort.roster,
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
    assert result.requested_cik_count == len(
        cohort.roster.range_ciks(0, cohort.row_count)
    )
    assert result.already_present_count == len(
        cohort.roster.range_ciks(0, cohort.row_count)
    )
    assert result.total_row_count == result.base_row_count
    assert session.calls == sessions_before
    assert metadata.snapshot_manifest("next").exists() is False
    assert current_snapshot_id(metadata) == pointer_before


def test_preflight_reports_the_work_before_anything_is_fetched(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, cohort, _, _ = _publish_baseline(client, session, tmp_path)
    requested = roster_of((*cohort.roster.range_ciks(0, cohort.row_count), EXTRA))

    check = preflight_augment(requested, metadata, base_snapshot_id="base")

    assert check.is_empty is False
    assert (
        check.requested_count == len(cohort.roster.range_ciks(0, cohort.row_count)) + 1
    )
    assert check.already_present_count == len(
        cohort.roster.range_ciks(0, cohort.row_count)
    )
    assert check.delta_count == 1
    assert "to fetch" in check.describe()


def test_preflight_reports_an_empty_delta_without_raising(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, cohort, _, _ = _publish_baseline(client, session, tmp_path)
    check = preflight_augment(cohort.roster, metadata, base_snapshot_id="base")
    assert check.is_empty is True
    assert check.delta_count == 0
    assert check.already_present_count == check.requested_count


def test_a_delta_calling_itself_a_delta_is_still_reduced_against_the_base(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """A hand-supplied increment is a request, not a claim about what is missing."""
    metadata, cohort, _, _ = _publish_baseline(client, session, tmp_path)
    already_covered = roster_of(cohort.roster.range_ciks(0, cohort.row_count))
    check = preflight_augment(already_covered, metadata, base_snapshot_id="base")
    assert check.is_empty is True


def test_augment_requires_an_existing_base(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    cohort = fixture_cohort("cik_sec_mini.csv")
    with pytest.raises(FileNotFoundError):
        augment(
            client,
            cohort.roster,
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
