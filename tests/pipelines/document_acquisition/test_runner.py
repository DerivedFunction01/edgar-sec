from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.sec_http.streaming import StreamFailure, StreamedResponse
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.run_state.operations import (
    get_operation_state,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    get_target_state,
)
from edgar_sec.pipelines.document_acquisition import runner as acquisition_runner
from edgar_sec.pipelines.document_acquisition.runner import execute_acquisition_run
from edgar_sec.pipelines.document_acquisition.runner_support import validate_redirect
from tests.acquisition_run_fixture import make_acquisition_run as _make_run

_ACCESSION = "0000320193-20-000096"
_ACCESSION_COMPACT = _ACCESSION.replace("-", "")
_INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    f"{_ACCESSION_COMPACT}/{_ACCESSION}-index.html"
)
_BUNDLE_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    f"{_ACCESSION_COMPACT}/{_ACCESSION}.txt"
)
_INDEX = (
    b"<table summary='Document Format Files'><tr><th>Seq</th><th>Description</th>"
    b"<th>Document</th><th>Type</th><th>Size</th></tr>"
    b"<tr><td>2</td><td>Annual report</td><td><a href='report.htm'>report.htm</a>"
    b"</td><td>10-K</td><td>12</td></tr></table>"
)
_UNLINKED_INDEX = (
    b"<table summary='Document Format Files'><tr><th>Seq</th><th>Description</th>"
    b"<th>Document</th><th>Type</th><th>Size</th></tr>"
    b"<tr><td>2</td><td>Annual report</td><td>not linked</td><td>10-K</td><td>12</td></tr>"
    b"<tr><td></td><td>Complete submission text file</td><td><a href='"
    + _BUNDLE_URL.encode()
    + b"'>bundle</a></td><td></td><td>100</td></tr></table>"
)


def test_redirect_validator_binds_to_requested_archive_cik() -> None:
    url = _BUNDLE_URL.replace("/320193/", "/320194/")

    validate_redirect(url, AccessionNumber(_ACCESSION), "320194")
    with pytest.raises(ValueError):
        validate_redirect(url, AccessionNumber(_ACCESSION), "320193")


class _MemoryTransport:
    def __init__(
        self,
        responses: dict[str, bytes],
        digest_overrides: dict[str, str] | None = None,
        failures: dict[str, StreamFailure] | None = None,
    ) -> None:
        self.responses = responses
        self.digest_overrides = digest_overrides or {}
        self.failures = failures or {}
        self.calls: list[tuple[str, int]] = []
        self.closed = False

    def stream_to_file(
        self,
        url,
        destination,
        *,
        max_response_bytes,
        validate_redirect,
    ):
        self.calls.append((url, max_response_bytes))
        validate_redirect(url)
        if url in self.failures:
            return self.failures[url]
        body = self.responses[url]
        path = Path(destination)
        path.write_bytes(body)
        return StreamedResponse(
            status_code=200,
            requested_url=url,
            final_url=url,
            sha256=self.digest_overrides.get(url, hashlib.sha256(body).hexdigest()),
            byte_size=len(body),
            content_type="text/html",
            content_encoding=None,
            path=path,
        )

    def close(self) -> None:
        self.closed = True


