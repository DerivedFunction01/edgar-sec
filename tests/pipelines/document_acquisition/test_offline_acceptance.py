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

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.settings.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.compaction import compact_lineage
from edgar_sec.infra.storage.dag.retention import analyze_retention
from edgar_sec.infra.storage.dag.tags import create_tag, read_tag
from edgar_sec.infra.sec_http.metrics import HttpMetrics
from edgar_sec.infra.sec_http.streaming import StreamedResponse
from edgar_sec.pipelines.document_acquisition import cli as acquisition_cli
from edgar_sec.pipelines.document_acquisition.fixture_store.capture import (
    capture_fixture_run,
    create_fixture,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    get_fixture_case,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import FixturePlanPin
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.plan_projection.project import (
    project_acquisition_run,
)
from edgar_sec.pipelines.document_acquisition.runner import execute_acquisition_run
from edgar_sec.pipelines.document_acquisition.run_state.store import get_target_state
from edgar_sec.pipelines.document_acquisition.schemas import (
    target_plan_bundle_schema_version,
    target_plan_matcher_version,
)
from edgar_sec.pipelines.document_planning.schemas import (
    OPERATION_INPUT_SCHEMA_VERSION,
    SOURCE_REQUEST_SCHEMA_VERSION,
    TARGET_OPERATION_SCHEMA_VERSION,
    TARGET_SCHEMA_VERSION,
)
from edgar_sec.pipelines.document_planning.paths import (
    resolve_document_planning_paths,
)
from edgar_sec.pipelines.document_planning.planner import create_document_plan
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.coordinator import run_missing_accessions
from edgar_sec.pipelines.document_inventory.snapshot.reader import (
    get_active_accession,
    get_active_entries,
)
from edgar_sec.pipelines.document_inventory.snapshot.projection import (
    project_catalog_plan,
)
from edgar_sec.pipelines.document_inventory.snapshot.specs import INVENTORY_RELATIONS
from edgar_sec.pipelines.document_inventory.snapshot.writer import (
    publish_committed_chunks,
)
from edgar_sec.pipelines.document_inventory.run_state.run_state import load_run_state
from edgar_sec.pipelines.filing_catalog.catalog_job import materialize
from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths
from edgar_sec.pipelines.filing_catalog.planner import plan as plan_catalog
from tests.pipelines.document_acquisition.plan_projection.plan_fixture import (
    write_plan_bundle,
)
from tests.support import fixture_path, load_fixture
from tests.pipelines.document_acquisition.fixture_store.fixture_helpers import (
    create_test_fixture_for_run,
)

_ACCESSION = "0000320193-20-000096"
_ACCESSION_COMPACT = _ACCESSION.replace("-", "")
_ARCHIVE_ROOT = f"https://www.sec.gov/Archives/edgar/data/320193/{_ACCESSION_COMPACT}/"
_TARGET_URL = _ARCHIVE_ROOT + f"{_ACCESSION}.txt"
_SELECTED_BODY = b"<html>selected filing body</html>"
_FIXTURE_ID = "offline-acceptance-v3"


def _write_pinned_plan(
    artifacts_root: Path,
    *,
    catalog_direct_selection: str | None = None,
    target_url: str = _TARGET_URL,
    bundle_child: bool = False,
) -> tuple[str, dict[str, Any]]:
    inventory_snapshot_id = "snapshot-m7b" if bundle_child else None
    inventory_snapshot_digest = "b" * 64 if bundle_child else None
    request_id = "primary:primary"
    target_role = "primary"
    target_type = target_role
    inventory_entry_id = "entry-sequence-2" if bundle_child else None
    identity = {
        "bundle_schema_version": target_plan_bundle_schema_version(),
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "target_operation_schema_version": TARGET_OPERATION_SCHEMA_VERSION,
        "source_request_schema_version": SOURCE_REQUEST_SCHEMA_VERSION,
        "operation_input_schema_version": OPERATION_INPUT_SCHEMA_VERSION,
        "matcher_version": target_plan_matcher_version(),
        "row_group_size": DEFAULT_ROW_GROUP_SIZE,
        "profile_digest": "c" * 64,
        "catalog_plan_id": "catalog-offline-acceptance",
        "catalog_plan_digest": "a" * 64,
        "inventory_snapshot_id": inventory_snapshot_id,
        "inventory_snapshot_digest": inventory_snapshot_digest,
    }
    plan_id = f"dplan_{canonical_hash(identity)[:32]}"
    plan_root = artifacts_root / "document_planning" / "plans" / plan_id
    row = {
        "target_id": "",
        "accession": _ACCESSION,
        "form": "10-K",
        "filing_date": "2020-01-30",
        "request_id": request_id,
        "target_role": target_role,
        "target_type": target_type,
        "optional": False,
        "inventory_entry_id": inventory_entry_id,
        "status": "matched",
        "status_reason": None,
        "source_origin": "inventory_index" if bundle_child else "catalog_direct",
        "retrieval_mode": "bundle_sequence" if bundle_child else "direct_url",
        "target_url": target_url,
        "sequence": 2 if bundle_child else 1,
        "byte_size": None,
        "availability_evidence": "index_html" if bundle_child else "catalog_direct",
        "catalog_direct_selection": (
            None if bundle_child else catalog_direct_selection
        ),
    }
    row["target_id"] = canonical_hash(
        [plan_id, _ACCESSION, row["request_id"], inventory_entry_id, "matched"]
    )
    write_plan_bundle(plan_root, plan_id, identity, [row])
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
        if url not in self.responses:
            raise AssertionError(f"unexpected SEC URL: {url}")
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


class _FixtureIndexHttp:
    def __init__(self, expected_url: str, body: bytes) -> None:
        self.expected_url = expected_url
        self.body = body
        self.calls: list[str] = []
        self.metrics = HttpMetrics()

    def peek_cache(self, url: str) -> bytes | None:
        if url != self.expected_url:
            raise AssertionError(f"unexpected SEC URL: {url}")
        return None

    def get_bytes(self, url: str, *, force_refresh: bool = False) -> bytes:
        if url != self.expected_url:
            raise AssertionError(f"unexpected SEC URL: {url}")
        self.calls.append(url)
        return self.body


def test_fixture_fill_and_parser_review_are_offline(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "source-artifacts"
    source_paths = resolve_acquisition_paths(artifacts_root=source_root)
    plan_id, plan_row = _write_pinned_plan(source_root)
    source_projection = project_acquisition_run(plan_id, paths=source_paths)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: type("Resources", (), {"workers": 1, "worker_ceiling": 1})(),
    )
    source_transport = _SyntheticTransport({_TARGET_URL: _SELECTED_BODY})
    source_report = execute_acquisition_run(
        source_projection.run_id,
        retry_failures=False,
        paths=source_paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=source_transport,
        clock=lambda: datetime(2026, 10, 10, tzinfo=UTC),
    )
    assert source_report.state == "complete"
    assert source_report.target_counts["acquired"] == 1
    assert source_transport.calls == [_TARGET_URL]
    assert source_transport.closed

    state = get_target_state(
        source_paths.run_state_path(source_projection.run_id), plan_row["target_id"]
    )
    assert state is not None and state.selected_body_relative_path
    create_test_fixture_for_run(source_paths, _FIXTURE_ID, source_projection.run_id)
    capture = capture_fixture_run(
        _FIXTURE_ID,
        source_projection.run_id,
        paths=source_paths,
        max_body_bytes=4096,
    )
    fixture_case = get_fixture_case(
        source_paths, _FIXTURE_ID, capture.capture_id, state.target_id
    )
    assert fixture_case.body_sha256 == hashlib.sha256(_SELECTED_BODY).hexdigest()
    assert fixture_case.byte_size == len(_SELECTED_BODY)

    review_root = tmp_path / "parser-review"
    result = acquisition_cli.main(
        [
            "review",
            "generate",
            "--fixture",
            _FIXTURE_ID,
            "--output",
            str(review_root),
            "--artifacts",
            str(source_root),
            "--no-progress",
            "--json",
        ]
    )
    assert result == 0
    assert source_transport.calls == [_TARGET_URL]
    assert source_transport.closed


def test_prepublication_vertical_acceptance_stays_offline_and_raw_only(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    artifacts_root = tmp_path / "artifacts"
    source_metadata = fixture_path("catalog/sample_submission_metadata.parquet")
    catalog_snapshot = materialize(source_metadata, artifacts_root)
    catalog_plan = plan_catalog(
        catalog_snapshot["catalog_id"],
        artifacts_root,
        forms=("10-K",),
        document_suffixes=(".htm", ".html"),
        accession_limit=1,
    )
    catalog_paths = resolve_filing_catalog_paths(artifacts_root=artifacts_root)
    catalog_target_parts = sorted(
        (catalog_paths.plan_dir(catalog_plan["plan_id"]) / "targets").rglob("*.parquet")
    )
    assert catalog_target_parts
    catalog_targets = pa.concat_tables(
        [pq.read_table(path) for path in catalog_target_parts],
        promote_options="default",
    )
    targets = catalog_targets.to_pylist()
    target = next(
        row
        for row in targets
        if str(row["source_cik"]) == str(row["accession"]).replace("-", "")[:10]
    )
    accession = str(AccessionNumber.from_any(target["accession"]))
    filing_cik = str(target["source_cik"])
    page_accession = "0000123456-26-000016"
    index_html = fixture_path("document_inventory_index_page.html").read_bytes()
    index_html = index_html.replace(
        page_accession.replace("-", "").encode("ascii"),
        accession.replace("-", "").encode("ascii"),
    ).replace(page_accession.encode("ascii"), accession.encode("ascii"))
    index_html = index_html.replace(b"/123456/", f"/{int(filing_cik)}/".encode("ascii"))
    index_html = index_html.replace(b'href="/ix?doc=', b'href="')
    assert page_accession.encode("ascii") not in index_html
    assert accession.encode("ascii") in index_html
    index_digest = hashlib.sha256(index_html).hexdigest()
    inventory_paths = InventoryPaths(artifacts_root)
    inventory_profile = derive_resources(
        requested_threads=1,
        cli_overrides={"runtime.temp_directory": str(tmp_path / "duckdb-tmp")},
    )
    inventory_projection = project_catalog_plan(
        catalog_plan["plan_id"],
        artifacts_root=artifacts_root,
        catalog_paths=catalog_paths,
        profile=inventory_profile,
        chunk_size=1,
    )
    work_order = pq.read_table(inventory_projection.paths.work_order_path()).to_pylist()
    assert len(work_order) == 1
    assert work_order[0]["accession"] == accession
    index_url = work_order[0]["index_url"]
    index_http = _FixtureIndexHttp(index_url, index_html)
    loaded_projection, inventory_run = load_run_state(
        artifacts_root, inventory_projection.run_id
    )
    run_identity = {
        "parent_snapshot_id": inventory_run.parent_snapshot_id,
        "canonical_cohort_id": inventory_run.canonical_cohort_id,
        "source_identity": inventory_run.source_identity,
        "parser_version": inventory_run.parser_version,
        "chunk_size": inventory_run.chunk_size,
        "refresh_mode": inventory_run.refresh_mode,
        "fetch_mode": inventory_run.fetch_mode,
        "fixture_id": inventory_run.fixture_id,
        "work_order_version": inventory_run.work_order_version,
    }
    inventory_run_summary = run_missing_accessions(
        loaded_projection.paths.work_order_path(),
        run_identity,
        loaded_projection.paths,
        http_client=index_http,
        profile=inventory_profile,
        workers=1,
    )
    assert inventory_run_summary.status == "completed"
    assert inventory_run_summary.refusal_count == 0
    assert inventory_run_summary.committed_count == 1
    assert index_http.calls == [index_url]
    publication = publish_committed_chunks(
        loaded_projection.paths,
        inventory_run,
        cohort_accessions_path=loaded_projection.paths.cohort_accessions_path(),
        cohort_sources_path=loaded_projection.paths.cohort_sources_path(),
        expected_parent_snapshot_id=inventory_run.parent_snapshot_id or None,
        profile=inventory_profile,
    )
    assert publication.was_published
    assert publication.snapshot is not None
    snapshot_id = publication.snapshot.snapshot_id
    before_accession = get_active_accession(
        inventory_paths.snapshots_root, accession, snapshot_id=snapshot_id
    )
    before_entries = sorted(
        get_active_entries(
            inventory_paths.snapshots_root, accession, snapshot_id=snapshot_id
        ),
        key=lambda row: row["entry_id"],
    )
    assert before_accession is not None
    assert before_accession["accession"] == accession
    assert before_accession["filing_cik"] == filing_cik
    assert before_accession["index_url"] == index_url
    assert before_accession["index_sha256"] == index_digest
    assert before_accession["first_indexed_by"] == inventory_run.source_identity
    filenames = {entry["filename"] for entry in before_entries}
    assert {"report.htm", "ex21.htm", "report.xsd"} <= filenames
    target_url = next(
        entry["archive_url"]
        for entry in before_entries
        if entry["filename"] == "report.htm"
    )

    planning_paths = resolve_document_planning_paths(artifacts_root=artifacts_root)
    profile_id = "s12-primary-raw"
    planning_paths.profiles_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        planning_paths.profiles_root / f"{profile_id}.json",
        {
            "profile_id": profile_id,
            "schema_version": "1",
            "version": "1",
            "rules": [
                {
                    "form_selector": "10-K",
                    "targets": [
                        {
                            "role": "primary",
                            "type": "primary",
                            "optional": False,
                            "acquisition_policy": {"operations": ["raw"]},
                        }
                    ],
                }
            ],
        },
    )
    target_plan = create_document_plan(
        catalog_plan["plan_id"],
        profile_id,
        snapshot_id,
        paths=planning_paths,
    )
    assert target_plan.manifest["inventory_snapshot_id"] == snapshot_id
    assert target_plan.manifest["target_row_count"] == 1

    acquisition_paths = resolve_acquisition_paths(artifacts_root=artifacts_root)
    projection = project_acquisition_run(target_plan.plan_id, paths=acquisition_paths)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: type("Resources", (), {"workers": 1, "worker_ceiling": 1})(),
    )
    body_fixture = load_fixture("document_storage/annual_10k_html.json")
    selected_body = body_fixture["source_text"].encode("utf-8")
    selected_digest = hashlib.sha256(selected_body).hexdigest()
    transport = _SyntheticTransport({target_url: selected_body})
    acquisition_report = execute_acquisition_run(
        projection.run_id,
        retry_failures=False,
        paths=acquisition_paths,
        policy=AcquisitionPolicy(max_response_bytes=100_000),
        transport=transport,
        clock=lambda: datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert acquisition_report.state == "complete"
    assert acquisition_report.target_counts["acquired"] == 1
    assert transport.calls == [target_url]
    assert transport.closed

    target_part = next(
        part["path"]
        for part in target_plan.manifest["parts"]
        if part["relation"] == "targets"
    )
    target_table = pq.read_table(target_plan.root / target_part)
    planned_target_id = target_table.to_pylist()[0]["target_id"]
    state = get_target_state(
        acquisition_paths.run_state_path(projection.run_id), planned_target_id
    )
    assert state is not None
    assert state.selected_sha256 == selected_digest
    assert state.selected_body_relative_path is not None
    selected_path = (
        acquisition_paths.run_dir(projection.run_id) / state.selected_body_relative_path
    )
    assert selected_path.is_relative_to(
        acquisition_paths.run_staging_root(projection.run_id)
    )
    assert file_sha256(selected_path) == selected_digest
    fixture_id = "s12-prepublication-acceptance"
    create_fixture(
        fixture_id,
        FixturePlanPin(
            target_plan_id=target_plan.plan_id,
            target_plan_digest=target_plan.manifest["plan_digest"],
            target_plan_schema_version=target_plan.manifest["target_schema_version"],
        ),
        paths=acquisition_paths,
    )
    captured = capture_fixture_run(
        fixture_id,
        projection.run_id,
        paths=acquisition_paths,
        max_body_bytes=100_000,
    )
    fixture_case = get_fixture_case(
        acquisition_paths, fixture_id, captured.capture_id, planned_target_id
    )
    assert fixture_case.source_origin == "inventory_index"
    assert fixture_case.body_sha256 == selected_digest
    assert fixture_case.byte_size == len(selected_body)

    assert acquisition_report.processing_complete
    assert acquisition_report.processing_success
    assert acquisition_report.processing_operation_counts["available"] == 1
    result_path = (
        acquisition_paths.run_staging_root(projection.run_id)
        / "processing"
        / f"{planned_target_id}.json"
    )
    result_manifest = json.loads(result_path.read_text(encoding="utf-8"))
    assert result_manifest["source_sha256"] == selected_digest
    assert result_manifest["body_verified_by_processing"]
    result_operations = {
        item["operation"]: item for item in result_manifest["operations"]
    }
    assert result_operations["raw"]["requested"]
    assert result_operations["raw"]["status"] == "available"
    assert result_operations["raw"]["output_sha256"] == selected_digest
    assert not result_operations["render_to_txt"]["requested"]
    assert not result_operations["render_to_xml"]["requested"]

    create_tag(
        inventory_paths.snapshots_root,
        "s12-old-inventory-tip",
        snapshot_id,
        message="pre-compaction acceptance evidence",
    )
    compacted = compact_lineage(
        inventory_paths.snapshots_root,
        INVENTORY_RELATIONS,
        snapshot_id,
        "s12-inventory-checkpoint",
        tmp_path / "inventory-checkpoint-staging",
        publish=True,
    )
    after_accession = get_active_accession(
        inventory_paths.snapshots_root,
        accession,
        snapshot_id=compacted.snapshot_id,
    )
    after_entries = sorted(
        get_active_entries(
            inventory_paths.snapshots_root,
            accession,
            snapshot_id=compacted.snapshot_id,
        ),
        key=lambda row: row["entry_id"],
    )
    assert after_accession == before_accession
    assert after_entries == before_entries
    old_tag = read_tag(inventory_paths.snapshots_root, "s12-old-inventory-tip")
    assert old_tag is not None and old_tag["snapshot_id"] == snapshot_id
    assert (
        DAGCatalog(inventory_paths.snapshots_root).get_manifest(snapshot_id) is not None
    )
    assert (
        sorted(
            get_active_entries(
                inventory_paths.snapshots_root, accession, snapshot_id=snapshot_id
            ),
            key=lambda row: row["entry_id"],
        )
        == before_entries
    )
    retention = analyze_retention(inventory_paths.snapshots_root)
    assert snapshot_id in retention.retained_snapshots
    assert snapshot_id not in retention.prunable_snapshots

    review_output_dir = tmp_path / "s7-review-output"
    assert (
        acquisition_cli.main(
            [
                "review",
                "generate",
                "--fixture",
                fixture_id,
                "--output",
                str(review_output_dir),
                "--artifacts",
                str(artifacts_root),
                "--json",
            ]
        )
        == 0
    )
    review_summary = json.loads(capsys.readouterr().out)
    assert review_summary["command"] == "review generate"
    assert review_summary["completed"] == 1
    review_output_root = Path(review_summary["output"])
    review_manifest_path = review_output_root / "manifest.jsonl"
    review_record = json.loads(review_manifest_path.read_text(encoding="utf-8"))
    review_output = review_record["outputs"]["processing-review.json"]
    review_artifact = review_output_root / review_output["path"]
    assert review_record["status"] == "complete"
    assert review_record["body_sha256"] == selected_digest
    assert file_sha256(review_artifact) == review_output["sha256"]
    review_payload = json.loads(review_artifact.read_text(encoding="utf-8"))
    assert review_payload["artifact_version"] == 3
    assert review_payload["fixture"]["body_sha256"] == selected_digest
    assert "receipt" not in review_payload
    assert "projection" not in review_payload

    assert not acquisition_paths.snapshots_root.exists()
    assert not list(acquisition_paths.snapshots_root.rglob("*.parquet"))
