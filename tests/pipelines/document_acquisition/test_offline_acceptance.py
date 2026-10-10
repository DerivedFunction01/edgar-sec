from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.settings.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.sec_http.streaming import StreamedResponse
from edgar_sec.pipelines.document_acquisition import cli as acquisition_cli
from edgar_sec.pipelines.document_acquisition.fixture_operator import (
    capture_fixture_case,
    create_fixture,
    replay_fixture_case,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    get_fixture_case,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.replay import (
    replay_fixture_response,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import (
    SCHEMA_VERSION as FIXTURE_SCHEMA_VERSION,
)
from edgar_sec.pipelines.document_acquisition.body_handoff import (
    get_staged_body_ref,
    read_body_consumption_receipt,
    record_body_consumption_receipt,
)
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.plan_projection.project import (
    project_acquisition_run,
)
from edgar_sec.pipelines.document_acquisition.runner import execute_acquisition_run
from edgar_sec.pipelines.document_acquisition.run_state.store import get_target_state
from edgar_sec.pipelines.document_acquisition.schemas import (
    RECEIPT_SCHEMA_VERSION,
    target_plan_bundle_schema_version,
    target_plan_matcher_version,
)
from edgar_sec.pipelines.document_planning.schemas import (
    TARGET_SCHEMA,
    TARGET_SCHEMA_VERSION,
)

_ACCESSION = "0000320193-20-000096"
_ACCESSION_COMPACT = _ACCESSION.replace("-", "")
_ARCHIVE_ROOT = f"https://www.sec.gov/Archives/edgar/data/320193/{_ACCESSION_COMPACT}/"
_TARGET_URL = _ARCHIVE_ROOT + f"{_ACCESSION}.txt"
_INDEX_URL = _ARCHIVE_ROOT + f"{_ACCESSION}-index.html"
_SELECTED_URL = _ARCHIVE_ROOT + "report.htm"
_INDEX = (
    b"<table summary='Document Format Files'><tr><th>Seq</th><th>Description</th>"
    b"<th>Document</th><th>Type</th><th>Size</th></tr>"
    b"<tr><td>2</td><td>Annual report</td><td><a href='report.htm'>report.htm</a>"
    b"</td><td>10-K</td><td>12</td></tr></table>"
)
_INITIAL_BODY = b"<html>catalog primary response</html>"
_SELECTED_BODY = b"<html>selected filing body</html>"
_FIXTURE_ID = "offline-acceptance-v3"


def _write_pinned_plan(artifacts_root: Path) -> tuple[str, dict[str, Any]]:
    identity = {
        "bundle_schema_version": target_plan_bundle_schema_version(),
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "matcher_version": target_plan_matcher_version(),
        "row_group_size": DEFAULT_ROW_GROUP_SIZE,
        "profile_digest": "c" * 64,
        "catalog_plan_id": "catalog-offline-acceptance",
        "catalog_plan_digest": "a" * 64,
        "inventory_snapshot_id": None,
        "inventory_snapshot_digest": None,
    }
    plan_id = f"dplan_{canonical_hash(identity)[:32]}"
    plan_root = artifacts_root / "document_planning" / "plans" / plan_id
    part = plan_root / "targets" / "form=10-K" / "part-00000.parquet"
    part.parent.mkdir(parents=True)
    row = {
        "target_id": "",
        "accession": _ACCESSION,
        "form": "10-K",
        "filing_date": "2020-01-30",
        "request_id": "primary:primary",
        "target_role": "primary",
        "target_type": "primary",
        "optional": False,
        "inventory_entry_id": None,
        "status": "matched",
        "status_reason": None,
        "source_origin": "catalog_direct",
        "retrieval_mode": "direct_url",
        "target_url": _TARGET_URL,
        "sequence": 1,
        "byte_size": None,
        "availability_evidence": "catalog_direct",
        "catalog_direct_selection": "exact_form_with_lazy_index",
    }
    row["target_id"] = canonical_hash(
        [plan_id, _ACCESSION, row["request_id"], None, "matched"]
    )
    pq.write_table(
        pa.Table.from_pylist([row], schema=TARGET_SCHEMA),
        part,
        row_group_size=DEFAULT_ROW_GROUP_SIZE,
    )
    manifest: dict[str, Any] = {
        "plan_id": plan_id,
        "bundle_schema_version": target_plan_bundle_schema_version(),
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "matcher_version": target_plan_matcher_version(),
        "row_group_size": identity["row_group_size"],
        "profile_id": "profile-offline-acceptance",
        "profile_schema_version": "1",
        "profile_version": "1",
        "profile_digest": identity["profile_digest"],
        "catalog_plan_id": identity["catalog_plan_id"],
        "catalog_plan_digest": identity["catalog_plan_digest"],
        "inventory_snapshot_id": None,
        "inventory_snapshot_digest": None,
        "plan_identity": identity,
        "target_row_count": 1,
        "status_counts": {"matched": 1},
        "origin_counts": {"catalog_direct": 1},
        "reason_counts": {},
        "parts": [
            {
                "path": "targets/form=10-K/part-00000.parquet",
                "form": "10-K",
                "rows": 1,
                "byte_size": part.stat().st_size,
                "sha256": file_sha256(part),
            }
        ],
    }
    manifest["plan_digest"] = canonical_hash(manifest)
    (plan_root / "plan.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return plan_id, row


class _SyntheticTransport:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.calls: list[str] = []
        self.closed = False

    def stream_to_file(
        self,
        url,
        destination,
        *,
        max_response_bytes,
        validate_redirect,
    ):
        self.calls.append(url)
        validate_redirect(url)
        body = self.responses[url]
        if len(body) > max_response_bytes:
            raise AssertionError("synthetic response exceeded its byte budget")
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
        self.closed = True


class _FixtureReplayTransport:
    def __init__(self, paths, fixture_id: str, case) -> None:
        self.paths = paths
        self.fixture_id = fixture_id
        self.responses = {
            _TARGET_URL: case.response_sha256,
            _INDEX_URL: case.index_response_sha256,
            _SELECTED_URL: case.selected_response_sha256,
        }
        self.calls: list[str] = []
        self.closed = False

    def stream_to_file(
        self,
        url,
        destination,
        *,
        max_response_bytes,
        validate_redirect,
    ):
        self.calls.append(url)
        validate_redirect(url)
        digest = self.responses[url]
        assert digest is not None
        path = Path(destination)
        with path.open("xb") as output:
            response = replay_fixture_response(
                self.paths, self.fixture_id, digest, output
            )
        assert response.byte_size <= max_response_bytes
        return StreamedResponse(
            status_code=200,
            requested_url=url,
            final_url=url,
            sha256=response.response_sha256,
            byte_size=response.byte_size,
            content_type="text/html",
            content_encoding=None,
            path=path,
        )

    def close(self) -> None:
        self.closed = True


def test_offline_projection_fixture_replay_commits_and_preserves_staged_body(
    tmp_path, monkeypatch, capsys
) -> None:
    source_root = tmp_path / "source-artifacts"
    source_paths = resolve_acquisition_paths(artifacts_root=source_root)
    plan_id, plan_row = _write_pinned_plan(source_root)
    source_projection = project_acquisition_run(plan_id, paths=source_paths)
    assert source_projection.manifest["bundle_schema_version"] == 3
    assert source_projection.manifest["inventory_snapshot_id"] is None

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: type("Resources", (), {"workers": 1, "worker_ceiling": 1})(),
    )
    clock = lambda: datetime(2026, 10, 10, tzinfo=UTC)
    source_transport = _SyntheticTransport(
        {
            _TARGET_URL: _INITIAL_BODY,
            _INDEX_URL: _INDEX,
            _SELECTED_URL: _SELECTED_BODY,
        }
    )
    source_report = execute_acquisition_run(
        source_projection.run_id,
        retry_failures=False,
        paths=source_paths,
        policy=AcquisitionPolicy(
            max_response_bytes=4096,
            retain_response_evidence=True,
        ),
        transport=source_transport,
        clock=clock,
    )
    assert source_report.state == "complete"
    assert source_report.target_counts["acquired"] == 1
    assert source_transport.calls == [_TARGET_URL, _INDEX_URL, _SELECTED_URL]
    assert source_transport.closed

    source_state = get_target_state(
        source_paths.run_state_path(source_projection.run_id), plan_row["target_id"]
    )
    assert source_state is not None and source_state.selected_body_relative_path
    with sqlite3.connect(source_paths.run_state_path(source_projection.run_id)) as db:
        initial_attempt_id = db.execute(
            "SELECT attempt_id FROM attempts WHERE target_id = ? "
            "AND attempt_kind = 'document_body' ORDER BY attempt_number LIMIT 1",
            (source_state.target_id,),
        ).fetchone()[0]

    create_fixture(_FIXTURE_ID, paths=source_paths)
    captured = capture_fixture_case(
        _FIXTURE_ID,
        source_projection.run_id,
        source_state.target_id,
        initial_attempt_id,
        paths=source_paths,
        max_response_bytes=4096,
    )
    fixture_case = get_fixture_case(
        source_paths, _FIXTURE_ID, captured.capture_id, source_state.target_id
    )
    fixture_manifest = json.loads(
        source_paths.fixture_manifest_path(_FIXTURE_ID).read_text(encoding="utf-8")
    )
    with sqlite3.connect(source_paths.fixture_database_path(_FIXTURE_ID)) as db:
        fixture_db_version = db.execute("PRAGMA user_version").fetchone()[0]
    assert FIXTURE_SCHEMA_VERSION == 3
    assert fixture_manifest["details"]["store_schema_version"] == 3
    assert fixture_db_version == 3
    assert fixture_case.response_sha256 != fixture_case.selected_sha256
    assert fixture_case.index_response_sha256 is not None
    assert fixture_case.selected_response_sha256 is not None
    assert fixture_case.selected_retrieval_mode == "direct_url"

    standalone_replay_root = tmp_path / "standalone-replay"
    standalone_replay_root.mkdir()
    standalone_output = standalone_replay_root / "selected.html"
    replay = replay_fixture_case(
        _FIXTURE_ID,
        captured.capture_id,
        source_state.target_id,
        standalone_output,
        paths=source_paths,
    )
    assert replay.output_path == standalone_output
    assert replay.selected_sha256 == hashlib.sha256(_SELECTED_BODY).hexdigest()
    assert standalone_output.read_bytes() == _SELECTED_BODY

    replay_root = tmp_path / "replay-artifacts"
    replay_paths = resolve_acquisition_paths(artifacts_root=replay_root)
    replay_plan_root = replay_paths.target_plan_dir(plan_id)
    replay_plan_root.parent.mkdir(parents=True)
    shutil.copytree(source_paths.target_plan_dir(plan_id), replay_plan_root)
    replay_paths.fixtures_root.mkdir(parents=True)
    shutil.copytree(
        source_paths.fixture_root(_FIXTURE_ID), replay_paths.fixture_root(_FIXTURE_ID)
    )
    replay_projection = project_acquisition_run(plan_id, paths=replay_paths)
    assert replay_projection.run_id == source_projection.run_id
    assert not replay_projection.reused
    replay_case = get_fixture_case(
        replay_paths, _FIXTURE_ID, captured.capture_id, source_state.target_id
    )
    fixture_transport = _FixtureReplayTransport(replay_paths, _FIXTURE_ID, replay_case)
    replay_report = execute_acquisition_run(
        replay_projection.run_id,
        retry_failures=False,
        paths=replay_paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=fixture_transport,
        clock=clock,
    )

    assert replay_report.state == "complete"
    assert replay_report.target_counts["acquired"] == 1
    assert fixture_transport.calls == [_TARGET_URL, _INDEX_URL, _SELECTED_URL]
    assert fixture_transport.closed
    replay_state = get_target_state(
        replay_paths.run_state_path(replay_projection.run_id), source_state.target_id
    )
    assert replay_state is not None
    assert replay_state.attempt_count == 3
    assert replay_state.selected_sha256 == hashlib.sha256(_SELECTED_BODY).hexdigest()
    assert replay_state.selected_body_relative_path is not None
    staged_body = (
        replay_paths.run_dir(replay_projection.run_id)
        / replay_state.selected_body_relative_path
    )
    assert staged_body.is_relative_to(
        replay_paths.run_staging_root(replay_projection.run_id)
    )
    assert staged_body.is_file()
    assert staged_body.stat().st_size == replay_state.selected_byte_size
    assert file_sha256(staged_body) == replay_state.selected_sha256
    assert staged_body.read_bytes() == _SELECTED_BODY

    fake_consumer_ref = get_staged_body_ref(
        replay_paths, replay_projection.run_id, source_state.target_id
    )
    with fake_consumer_ref.path.open("rb") as selected_stream:
        fake_consumer_digest = hashlib.sha256()
        fake_consumer_size = 0
        while chunk := selected_stream.read(65536):
            fake_consumer_digest.update(chunk)
            fake_consumer_size += len(chunk)
    assert fake_consumer_digest.hexdigest() == fake_consumer_ref.sha256
    assert fake_consumer_size == fake_consumer_ref.byte_size
    fake_receipt = {
        "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
        "run_id": fake_consumer_ref.run_id,
        "target_id": fake_consumer_ref.target_id,
        "source_response_sha256": fake_consumer_ref.source_response_sha256,
        "selected_sha256": fake_consumer_ref.sha256,
        "processing_run_id": "fake-consumer-1",
        "consumed_at_utc": "2026-10-10T21:00:00Z",
    }
    recorded_receipt = record_body_consumption_receipt(replay_paths, fake_receipt)
    assert recorded_receipt == fake_receipt
    assert (
        read_body_consumption_receipt(
            replay_paths, replay_projection.run_id, source_state.target_id
        )
        == fake_receipt
    )
    cleanup_transport = _SyntheticTransport({})
    cleanup_report = execute_acquisition_run(
        replay_projection.run_id,
        retry_failures=False,
        paths=replay_paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=cleanup_transport,
        clock=clock,
    )
    assert cleanup_report.state == "complete"
    assert cleanup_transport.closed
    assert staged_body.is_file()
    assert file_sha256(staged_body) == fake_consumer_ref.sha256
    assert (
        read_body_consumption_receipt(
            replay_paths, replay_projection.run_id, source_state.target_id
        )
        == fake_receipt
    )

    assert (
        acquisition_cli.main(
            [
                "status",
                "--run-id",
                replay_projection.run_id,
                "--artifacts",
                str(replay_root),
                "--json",
            ]
        )
        == 0
    )
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["runs"][0]["state"] == "complete"
    assert status_payload["runs"][0]["target_counts"]["acquired"] == 1
