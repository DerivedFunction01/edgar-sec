"""Acquire one target directly from its streamed response."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.infra.sec_http.streaming import StreamedResponse
from edgar_sec.pipelines.document_acquisition.execution.attempts import (
    build_attempt as _attempt,
    relative_path as _relative,
)
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    TargetSlotResolution,
)
from edgar_sec.pipelines.document_acquisition.execution.runner_support import (
    outcome as _outcome,
)
from edgar_sec.pipelines.document_acquisition.run_state.models import TargetState


def acquire_direct_target(
    state: TargetState,
    *,
    number: int,
    requested_url: str,
    response: StreamedResponse,
    started: str,
    finished: str,
    source_path: Path,
    run_root: Path,
) -> tuple[
    tuple[AcquisitionAttempt, ...],
    AcquisitionOutcome,
    TargetSlotResolution | None,
    str | None,
]:
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


__all__ = ["acquire_direct_target"]
