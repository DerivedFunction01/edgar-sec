import hashlib

from edgar_sec.infra.sec_http.streaming import StreamedResponse
from edgar_sec.pipelines.document_acquisition.attempts import build_attempt


def test_build_attempt_records_source_and_selected_body_evidence(tmp_path) -> None:
    response_body = b"complete response"
    selected_body = b"selected document"
    response_path = tmp_path / "response.bin"
    selected_path = tmp_path / "selected.bin"
    response_path.write_bytes(response_body)
    selected_path.write_bytes(selected_body)
    response = StreamedResponse(
        status_code=200,
        requested_url="https://www.sec.gov/request",
        final_url="https://www.sec.gov/final",
        sha256=hashlib.sha256(response_body).hexdigest(),
        byte_size=len(response_body),
        content_type="text/plain",
        content_encoding=None,
        path=response_path,
    )

    attempt = build_attempt(
        target_id="target-1",
        number=1,
        kind="document_body",
        requested_url=response.requested_url,
        result=response,
        started_at_utc="2025-01-01T00:00:00+00:00",
        finished_at_utc="2025-01-01T00:00:01+00:00",
        source_path=response_path,
        selected_path=selected_path,
        run_root=tmp_path,
    )

    assert attempt.outcome == "acquired"
    assert attempt.source_sha256 == hashlib.sha256(response_body).hexdigest()
    assert attempt.source_byte_size == len(response_body)
    assert attempt.source_body_relative_path == "response.bin"
    assert attempt.selected_sha256 == hashlib.sha256(selected_body).hexdigest()
    assert attempt.selected_byte_size == len(selected_body)
    assert attempt.selected_body_relative_path == "selected.bin"