def test_runner_uses_exact_lazy_index_and_atomically_records_all_attempts(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(tmp_path)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    selected_url = _INDEX_URL.rsplit("/", 1)[0] + "/report.htm"
    transport = _MemoryTransport(
        {
            row["target_url"]: b"<html>unverifiable cover</html>",
            _INDEX_URL: _INDEX,
            selected_url: b"<html>selected filing</html>",
        }
    )
    process = acquisition_runner.process_acquired_target
    processing_targets: list[str] = []

    def process_under_run_lock(target, **kwargs):
        assert paths.run_lock_path(run_id).is_file()
        target_state = get_target_state(
            paths.run_state_path(run_id), str(target["target_id"])
        )
        assert target_state is not None and target_state.outcome == "acquired"
        processing_targets.append(str(target["target_id"]))
        return process(target, **kwargs)

    monkeypatch.setattr(
        acquisition_runner, "process_acquired_target", process_under_run_lock
    )

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=4096, requested_workers=2),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.attempted_count == 1
    assert report.target_counts["acquired"] == 1
    assert report.state == "complete"
    assert processing_targets == ["target-1"]
    assert transport.closed
    assert [url for url, _ in transport.calls] == [
        row["target_url"],
        _INDEX_URL,
        selected_url,
    ]
    assert {limit for _, limit in transport.calls} == {4096}
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None
    assert state.attempt_count == 3
    assert state.selected_body_relative_path is not None
    raw_operation_id = canonical_hash([state.target_id, "raw"])
    operation_state = get_operation_state(
        paths.run_state_path(run_id), raw_operation_id
    )
    assert operation_state is not None
    assert operation_state.status == "succeeded"
    assert operation_state.attempt_count == 1
    selected_body = paths.run_dir(run_id) / state.selected_body_relative_path
    assert selected_body.read_bytes() == b"<html>selected filing</html>"
    assert state.source_body_relative_path is None
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        attempts = connection.execute(
            "SELECT attempt_id, attempt_kind, outcome FROM attempts ORDER BY attempt_number"
        ).fetchall()
        selected_filenames = connection.execute(
            "SELECT selected_filename FROM attempts ORDER BY attempt_number"
        ).fetchall()
        evidence_paths = connection.execute(
            "SELECT source_body_relative_path FROM attempts ORDER BY attempt_number"
        ).fetchall()
        resolution = connection.execute(
            "SELECT screen_result, result, index_attempt_id "
            "FROM target_slot_resolutions"
        ).fetchone()
    assert [row[1:] for row in attempts] == [
        ("document_body", "acquired"),
        ("lazy_index", "acquired"),
        ("document_body", "acquired"),
    ]
    assert evidence_paths == [(None,), (None,), (None,)]
    assert selected_filenames[-1] == ("report.htm",)
    assert resolution == ("unverifiable", "recovered", attempts[1][0])


