from __future__ import annotations

import uuid
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.sec_http.streaming import (
    StreamFailure,
    StreamResult,
    StreamedResponse,
)
from edgar_sec.pipelines.document_acquisition.models import AcquisitionAttempt


def relative_path(run_root: Path, path: Path | None) -> str | None:
    return None if path is None else path.relative_to(run_root).as_posix()


def build_attempt(
    *,
    target_id: str,
    number: int,
    kind: str,
    requested_url: str,
    result: StreamResult,
    started_at_utc: str,
    finished_at_utc: str,
    source_path: Path | None,
    selected_path: Path | None,
    run_root: Path,
    source: str = "live_sec",
    outcome: str | None = None,
    error_code: str | None = None,
) -> AcquisitionAttempt:
    response = result if isinstance(result, StreamedResponse) else None
    status = outcome or ("acquired" if response is not None else "failed")
    retryable = result.retryable if isinstance(result, StreamFailure) else False
    selected_digest = (
        file_sha256(selected_path) if selected_path and selected_path.exists() else None
    )
    selected_size = selected_path.stat().st_size if selected_digest else None
    return AcquisitionAttempt(
        attempt_id=uuid.uuid4().hex,
        target_id=target_id,
        attempt_number=number,
        attempt_kind=kind,
        source=source,
        requested_url=requested_url,
        outcome=status,
        retryable=retryable if status == "failed" else False,
        error_code=error_code
        or (result.code if isinstance(result, StreamFailure) else None),
        http_status=(response.status_code if response else result.http_status),
        final_url=response.final_url if response else None,
        started_at_utc=started_at_utc,
        finished_at_utc=finished_at_utc,
        source_sha256=response.sha256 if response else None,
        source_byte_size=response.byte_size if response else None,
        source_body_relative_path=relative_path(run_root, source_path),
        selected_sha256=selected_digest,
        selected_byte_size=selected_size,
        selected_body_relative_path=relative_path(
            run_root, selected_path if selected_digest else None
        ),
    )
