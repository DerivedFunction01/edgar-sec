from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.sec_http.streaming import StreamFailure, StreamedResponse
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.run_state.models import (
    WorkOrderTargetSeed,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    SCHEMA_VERSION as RUN_STATE_SCHEMA_VERSION,
    get_target_state,
    initialize_run_state,
)
from edgar_sec.pipelines.document_acquisition.runner import execute_acquisition_run
from edgar_sec.pipelines.document_acquisition.target_runner import _validate_redirect
from edgar_sec.pipelines.document_acquisition.schemas import (
    ACQUISITION_CONTRACT_VERSION,
    RUN_SCHEMA_VERSION,
    WORK_ORDER_SCHEMA_VERSION,
)
from edgar_sec.pipelines.document_planning.schemas import TARGET_SCHEMA

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

    _validate_redirect(url, AccessionNumber(_ACCESSION), "320194")
    with pytest.raises(ValueError):
        _validate_redirect(url, AccessionNumber(_ACCESSION), "320193")


def _make_run(
    tmp_path: Path,
    *,
    lazy: bool = True,
    bundle: bool = False,
    executable: bool = True,
):
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id = "acq_test-run"
    run_root = paths.run_dir(run_id)
    work_order_root = paths.work_order_root(run_id)
    work_order_root.mkdir(parents=True)
    target_url = (
        f"https://www.sec.gov/Archives/edgar/data/320193/{_ACCESSION_COMPACT}/"
        f"{_ACCESSION}.txt"
        if bundle
        else f"https://www.sec.gov/Archives/edgar/data/320193/{_ACCESSION_COMPACT}/cover.htm"
    )
    row = {
        "target_id": "target-1",
        "accession": _ACCESSION,
        "form": "10-K",
        "filing_date": "2020-01-30",
        "request_id": "request-1",
        "target_role": "primary",
        "target_type": "primary",
        "optional": False,
        "inventory_entry_id": None,
        "status": "matched",
        "status_reason": None,
        "source_origin": "catalog_direct" if lazy else "inventory_index",
        "retrieval_mode": "bundle_sequence" if bundle else "direct_url",
        "target_url": target_url,
        "sequence": 2 if bundle else 1,
        "byte_size": None,
        "availability_evidence": "catalog_direct" if lazy else "index_row",
        "catalog_direct_selection": "exact_form_with_lazy_index" if lazy else None,
        "executable": executable,
        "skip_reason": None if executable else "target_not_matched",
    }
    work_order_schema = pa.schema(
        [
            *TARGET_SCHEMA,
            pa.field("executable", pa.bool_(), nullable=False),
            pa.field("skip_reason", pa.string(), nullable=True),
        ],
        metadata=TARGET_SCHEMA.metadata,
    )
    work_order_path = work_order_root / "part-00000.parquet"
    pq.write_table(
        pa.Table.from_pylist([row], schema=work_order_schema), work_order_path
    )
    initialize_run_state(
        paths.run_state_path(run_id),
        [WorkOrderTargetSeed("target-1", executable, row["skip_reason"])],
    )
    manifest = {
        "run_id": run_id,
        "run_schema_version": RUN_SCHEMA_VERSION,
        "acquisition_contract_version": ACQUISITION_CONTRACT_VERSION,
        "target_plan_id": "plan-1",
        "target_plan_digest": "a" * 64,
        "bundle_schema_version": 3,
        "target_schema_version": 1,
        "matcher_version": "matcher-v1",
        "catalog_plan_id": "catalog-1",
        "catalog_plan_digest": "b" * 64,
        "inventory_snapshot_id": None,
        "inventory_snapshot_digest": None,
        "work_order_schema_version": WORK_ORDER_SCHEMA_VERSION,
        "work_order_parts": [
            {
                "path": "work_order/part-00000.parquet",
                "row_count": 1,
                "byte_size": work_order_path.stat().st_size,
                "sha256": file_sha256(work_order_path),
            }
        ],
        "target_row_count": 1,
        "executable_count": int(executable),
        "skipped_count": int(not executable),
        "run_state_schema_version": RUN_STATE_SCHEMA_VERSION,
    }
    manifest["run_digest"] = canonical_hash(manifest)
    atomic_write_json(paths.run_manifest_path(run_id), manifest)
    return paths, run_id, row


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
    selected_body = paths.run_dir(run_id) / state.selected_body_relative_path
    assert selected_body.read_bytes() == b"<html>selected filing</html>"
    assert state.source_body_relative_path is None
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        attempts = connection.execute(
            "SELECT attempt_id, attempt_kind, outcome FROM attempts ORDER BY attempt_number"
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
    assert resolution == ("unverifiable", "recovered", attempts[1][0])


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

    assert report.target_counts["failed"] == 1
    assert [url for url, _ in transport.calls] == [row["target_url"], _INDEX_URL]
    assert not list(paths.run_staging_root(run_id).iterdir())
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