def test_form_4_exhibit_primary_candidate_recovers_form_document(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(tmp_path, form="4", filename="ex99.htm", lazy=True)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    index = (
        b"<table summary='Document Format Files'><tr><th>Seq</th><th>Description</th>"
        b"<th>Document</th><th>Type</th><th>Size</th></tr>"
        b"<tr><td>1</td><td>Ownership</td><td><a href='form4.htm'>form4.htm</a>"
        b"</td><td>4</td><td>100</td></tr></table>"
        b"<table summary='Data Files'><tr><th>Seq</th><th>Description</th>"
        b"<th>Document</th><th>Type</th><th>Size</th></tr>"
        b"<tr><td>2</td><td>Press release</td><td><a href='ex99.htm'>ex99.htm</a>"
        b"</td><td>EX-99.1</td><td>200</td></tr></table>"
    )
    selected_url = _INDEX_URL.rsplit("/", 1)[0] + "/form4.htm"
    ownership = (
        b"<html><body><h1>FORM 4</h1><p>Issuer Acme</p>"
        b"<p>Reporting Owner</p><p>Relationship of Reporting Person</p>"
        b"<p>Table I - Non-Derivative</p></body></html>"
    )
    transport = _MemoryTransport(
        {
            row[
                "target_url"
            ]: b"<html><h1>Exhibit 99.1</h1><p>Acme press release</p></html>",
            _INDEX_URL: index,
            selected_url: ownership,
        }
    )

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.target_counts["acquired"] == 1
    assert [url for url, _ in transport.calls] == [
        row["target_url"],
        _INDEX_URL,
        selected_url,
    ]
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.selected_body_relative_path is not None
    assert (
        paths.run_dir(run_id) / state.selected_body_relative_path
    ).read_bytes() == ownership
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        resolution = connection.execute(
            "SELECT expected_statutory_type, result FROM target_slot_resolutions"
        ).fetchone()
    assert resolution == ("4", "recovered")


def test_runner_recovers_unlinked_index_row_from_exact_bundle_sequence(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(tmp_path)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    selected_body = b"exact bundled body"
    bundle = (
        b"<DOCUMENT><SEQUENCE>1<TYPE>EX-99<TEXT>other</TEXT></DOCUMENT>"
        b"<DOCUMENT><SEQUENCE>2<TYPE>10-K<TEXT>" + selected_body + b"</TEXT></DOCUMENT>"
    )
    transport = _MemoryTransport(
        {
            row["target_url"]: b"<html>unverifiable cover</html>",
            _INDEX_URL: _UNLINKED_INDEX,
            _BUNDLE_URL: bundle,
        }
    )

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.target_counts["acquired"] == 1
    assert [url for url, _ in transport.calls] == [
        row["target_url"],
        _INDEX_URL,
        _BUNDLE_URL,
    ]
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.selected_body_relative_path is not None
    assert (
        paths.run_dir(run_id) / state.selected_body_relative_path
    ).read_bytes() == selected_body
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        resolution = connection.execute(
            "SELECT selected_sequence, selected_retrieval_mode, selected_url, result "
            "FROM target_slot_resolutions"
        ).fetchone()
    assert resolution == (2, "bundle_sequence", _BUNDLE_URL, "recovered")


def test_empty_work_order_does_not_construct_transport(tmp_path, monkeypatch) -> None:
    paths, run_id, _ = _make_run(tmp_path, lazy=False, executable=False)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    transport = _MemoryTransport({})

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=512),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert transport.calls == []
    assert report.attempted_count == 0
    assert report.target_counts["skipped"] == 1


def test_lazy_index_bytes_must_match_streamed_response_digest(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(tmp_path)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    transport = _MemoryTransport(
        {
            row["target_url"]: b"<html>unverifiable cover</html>",
            _INDEX_URL: _INDEX,
        },
        digest_overrides={_INDEX_URL: "0" * 64},
    )

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.target_counts["acquired"] == 1
    assert [url for url, _ in transport.calls] == [row["target_url"], _INDEX_URL]
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.selected_body_relative_path is not None
    assert (
        paths.run_dir(run_id) / state.selected_body_relative_path
    ).read_bytes() == b"<html>unverifiable cover</html>"
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        assert connection.execute(
            "SELECT outcome, error_code FROM attempts ORDER BY attempt_number DESC LIMIT 1"
        ).fetchone() == ("acquired", None)
        assert connection.execute(
            "SELECT result FROM target_slot_resolutions"
        ).fetchone() == ("failed",)


def test_runner_extracts_only_the_planned_bundle_sequence(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=False, bundle=True)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    bundle_url = row["target_url"]
    body = b"selected exact bytes\r\n"
    envelope = (
        b"<DOCUMENT><SEQUENCE>1<TEXT>ignored body</TEXT></DOCUMENT>"
        b"<DOCUMENT><SEQUENCE>2<TYPE>10-K<TEXT>" + body + b"</TEXT></DOCUMENT>"
    )
    transport = _MemoryTransport({bundle_url: envelope})

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.target_counts["acquired"] == 1
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None
    selected_body = paths.run_dir(run_id) / state.selected_body_relative_path
    assert selected_body.read_bytes() == body
    assert state.source_sha256 == hashlib.sha256(envelope).hexdigest()
    assert state.selected_sha256 == hashlib.sha256(body).hexdigest()
    assert state.source_body_relative_path is None
    assert not list(paths.run_staging_root(run_id).glob("response-*.bin"))


def test_runner_retains_primary_bundle_response_evidence_when_enabled(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=False, bundle=True)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    bundle_url = row["target_url"]
    body = b"selected exact bytes\r\n"
    envelope = (
        b"<DOCUMENT><SEQUENCE>1<TEXT>ignored body</TEXT></DOCUMENT>"
        b"<DOCUMENT><SEQUENCE>2<TYPE>10-K<TEXT>" + body + b"</TEXT></DOCUMENT>"
    )
    transport = _MemoryTransport({bundle_url: envelope})

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(
            max_response_bytes=4096, retain_response_evidence=True
        ),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.target_counts["acquired"] == 1
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        attempt = connection.execute(
            "SELECT source_sha256, source_byte_size, source_body_relative_path, "
            "selected_body_relative_path FROM attempts"
        ).fetchone()
    assert attempt is not None
    source_path = paths.run_dir(run_id) / attempt[2]
    selected_path = paths.run_dir(run_id) / attempt[3]
    assert source_path.read_bytes() == envelope
    assert file_sha256(source_path) == attempt[0]
    assert source_path.stat().st_size == attempt[1]
    assert selected_path.read_bytes() == body
    assert source_path != selected_path


def test_runner_retains_each_lazy_response_as_attempt_evidence_when_enabled(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(tmp_path)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    selected_url = _INDEX_URL.rsplit("/", 1)[0] + "/report.htm"
    responses = {
        row["target_url"]: b"<html>unverifiable cover</html>",
        _INDEX_URL: _INDEX,
        selected_url: b"<html>selected filing</html>",
    }
    transport = _MemoryTransport(responses)

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(
            max_response_bytes=4096, retain_response_evidence=True
        ),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.target_counts["acquired"] == 1
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        attempts = connection.execute(
            "SELECT requested_url, source_sha256, source_byte_size, "
            "source_body_relative_path, selected_body_relative_path "
            "FROM attempts ORDER BY attempt_number"
        ).fetchall()
    assert [attempt[0] for attempt in attempts] == [
        row["target_url"],
        _INDEX_URL,
        selected_url,
    ]
    for attempt in attempts:
        source_path = paths.run_dir(run_id) / attempt[3]
        assert source_path.is_file()
        assert file_sha256(source_path) == attempt[1]
        assert source_path.stat().st_size == attempt[2]
    selected_path = paths.run_dir(run_id) / attempts[-1][4]
    assert selected_path.is_file()
    assert selected_path.read_bytes() == responses[selected_url]
    assert selected_path != paths.run_dir(run_id) / attempts[-1][3]


def test_runner_retains_lazy_response_evidence_after_index_parse_failure(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(
        tmp_path, form="4", filename="ex99.htm", default_candidates=True
    )
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    responses = {
        row["target_url"]: b"<html>unverifiable cover</html>",
        _INDEX_URL: b"<html>unrecognized index</html>",
    }
    transport = _MemoryTransport(responses)

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(
            max_response_bytes=4096, retain_response_evidence=True
        ),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.target_counts["acquired"] == 1
    raw_state = get_operation_state(
        paths.run_state_path(run_id), canonical_hash(["target-1", "raw"])
    )
    xml_state = get_operation_state(
        paths.run_state_path(run_id), canonical_hash(["target-1", "render_to_xml"])
    )
    assert raw_state is not None and raw_state.status == "succeeded"
    assert (
        xml_state is not None
        and xml_state.status == "failed"
        and xml_state.error_code == "unsupported:primary_document_identity_mismatch"
    )
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        attempts = connection.execute(
            "SELECT requested_url, source_sha256, source_byte_size, "
            "source_body_relative_path FROM attempts ORDER BY attempt_number"
        ).fetchall()
    assert [attempt[0] for attempt in attempts] == [
        row["target_url"],
        _INDEX_URL,
        row["target_url"],
    ]
    for attempt in attempts[:2]:
        source_path = paths.run_dir(run_id) / attempt[3]
        assert source_path.read_bytes() == responses[attempt[0]]
        assert file_sha256(source_path) == attempt[1]
        assert source_path.stat().st_size == attempt[2]
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.selected_body_relative_path is not None
    assert (
        paths.run_dir(run_id) / state.selected_body_relative_path
    ).read_bytes() == responses[row["target_url"]]


@pytest.mark.parametrize(
    ("document_type", "expected_screen"),
    [(b"<TYPE>8-K", "type_mismatch"), (b"", "unverifiable")],
)
def test_runner_uses_lazy_index_when_bundle_type_mismatches_or_is_missing(
    tmp_path, monkeypatch, document_type: bytes, expected_screen: str
) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=True, bundle=True)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    bundle = (
        b"<DOCUMENT><SEQUENCE>2"
        + document_type
        + b"<TEXT>wrong initial form</TEXT></DOCUMENT>"
    )
    selected_url = _INDEX_URL.rsplit("/", 1)[0] + "/report.htm"
    transport = _MemoryTransport(
        {
            row["target_url"]: bundle,
            _INDEX_URL: _INDEX,
            selected_url: b"<html>index-identified form</html>",
        }
    )

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.target_counts["acquired"] == 1
    assert [url for url, _ in transport.calls] == [
        row["target_url"],
        _INDEX_URL,
        selected_url,
    ]
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        resolution = connection.execute(
            "SELECT screen_kind, screen_result, result FROM target_slot_resolutions"
        ).fetchone()
    assert resolution == (
        "sgml_type",
        expected_screen,
        "recovered",
    )


def test_runner_bundle_amendment_matches_base_sgml_type(tmp_path, monkeypatch) -> None:
    paths, run_id, row = _make_run(tmp_path, form="4/A", lazy=True, bundle=True)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    body = (
        b"FORM 4 Reporting Person Issuer Relationship of Reporting Person "
        b"Table I - Non-Derivative Securities"
    )
    bundle = b"<DOCUMENT><SEQUENCE>2<TYPE>4<TEXT>" + body + b"</TEXT></DOCUMENT>"
    transport = _MemoryTransport({row["target_url"]: bundle})

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.target_counts["acquired"] == 1
    assert [url for url, _ in transport.calls] == [row["target_url"]]
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.selected_body_relative_path is not None
    selected_path = paths.run_dir(run_id) / state.selected_body_relative_path
    assert selected_path.read_bytes() == body


def test_runner_does_not_screen_bundle_type_without_lazy_selector(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=False, bundle=True)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    bundle = b"<DOCUMENT><SEQUENCE>2<TYPE>8-K<TEXT>wrong</TEXT></DOCUMENT>"
    transport = _MemoryTransport({row["target_url"]: bundle})

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.target_counts["acquired"] == 1
    assert [url for url, _ in transport.calls] == [row["target_url"]]
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.outcome == "acquired"
    selected_path = paths.run_dir(run_id) / state.selected_body_relative_path
    assert selected_path.read_bytes() == b"wrong"


def test_direct_404_is_failed_without_lazy_index_recovery(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=False)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    transport = _MemoryTransport(
        {},
        failures={
            row["target_url"]: StreamFailure("http_not_found", False, 404, "missing")
        },
    )

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.target_counts["failed"] == 1
    assert transport.calls == [(row["target_url"], 4096)]
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None
    assert state.error_code == "http_not_found"
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM target_slot_resolutions"
        ).fetchone() == (0,)


def test_failed_sibling_does_not_remove_acquired_body(tmp_path, monkeypatch) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=False, sibling_failure=True)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    sibling_url = row["target_url"].rsplit("/", 1)[0] + "/sibling.htm"
    transport = _MemoryTransport(
        {row["target_url"]: b"selected primary body"},
        failures={sibling_url: StreamFailure("http_not_found", False, 404, "missing")},
    )

    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.target_counts["acquired"] == 1
    assert report.target_counts["failed"] == 1
    acquired = get_target_state(paths.run_state_path(run_id), "target-1")
    failed = get_target_state(paths.run_state_path(run_id), "target-2")
    assert acquired is not None and acquired.outcome == "acquired"
    assert failed is not None and failed.outcome == "failed"
    body_path = paths.run_dir(run_id) / acquired.selected_body_relative_path
    assert body_path.read_bytes() == b"selected primary body"


def test_interrupt_during_transfer_leaves_target_pending_and_cleans_partial(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, _ = _make_run(tmp_path, lazy=False)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )

    class InterruptTransport(_MemoryTransport):
        def stream_to_file(
            self, url, destination, *, max_response_bytes, validate_redirect
        ):
            self.calls.append((url, max_response_bytes))
            validate_redirect(url)
            Path(destination).write_bytes(b"partial")
            raise KeyboardInterrupt

    transport = InterruptTransport({})
    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert report.cancelled
    assert report.target_counts["pending"] == 1
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.attempt_count == 0
    assert not list(paths.run_staging_root(run_id).iterdir())


def test_concurrent_execution_acquires_multiple_targets(tmp_path, monkeypatch) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=False, sibling_failure=True)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=2, worker_ceiling=4),
    )
    sibling_url = row["target_url"].rsplit("/", 1)[0] + "/sibling.htm"
    transport = _MemoryTransport(
        {
            row["target_url"]: b"selected primary body",
            sibling_url: b"selected sibling body",
        },
    )
    progress_records: list[dict] = []
    report = execute_acquisition_run(
        run_id,
        retry_failures=False,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=4096, requested_workers=2),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
        progress_callback=progress_records.append,
    )

    assert report.target_counts["acquired"] == 2
    assert report.attempted_count == 2
    assert len(progress_records) == 2
    state1 = get_target_state(paths.run_state_path(run_id), "target-1")
    state2 = get_target_state(paths.run_state_path(run_id), "target-2")
    assert state1 is not None and state1.outcome == "acquired"
    assert state2 is not None and state2.outcome == "acquired"


