"""Source registry and delta augmentation tests.

The augmentation contract under test: a snapshot holding N CIKs that receives
K new ones publishes N+K rows, and the N base CIKs are never refetched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

from edgar_sec.domain.sec_urls import submissions_url
from edgar_sec.pipelines.metadata_sync.augmentation import (
    augment,
    augment_from_manifest,
    base_snapshot_ciks,
    plan_delta,
)
from edgar_sec.pipelines.metadata_sync.checkpoints import discover_completed_chunks
from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from edgar_sec.pipelines.metadata_sync.merger import MergeError, merge_chunks
from edgar_sec.pipelines.metadata_sync.paths import (
    resolve_metadata_paths,
    resolve_run_paths,
)
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from edgar_sec.pipelines.metadata_sync.worker import run_chunk
from tests.support import FakeSession, fixture_path, load_fixture

FORD = "0000037996"
EXTRA = "0000005555"
HIST_URL = f"https://data.sec.gov/submissions/CIK{FORD}-submissions-001.json"


def _cik_payload(cik: str, name: str) -> dict:
    return {
        "name": name,
        "filings": {
            "recent": {
                "accessionNumber": [f"{cik}-26-000001"],
                "filingDate": ["2026-01-02"],
                "form": ["10-K"],
                "size": [1024],
            },
            "files": [],
        },
    }


def _seed(session: FakeSession, extra: bool = False) -> None:
    session.register(submissions_url(FORD), load_fixture("recent_submissions.json"))
    session.register(HIST_URL, load_fixture("historical_submissions.json"))
    session.register(submissions_url("0000001985"), _cik_payload("0000001985", "ACCEL"))
    session.register(
        submissions_url("0000001761"), _cik_payload("0000001761", "TRANZONIC")
    )
    session.register(
        submissions_url("0000000020"), _cik_payload("0000000020", "K TRON")
    )
    if extra:
        session.register(submissions_url(EXTRA), _cik_payload(EXTRA, "EXTRA CO"))


def _publish_baseline(client, session: FakeSession, tmp_path: Path):
    _seed(session)
    metadata = resolve_metadata_paths(tmp_path)
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    plan = build_plan(manifest, chunk_size=2, partition_count=1)
    run_paths = resolve_run_paths(plan["plan_id"], metadata.artifacts_root)
    write_plan(plan, run_paths)
    for chunk in plan["chunks"]:
        run_chunk(
            client,
            plan,
            run_paths,
            int(chunk["chunk_id"]),
            snapshot_id="base",
            workers=2,
        )
    report = merge_chunks(plan, run_paths, "base")
    return metadata, manifest, plan, report


# ------------------------------------------------------------ source registry


# ------------------------------------------------------------------ delta plan


def test_plan_delta_excludes_base_ciks(tmp_path: Path) -> None:
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    base = {"0000001985", "0000001761"}
    plan = plan_delta(manifest, base, chunk_size=2)
    assert plan["cik_padded"] == ["0000000020", FORD]
    assert plan["is_empty"] is False


def test_plan_delta_reports_empty_when_all_present() -> None:
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    plan = plan_delta(manifest, set(manifest.ciks), chunk_size=2)
    assert plan["is_empty"] is True
    assert plan["cik_padded"] == []


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


def test_augment_base_snapshot_is_preserved_verbatim(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, _, _, _ = _publish_baseline(client, session, tmp_path)
    base_table = pq.read_table(metadata.snapshot_file("base"))

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

    next_table = pq.read_table(metadata.snapshot_file("next"))
    base_rows = {row["cik"]: row for row in base_table.to_pylist()}
    for row in next_table.to_pylist():
        if row["cik"] in base_rows:
            assert row == base_rows[row["cik"]]


def test_augment_rejects_when_nothing_new(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest, _, _ = _publish_baseline(client, session, tmp_path)
    try:
        augment(
            client,
            manifest,
            metadata,
            base_snapshot_id="base",
            new_snapshot_id="next",
            chunk_size=2,
        )
    except MergeError as exc:
        assert "no work" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected MergeError")


def test_augment_requires_existing_base(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    try:
        augment(
            client,
            manifest,
            metadata,
            base_snapshot_id="missing",
            new_snapshot_id="next",
            chunk_size=2,
        )
    except FileNotFoundError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected FileNotFoundError")


def test_base_snapshot_ciks_reads_published_set(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest, plan, _ = _publish_baseline(client, session, tmp_path)
    assert base_snapshot_ciks(metadata, "base") == set(manifest.ciks)
    completed = discover_completed_chunks(
        plan, resolve_run_paths(plan["plan_id"], metadata.artifacts_root)
    )
    assert set(completed) == {0, 1}
