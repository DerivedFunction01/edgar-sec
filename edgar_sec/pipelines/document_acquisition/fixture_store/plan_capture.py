from __future__ import annotations

import fcntl
import os
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from edgar_sec.foundation.runtime.resources import derive_resources

from edgar_sec.domain.document_inventory.models import IndexPageInput
from edgar_sec.domain.document.route import archive_root_candidate
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import (
    archives_url,
    index_url_for,
    validate_archive_url,
)
from edgar_sec.engine.document.unpacking.streaming import (
    BundleExtractionFailure,
    extract_bundle_document_by_type,
    extract_bundle_sequence,
)
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.infra.sec_http.streaming import StreamFailure, StreamedResponse
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureOperationError,
    FixturePlanCaptureResult,
    FixturePlanPin,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    count_fixture_lazy_indexes,
    iter_fixture_cases,
    read_fixture_lazy_index,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import (
    fixture_plan_pin,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    append_fixture_case,
    append_fixture_lazy_index,
)
from edgar_sec.pipelines.document_acquisition.index_selection import (
    IndexSelection,
    select_index_entry,
)
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.plan_projection.target_plan import (
    load_acquisition_work_order,
)
from edgar_sec.pipelines.document_acquisition.run_validation import (
    iter_work_order_rows,
)
from edgar_sec.pipelines.document_acquisition.target_runner import (
    AcquisitionTransport,
    _stream,
)


class _TargetCaptureError(RuntimeError):
    pass


class _TargetSkipped(RuntimeError):
    pass


