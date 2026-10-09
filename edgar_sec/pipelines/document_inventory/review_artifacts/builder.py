"""Build bounded, offline parser review artifacts from one fixture."""

from __future__ import annotations

import csv
import multiprocessing
import os
import tempfile
from collections import deque
from collections.abc import Iterable
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass, fields
from pathlib import Path

from edgar_sec.domain.document_inventory.models import (
    IndexPageInput,
    IndexParseFailure,
    InventoryEntry,
    ParsedIndexPage,
    UnrecognizedIndexPage,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.index_pages.parser import PARSER_FINGERPRINT, parse_html_index
from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json, atomic_write_text
from edgar_sec.pipelines.document_inventory.fixture_store.models import (
    CapturedIndexCase,
    IndexFixtureError,
    IndexResponseKey,
)
from edgar_sec.pipelines.document_inventory.fixture_store.reader import (
    open_index_fixture,
)
from edgar_sec.foundation.runtime.fixtures import FixturePaths

from .models import ReviewRunResult, ReviewSummary
from .paths import (
    OBSERVATIONS_FILE,
    REVIEW_ENTRIES_FILE,
    SOURCE_PREVIEW_FILE,
    ReviewArtifactPaths,
)
from .sanitizer import render_inert

_ENTRY_FIELDS = tuple(field.name for field in fields(InventoryEntry))
_RECLAIM_INTERVAL = 32


@dataclass(frozen=True, slots=True)
class _CaseRecord:
    accession: str
    request_url: str
    response_sha256: str
    fixture_id: str
    status: str
    entry_count: int
    diagnostic_count: int
    output_digests: dict[str, str]
    files_written: tuple[str, ...]
    error: str | None = None


def _diagnostics(outcome) -> tuple[list[dict], int]:
    if isinstance(outcome, IndexParseFailure):
        diagnostic = outcome.diagnostic
        return (
            [
                {
                    "code": diagnostic.code,
                    "row_key": None
                    if diagnostic.row_key is None
                    else list(diagnostic.row_key),
                    "detail": diagnostic.detail,
                }
            ],
            0,
        )
    diagnostics = outcome.diagnostics
    return (
        [
            {
                "code": item.code,
                "row_key": None if item.row_key is None else list(item.row_key),
                "detail": item.detail,
            }
            for item in diagnostics.items
        ],
        diagnostics.suppressed_count,
    )


def _write_entries(path: Path, entries: tuple[InventoryEntry, ...]) -> None:
    ordered = sorted(entries, key=lambda item: (item.table_kind, item.row_ordinal))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_ENTRY_FIELDS)
        writer.writeheader()
        for entry in ordered:
            writer.writerow({name: getattr(entry, name) for name in _ENTRY_FIELDS})


