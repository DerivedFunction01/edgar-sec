"""Extract and screen the selected document from a streamed bundle."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

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
)
from edgar_sec.pipelines.document_acquisition.run_state.models import TargetState


class BundleRecovery(NamedTuple):
    """State the orchestrator needs to continue into lazy recovery."""

    fallback_selected_path: Path
    fallback_selected_filename: str | None
    screen_context: dict[str, str | None]


def extract_bundle_selection(
    row: dict[str, object],
    state: TargetState,
    *,
    response: StreamedResponse,
    staging_root: Path,
    run_root: Path,
    number: int,
    requested_url: str,
    started: str,
    finished: str,
    retain_evidence: bool,
    fallback_selected_path: Path,
    fallback_selected_filename: str | None,
    screen_context: dict[str, str | None],
) -> (
    tuple[
        tuple[AcquisitionAttempt, ...],
        AcquisitionOutcome,
        TargetSlotResolution | None,
        str | None,
    ]
    | BundleRecovery
):
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
    return BundleRecovery(
        fallback_selected_path=fallback_selected_path,
        fallback_selected_filename=fallback_selected_filename,
        screen_context=screen_context,
    )


__all__ = ["BundleRecovery", "extract_bundle_selection"]
