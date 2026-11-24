"""Screen and seat the body recovered through the submission index."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from shutil import copyfile
from urllib.parse import urlsplit

from edgar_sec.domain.document_inventory.models import InventoryEntry
from edgar_sec.engine.document.screening import screen_candidate_document
from edgar_sec.engine.document.unpacking.streaming import (
    BundleExtraction,
    extract_bundle_sequence,
)
from edgar_sec.infra.sec_http.streaming import StreamedResponse
from edgar_sec.pipelines.document_acquisition.execution.attempts import (
    build_attempt as _attempt,
    relative_path as _relative,
)
from edgar_sec.pipelines.document_acquisition.execution.index_selection import (
    IndexSelection,
)
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    AcquisitionStatus,
    TargetSlotResolution,
)
from edgar_sec.pipelines.document_acquisition.execution.runner_support import (
    apply_structure_screen as _apply_structure_screen,
    has_lazy_index_trigger as _has_lazy_index_trigger,
    new_staging_path as _new_path,
    outcome as _outcome,
    read_screen_head as _read_screen_head,
    resolution_screen_kind as _resolution_screen_kind,
    unresolved_source_outcome as _unresolved_source_outcome,
    utc_now as _utc,
)
from edgar_sec.pipelines.document_acquisition.execution.resolution import (
    build_resolution as _resolution,
)
from edgar_sec.pipelines.document_acquisition.run_state.models import TargetState


def seat_recovered_body(
    row: dict[str, object],
    state: TargetState,
    *,
    run_id: str,
    run_root: Path,
    staging_root: Path,
    response: StreamedResponse,
    first_attempt: AcquisitionAttempt,
    index_attempt: AcquisitionAttempt,
    index_result: StreamedResponse,
    selection: IndexSelection,
    entry: InventoryEntry,
    body_result: StreamedResponse,
    body_started: str,
    body_finished: str,
    attempts: tuple[AcquisitionAttempt, ...],
    number: int,
    started: str,
    finished: str,
    source_path: Path,
    fallback_selected_path: Path,
    fallback_selected_filename: str | None,
    retain_evidence: bool,
    screen_context: dict[str, str | None],
    clock: Callable[[], datetime],
) -> tuple[
    tuple[AcquisitionAttempt, ...],
    AcquisitionOutcome,
    TargetSlotResolution | None,
    str | None,
]:
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


__all__ = ["seat_recovered_body"]
