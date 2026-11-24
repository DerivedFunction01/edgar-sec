"""Recover one target through its filing's submission index."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from edgar_sec.domain.document_inventory.models import IndexPageInput
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import full_submission_url_for, validate_archive_url
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.infra.sec_http.streaming import StreamFailure, StreamedResponse
from edgar_sec.pipelines.document_acquisition.execution.attempts import (
    build_attempt as _attempt,
)
from edgar_sec.pipelines.document_acquisition.execution.index_selection import (
    IndexSelection,
    select_index_entry,
)
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    AcquisitionPolicy,
    TargetSlotResolution,
)
from edgar_sec.pipelines.document_acquisition.execution.runner_support import (
    AcquisitionTransport,
    new_staging_path as _new_path,
    stream as _stream,
    unresolved_source_outcome as _unresolved_source_outcome,
    utc_now as _utc,
)
from edgar_sec.pipelines.document_acquisition.run_state.models import TargetState
from edgar_sec.pipelines.document_acquisition.execution.lazy_recovery import (
    seat_recovered_body,
)


def acquire_lazy_target(
    row: dict[str, object],
    state: TargetState,
    *,
    run_id: str,
    run_root: Path,
    staging_root: Path,
    response: StreamedResponse,
    number: int,
    requested_url: str,
    started: str,
    finished: str,
    source_path: Path,
    fallback_selected_path: Path,
    fallback_selected_filename: str | None,
    retain_evidence: bool,
    screen_context: dict[str, str | None],
    accession: AccessionNumber,
    policy: AcquisitionPolicy,
    transport: AcquisitionTransport,
    clock: Callable[[], datetime],
) -> tuple[
    tuple[AcquisitionAttempt, ...],
    AcquisitionOutcome,
    TargetSlotResolution | None,
    str | None,
]:
    first_attempt = _attempt(
        target_id=state.target_id,
        number=number,
        kind="document_body",
        requested_url=requested_url,
        result=response,
        started_at_utc=started,
        finished_at_utc=finished,
        source_path=response.path if retain_evidence else None,
        selected_path=None,
        run_root=run_root,
    )
    archive_cik = validate_archive_url(requested_url, accession).archive_cik
    index_url = full_submission_url_for(archive_cik, str(accession))
    index_url = index_url.removesuffix(".txt") + "-index.html"
    index_path = _new_path(staging_root, "index")
    index_started = _utc(clock)
    index_result = _stream(transport, index_url, index_path, accession, policy)
    index_finished = _utc(clock)
    if isinstance(index_result, StreamFailure):
        index_attempt = _attempt(
            target_id=state.target_id,
            number=number + 1,
            kind="lazy_index",
            requested_url=index_url,
            result=index_result,
            started_at_utc=index_started,
            finished_at_utc=index_finished,
            source_path=None,
            selected_path=None,
            run_root=run_root,
        )
        return _unresolved_source_outcome(
            row=row,
            state=state,
            run_id=run_id,
            run_root=run_root,
            response=response,
            first_attempt=first_attempt,
            index_attempt=index_attempt,
            index_response=None,
            index_result="failed",
            number=number,
            started=started,
            finished=finished,
            source_path=source_path,
            selected_path=fallback_selected_path,
            selected_filename=fallback_selected_filename,
            retain_evidence=retain_evidence,
            screen_context=screen_context,
            clock=clock,
        )

    index_bytes = index_result.path.read_bytes()
    parsed = parse_html_index(
        IndexPageInput(accession, index_result.final_url, index_bytes)
    )
    selection = select_index_entry(
        parsed,
        accession=accession,
        expected_form=str(row["form"]),
        optional=bool(row["optional"]),
    )
    if parsed.page_sha256 != index_result.sha256:
        selection = IndexSelection("failed", (), None, "index_response_mismatch")
    index_attempt = _attempt(
        target_id=state.target_id,
        number=number + 1,
        kind="lazy_index",
        requested_url=index_url,
        result=index_result,
        started_at_utc=index_started,
        finished_at_utc=index_finished,
        source_path=index_result.path if retain_evidence else None,
        selected_path=None,
        run_root=run_root,
    )
    if not retain_evidence:
        index_result.path.unlink(missing_ok=True)
    attempts = (first_attempt, index_attempt)
    if selection.result != "selected":
        status = selection.result
        return _unresolved_source_outcome(
            row=row,
            state=state,
            run_id=run_id,
            run_root=run_root,
            response=response,
            first_attempt=first_attempt,
            index_attempt=index_attempt,
            index_response=index_result,
            index_result="not_filed" if status == "not_filed" else status,
            number=number,
            started=started,
            finished=finished,
            source_path=source_path,
            selected_path=fallback_selected_path,
            selected_filename=fallback_selected_filename,
            retain_evidence=retain_evidence,
            screen_context=screen_context,
            clock=clock,
        )

    entry = selection.entry
    if entry is None or selection.selected_url is None:
        raise ValueError("selected index entry is not addressable")
    body_source_path = _new_path(staging_root, "body-source")
    body_started = _utc(clock)
    body_result = _stream(
        transport, selection.selected_url, body_source_path, accession, policy
    )
    body_finished = _utc(clock)
    if isinstance(body_result, StreamFailure):
        body_attempt = _attempt(
            target_id=state.target_id,
            number=number + 2,
            kind="document_body",
            requested_url=selection.selected_url,
            result=body_result,
            started_at_utc=body_started,
            finished_at_utc=body_finished,
            source_path=None,
            selected_path=None,
            run_root=run_root,
        )
        return _unresolved_source_outcome(
            row=row,
            state=state,
            run_id=run_id,
            run_root=run_root,
            response=response,
            first_attempt=first_attempt,
            index_attempt=index_attempt,
            index_response=index_result,
            index_result="failed",
            number=number,
            started=started,
            finished=finished,
            source_path=source_path,
            selected_path=fallback_selected_path,
            selected_filename=fallback_selected_filename,
            retain_evidence=retain_evidence,
            screen_context=screen_context,
            clock=clock,
            extra_attempts=(body_attempt,),
            fallback_number=number + 3,
        )
    return seat_recovered_body(
        row,
        state,
        run_id=run_id,
        run_root=run_root,
        staging_root=staging_root,
        response=response,
        first_attempt=first_attempt,
        index_attempt=index_attempt,
        index_result=index_result,
        selection=selection,
        entry=entry,
        body_result=body_result,
        body_started=body_started,
        body_finished=body_finished,
        attempts=attempts,
        number=number,
        started=started,
        finished=finished,
        source_path=source_path,
        fallback_selected_path=fallback_selected_path,
        fallback_selected_filename=fallback_selected_filename,
        retain_evidence=retain_evidence,
        screen_context=screen_context,
        clock=clock,
    )


__all__ = ["acquire_lazy_target"]