def _sgml_document(
    document_type: str, sequence: int, filename: str, body: str
) -> bytes:
    return (
        f"<DOCUMENT>\n<TYPE>{document_type}\n<SEQUENCE>{sequence}\n"
        f"<FILENAME>{filename}\n<TEXT>{body}</TEXT>\n</DOCUMENT>\n"
    ).encode()


def _scan_row(**overrides):
    row = {
        "run_id": "run-scan",
        "target_id": "target-1",
        "accession": _ACCESSION,
        "form": "4",
        "filing_date": "1999-12-01",
        "report_date": "1999-11-30",
        "request_id": "request-1",
        "target_role": "primary",
        "target_type": "primary",
        "optional": False,
        "inventory_entry_id": None,
        "status": "matched",
        "status_reason": "sgml_bundle_scan_pre2000",
        "source_origin": "catalog_direct",
        "retrieval_mode": "bundle_scan",
        "target_url": _BUNDLE_URL,
        "sequence": None,
        "byte_size": None,
        "availability_evidence": "catalog_metadata",
        "catalog_direct_selection": "submitted_primary",
        "executable": True,
        "skip_reason": None,
        "lazy_index_trigger_id": None,
        "lazy_index_trigger_version": None,
    }
    row.update(overrides)
    return row


def _run_scan(tmp_path, bundle: bytes, **row_overrides):
    from edgar_sec.pipelines.document_acquisition.paths import (
        resolve_acquisition_paths,
    )
    from edgar_sec.pipelines.document_acquisition.run_state.models import (
        TargetState,
    )
    from edgar_sec.pipelines.document_acquisition.target_runner import (
        acquire_target,
    )

    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    paths.run_staging_root("run-scan").mkdir(parents=True, exist_ok=True)
    state = TargetState(
        "target-1",
        True,
        None,
        "pending",
        None,
        False,
        0,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    transport = _MemoryTransport({_BUNDLE_URL: bundle})
    attempts, outcome, resolution, _recorded = acquire_target(
        _scan_row(**row_overrides),
        state,
        run_id="run-scan",
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=100000),
        transport=transport,
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )
    return paths, transport, attempts, outcome, resolution


