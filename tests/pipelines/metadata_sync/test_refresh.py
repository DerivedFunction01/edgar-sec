"""Feed refresh: the feed names affected CIKs; canonical rows come from fetch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from edgar_sec.apps.client.cache import DocumentCache
from edgar_sec.apps.client.fast_query.submissions import collect_submissions_fallback
from edgar_sec.domain.sec_urls import current_filings_url, submissions_url
from edgar_sec.engine.feeds.client import FeedClient
from edgar_sec.pipelines.metadata_sync.commands.refresh import cmd_refresh
from edgar_sec.pipelines.metadata_sync.discovery import current_snapshot_id
from edgar_sec.pipelines.metadata_sync.merger import merge_chunks, publish_snapshot
from edgar_sec.pipelines.metadata_sync.options import refresh_options
from edgar_sec.pipelines.metadata_sync.paths import (
    resolve_metadata_paths,
    resolve_run_paths,
)
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from edgar_sec.pipelines.metadata_sync.refresh import refresh
from edgar_sec.pipelines.metadata_sync.snapshot import (
    SnapshotCatalogError,
    resolve_snapshot_parts,
)
from edgar_sec.pipelines.metadata_sync.worker import run_chunk
from tests.support import FakeSession, build_test_http, roster_of

A = "0000001985"
B = "0000001761"
C = "0000000020"
D = "0000005555"
OLD_ACCEPTANCE = "2026-01-02T00:00:00.000Z"
NEW_A = "0000001985-26-000099"
NEW_D = "0000005555-26-000007"
FEED_UPDATED = "2026-11-06T21:55:03-05:00"


def _payload(cik: str, name: str, accession: str, acceptance: str) -> dict[str, Any]:
    return {
        "name": name,
        "filings": {
            "recent": {
                "accessionNumber": [accession],
                "filingDate": ["2026-11-06"],
                "reportDate": ["2026-11-05"],
                "acceptanceDateTime": [acceptance],
                "form": ["8-K"],
                "primaryDocument": ["doc.htm"],
                "size": [100],
            },
            "files": [],
        },
    }


def _old(cik: str, name: str) -> dict[str, Any]:
    return _payload(cik, name, f"{cik}-26-000001", OLD_ACCEPTANCE)


def _entry(cik: str, company: str, accession: str, updated: str) -> str:
    return (
        f"<entry><title>8-K - {company} ({cik}) (Issuer)</title>"
        f'<link rel="alternate" type="text/html" '
        f'href="https://www.sec.gov/Archives/edgar/data/{int(cik)}/x-index.htm"/>'
        f'<summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2026-11-06 '
        f"&lt;b&gt;AccNo:&lt;/b&gt; {accession} &lt;b&gt;Size:&lt;/b&gt; 5 KB</summary>"
        f"<updated>{updated}</updated></entry>"
    )


def _atom(entries: list[str]) -> bytes:
    body = "".join(entries)
    return (
        f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'
    ).encode("utf-8")


_EMPTY = _atom([])


def _feed_client(session: FakeSession) -> FeedClient:
    return FeedClient(build_test_http(session), page_size=2)


def _register_feed(session: FakeSession) -> None:
    session.register_bytes(
        current_filings_url(count=2, start=0),
        _atom(
            [
                _entry(A, "ACCEL", NEW_A, FEED_UPDATED),
                _entry(B, "TRANZONIC", f"{B}-26-000001", FEED_UPDATED),
            ]
        ),
    )
    session.register_bytes(
        current_filings_url(count=2, start=2),
        _atom([_entry(D, "EXTRA CO", NEW_D, "2026-11-06T21:54:24-05:00")]),
    )
    session.register_bytes(current_filings_url(count=2, start=3), _EMPTY)


def _publish_baseline(client, session: FakeSession, tmp_path: Path):
    for cik, name in ((A, "ACCEL"), (B, "TRANZONIC"), (C, "K TRON")):
        session.register(submissions_url(cik), _old(cik, name))
    metadata = resolve_metadata_paths(tmp_path)
    plan = build_plan(roster_of((A, B, C)), chunk_size=2)
    run_paths = resolve_run_paths(plan.plan_id, metadata.artifacts_root)
    write_plan(plan, run_paths)
    for chunk_id in plan.chunk_ids():
        run_chunk(client, plan, run_paths, chunk_id, snapshot_id="base", workers=2)
    report = merge_chunks(plan, run_paths, "base")
    publish_snapshot(report, metadata)
    return metadata


def _register_refetch(session: FakeSession) -> None:
    session.register(
        submissions_url(A),
        _payload(A, "ACCEL", NEW_A, "2026-11-06T12:00:00.000Z"),
    )
    session.register(
        submissions_url(D),
        _payload(D, "EXTRA CO", NEW_D, "2026-11-06T12:00:00.000Z"),
    )


def _rows(metadata, snapshot_id: str) -> dict[str, dict[str, Any]]:
    parts = resolve_snapshot_parts(metadata, snapshot_id)
    rows: dict[str, dict[str, Any]] = {}
    for path in parts.paths:
        for row in pq.read_table(path).to_pylist():
            rows[str(row["cik"])] = row
    return rows


def _accessions(row: dict[str, Any]) -> set[str]:
    return {str(f["accession_number"]) for f in row["filings"]}


def test_refresh_replaces_only_affected_and_carries_the_rest(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata = _publish_baseline(client, session, tmp_path)
    base_rows = _rows(metadata, "base")
    _register_feed(session)
    _register_refetch(session)
    calls_after_base = len(session.calls)

    result = refresh(
        client,
        _feed_client(session),
        metadata,
        chunk_size=2,
        workers=2,
        new_snapshot_id="next",
    )

    assert not result.no_op
    assert result.events_seen == 3
    assert result.pages_pulled == 3
    assert result.parse_failures == 0
    assert result.new_accessions == tuple(
        sorted([NEW_A.replace("-", ""), NEW_D.replace("-", "")])
    )
    assert result.affected_ciks == (A, D)
    assert result.carried_rows == 2
    assert result.normalized_rows == 2
    assert result.base_row_count == 3
    assert result.total_row_count == 4
    assert current_snapshot_id(metadata) == "next"

    fetched = {url for url in session.calls[calls_after_base:]}
    assert submissions_url(A) in fetched
    assert submissions_url(D) in fetched
    assert submissions_url(B) not in fetched
    assert submissions_url(C) not in fetched

    rows = _rows(metadata, "next")
    assert set(rows) == {A, B, C, D}
    assert rows[B] == base_rows[B]
    assert rows[C] == base_rows[C]
    assert _accessions(rows[A]) == {NEW_A}
    assert rows[A]["snapshot_id"] == "next"
    assert _accessions(rows[D]) == {NEW_D}


def test_a_repeat_refresh_is_a_no_op(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata = _publish_baseline(client, session, tmp_path)
    _register_feed(session)
    _register_refetch(session)
    first = refresh(
        client,
        _feed_client(session),
        metadata,
        chunk_size=2,
        workers=2,
        new_snapshot_id="next",
    )
    assert not first.no_op

    second = refresh(client, _feed_client(session), metadata, workers=2)

    assert second.no_op
    assert second.new_snapshot_id == ""
    assert second.affected_ciks == ()
    assert second.events_seen == 3
    assert current_snapshot_id(metadata) == "next"


def test_the_facade_serves_a_refreshed_cik_without_http(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata = _publish_baseline(client, session, tmp_path)
    _register_feed(session)
    _register_refetch(session)
    refresh(
        client,
        _feed_client(session),
        metadata,
        chunk_size=2,
        workers=2,
        new_snapshot_id="next",
    )

    class Exploding:
        def get_bytes(self, url: str) -> bytes:
            raise AssertionError(f"unexpected HTTP fetch: {url}")

    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    items = collect_submissions_fallback(
        [A], None, None, None, {}, Exploding(), cache, artifacts_root=tmp_path
    )
    assert [item.accession.raw for item in items] == [NEW_A]


def test_a_page_at_or_before_the_tip_bound_stops_the_walk(
    client, session: FakeSession, tmp_path: Path
) -> None:
    for cik, name in ((A, "ACCEL"), (B, "TRANZONIC"), (C, "K TRON")):
        session.register(
            submissions_url(cik),
            _payload(cik, name, f"{cik}-26-000001", "2026-11-07T03:00:00.000Z"),
        )
    metadata = resolve_metadata_paths(tmp_path)
    plan = build_plan(roster_of((A, B, C)), chunk_size=2)
    run_paths = resolve_run_paths(plan.plan_id, metadata.artifacts_root)
    write_plan(plan, run_paths)
    for chunk_id in plan.chunk_ids():
        run_chunk(client, plan, run_paths, chunk_id, snapshot_id="base", workers=2)
    publish_snapshot(merge_chunks(plan, run_paths, "base"), metadata)
    session.register_bytes(
        current_filings_url(count=2, start=0),
        _atom([_entry(A, "ACCEL", NEW_A, FEED_UPDATED)]),
    )
    calls_after_base = len(session.calls)

    result = refresh(client, _feed_client(session), metadata, workers=2)

    assert result.no_op
    assert result.pages_pulled == 1
    assert result.events_seen == 1
    assert session.calls[calls_after_base:] == [current_filings_url(count=2, start=0)]
    assert current_snapshot_id(metadata) == "base"


def test_refresh_without_a_tip_is_refused(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    with pytest.raises(SnapshotCatalogError):
        refresh(client, _feed_client(session), metadata, workers=2)


def test_cmd_refresh_publishes_and_reports(
    client, session: FakeSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    metadata = _publish_baseline(client, session, tmp_path)
    _register_feed(session)
    _register_refetch(session)

    code = cmd_refresh(
        refresh_options(artifacts_root=tmp_path, chunk_size=2, workers=2),
        client=client,
        feed_client=_feed_client(session),
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "no_op" in out and "False" in out
    tip = current_snapshot_id(metadata)
    assert tip and tip != "base"
    assert set(_rows(metadata, tip)) == {A, B, C, D}