def _optional_text(value: object) -> str | None:
    """Return a trimmed plan field, or None when the plan leaves it unset."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@contextmanager
def _fixture_fill_lock(paths: AcquisitionPaths, fixture_id: str) -> Iterator[None]:
    lock_path = paths.fixture_database_path(fixture_id)
    descriptor = os.open(
        lock_path,
        os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise FixtureOperationError(
                "fixture fill is already in progress"
            ) from error
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _stream_response(
    transport: AcquisitionTransport,
    url: str,
    destination: Path,
    accession: AccessionNumber,
    policy: AcquisitionPolicy,
) -> StreamedResponse:
    response = _stream(transport, url, destination, accession, policy)
    if isinstance(response, StreamFailure):
        raise _TargetCaptureError(response.code)
    return response


_SQLITE_LAZY_LOCK = threading.Lock()


def _lazy_index(
    fixture_id: str,
    accession: AccessionNumber,
    target_url: str,
    *,
    paths: AcquisitionPaths,
    staging: Path,
    max_body_bytes: int,
    policy: AcquisitionPolicy,
    transport: AcquisitionTransport,
) -> tuple[str, str, bytes, int, bool]:
    archive = validate_archive_url(target_url, accession)
    index_url = index_url_for(accession, archive.archive_cik)
    with _SQLITE_LAZY_LOCK:
        cached = read_fixture_lazy_index(paths, fixture_id, str(accession))
        if cached is not None:
            if cached.index_url != index_url:
                raise _TargetCaptureError("cached_index_url_mismatch")
            return index_url, cached.body_sha256, cached.body, 0, True
        response = _stream_response(
            transport,
            index_url,
            staging / f"index-{accession}-{uuid.uuid4().hex}.bin",
            accession,
            policy,
        )
        if response.byte_size > max_body_bytes:
            raise _TargetCaptureError("lazy_index_too_large")
        with response.path.open("rb") as stream:
            index_ref = append_fixture_lazy_index(
                paths,
                fixture_id,
                str(accession),
                index_url,
                stream,
                max_body_bytes=max_body_bytes,
            )
        return (
            index_url,
            index_ref.body_sha256,
            response.path.read_bytes(),
            1,
            False,
        )


def _resolve_lazy_target(
    row: dict[str, object],
    *,
    fixture_id: str,
    paths: AcquisitionPaths,
    staging: Path,
    max_body_bytes: int,
    policy: AcquisitionPolicy,
    transport: AcquisitionTransport,
) -> tuple[str, str, int | None, str | None, str, int, str]:
    accession = AccessionNumber.from_any(str(row["accession"]))
    target_url = row["target_url"]
    if not isinstance(target_url, str):
        raise _TargetCaptureError("lazy_target_url_missing")
    index_url, index_sha256, index_bytes, fetched, _ = _lazy_index(
        fixture_id,
        accession,
        target_url,
        paths=paths,
        staging=staging,
        max_body_bytes=max_body_bytes,
        policy=policy,
        transport=transport,
    )
    parsed = parse_html_index(IndexPageInput(accession, index_url, index_bytes))
    selection: IndexSelection = select_index_entry(
        parsed,
        accession=accession,
        expected_form=str(row["form"]),
        optional=bool(row["optional"]),
    )
    if selection.result == "not_filed":
        raise _TargetSkipped("optional_document_not_filed")
    if (
        selection.result != "selected"
        or selection.selected_url is None
        or selection.retrieval_mode is None
        or selection.entry is None
    ):
        raise _TargetCaptureError(selection.error_code or selection.result)
    sequence = (
        selection.entry.sequence
        if selection.retrieval_mode == "bundle_sequence"
        else None
    )
    filename = selection.entry.filename
    if selection.retrieval_mode == "direct_url" and not filename:
        filename = urlsplit(selection.selected_url).path.rsplit("/", 1)[-1]
    if selection.retrieval_mode == "direct_url" and not filename:
        raise _TargetCaptureError("selected_filename_missing")
    return (
        selection.selected_url,
        selection.retrieval_mode,
        sequence,
        filename,
        index_sha256,
        fetched,
        "fixture_lazy_index",
    )


def _capture_document(
    row: dict[str, object],
    *,
    fixture_id: str,
    paths: AcquisitionPaths,
    staging: Path,
    max_body_bytes: int,
    policy: AcquisitionPolicy,
    transport: AcquisitionTransport,
) -> tuple[
    Path,
    str,
    str,
    int | None,
    str | None,
    str | None,
    int,
    str,
    int,
]:
    accession = AccessionNumber.from_any(str(row["accession"]))
    lazy = (
        row["source_origin"] == "catalog_direct"
        and row["inventory_entry_id"] is None
        and row["catalog_direct_selection"] == "exact_form_with_lazy_index"
    )
    if lazy:
        (
            target_url,
            retrieval_mode,
            sequence,
            filename,
            index_sha256,
            fetched_indexes,
            selection_source,
        ) = _resolve_lazy_target(
            row,
            fixture_id=fixture_id,
            paths=paths,
            staging=staging,
            max_body_bytes=max_body_bytes,
            policy=policy,
            transport=transport,
        )
    else:
        target_url = row["target_url"]
        retrieval_mode = row["retrieval_mode"]
        sequence = row["sequence"] if retrieval_mode == "bundle_sequence" else None
        filename = (
            urlsplit(str(target_url or "")).path.rsplit("/", 1)[-1]
            if retrieval_mode == "direct_url"
            else None
        )
        index_sha256 = None
        fetched_indexes = 0
        selection_source = (
            "inventory_index"
            if row["source_origin"] == "inventory_index"
            else "planned_source"
        )
    if not isinstance(target_url, str):
        raise _TargetCaptureError("target_url_missing")
    if retrieval_mode == "direct_url":
        try:
            parsed_archive = validate_archive_url(target_url, accession)
            root_cand = archive_root_candidate(parsed_archive.document_path)
            if root_cand is not None and root_cand.casefold().endswith(".xml"):
                target_url = archives_url(
                    parsed_archive.archive_cik,
                    parsed_archive.accession,
                    root_cand,
                )
                filename = root_cand
        except ValueError:
            pass
    if retrieval_mode not in {"direct_url", "bundle_sequence", "bundle_scan"}:
        raise _TargetCaptureError("retrieval_mode_unsupported")
    if retrieval_mode == "direct_url" and not filename:
        raise _TargetCaptureError("selected_filename_missing")
    response = _stream_response(
        transport,
        target_url,
        staging / f"body-{uuid.uuid4().hex}.bin",
        accession,
        policy,
    )
    if retrieval_mode == "bundle_sequence":
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise _TargetCaptureError("bundle_sequence_invalid")
        selected_path = staging / f"selected-{uuid.uuid4().hex}.bin"
        extracted = extract_bundle_sequence(
            response.path,
            sequence,
            selected_path,
            expected_filename=filename,
            expected_document_type=(
                str(row["form"]) if selection_source == "fixture_lazy_index" else None
            ),
            expected_source_sha256=response.sha256,
        )
        if isinstance(extracted, BundleExtractionFailure):
            raise _TargetCaptureError(extracted.code)
        filename = extracted.selected.filename or filename
        if not filename:
            raise _TargetCaptureError("selected_filename_missing")
        body_sha256 = extracted.body_sha256
        selected_bytes = extracted.body_size
    elif retrieval_mode == "bundle_scan":
        selected_path = staging / f"selected-{uuid.uuid4().hex}.bin"
        scanned = extract_bundle_document_by_type(
            response.path,
            str(row["form"]),
            selected_path,
            expected_source_sha256=response.sha256,
        )
        if isinstance(scanned, BundleExtractionFailure):
            raise _TargetCaptureError(scanned.code)
        filename = scanned.selected.filename
        if not filename:
            raise _TargetCaptureError("selected_filename_missing")
        sequence = scanned.selected.sequence
        body_sha256 = scanned.body_sha256
        selected_bytes = scanned.body_size
    else:
        selected_path = response.path
        body_sha256 = response.sha256
        selected_bytes = response.byte_size
    if selected_bytes > max_body_bytes:
        raise _TargetCaptureError("selected_body_too_large")
    return (
        selected_path,
        response.final_url,
        str(retrieval_mode),
        sequence,
        filename,
        index_sha256,
        fetched_indexes,
        selection_source,
        body_sha256,
        selected_bytes,
    )


def capture_fixture_plan(
    fixture_id: str,
    *,
    paths: AcquisitionPaths,
    max_body_bytes: int,
    transport: AcquisitionTransport,
    limit: int | None = None,
    workers: int | None = None,
    on_target: Callable[[int, int], None] | None = None,
) -> FixturePlanCaptureResult:
    if (
        isinstance(max_body_bytes, bool)
        or not isinstance(max_body_bytes, int)
        or max_body_bytes < 1
    ):
        raise FixtureOperationError("max_body_bytes must be positive")
    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
    ):
        raise FixtureOperationError("limit must be a positive integer")
    pin = fixture_plan_pin(paths, fixture_id)
    with _fixture_fill_lock(paths, fixture_id):
        return _capture_fixture_plan_locked(
            fixture_id,
            pin=pin,
            paths=paths,
            max_body_bytes=max_body_bytes,
            transport=transport,
            limit=limit,
            workers=workers,
            on_target=on_target,
        )


def _capture_fixture_plan_locked(
    fixture_id: str,
    *,
    pin: FixturePlanPin,
    paths: AcquisitionPaths,
    max_body_bytes: int,
    transport: AcquisitionTransport,
    limit: int | None,
    workers: int | None,
    on_target: Callable[[int, int], None] | None,
) -> FixturePlanCaptureResult:
    with tempfile.TemporaryDirectory(prefix="acquisition-fixture-plan-") as temporary:
        work_order_path = Path(temporary) / "work-order.parquet"
        projection = load_acquisition_work_order(
            paths.target_plan_dir(pin.target_plan_id), work_order_path
        )
        if (
            projection.plan_id != pin.target_plan_id
            or projection.plan_digest != pin.target_plan_digest
            or projection.target_schema_version != pin.target_plan_schema_version
        ):
            raise FixtureOperationError(
                "published target plan differs from fixture pin"
            )
        existing_targets = {
            case.target_id for case in iter_fixture_cases(paths, fixture_id=fixture_id)
        }
        initial_lazy_index_count = count_fixture_lazy_indexes(paths, fixture_id)
        remaining = max(0, projection.executable_count - len(existing_targets))
        total = min(limit, remaining) if limit is not None else remaining
        capture_id = f"cap_{uuid.uuid4().hex}"
        capture = {
            "capture_id": capture_id,
            "target_plan_id": pin.target_plan_id,
            "target_plan_digest": pin.target_plan_digest,
            "target_plan_schema_version": pin.target_plan_schema_version,
            "captured_at_utc": datetime.now(UTC).isoformat(timespec="microseconds"),
        }
        captured = skipped = failed = reused_indexes = 0
        failure_counts: dict[str, int] = {}
        considered = 0
        policy = AcquisitionPolicy(max_response_bytes=max_body_bytes)
        with tempfile.TemporaryDirectory(prefix="fixture-target-") as target_temp:
            staging = Path(target_temp)
            resources = derive_resources()
            worker_count = (
                min(resources.workers, resources.worker_ceiling)
                if workers is None
                else min(workers, resources.worker_ceiling)
            )
            worker_count = max(1, worker_count)

            def _fetch_target(
                target_row: dict[str, object],
            ) -> tuple[dict[str, object], tuple[object, ...] | None, Exception | None]:
                try:
                    result = _capture_document(
                        target_row,
                        fixture_id=fixture_id,
                        paths=paths,
                        staging=staging,
                        max_body_bytes=max_body_bytes,
                        policy=policy,
                        transport=transport,
                    )
                    return target_row, result, None
                except Exception as exc:
                    return target_row, None, exc

            def _commit_outcome(
                target_row: dict[str, object],
                res: tuple[object, ...] | None,
                exc: Exception | None,
            ) -> None:
                nonlocal captured, skipped, failed, reused_indexes
                target_id = str(target_row["target_id"])
                if exc is not None:
                    if isinstance(exc, _TargetSkipped):
                        skipped += 1
                    elif isinstance(exc, _TargetCaptureError):
                        failed += 1
                        failure_counts[str(exc)] = failure_counts.get(str(exc), 0) + 1
                    elif isinstance(exc, ValueError):
                        failed += 1
                        failure_counts["target_validation"] = (
                            failure_counts.get("target_validation", 0) + 1
                        )
                    elif isinstance(exc, OSError):
                        raise FixtureOperationError(
                            f"cannot capture target {target_id}: {exc}"
                        ) from exc
                    else:
                        failed += 1
                        failure_counts[type(exc).__name__] = (
                            failure_counts.get(type(exc).__name__, 0) + 1
                        )
                    return

                (
                    body_path,
                    target_url,
                    retrieval_mode,
                    sequence,
                    filename,
                    index_sha256,
                    fetched_index_count,
                    selection_source,
                    body_sha256,
                    body_byte_size,
                ) = res  # type: ignore[misc]
                case = {
                    "capture_id": capture_id,
                    "target_id": target_id,
                    "inventory_entry_id": target_row["inventory_entry_id"],
                    "selection_source": selection_source,
                    "index_sha256": index_sha256,
                    "accession": str(target_row["accession"]),
                    "form": str(target_row["form"]),
                    "request_id": str(target_row["request_id"]),
                    "target_role": str(target_row["target_role"]),
                    "target_type": str(target_row["target_type"]),
                    "source_origin": str(target_row["source_origin"]),
                    "retrieval_mode": retrieval_mode,
                    "target_url": target_url,
                    "sequence": sequence,
                    "selected_filename": filename,
                    "body_sha256": body_sha256,
                    "byte_size": body_byte_size,
                    "filing_date": _optional_text(target_row.get("filing_date")),
                    "report_date": _optional_text(target_row.get("report_date")),
                }
                with body_path.open("rb") as source:
                    append_fixture_case(
                        paths,
                        fixture_id,
                        capture,
                        case,
                        source,
                        max_body_bytes=max_body_bytes,
                    )
                try:
                    body_path.unlink(missing_ok=True)
                except OSError:
                    pass
                captured += 1
                if index_sha256 is not None and fetched_index_count == 0:
                    reused_indexes += 1
                existing_targets.add(target_id)

            if hasattr(transport, "warm") and callable(transport.warm):
                transport.warm()
            executor = ThreadPoolExecutor(
                max_workers=worker_count, thread_name_prefix="fixture-fill"
            )
            pending: dict[
                Future[
                    tuple[
                        dict[str, object],
                        tuple[object, ...] | None,
                        Exception | None,
                    ]
                ],
                dict[str, object],
            ] = {}
            try:
                for row in iter_work_order_rows((projection.parquet_path,)):
                    target_id = str(row["target_id"])
                    if target_id in existing_targets or not row["executable"]:
                        skipped += 1
                        continue
                    if limit is not None and considered >= limit:
                        break
                    considered += 1
                    fut = executor.submit(_fetch_target, row)
                    pending[fut] = row
                    if len(pending) >= worker_count:
                        done, _ = wait(pending, return_when=FIRST_COMPLETED)
                        for f in done:
                            t_row = pending.pop(f)
                            _, res, exc = f.result()
                            _commit_outcome(t_row, res, exc)
                            if on_target is not None:
                                on_target(considered, total)

                while pending:
                    done, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for f in done:
                        t_row = pending.pop(f)
                        _, res, exc = f.result()
                        _commit_outcome(t_row, res, exc)
                        if on_target is not None:
                            on_target(considered, total)
            except KeyboardInterrupt:
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            else:
                executor.shutdown(wait=True)
    return FixturePlanCaptureResult(
        fixture_id,
        capture_id if captured else None,
        captured,
        skipped,
        failed,
        max(
            0,
            count_fixture_lazy_indexes(paths, fixture_id) - initial_lazy_index_count,
        ),
        reused_indexes,
        dict(sorted(failure_counts.items())),
    )