def _process_case(
    case: CapturedIndexCase,
    body: bytes,
    fixture_id: str,
    paths: ReviewArtifactPaths,
) -> _CaseRecord:
    accession = str(case.accession)
    digest = case.key.response_sha256
    if sha256_bytes(body) != digest:
        raise IndexFixtureError(f"replayed page digest mismatch for {accession}")
    outcome = parse_html_index(
        IndexPageInput(case.accession, case.key.request_url, body)
    )
    inert_html = render_inert(body)
    case_root = paths.case_root(case.accession, case.key)
    paths.cases_root.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix="case-", dir=paths.case_staging_root()))
    try:
        atomic_write_text(staging_root / SOURCE_PREVIEW_FILE, inert_html)
        output_digests = {
            SOURCE_PREVIEW_FILE: file_sha256(staging_root / SOURCE_PREVIEW_FILE)
        }
        diagnostics, suppressed = _diagnostics(outcome)
        entry_count = 0
        files = [SOURCE_PREVIEW_FILE]
        if isinstance(outcome, ParsedIndexPage):
            entry_count = len(outcome.entries)
            _write_entries(staging_root / REVIEW_ENTRIES_FILE, outcome.entries)
            output_digests[REVIEW_ENTRIES_FILE] = file_sha256(
                staging_root / REVIEW_ENTRIES_FILE
            )
            files.append(REVIEW_ENTRIES_FILE)
            status = "parsed"
            bundle_url = outcome.bundle_url
            bundle_size = outcome.bundle_size
            xbrl_url = outcome.xbrl_candidate_url
        elif isinstance(outcome, UnrecognizedIndexPage):
            status = "unrecognized"
            bundle_url = bundle_size = xbrl_url = None
        else:
            status = "parse_failure"
            bundle_url = bundle_size = xbrl_url = None
        observation = {
            "fixture_id": fixture_id,
            "accession": accession,
            "request_url": case.key.request_url,
            "response_sha256": digest,
            "parser_fingerprint": PARSER_FINGERPRINT,
            "status": status,
            "bundle_url": bundle_url,
            "bundle_size": bundle_size,
            "xbrl_candidate_url": xbrl_url,
            "diagnostics": {"items": diagnostics, "suppressed_count": suppressed},
            "entry_count": entry_count,
        }
        atomic_write_json(staging_root / OBSERVATIONS_FILE, observation)
        output_digests[OBSERVATIONS_FILE] = file_sha256(
            staging_root / OBSERVATIONS_FILE
        )
        files.append(OBSERVATIONS_FILE)
        case_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_root, case_root)
        record = _CaseRecord(
            accession,
            case.key.request_url,
            digest,
            fixture_id,
            status,
            entry_count,
            len(diagnostics) + suppressed,
            output_digests,
            tuple(files),
        )
        del body, inert_html, outcome
        reclaim()
        return record
    except BaseException:
        _remove_tree(staging_root)
        raise


def _remove_tree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def _failure_record(
    case: CapturedIndexCase, fixture_id: str, detail: str
) -> _CaseRecord:
    return _CaseRecord(
        str(case.accession),
        case.key.request_url,
        case.key.response_sha256,
        fixture_id,
        "execution_error",
        0,
        0,
        {},
        (),
        detail[:2000],
    )


def _manifest_record(
    record: _CaseRecord, review_id: str, paths: ReviewArtifactPaths
) -> dict:
    return {
        "review_id": review_id,
        "fixture_id": record.fixture_id,
        "accession": record.accession,
        "request_url": record.request_url,
        "response_sha256": record.response_sha256,
        "parser_fingerprint": PARSER_FINGERPRINT,
        "status": record.status,
        "entry_count": record.entry_count,
        "diagnostic_count": record.diagnostic_count,
        "outputs": {
            name: {
                "path": str(
                    paths.case_root(
                        AccessionNumber(record.accession),
                        IndexResponseKey(record.request_url, record.response_sha256),
                    ).relative_to(paths.root)
                    / name
                ),
                "sha256": digest,
            }
            for name, digest in record.output_digests.items()
        },
        "error": record.error,
    }


