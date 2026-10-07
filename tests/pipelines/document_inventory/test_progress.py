"""Transactional S4 progress journal recovery and identity checks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from edgar_sec.domain.document_inventory.models import IndexPageInput, IndexWorkItem
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.document_inventory.paths import inventory_run_paths
from edgar_sec.pipelines.document_inventory.progress import open_progress
from edgar_sec.pipelines.document_inventory.run_manifest import (
    iter_work_order_chunks,
    write_run_manifest,
    write_work_order,
)

ACCESSION = AccessionNumber.from_any("000012345626000016")
OTHER = AccessionNumber.from_any("000012345626000017")
INDEX_URL = "https://example.test/000012345626000016-index.htm"
IDENTITY = {
    "parent_snapshot_id": "snap-1",
    "canonical_cohort_id": "cohort-1",
    "source_identity": "source-1",
    "parser_version": "parser-1",
    "chunk_size": 4,
    "refresh_mode": "normal",
    "fetch_mode": "live",
}
HTML = b"""<table summary='Document Format Files'>
<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
<tr><td>1</td><td>report</td><td><a href='/Archives/edgar/data/1/000012345626000016/report.htm'>report.htm</a></td><td>10-K</td><td>9</td></tr>
</table>"""


def _setup(tmp_path: Path):
    paths = inventory_run_paths(tmp_path, "progress-run")
    items = [
        IndexWorkItem(ACCESSION, INDEX_URL),
        IndexWorkItem(OTHER, "https://example.test/other-index.htm"),
    ]
    write_work_order(paths.work_order_path(), items)
    run = write_run_manifest(paths, work_order_path=paths.work_order_path(), **IDENTITY)
    chunk, members = next(
        iter_work_order_chunks(
            paths.work_order_path(),
            chunk_size=run.chunk_size,
            work_order_version=run.work_order_version,
        )
    )
    parsed = parse_html_index(IndexPageInput(ACCESSION, INDEX_URL, HTML))
    return paths, run, chunk, members, parsed, derive_resources()


def test_committed_parse_survives_reopen_and_interrupted_parse_rolls_back(
    tmp_path: Path,
) -> None:
    paths, run, chunk, members, parsed, profile = _setup(tmp_path)
    store = open_progress(paths, chunk, run, profile=profile)
    store.record(parsed, index_url=INDEX_URL)
    connection = store._con

    class _FailBeforeCompletion:
        def execute(self, query, *args):  # noqa: ANN001
            if query == "INSERT INTO completed VALUES (?)":
                raise RuntimeError("injected interruption")
            return connection.execute(query, *args)

        def __getattr__(self, name):  # noqa: ANN204
            return getattr(connection, name)

    store._con = _FailBeforeCompletion()
    other = parse_html_index(
        IndexPageInput(OTHER, "https://example.test/other-index.htm", HTML)
    )
    with pytest.raises(RuntimeError, match="injected interruption"):
        store.record(other, index_url="https://example.test/other-index.htm")
    store._con = connection
    attempt_id = store.attempt_id
    store.close()

    reopened = open_progress(paths, chunk, run, profile=profile)
    assert reopened.attempt_id == attempt_id
    assert reopened.completed_accessions(members) == (str(OTHER),)
    outcomes, refusals, entries = reopened.counts()
    assert outcomes == 1
    assert refusals == 0
    assert entries == len(parsed.entries)
    reopened.close()


def test_wrong_progress_identity_starts_a_new_database(tmp_path: Path) -> None:
    paths, run, chunk, _members, parsed, profile = _setup(tmp_path)
    first = open_progress(paths, chunk, run, profile=profile)
    first.record(parsed, index_url=INDEX_URL)
    first_id = first.attempt_id
    first.close()

    changed = replace(run, parser_version="parser-2")
    replacement = open_progress(paths, chunk, changed, profile=profile)
    try:
        assert replacement.attempt_id != first_id
        assert replacement.counts() == (0, 0, 0)
    finally:
        replacement.close()


def test_structurally_invalid_journal_is_replaced(tmp_path: Path) -> None:
    paths, run, chunk, _members, parsed, profile = _setup(tmp_path)
    first = open_progress(paths, chunk, run, profile=profile)
    first.record(parsed, index_url=INDEX_URL)
    first_id = first.attempt_id
    first.close()

    database = paths.progress_database_path(chunk.chunk_id, first_id)
    with connect(profile=profile, database=database) as con:
        con.execute("UPDATE progress_metadata SET payload = '{}' ")

    replacement = open_progress(paths, chunk, run, profile=profile)
    try:
        assert replacement.attempt_id != first_id
        assert replacement.counts() == (0, 0, 0)
    finally:
        replacement.close()