def test_scan_target_acquires_type_match_at_later_sequence(tmp_path) -> None:
    bundle = (
        _sgml_document("EX-99", 1, "ex99.txt", "exhibit")
        + _sgml_document("GRAPHIC", 2, "chart.jpg", "image")
        + _sgml_document("4", 3, "form4.txt", "FORM FOUR BODY")
    )
    _paths, transport, attempts, outcome, resolution = _run_scan(tmp_path, bundle)

    assert [url for url, _ in transport.calls] == [_BUNDLE_URL]
    assert outcome.status == "acquired"
    assert outcome.selected_sha256 == hashlib.sha256(b"FORM FOUR BODY").hexdigest()
    assert len(attempts) == 1
    assert attempts[0].selected_filename == "form4.txt"
    assert resolution is not None
    assert resolution.selector == "sgml_bundle_scan"
    assert resolution.result == "selected_in_bundle"
    assert resolution.selected_sequence == 3
    assert resolution.selected_retrieval_mode == "bundle_scan"
    assert resolution.initial_sequence is None
    assert resolution.index_attempt_id is None


def test_scan_target_duplicate_type_is_ambiguous(tmp_path) -> None:
    bundle = _sgml_document("4", 1, "a.txt", "one") + _sgml_document(
        "4", 2, "b.txt", "two"
    )
    _paths, _t, _a, outcome, resolution = _run_scan(tmp_path, bundle)

    assert outcome.status == "ambiguous"
    assert resolution is not None
    assert resolution.result == "ambiguous"
    assert resolution.selected_sequence is None


