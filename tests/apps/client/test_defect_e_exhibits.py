"""End-to-end tests: non-primary intents acquired and retained per run."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.filing_catalog.schemas import (
    TARGET_PLAN_SCHEMA_VERSION,
    TARGET_SCHEMA,
)
from edgar_sec.engine.index_pages.enumeration import TargetIntent
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.sec_http.streaming import StreamFailure, StreamedResponse
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.plan_projection.project import (
    project_acquisition_run,
)
from edgar_sec.pipelines.document_acquisition.runner import execute_acquisition_run
from edgar_sec.pipelines.document_acquisition.run_state.ephemeral import (
    read_ephemeral_targets,
)
from edgar_sec.pipelines.document_planning.paths import (
    resolve_catalog_paths,
    resolve_document_planning_paths,
)
from edgar_sec.pipelines.document_planning.planner import create_document_plan
from edgar_sec.pipelines.document_planning.profiles import (
    get_or_create_baseline_profile,
)
from edgar_sec.pipelines.filing_catalog.paths import PLAN_TARGETS_DIR
from tests.support import fixture_path

_ACCESSION = "0001234567-24-000042"
_ARCHIVE_ACCESSION = "000123456724000042"
_ARCHIVE_ROOT = f"https://www.sec.gov/Archives/edgar/data/1234567/{_ARCHIVE_ACCESSION}/"
_INDEX_URL = _ARCHIVE_ROOT + f"{_ACCESSION}-index.html"
_PRIMARY_BODY = b"<html><body>Current report on Form 8-K.</body></html>"
_EXHIBIT_BODY = (
    b"<html><body><p>Example Corp reports first quarter results.</p>"
    b"<table>"
    b"<tr><td></td><td>Q1 2024</td><td>Q1 2023</td></tr>"
    b"<tr><td>Total revenues</td><td>$ 1,234</td><td>$ 1,000</td></tr>"
    b"<tr><td>Net income</td><td>$ 234</td><td>$ 180</td></tr>"
    b"<tr><td>Diluted EPS</td><td>$ 1.23</td><td>$ 0.95</td></tr>"
    b"</table></body></html>"
)


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


def _publish_catalog(artifacts_root: Path) -> None:
    row = {
        "occurrence_id": "occ-1",
        "document_locator_key": "locator-1",
        "source_cik": "0001234567",
        "accession": _ARCHIVE_ACCESSION,
        "form": "8-K",
        "filing_date": "2024-05-01",
        "report_date": "2024-04-30",
        "primary_document": "primary.htm",
        "document_path": "primary.htm",
        "archive_url": _ARCHIVE_ROOT + "primary.htm",
        "document_path_source": "primary_document",
        "reported_size": 100,
        "is_xbrl": False,
        "is_inline_xbrl": False,
        "is_xbrl_numeric": False,
    }
    catalog_paths = resolve_catalog_paths(artifacts_root)
    root = catalog_paths.plan_dir("catalog-plan")
    part = root / "targets" / "form=8-K" / "data.parquet"
    part.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist([row], schema=TARGET_SCHEMA), part, compression="zstd"
    )
    manifest = {
        "plan_id": "catalog-plan",
        "plan_schema_version": TARGET_PLAN_SCHEMA_VERSION,
        "catalog_id": "catalog-snapshot",
        "scope": "deterministic",
        "plan_fingerprint": "catalog-fingerprint",
        "forms": [],
        "counts": {"8-K": 1},
        "selected_rows": 1,
        "target_parts": [
            {
                "form": "8-K",
                "path": "targets/form=8-K/data.parquet",
                "row_count": 1,
                "byte_size": part.stat().st_size,
                "sha256": file_sha256(part),
            }
        ],
    }
    (root / "plan.json").write_text(json.dumps(manifest), encoding="utf-8")


def _run_fetch(
    tmp_path: Path, monkeypatch, intent: TargetIntent
) -> tuple[FilingsResult, Any, Path]:
    artifacts_root = tmp_path / "artifacts"
    planning_paths = resolve_document_planning_paths(tmp_path, artifacts_root)
    _publish_catalog(artifacts_root)
    get_or_create_baseline_profile(planning_paths.profiles_root)
    plan = create_document_plan("catalog-plan", "primary-only", paths=planning_paths)
    acquisition_paths = resolve_acquisition_paths(artifacts_root=artifacts_root)
    projection = project_acquisition_run(plan.plan_id, paths=acquisition_paths)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    transport = _Transport(
        {
            _ARCHIVE_ROOT + "primary.htm": _PRIMARY_BODY,
            _INDEX_URL: fixture_path(
                "document_planning_index_page.html"
            ).read_bytes(),
            _ARCHIVE_ROOT + "ex991.htm": _EXHIBIT_BODY,
        }
    )
    report = execute_acquisition_run(
        projection.run_id,
        retry_failures=False,
        paths=acquisition_paths,
        policy=AcquisitionPolicy(max_response_bytes=100_000),
        transport=transport,
        clock=lambda: datetime(2026, 10, 12, tzinfo=UTC),
        ephemeral_intents=(intent,),
    )
    result = FilingsResult(
        run_id=projection.run_id,
        plan_id=plan.plan_id,
        target_parquet_glob=str(
            planning_paths.plan_dir(plan.plan_id) / PLAN_TARGETS_DIR / "**" / "*.parquet"
        ),
        run_state_sqlite_path=acquisition_paths.run_state_path(projection.run_id),
        artifacts_root=artifacts_root,
    )
    return result, report, acquisition_paths.run_state_path(projection.run_id)


def _intent(doc_type: str) -> TargetIntent:
    return TargetIntent(
        role="exhibit",
        type=doc_type,
        optional=True,
        request_id=f"exhibit:{doc_type}",
    )


def test_exhibit_intent_is_acquired_and_retained(tmp_path: Path, monkeypatch) -> None:
    result, report, state_path = _run_fetch(tmp_path, monkeypatch, _intent("EX-99.1"))
    assert report.state == "complete"
    assert report.ephemeral_counts == {"acquired": 1}
    (record,) = read_ephemeral_targets(state_path)
    assert record["status"] == "matched"
    assert record["outcome"] == "acquired"

    filings = list(result)
    assert len(filings) == 1
    filing = filings[0]
    assert filing.primary_document_path == "primary.htm"
    assert filing.raw() == _PRIMARY_BODY
    exhibits = filing.exhibits
    assert [item.filename for item in exhibits] == ["ex991.htm"]
    assert exhibits[0].document_type == "EX-99.1"
    assert exhibits[0].raw() == _EXHIBIT_BODY
    assert len(result.exhibits()) == 1

    earnings = Edgar(artifacts_root=tmp_path / "artifacts").earnings_exhibit(filing)
    assert earnings.absence_reason is None
    assert earnings.exhibit is not None
    assert earnings.exhibit.filename == "ex991.htm"


def test_absent_exhibit_intent_is_recorded_and_stays_absent(
    tmp_path: Path, monkeypatch
) -> None:
    result, report, state_path = _run_fetch(tmp_path, monkeypatch, _intent("EX-99.2"))
    assert report.state == "complete"
    assert report.ephemeral_counts == {"not_acquired": 1}
    (record,) = read_ephemeral_targets(state_path)
    assert record["status"] == "not_filed"
    assert record["outcome"] == "not_acquired"

    filing = next(iter(result))
    assert filing.exhibits == ()
    earnings = Edgar(artifacts_root=tmp_path / "artifacts").earnings_exhibit(filing)
    assert earnings.exhibit is None
    assert earnings.absence_reason == "no_ex99_exhibit"
