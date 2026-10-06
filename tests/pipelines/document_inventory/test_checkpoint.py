"""Chunk attempt commit, pointer-advance, and resume validation contracts."""

from pathlib import Path

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.document_inventory.models import (
    IndexPageInput,
    IndexParseFailure,
    IndexParseOutcome,
    ParsedIndexPage,
    ParserDiagnostic,
    ParserDiagnostics,
    UnrecognizedIndexPage,
)
from edgar_sec.domain.document_inventory.models import IndexWorkItem
from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.pipelines.document_inventory.broker import IndexFetchFailure
from edgar_sec.pipelines.document_inventory.checkpoint import (
    AttemptValidationError,
    AttemptWriters,
    OUTCOME_SCHEMA,
    PARSER_REFUSAL_STATUSES,
    REFUSAL_STATUSES,
    RETRYABLE_STATUSES,
    advance_pointer,
    entry_rows,
    finalize_attempt,
    new_attempt_id,
    outcome_row,
    read_attempt_manifest,
    read_outcome_rows,
    split_retryable,
    validate_committed_chunk,
)
from edgar_sec.pipelines.document_inventory.worker import IndexWorkerFailure
from edgar_sec.pipelines.document_inventory.paths import inventory_run_paths
from edgar_sec.pipelines.document_inventory.run_manifest import (
    partition_into_chunks,
    write_run_manifest,
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

INDEX_HTML = b"""<table summary='Document Format Files'>
<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
<tr><td>1</td><td>report</td><td><a href='/Archives/edgar/data/1/000012345626000016/report.htm'>report.htm</a></td><td>10-K</td><td>9</td></tr>
</table>"""


def _parsed(accession: AccessionNumber = ACCESSION) -> ParsedIndexPage:
    from edgar_sec.engine.index_pages.parser import parse_html_index

    result = parse_html_index(IndexPageInput(accession, INDEX_URL, INDEX_HTML))
    assert isinstance(result, ParsedIndexPage)
    return result


def _run_manifest(tmp_path: Path, items: list) -> tuple:
    paths = inventory_run_paths(tmp_path, "run-1")
    manifest = write_run_manifest(paths, work_items=items, **IDENTITY)
    chunk = partition_into_chunks(
        items,
        chunk_size=manifest.chunk_size,
        work_order_version=manifest.work_order_version,
    )[0]
    chunk_id, *members = chunk
    identity = next(ci for ci in manifest.chunk_identities if ci.chunk_id == chunk_id)
    return paths, manifest, chunk_id, tuple(members), identity


def _commit(
    tmp_path: Path,
    results: list,
    items: list,
) -> tuple:
    paths, manifest, chunk_id, members, identity = _run_manifest(tmp_path, items)
    attempt = new_attempt_id()
    writers = AttemptWriters(paths, chunk_id, attempt)
    for result in results:
        url = INDEX_URL if result.accession == ACCESSION else "https://x.test/o.htm"
        writers.add(outcome_row(result, index_url=url), entry_rows(result))
    writers.close()
    finalize_attempt(
        paths,
        chunk_id,
        attempt,
        membership=tuple(str(m.accession) for m in members),
        run=manifest,
    )
    return paths, manifest, chunk_id, identity, attempt


def test_status_sets_partition_outcomes() -> None:
    assert RETRYABLE_STATUSES == {"fetch_failed", "worker_error"}
    assert PARSER_REFUSAL_STATUSES == {"unrecognized", "parse_failure"}
    assert RETRYABLE_STATUSES | PARSER_REFUSAL_STATUSES == REFUSAL_STATUSES
    assert not RETRYABLE_STATUSES & PARSER_REFUSAL_STATUSES


def test_outcome_row_for_parsed_page() -> None:
    row = outcome_row(_parsed(), index_url=INDEX_URL, response_size=4321)
    assert row["accession"] == str(ACCESSION)
    assert row["status"] == "parsed"
    assert row["entry_count"] == 1
    assert row["response_size"] == 4321
    assert row["page_sha256"]
    assert row["error_code"] is None


def test_outcome_row_for_fetch_failure_is_empty_of_entries() -> None:
    failure = IndexFetchFailure(ACCESSION, "fetch_failed", "404")
    row = outcome_row(failure, index_url=INDEX_URL)
    assert row["status"] == "fetch_failed"
    assert row["entry_count"] == 0
    assert row["page_sha256"] is None
    assert row["error_detail"] == "404"
    assert entry_rows(failure) == []


def test_outcome_row_keeps_parser_diagnostics_inline() -> None:
    diagnostic = ParserDiagnostic("table_not_found", None, "missing table")
    failure = IndexParseFailure(
        ACCESSION, INDEX_URL, page_sha256="abc", diagnostic=diagnostic
    )
    row = outcome_row(failure, index_url=INDEX_URL)
    assert row["status"] == "parse_failure"
    assert row["diagnostics_json"]
    assert row["error_code"] == "table_not_found"


def test_worker_failure_status_uses_its_code() -> None:
    failure = IndexWorkerFailure(ACCESSION, "worker_error", "boom")
    row = outcome_row(failure, index_url=INDEX_URL)
    assert row["status"] == "worker_error"
    assert row["status"] in RETRYABLE_STATUSES
    assert row["status"] not in PARSER_REFUSAL_STATUSES


def test_unrecognized_page_is_not_retryable() -> None:
    page = UnrecognizedIndexPage(
        ACCESSION, INDEX_URL, page_sha256="abc", diagnostics=ParserDiagnostics((), 0)
    )
    row = outcome_row(page, index_url=INDEX_URL)
    assert row["status"] == "unrecognized"
    _, retry = split_retryable([row])
    assert retry == set()


def test_split_retryable_separates_transport_from_parser() -> None:
    rows = [
        {"accession": "a", "status": "parsed"},
        {"accession": "b", "status": "fetch_failed"},
        {"accession": "c", "status": "worker_error"},
        {"accession": "d", "status": "unrecognized"},
    ]
    carry, retry = split_retryable(rows)
    assert retry == {"b", "c"}
    assert {row["accession"] for row in carry} == {"a", "d"}


def test_commit_advances_pointer_and_validates(tmp_path: Path) -> None:
    items = [
        IndexWorkItem(accession=ACCESSION, index_url=INDEX_URL),
        IndexWorkItem(accession=OTHER, index_url="https://x.test/o.htm"),
    ]
    paths, manifest, chunk_id, identity, attempt = _commit(
        tmp_path, [_parsed(), IndexFetchFailure(OTHER, "fetch_failed", "boom")], items
    )
    validation = validate_committed_chunk(paths, chunk_id, run=manifest, chunk=identity)
    assert validation.valid
    assert validation.attempt_id == attempt
    assert validation.manifest is not None
    assert validation.manifest.outcomes_rows == 2
    assert not list(paths.run_root.rglob("*.tmp"))


def test_missing_pointer_never_validates(tmp_path: Path) -> None:
    items = [IndexWorkItem(accession=ACCESSION, index_url=INDEX_URL)]
    paths, manifest, chunk_id, identity, _attempt = _commit(
        tmp_path, [_parsed()], items
    )
    pointer = paths.chunk_pointer_path(chunk_id)
    pointer.unlink()
    validation = validate_committed_chunk(paths, chunk_id, run=manifest, chunk=identity)
    assert not validation.valid
    assert validation.reason == "no chunk pointer"


def test_attempt_without_manifest_never_validates(tmp_path: Path) -> None:
    items = [IndexWorkItem(accession=ACCESSION, index_url=INDEX_URL)]
    paths, manifest, chunk_id, identity, attempt = _commit(tmp_path, [_parsed()], items)
    paths.attempt_manifest_path(chunk_id, attempt).unlink()
    validation = validate_committed_chunk(paths, chunk_id, run=manifest, chunk=identity)
    assert not validation.valid
    assert "manifest" in validation.reason


def test_tampered_outcomes_file_is_rejected(tmp_path: Path) -> None:
    items = [IndexWorkItem(accession=ACCESSION, index_url=INDEX_URL)]
    paths, manifest, chunk_id, identity, attempt = _commit(tmp_path, [_parsed()], items)
    outcomes = paths.attempt_outcomes_path(chunk_id, attempt)
    outcomes.write_bytes(outcomes.read_bytes() + b"corruption")
    validation = validate_committed_chunk(paths, chunk_id, run=manifest, chunk=identity)
    assert not validation.valid


def test_stale_schema_version_is_rejected(tmp_path: Path) -> None:
    items = [IndexWorkItem(accession=ACCESSION, index_url=INDEX_URL)]
    paths, manifest, chunk_id, identity, attempt = _commit(tmp_path, [_parsed()], items)
    import json

    manifest_path = paths.attempt_manifest_path(chunk_id, attempt)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["outcome_schema_version"] = 99
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    validation = validate_committed_chunk(paths, chunk_id, run=manifest, chunk=identity)
    assert not validation.valid
    assert "schema" in validation.reason


def test_wrong_membership_in_manifest_is_rejected(tmp_path: Path) -> None:
    items = [
        IndexWorkItem(accession=ACCESSION, index_url=INDEX_URL),
        IndexWorkItem(accession=OTHER, index_url="https://x.test/o.htm"),
    ]
    paths, manifest, chunk_id, identity, attempt = _commit(
        tmp_path, [_parsed(), IndexFetchFailure(OTHER, "fetch_failed", "x")], items
    )
    import json

    manifest_path = paths.attempt_manifest_path(chunk_id, attempt)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["membership_digest"] = "0" * 64
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    validation = validate_committed_chunk(paths, chunk_id, run=manifest, chunk=identity)
    assert not validation.valid


def test_crash_before_pointer_keeps_prior_commit(tmp_path: Path) -> None:
    items = [IndexWorkItem(accession=ACCESSION, index_url=INDEX_URL)]
    paths, manifest, chunk_id, identity, first = _commit(tmp_path, [_parsed()], items)
    orphan = new_attempt_id()
    writers = AttemptWriters(paths, chunk_id, orphan)
    writers.add(
        outcome_row(
            IndexFetchFailure(ACCESSION, "fetch_failed", "x"), index_url=INDEX_URL
        )
    )
    writers.close()
    manifest_path = paths.attempt_manifest_path(chunk_id, orphan)
    assert not manifest_path.is_file()
    validation = validate_committed_chunk(paths, chunk_id, run=manifest, chunk=identity)
    assert validation.valid
    assert validation.attempt_id == first


def test_schema_and_row_roundtrip(tmp_path: Path) -> None:
    items = [IndexWorkItem(accession=ACCESSION, index_url=INDEX_URL)]
    paths, _manifest, chunk_id, _identity, attempt = _commit(
        tmp_path, [_parsed()], items
    )
    rows = read_outcome_rows(paths, chunk_id, attempt)
    assert len(rows) == 1
    assert rows[0]["status"] == "parsed"
    loaded = read_attempt_manifest(paths, chunk_id, attempt)
    assert loaded is not None
    assert loaded.chunk_id == chunk_id
    assert OUTCOME_SCHEMA.names[0] == "accession"
    assert ENTRY_SCHEMA.names[0] == "entry_id"


def test_finalize_rejects_membership_mismatch(tmp_path: Path) -> None:
    items = [IndexWorkItem(accession=ACCESSION, index_url=INDEX_URL)]
    paths, manifest, chunk_id, _identity, attempt = _run_manifest(tmp_path, items)
    attempt = new_attempt_id()
    writers = AttemptWriters(paths, chunk_id, attempt)
    writers.add(outcome_row(_parsed(), index_url=INDEX_URL), entry_rows(_parsed()))
    writers.close()
    with pytest.raises(AttemptValidationError):
        finalize_attempt(
            paths, chunk_id, attempt, membership=(str(OTHER),), run=manifest
        )


def test_advance_pointer_writes_canonical_payload(tmp_path: Path) -> None:
    import json

    paths = inventory_run_paths(tmp_path, "run-1")
    advance_pointer(paths, "chunk-000000-abcd1234", "cafebabe")
    data = json.loads(paths.chunk_pointer_path("chunk-000000-abcd1234").read_text())
    assert data["attempt_id"] == "cafebabe"
    assert data["chunk_id"] == "chunk-000000-abcd1234"