def test_scan_target_without_type_match(tmp_path) -> None:
    bundle = _sgml_document("EX-99", 1, "ex99.txt", "exhibit")
    _p, _t, _a, outcome, resolution = _run_scan(tmp_path, bundle)
    assert outcome.status == "required_missing"
    assert resolution is not None and resolution.result == "required_missing"

    _p, _t, _a, optional_outcome, _r = _run_scan(tmp_path, bundle, optional=True)
    assert optional_outcome.status == "not_filed"


def test_scan_target_amendment_form_matches_base_type(tmp_path) -> None:
    bundle = _sgml_document("4", 1, "form4a.txt", "AMENDED BODY")
    _p, _t, _a, outcome, resolution = _run_scan(tmp_path, bundle, form="4/A")

    assert outcome.status == "acquired"
    assert outcome.selected_sha256 == hashlib.sha256(b"AMENDED BODY").hexdigest()
    assert resolution is not None and resolution.selected_sequence == 1


def test_scan_resolution_is_recorded_in_run_state(tmp_path) -> None:
    from edgar_sec.pipelines.document_acquisition.run_state.models import (
        WorkOrderTargetSeed,
    )
    from edgar_sec.pipelines.document_acquisition.run_state.store import (
        commit_attempts_and_update_target,
        initialize_run_state,
    )

    bundle = _sgml_document("4", 3, "form4.txt", "FORM FOUR BODY")
    paths, _t, attempts, outcome, resolution = _run_scan(tmp_path, bundle)
    database = paths.run_state_path("run-scan")
    initialize_run_state(database, [WorkOrderTargetSeed("target-1", True, None)])
    commit_attempts_and_update_target(
        database,
        attempts,
        outcome,
        resolution=resolution,
        recorded_at_utc="2025-01-01T00:00:00+00:00",
    )

    state = get_target_state(database, "target-1")
    assert state is not None and state.outcome == "acquired"
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT selector, initial_sequence, selected_sequence,"
            " selected_retrieval_mode, result, resolution_schema_version"
            " FROM target_slot_resolutions"
        ).fetchall()
    assert rows == [
        ("sgml_bundle_scan", None, 3, "bundle_scan", "selected_in_bundle", "2")
    ]
