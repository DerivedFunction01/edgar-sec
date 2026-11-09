"""Tests for the acquisition-time ephemeral intent pass."""

from __future__ import annotations

import hashlib
from pathlib import Path

from edgar_sec.engine.index_pages.enumeration import TargetIntent
from edgar_sec.infra.sec_http.streaming import StreamFailure, StreamedResponse
from edgar_sec.pipelines.document_acquisition.ephemeral import run_ephemeral_pass
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.run_state.ephemeral import (
    read_ephemeral_targets,
)
from tests.support import fixture_path

_ACCESSION = "0001234567-24-000042"
_ARCHIVE_ROOT = "https://www.sec.gov/Archives/edgar/data/1234567/000123456724000042/"
_INDEX_URL = _ARCHIVE_ROOT + f"{_ACCESSION}-index.html"
_EXHIBIT_BODY = b"<html><body>Press release.</body></html>"


class _Transport:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def stream_to_file(self, url, destination, *, max_response_bytes, validate_redirect):
        self.calls.append(url)
        if url not in self.responses:
            return StreamFailure(
                code="http_not_found",
                retryable=False,
                http_status=404,
                detail="fixture has no such document",
            )
        validate_redirect(url)
        body = self.responses[url]
        path = Path(destination)
        path.write_bytes(body)
        return StreamedResponse(
            status_code=200,
            requested_url=url,
            final_url=url,
            sha256=hashlib.sha256(body).hexdigest(),
            byte_size=len(body),
            content_type="text/html",
            content_encoding=None,
            path=path,
        )

    def close(self) -> None:
        pass


def _intent(doc_type: str) -> TargetIntent:
    return TargetIntent(
        role="exhibit",
        type=doc_type,
        optional=True,
        request_id=f"exhibit:{doc_type}",
    )


def _run(tmp_path: Path, transport: _Transport, intents: tuple[TargetIntent, ...]):
    paths = resolve_acquisition_paths(artifacts_root=tmp_path / "artifacts")
    counts = run_ephemeral_pass(
        run_id="run-1",
        accessions=(_ACCESSION,),
        intents=intents,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=100_000),
        transport=transport,
        workers=1,
    )
    return paths, counts


def test_matched_intent_is_acquired_and_recorded(tmp_path: Path) -> None:
    transport = _Transport(
        {
            _INDEX_URL: fixture_path(
                "document_planning_index_page.html"
            ).read_bytes(),
            _ARCHIVE_ROOT + "ex991.htm": _EXHIBIT_BODY,
        }
    )
    paths, counts = _run(tmp_path, transport, (_intent("EX-99.1"),))
    assert counts == {"acquired": 1}
    assert transport.calls == [_INDEX_URL, _ARCHIVE_ROOT + "ex991.htm"]
    (row,) = read_ephemeral_targets(paths.run_state_path("run-1"))
    assert row["status"] == "matched"
    assert row["outcome"] == "acquired"
    assert row["document_type"] == "EX-99.1"
    assert row["filename"] == "ex991.htm"
    body_path = paths.run_dir("run-1") / row["body_relative_path"]
    assert body_path.read_bytes() == _EXHIBIT_BODY


def test_absent_intent_is_recorded_not_filed(tmp_path: Path) -> None:
    transport = _Transport(
        {_INDEX_URL: fixture_path("document_planning_index_page.html").read_bytes()}
    )
    paths, counts = _run(tmp_path, transport, (_intent("EX-99.2"),))
    assert counts == {"not_acquired": 1}
    (row,) = read_ephemeral_targets(paths.run_state_path("run-1"))
    assert row["status"] == "not_filed"
    assert row["outcome"] == "not_acquired"


def test_index_failure_is_recorded_per_intent(tmp_path: Path) -> None:
    paths, counts = _run(tmp_path, _Transport({}), (_intent("EX-99.1"),))
    assert counts == {"not_acquired": 1}
    (row,) = read_ephemeral_targets(paths.run_state_path("run-1"))
    assert row["status"] == "unresolved"
    assert row["status_reason"] == "index_fetch_failed"
