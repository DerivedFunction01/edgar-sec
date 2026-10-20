"""Acquire one validated target with bounded response staging."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from shutil import copyfile
from urllib.parse import urlsplit

from edgar_sec.domain.document_inventory.models import IndexPageInput
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import full_submission_url_for, validate_archive_url
from edgar_sec.engine.document.screening import (
    screen_candidate_document,
)
from edgar_sec.engine.document.unpacking.streaming import (
    BundleExtraction,
    extract_bundle_sequence,
)
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.infra.sec_http.streaming import (
    StreamFailure,
    StreamedResponse,
)
from edgar_sec.pipelines.document_acquisition.attempts import (
    build_attempt as _attempt,
    relative_path as _relative,
)
from edgar_sec.pipelines.document_acquisition.index_selection import (
    IndexSelection,
    select_index_entry,
)
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    AcquisitionPolicy,
    AcquisitionStatus,
    TargetSlotResolution,
)
from edgar_sec.pipelines.document_acquisition.runner_support import (
    AcquisitionTransport,
    apply_structure_screen as _apply_structure_screen,
    has_lazy_index_trigger as _has_lazy_index_trigger,
    outcome as _outcome,
    read_screen_head as _read_screen_head,
    resolution_screen_kind as _resolution_screen_kind,
    stream as _stream,
    unresolved_source_outcome as _unresolved_source_outcome,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.resolution import (
    build_resolution as _resolution,
)
from edgar_sec.pipelines.document_acquisition.run_state.models import TargetState


def _utc(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("acquisition clock must return timezone-aware datetimes")
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _new_path(staging_root: Path, prefix: str) -> Path:
    return staging_root / f"{prefix}-{uuid.uuid4().hex}.bin"


def acquire_target(
    row: dict[str, object],
    state: TargetState,
    *,
    run_id: str,
    paths: AcquisitionPaths,
    policy: AcquisitionPolicy,
    transport: AcquisitionTransport,
    clock: Callable[[], datetime],
) -> tuple[
    tuple[AcquisitionAttempt, ...],
    AcquisitionOutcome,
    TargetSlotResolution | None,
    str | None,
]:
    run_root = paths.run_dir(run_id)
    staging_root = paths.run_staging_root(run_id)
    if staging_root.is_symlink():
        raise ValueError("run staging directory is unsafe")
    staging_root.mkdir(parents=True, exist_ok=True)
    if not staging_root.resolve().is_relative_to(run_root.resolve()):
        raise ValueError("run staging directory escapes its run")
    accession = AccessionNumber(str(row["accession"]))
    requested_url = row["target_url"]
    if not isinstance(requested_url, str):
        raise ValueError("executable work-order row has no target URL")
    retain_evidence = (
        policy.retain_response_evidence
        and row["target_role"] == "primary"
        and (row["retrieval_mode"] == "bundle_sequence" or _has_lazy_index_trigger(row))
    )
    source_path = _new_path(staging_root, "response")
    selected_path: Path | None = None
    started = _utc(clock)
    response = _stream(transport, requested_url, source_path, accession, policy)
    finished = _utc(clock)
    number = state.attempt_count + 1
    if isinstance(response, StreamFailure):
        attempt = _attempt(
            target_id=state.target_id,
            number=number,
            kind="document_body",
            requested_url=requested_url,
            result=response,
            started_at_utc=started,
            finished_at_utc=finished,
            source_path=None,
            selected_path=None,
            run_root=run_root,
        )
        return (
            (attempt,),
            _outcome(state.target_id, (attempt,), "failed", error_code=response.code),
            None,
            None,
        )

    sgml_recovery = False
    fallback_selected_path = source_path
    fallback_selected_filename: str | None = None
    screen_context: dict[str, str | None] = {
        "screen_kind": "html_cover",
        "screen_result": "unverifiable",
        "observed_body_type": None,
    }
    if row["retrieval_mode"] == "bundle_sequence":
        sequence = row["sequence"]
        selected_path = _new_path(staging_root, "selected")
        extracted = extract_bundle_sequence(
            response.path,
            sequence,
            selected_path,
            expected_source_sha256=response.sha256,
        )
        if isinstance(extracted, BundleExtraction):
            screen = (
                _apply_structure_screen(
                    screen_candidate_document(
                        str(row["form"]),
                        observed_sgml_type=extracted.selected.document_type,
                    ),
                    str(row["form"]),
                    str(row["target_role"]),
                    _read_screen_head(selected_path),
                )
                if _has_lazy_index_trigger(row)
                else None
            )
            if screen is not None and screen.screen_result != "form_match":
                sgml_recovery = True
                screen_context = {
                    "screen_kind": _resolution_screen_kind(screen),
                    "screen_result": screen.screen_result,
                    "observed_body_type": screen.observed_body_type,
                }
                fallback_selected_path = selected_path
                fallback_selected_filename = extracted.selected.filename
            else:
                attempt = _attempt(
                    target_id=state.target_id,
                    number=number,
                    kind="document_body",
                    requested_url=requested_url,
                    result=response,
                    started_at_utc=started,
                    finished_at_utc=finished,
                    source_path=response.path if retain_evidence else None,
                    selected_path=selected_path,
                    run_root=run_root,
                    selected_filename=extracted.selected.filename,
                )
                if not retain_evidence:
                    response.path.unlink(missing_ok=True)
                outcome = _outcome(
                    state.target_id,
                    (attempt,),
                    "acquired",
                    source_sha256=response.sha256,
                    source_byte_size=response.byte_size,
                    selected_sha256=extracted.body_sha256,
                    selected_byte_size=extracted.body_size,
                    selected_path=_relative(run_root, selected_path),
                )
                return (attempt,), outcome, None, None
        else:
            if not retain_evidence:
                response.path.unlink(missing_ok=True)
            selected_path.unlink(missing_ok=True)
            status: AcquisitionStatus = (
                "not_filed"
                if extracted.code == "sequence_not_found"
                else "ambiguous"
                if extracted.code == "duplicate_sequence"
                else "failed"
            )
            attempt = _attempt(
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
                outcome=status,
                error_code=extracted.code if status == "failed" else None,
            )
            return (
                (attempt,),
                _outcome(
                    state.target_id,
                    (attempt,),
                    status,
                    error_code=extracted.code if status == "failed" else None,
                ),
                None,
                None,
            )

    direct_screen_recovery = False
    if (
        row["retrieval_mode"] == "direct_url"
        and _has_lazy_index_trigger(row)
        and row["sequence"] == 1
    ):
        head = _read_screen_head(source_path)
        screen = _apply_structure_screen(
            screen_candidate_document(
                str(row["form"]),
                filename=urlsplit(requested_url).path.rsplit("/", 1)[-1],
                raw_content=head,
            ),
            str(row["form"]),
            str(row["target_role"]),
            head,
        )
        if screen.screen_result != "form_match":
            direct_screen_recovery = True
            screen_context = {
                "screen_kind": _resolution_screen_kind(screen),
                "screen_result": screen.screen_result,
                "observed_body_type": screen.observed_body_type,
            }
    lazy = sgml_recovery or direct_screen_recovery
    if not lazy:
        selected_path = source_path
        attempt = _attempt(
            target_id=state.target_id,
            number=number,
            kind="document_body",
            requested_url=requested_url,
            result=response,
            started_at_utc=started,
            finished_at_utc=finished,
            source_path=source_path,
            selected_path=selected_path,
            run_root=run_root,
        )
        outcome = _outcome(
            state.target_id,
            (attempt,),
            "acquired",
            source_sha256=response.sha256,
            source_byte_size=response.byte_size,
            source_path=_relative(run_root, source_path),
            selected_sha256=response.sha256,
            selected_byte_size=response.byte_size,
            selected_path=_relative(run_root, source_path),
        )
        if (
            attempt.selected_sha256 != response.sha256
            or attempt.selected_byte_size != response.byte_size
        ):
            source_path.unlink(missing_ok=True)
            failed_attempt = _attempt(
                target_id=state.target_id,
                number=number,
                kind="document_body",
                requested_url=requested_url,
                result=response,
                started_at_utc=started,
                finished_at_utc=finished,
                source_path=None,
                selected_path=None,
                run_root=run_root,
                outcome="failed",
                error_code="source_mismatch",
            )
            return (
                (failed_attempt,),
                _outcome(
                    state.target_id,
                    (failed_attempt,),
                    "failed",
                    error_code="source_mismatch",
                ),
                None,
                None,
            )
        return (attempt,), outcome, None, None

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
    if selection.retrieval_mode == "direct_url" and _has_lazy_index_trigger(row):
        recovered_screen = _apply_structure_screen(
            screen_candidate_document(
                str(row["form"]),
                filename=entry.filename,
                raw_content=_read_screen_head(body_result.path),
            ),
            str(row["form"]),
            str(row["target_role"]),
            _read_screen_head(body_result.path),
        )
        if recovered_screen.is_inversion:
            if not retain_evidence:
                body_result.path.unlink(missing_ok=True)
            body_attempt = _attempt(
                target_id=state.target_id,
                number=number + 2,
                kind="document_body",
                requested_url=selection.selected_url,
                result=body_result,
                started_at_utc=body_started,
                finished_at_utc=body_finished,
                source_path=body_result.path if retain_evidence else None,
                selected_path=None,
                run_root=run_root,
                outcome="failed",
                error_code="recovered_document_identity_mismatch",
            )
            attempts = (*attempts, body_attempt)
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
                screen_context={
                    "screen_kind": _resolution_screen_kind(recovered_screen),
                    "screen_result": recovered_screen.screen_result,
                    "observed_body_type": recovered_screen.observed_body_type,
                },
                clock=clock,
                extra_attempts=(body_attempt,),
                fallback_number=number + 3,
            )
    if selection.retrieval_mode == "bundle_sequence":
        if entry.sequence is None:
            raise ValueError("selected bundle entry has no sequence")
        selected_path = _new_path(staging_root, "selected")
        extracted = extract_bundle_sequence(
            body_result.path,
            entry.sequence,
            selected_path,
            expected_source_sha256=body_result.sha256,
        )
        if not retain_evidence:
            body_result.path.unlink(missing_ok=True)
        if not isinstance(extracted, BundleExtraction):
            selected_path.unlink(missing_ok=True)
            status: AcquisitionStatus = (
                "ambiguous" if extracted.code == "duplicate_sequence" else "failed"
            )
            body_attempt = _attempt(
                target_id=state.target_id,
                number=number + 2,
                kind="document_body",
                requested_url=selection.selected_url,
                result=body_result,
                started_at_utc=body_started,
                finished_at_utc=body_finished,
                source_path=body_result.path if retain_evidence else None,
                selected_path=None,
                run_root=run_root,
                outcome=status,
                error_code=extracted.code if status == "failed" else None,
            )
            attempts = (*attempts, body_attempt)
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
        if _has_lazy_index_trigger(row):
            screen = _apply_structure_screen(
                screen_candidate_document(
                    str(row["form"]),
                    observed_sgml_type=extracted.selected.document_type,
                ),
                str(row["form"]),
                str(row["target_role"]),
                _read_screen_head(selected_path),
            )
            if screen.screen_result != "form_match":
                selected_path.unlink(missing_ok=True)
                body_attempt = _attempt(
                    target_id=state.target_id,
                    number=number + 2,
                    kind="document_body",
                    requested_url=selection.selected_url,
                    result=body_result,
                    started_at_utc=body_started,
                    finished_at_utc=body_finished,
                    source_path=body_result.path if retain_evidence else None,
                    selected_path=None,
                    run_root=run_root,
                    outcome="failed",
                    error_code=(
                        "document_type_mismatch"
                        if screen.screen_result == "type_mismatch"
                        else "document_type_unverifiable"
                    ),
                )
                attempts = (*attempts, body_attempt)
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
                    screen_context={
                        "screen_kind": _resolution_screen_kind(screen),
                        "screen_result": screen.screen_result,
                        "observed_body_type": screen.observed_body_type,
                    },
                    clock=clock,
                    extra_attempts=(body_attempt,),
                    fallback_number=number + 3,
                )
        body_attempt = _attempt(
            target_id=state.target_id,
            number=number + 2,
            kind="document_body",
            requested_url=selection.selected_url,
            result=body_result,
            started_at_utc=body_started,
            finished_at_utc=body_finished,
            source_path=body_result.path if retain_evidence else None,
            selected_path=selected_path,
            run_root=run_root,
            selected_filename=extracted.selected.filename,
        )
        if (
            body_attempt.selected_sha256 != extracted.body_sha256
            or body_attempt.selected_byte_size != extracted.body_size
        ):
            selected_path.unlink(missing_ok=True)
            body_attempt = _attempt(
                target_id=state.target_id,
                number=number + 2,
                kind="document_body",
                requested_url=selection.selected_url,
                result=body_result,
                started_at_utc=body_started,
                finished_at_utc=body_finished,
                source_path=body_result.path if retain_evidence else None,
                selected_path=None,
                run_root=run_root,
                outcome="failed",
                error_code="source_mismatch",
            )
            attempts = (*attempts, body_attempt)
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
        if not retain_evidence:
            source_path.unlink(missing_ok=True)
            fallback_selected_path.unlink(missing_ok=True)
        attempts = (*attempts, body_attempt)
        resolution = _resolution(
            row | {"run_id": run_id},
            response,
            index_attempt,
            index_result,
            selection,
            "recovered",
            **screen_context,
        )
        return (
            attempts,
            _outcome(
                state.target_id,
                attempts,
                "acquired",
                source_sha256=body_result.sha256,
                source_byte_size=body_result.byte_size,
                selected_sha256=extracted.body_sha256,
                selected_byte_size=extracted.body_size,
                selected_path=_relative(run_root, selected_path),
            ),
            resolution,
            _utc(clock),
        )
    if retain_evidence:
        selected_path = _new_path(staging_root, "selected")
        copyfile(body_result.path, selected_path)
    else:
        selected_path = body_result.path
    body_attempt = _attempt(
        target_id=state.target_id,
        number=number + 2,
        kind="document_body",
        requested_url=selection.selected_url,
        result=body_result,
        started_at_utc=body_started,
        finished_at_utc=body_finished,
        source_path=body_result.path if retain_evidence else None,
        selected_path=selected_path,
        run_root=run_root,
        selected_filename=urlsplit(selection.selected_url).path.rsplit("/", 1)[-1],
    )
    attempts = (*attempts, body_attempt)
    if (
        body_attempt.selected_sha256 != body_result.sha256
        or body_attempt.selected_byte_size != body_result.byte_size
    ):
        selected_path.unlink(missing_ok=True)
        body_attempt = _attempt(
            target_id=state.target_id,
            number=number + 2,
            kind="document_body",
            requested_url=selection.selected_url,
            result=body_result,
            started_at_utc=body_started,
            finished_at_utc=body_finished,
            source_path=body_result.path if retain_evidence else None,
            selected_path=None,
            run_root=run_root,
            outcome="failed",
            error_code="source_mismatch",
        )
        attempts = (*attempts[:-1], body_attempt)
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
    if not retain_evidence:
        source_path.unlink(missing_ok=True)
        fallback_selected_path.unlink(missing_ok=True)
    resolution = _resolution(
        row | {"run_id": run_id},
        response,
        index_attempt,
        index_result,
        selection,
        "recovered",
        **screen_context,
    )
    outcome = _outcome(
        state.target_id,
        attempts,
        "acquired",
        source_sha256=body_result.sha256,
        source_byte_size=body_result.byte_size,
        source_path=None,
        selected_sha256=body_result.sha256,
        selected_byte_size=body_result.byte_size,
        selected_path=_relative(run_root, selected_path),
    )
    return attempts, outcome, resolution, _utc(clock)


__all__ = ["AcquisitionTransport", "acquire_target"]
