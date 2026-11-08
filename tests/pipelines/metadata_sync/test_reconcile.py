"""Daily-index reconciliation: the index names missing accessions; canonical
rows still come from the per-CIK fetch, and a zero-diff range publishes nothing.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.sec_urls import daily_index_url, submissions_url
from edgar_sec.infra.sec_http.errors import PermanentHttpError
from edgar_sec.pipelines.metadata_sync.commands.reconcile import cmd_reconcile
from edgar_sec.pipelines.metadata_sync.discovery import current_snapshot_id
from edgar_sec.pipelines.metadata_sync.merger import merge_chunks, publish_snapshot
from edgar_sec.pipelines.metadata_sync.options import reconcile_options
from edgar_sec.pipelines.metadata_sync.paths import (
    resolve_metadata_paths,
    resolve_run_paths,
)
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from edgar_sec.pipelines.metadata_sync.reconcile import reconcile
from edgar_sec.pipelines.metadata_sync.snapshot import resolve_snapshot_parts
from edgar_sec.pipelines.metadata_sync.worker import run_chunk
from tests.support import FakeSession, roster_of

A = "0000001985"
B = "0000001761"
C = "0000000020"
D = "0000005555"
OLD_ACCEPTANCE = "2026-01-02T00:00:00.000Z"
NEW_A = "0000001985-26-000099"
NEW_D = "0000005555-26-000007"
DAY = date(2026, 11, 6)


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


def _idx_row(cik: str, name: str, accession: str) -> str:
    return f"{int(cik)}|{name}|8-K|20261106|edgar/data/{int(cik)}/{accession}.txt"


def _index_bytes(rows: list[str]) -> bytes:
    lines = [
        "Description:           Daily Index of EDGAR Dissemination Feed",
        "Last Data Received:    Nov 6, 2026",
        "",
        "CIK|Company Name|Form Type|Date Filed|File Name",
        "-" * 80,
        *rows,
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _index_payload() -> bytes:
    return _index_bytes(
        [
            _idx_row(A, "ACCEL", NEW_A),
            _idx_row(B, "TRANZONIC", f"{B}-26-000001"),
            _idx_row(D, "EXTRA CO", NEW_D),
            "garbage row with no pipes",
        ]
    )


def _fetch(payloads: dict[str, bytes]):
    def fetch(url: str) -> bytes:
        if url not in payloads:
            raise PermanentHttpError(url, "not found", 404)
        return payloads[url]

    return fetch


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


def test_reconcile_publishes_exactly_the_index_proven_missing(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata = _publish_baseline(client, session, tmp_path)
    base_rows = _rows(metadata, "base")
    _register_refetch(session)
    calls_after_base = len(session.calls)

    result = reconcile(
        client,
        metadata,
        start_date=DAY,
        end_date=DAY,
        fetch_bytes=_fetch({daily_index_url(DAY): _index_payload()}),
        chunk_size=2,
        workers=2,
        new_snapshot_id="next",
    )

    assert not result.no_op
    assert result.days_pulled == 1
    assert result.days_missing == 0
    assert result.index_rows == 3
    assert result.malformed_rows == 1
    assert result.missing_accessions == tuple(
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
    assert _accessions(rows[D]) == {NEW_D}


def test_a_repeat_reconcile_is_a_no_op(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata = _publish_baseline(client, session, tmp_path)
    _register_refetch(session)
    fetch = _fetch({daily_index_url(DAY): _index_payload()})
    first = reconcile(
        client,
        metadata,
        start_date=DAY,
        end_date=DAY,
        fetch_bytes=fetch,
        chunk_size=2,
        workers=2,
        new_snapshot_id="next",
    )
    assert not first.no_op

    second = reconcile(
        client, metadata, start_date=DAY, end_date=DAY, fetch_bytes=fetch, workers=2
    )

    assert second.no_op
    assert second.new_snapshot_id == ""
    assert second.missing_accessions == ()
    assert current_snapshot_id(metadata) == "next"


def test_a_range_of_unpublished_days_is_a_no_op(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata = _publish_baseline(client, session, tmp_path)
    result = reconcile(
        client,
        metadata,
        start_date=date(2026, 11, 7),
        end_date=date(2026, 11, 8),
        fetch_bytes=_fetch({}),
        workers=2,
    )
    assert result.no_op
    assert result.days_pulled == 0
    assert result.days_missing == 2
    assert current_snapshot_id(metadata) == "base"


def test_reconcile_rejects_a_reversed_range(
    client, session: FakeSession, tmp_path: Path
) -> None:
    metadata = _publish_baseline(client, session, tmp_path)
    with pytest.raises(ValueError):
        reconcile(
            client,
            metadata,
            start_date=date(2026, 11, 8),
            end_date=date(2026, 11, 6),
            fetch_bytes=_fetch({}),
            workers=2,
        )


def test_cmd_reconcile_publishes_and_reports(
    client, session: FakeSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    metadata = _publish_baseline(client, session, tmp_path)
    _register_refetch(session)

    code = cmd_reconcile(
        reconcile_options(
            start_date="2026-11-06",
            end_date="2026-11-06",
            artifacts_root=tmp_path,
            chunk_size=2,
            workers=2,
        ),
        client=client,
        fetch_bytes=_fetch({daily_index_url(DAY): _index_payload()}),
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "no_op" in out and "False" in out
    tip = current_snapshot_id(metadata)
    assert tip and tip != "base"
    assert set(_rows(metadata, tip)) == {A, B, C, D}