def _sync_parent(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _manifest_temp(path: Path) -> tuple[Path, object]:
    descriptor, name = tempfile.mkstemp(prefix=".manifest-", dir=path.parent)
    return Path(name), os.fdopen(descriptor, "w", encoding="utf-8", newline="")


def _summary_record(status: str, summary: dict[str, int], entry_count: int) -> None:
    summary["total"] += 1
    if status in {
        "parsed",
        "unrecognized",
        "parse_failure",
        "replay_failure",
        "execution_error",
    }:
        summary[status] += 1
    summary["entries_total"] += entry_count
    if status != "parsed":
        summary["failed"] += 1


def _work_cases(
    reader,
    requested: set[str] | None,
    limit: int | None,
) -> Iterable[CapturedIndexCase]:
    selected_accessions = 0
    prior_accession = None
    for case in reader.iter_cases(batch_size=128):
        accession = str(case.accession)
        if requested is not None and accession not in requested:
            continue
        if accession != prior_accession:
            if limit is not None and selected_accessions >= limit:
                break
            selected_accessions += 1
            prior_accession = accession
        yield case


def build_review_artifacts(
    fixture: FixturePaths,
    output: str | os.PathLike[str],
    *,
    accessions: Iterable[str | AccessionNumber] | None = None,
    limit: int | None = None,
    workers: int | None = None,
) -> ReviewRunResult:
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    resources = derive_resources()
    if workers is not None and workers < 1:
        raise ValueError("workers must be positive")
    worker_count = (
        resources.workers if workers is None else min(workers, resources.workers)
    )
    if worker_count < 1:
        raise ValueError("no review workers are available in the resource budget")
    output_root = Path(output).expanduser().resolve()
    paths = ReviewArtifactPaths(output_root)
    created = not output_root.exists()
    if output_root.exists() and (
        not output_root.is_dir() or any(output_root.iterdir())
    ):
        raise ValueError(
            f"review output must be a new or empty directory: {output_root}"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    paths.case_staging_root().mkdir(parents=True, exist_ok=True)
    requested = (
        None
        if accessions is None
        else {str(AccessionNumber.from_any(item)) for item in accessions}
    )
    review_id = paths.review_id
    counts = {
        "total": 0,
        "parsed": 0,
        "unrecognized": 0,
        "parse_failure": 0,
        "replay_failure": 0,
        "execution_error": 0,
        "entries_total": 0,
        "failed": 0,
    }
    manifest_path = paths.manifest_path
    temporary, manifest_stream = _manifest_temp(manifest_path)
    pending: deque[tuple[CapturedIndexCase, Future[_CaseRecord]]] = deque()
    executor = None
    try:
        with open_index_fixture(fixture) as reader:
            fixture_id = reader.fixture_id or fixture.root.name
            worker_count = min(worker_count, max(1, reader.count_cases()))
            if worker_count > 1:
                executor = ProcessPoolExecutor(
                    max_workers=worker_count,
                    mp_context=multiprocessing.get_context("spawn"),
                )

            def emit(record: _CaseRecord) -> None:
                manifest_stream.write(
                    canonical_json(_manifest_record(record, review_id, paths)) + "\n"
                )
                _summary_record(record.status, counts, record.entry_count)
                if counts["total"] % _RECLAIM_INTERVAL == 0:
                    reclaim()

            def drain_oldest() -> None:
                case, future = pending.popleft()
                try:
                    emit(future.result())
                except Exception as exc:
                    emit(
                        _failure_record(
                            case, fixture_id, str(exc) or type(exc).__name__
                        )
                    )

            for case in _work_cases(reader, requested, limit):
                try:
                    page = reader.replay(case.accession, case.key)
                except Exception as exc:
                    while pending:
                        drain_oldest()
                    emit(
                        _CaseRecord(
                            str(case.accession),
                            case.key.request_url,
                            case.key.response_sha256,
                            fixture_id,
                            "replay_failure",
                            0,
                            0,
                            {},
                            (),
                            str(exc)[:2000],
                        )
                    )
                    continue
                if executor is None:
                    try:
                        emit(_process_case(case, page.body, fixture_id, paths))
                    except Exception as exc:
                        emit(
                            _failure_record(
                                case, fixture_id, str(exc) or type(exc).__name__
                            )
                        )
                    del page
                else:
                    try:
                        future = executor.submit(
                            _process_case, case, page.body, fixture_id, paths
                        )
                    except Exception as exc:
                        while pending:
                            drain_oldest()
                        emit(
                            _failure_record(
                                case, fixture_id, str(exc) or type(exc).__name__
                            )
                        )
                        continue
                    pending.append((case, future))
                    del page
                    if len(pending) >= worker_count:
                        drain_oldest()
                        reclaim()
            while pending:
                drain_oldest()
                reclaim()
        if counts["total"] == 0:
            _remove_tree(paths.case_staging_root())
            if created:
                _remove_tree(output_root)
            else:
                temporary.unlink(missing_ok=True)
            raise ValueError("review selection is empty")
        manifest_stream.flush()
        os.fsync(manifest_stream.fileno())
        manifest_stream.close()
        os.replace(temporary, manifest_path)
        _sync_parent(manifest_path)
    except BaseException:
        if not manifest_stream.closed:
            manifest_stream.close()
        temporary.unlink(missing_ok=True)
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        if executor is not None:
            executor.shutdown(wait=True)
        _remove_tree(paths.case_staging_root())

    summary = ReviewSummary(**counts)
    return ReviewRunResult(
        review_id=review_id,
        output_root=output_root,
        summary=summary,
        exit_code=0 if summary.failed == 0 else 1,
    )
