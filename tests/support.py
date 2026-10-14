"""Fixture paths and offline HTTP doubles shared by tests."""

from __future__ import annotations

import atexit
import json
import tempfile
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.sec_urls import historical_submissions_url, submissions_url
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.pipelines.cohort.ingestion import ingest_file_to_cohort
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.pipelines.cohort.sources import SOURCE_URLS, refresh_official_source
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.rate_limit import RateLimiter
from edgar_sec.infra.sec_http.retry import RetryPolicy
from edgar_sec.pipelines.metadata_sync.roster import (
    Roster,
    cohort_record_to_roster,
    write_roster_rows,
)
from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient
from tests.acquisition_run_fixture import make_acquisition_run

TESTS_ROOT = Path(__file__).resolve().parent
FIXTURES = TESTS_ROOT / "fixtures"
CATALOG_FIXTURES = FIXTURES / "catalog"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_path(name: str) -> Path:
    return FIXTURES / name


def catalog_fixture_path(name: str) -> Path:
    return CATALOG_FIXTURES / name


def load_catalog_fixture(name: str) -> Any:
    return json.loads((CATALOG_FIXTURES / name).read_text(encoding="utf-8"))


def submissions_document(cik_padded: str) -> str:
    return submissions_url(cik_padded)


def historical_url(name: str) -> str:
    return historical_submissions_url(name)


def cik_payload(cik: str, name: str, accession: str | None = None) -> dict[str, Any]:
    """A well-formed row is enough here; golden replay tests use the real fixtures."""
    accession = accession or f"{cik}-26-000001"
    return {
        "name": name,
        "filings": {
            "recent": {
                "accessionNumber": [accession],
                "filingDate": ["2026-01-02"],
                "form": ["10-K"],
                "size": [1024],
            },
            "files": [],
        },
    }


#: A roster references a real Parquet artifact, so these scratch dirs go at exit.
_SCRATCH: list[tempfile.TemporaryDirectory[str]] = []


def roster_of(
    ciks: Iterable[str], names: Iterable[str] = (), *, name: str = "cohort.parquet"
) -> Roster:
    """Prefer a test's own ``tmp_path`` when the path matters to the assertion."""
    cik_list = tuple(ciks)
    name_list = tuple(names) or ("",) * len(cik_list)
    if len(name_list) != len(cik_list):
        raise ValueError("roster_of needs one name per CIK")
    scratch = tempfile.TemporaryDirectory(prefix="edgar-test-cohort-")
    _SCRATCH.append(scratch)
    roster, _digest = write_roster_rows(
        list(zip(cik_list, name_list, strict=True)),
        Path(scratch.name) / name,
    )
    return roster


atexit.register(lambda: [scratch.cleanup() for scratch in _SCRATCH])


def era_submission_metadata(destination: Path) -> Path:
    """Copy the committed catalog fixture with pre-2005 filings appended.

    Its rows pin the candidate window's edges and a co-filer group.
    """
    import pyarrow.parquet as pq

    table = pq.read_table(catalog_fixture_path("sample_submission_metadata.parquet"))
    filings = table.column("filings").to_pylist()
    template = filings[0][0]
    appended: dict[str, list[dict[str, Any]]] = {}

    for cik, accession, filing_date, form, primary_document in ERA_FILINGS:
        row = dict(template)
        row.update(
            accession_number=accession,
            accession_number_normalized=accession.replace("-", ""),
            filing_date=filing_date,
            report_date="",
            acceptance_datetime=f"{filing_date}T16:30:00.000Z",
            form=form,
            file_number="",
            film_number="",
            items=[],
            core_type="",
            size=None,
            is_xbrl=None,
            is_inline_xbrl=None,
            is_xbrl_numeric=None,
            primary_document=primary_document,
            primary_doc_description=primary_document,
            archive_url="",
            source_section="recent",
            source_array_index=len(appended.get(cik, ())) + 900,
        )
        appended.setdefault(cik, []).append(row)

    patched = [
        list(filings[index]) + appended.get(str(table.column("cik")[index].as_py()), [])
        for index in range(table.num_rows)
    ]
    pq.write_table(
        table.set_column(
            table.schema.get_field_index("filings"), "filings", pa.array(patched)
        ),
        destination,
    )
    return destination


#: ``(cik, accession, filing_date, form, primary_document)``. The first two rows are
#: co-filers of one document with agreeing dates; the rest pin the window's edges.
ERA_FILINGS: tuple[tuple[str, str, str, str, str], ...] = (
    ("0000320193", "0000320193-02-000123", "2002-05-15", "10-K", "ex21.txt"),
    ("0000789019", "0000320193-02-000123", "2002-05-15", "10-K", "ex21.txt"),
    ("0001326801", "0001326801-04-000077", "2004-12-31", "8-K", "ex99.txt"),
    ("0001652044", "0001652044-01-000011", "2000-01-01", "10-K", "annual-report.htm"),
    ("0000019617", "0000019617-05-000045", "2005-06-01", "10-K", "ex99.txt"),
)


def scratch_root() -> Path:
    """Compiling writes a dataset, so read-only tests still need somewhere to put it."""
    global _ROOT_SCRATCH
    if _ROOT_SCRATCH is None:
        _ROOT_SCRATCH = tempfile.TemporaryDirectory(prefix="edgar-test-root-")
        _SCRATCH.append(_ROOT_SCRATCH)
    return Path(_ROOT_SCRATCH.name)


_ROOT_SCRATCH: tempfile.TemporaryDirectory[str] | None = None


@dataclass(frozen=True, slots=True)
class FixtureCohort:
    cohort_id: str
    row_count: int
    roster: Roster
    dataset: Path
    input_name: str
    input_path: Path
    input_fingerprint: str
    selected_limit: int | None
    rejected_row_count: int
    duplicate_row_count: int
    dataset_sha256: str


def _compile_fixture_cohort(
    fixture_name: str, root: str | Path, *, limit: int | None = None
) -> FixtureCohort:
    source = fixture_path(fixture_name).resolve()
    paths = resolve_cohort_paths(root)
    catalog = CohortCatalog(paths)
    result = ingest_file_to_cohort(source, catalog=catalog, paths=paths, limit=limit)
    record = result.cohort
    dataset = paths.resolve_relative_path(record.dataset_path)
    return FixtureCohort(
        cohort_id=record.cohort_id,
        row_count=record.row_count,
        roster=cohort_record_to_roster(record, paths),
        dataset=dataset,
        input_name=source.name,
        input_path=source,
        input_fingerprint=file_sha256(source),
        selected_limit=limit,
        rejected_row_count=result.quality.rejected_rows,
        duplicate_row_count=result.quality.duplicate_rows,
        dataset_sha256=record.dataset_sha256,
    )


def fixture_cohort(fixture_name: str, *, limit: int | None = None) -> FixtureCohort:
    """Compile a fixture as a temporary shared cohort and metadata roster."""
    return _compile_fixture_cohort(fixture_name, scratch_root(), limit=limit)


def fixture_ciks(fixture_name: str) -> tuple[str, ...]:
    """The usable CIKs of a committed fixture, in cohort order."""
    cohort = fixture_cohort(fixture_name)
    return cohort.roster.range_ciks(0, cohort.row_count)


def compiled_cohort(
    fixture_name: str, root: str | Path, *, limit: int | None = None
) -> FixtureCohort:
    """Compile a fixture under the caller's accepted storage root."""
    return _compile_fixture_cohort(fixture_name, root, limit=limit)


def published_universe(
    root: str | Path, fixture_name: str = "cik_lookup_universe_mini.txt"
) -> Path:
    """Publish and compile a registrant universe under ``root``; return its dataset.

    Goes through the real publish and compile path, on the committed mini fixture.
    """
    session = FakeSession()
    session.register_bytes(
        SOURCE_URLS["cik_lookup"], fixture_path(fixture_name).read_bytes()
    )
    paths = resolve_cohort_paths(root)
    catalog = CohortCatalog(paths)
    record = refresh_official_source(
        "cik_lookup", client=build_test_http(session), paths=paths, catalog=catalog
    )
    return paths.resolve_relative_path(record.dataset_path)


class FakeResponse:
    def __init__(
        self, status_code: int = 200, content: bytes = b"{}", headers: Any = None
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class FakeSession:
    """Thread-safe because workers fetch concurrently; an unknown URL 404s."""

    def __init__(self) -> None:
        self.payloads: dict[str, Any] = {}
        self.raw: dict[str, bytes] = {}
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def register(self, url: str, payload: Any) -> None:
        with self._lock:
            self.payloads[url] = payload

    def register_bytes(self, url: str, content: bytes) -> None:
        with self._lock:
            self.raw[url] = content

    def get(self, url: str, headers: Any = None, timeout: Any = None) -> FakeResponse:
        with self._lock:
            self.calls.append(url)
            if url in self.raw:
                return FakeResponse(200, self.raw[url])
            if url in self.payloads:
                return FakeResponse(200, json.dumps(self.payloads[url]).encode("utf-8"))
        return FakeResponse(404, b"not found")


def build_test_http(session: FakeSession) -> SecHttpClient:
    """Pacing collapses to near-zero; retry, cache, and ledger still run for real."""
    return SecHttpClient(
        user_agent="TestClient/1.0 test@example.com",
        rate_limiter=RateLimiter(min_interval_s=0.001),
        retry_policy=RetryPolicy(max_retries=1, backoff_base_s=0.001, jitter=0.0),
        timeout_s=1.0,
        session_factory=lambda: session,
    )


def build_test_client(session: FakeSession) -> SubmissionsClient:
    return SubmissionsClient(http=build_test_http(session))


_PROCESSING_ACCESSION = "0000320193-20-000096"
_PROCESSING_ARCHIVE_ROOT = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    f"{_PROCESSING_ACCESSION.replace('-', '')}/"
)
_PROCESSING_TARGET_URL = f"{_PROCESSING_ARCHIVE_ROOT}{_PROCESSING_ACCESSION}.txt"
_PROCESSING_INDEX_URL = f"{_PROCESSING_ARCHIVE_ROOT}index.html"
_PROCESSING_SELECTED_URL = f"{_PROCESSING_ARCHIVE_ROOT}report.htm"
PROCESSING_TEST_BODY = b"fixture text body\n"
_PROCESSING_TIMESTAMP = "2026-10-11T00:00:00+00:00"


def acquired_processing_request(
    tmp_path: Path,
    *,
    lazy_selected: bool = False,
    selected_filename: str | None = None,
):
    import hashlib
    import sqlite3

    import pyarrow.parquet as pq
    import pytest

    from edgar_sec.domain.identity import AccessionNumber
    from edgar_sec.domain.sec_urls import validate_archive_url
    from edgar_sec.pipelines.document_acquisition.body_handoff import (
        get_staged_body_ref,
    )
    from edgar_sec.pipelines.document_acquisition.models import (
        AcquisitionAttempt,
        AcquisitionOutcome,
        TargetSlotResolution,
    )
    from edgar_sec.pipelines.document_acquisition.paths import (
        resolve_acquisition_paths,
    )
    from edgar_sec.pipelines.document_acquisition.plan_projection.project import (
        project_acquisition_run,
    )
    from edgar_sec.pipelines.document_acquisition.processing.models import (
        OperationRequest,
        ProcessingRequest,
    )
    from edgar_sec.pipelines.document_acquisition.run_state.store import (
        append_attempt_and_update_target,
        commit_attempts_and_update_target,
    )
    from tests.pipelines.document_acquisition.test_offline_acceptance import (
        _write_pinned_plan,
    )

    paths = resolve_acquisition_paths(artifacts_root=tmp_path / "artifacts")
    plan_id, target, _ = _write_pinned_plan(paths.artifacts_root)
    import edgar_sec.pipelines.document_acquisition.plan_projection.project as projection

    def compare_operation_seeds(
        database_path: Path, parts: tuple[Path, ...]
    ) -> tuple[int, int, int]:
        expected = sum(pq.ParquetFile(part).metadata.num_rows for part in parts)
        with sqlite3.connect(database_path) as connection:
            actual = connection.execute(
                "SELECT COUNT(*) FROM operation_state"
            ).fetchone()[0]
        return expected, actual, int(expected != actual)

    with pytest.MonkeyPatch.context() as fixture_patch:
        fixture_patch.setattr(
            projection, "compare_operation_seeds", compare_operation_seeds
        )
        projected = project_acquisition_run(plan_id, paths=paths)
    body_dir = paths.run_staging_root(projected.run_id)
    body_dir.mkdir(parents=True, exist_ok=True)
    relative_path = "staging/selected.txt"
    body_path = body_dir / "selected.txt"
    source_body = (
        b"<html>submitted primary response</html>"
        if lazy_selected
        else PROCESSING_TEST_BODY
    )
    selected_body = (
        b"<html>selected filing body</html>" if lazy_selected else PROCESSING_TEST_BODY
    )
    initial_relative = "staging/initial.txt"
    (body_dir / "initial.txt").write_bytes(source_body)
    body_path.write_bytes(selected_body)
    source_digest = hashlib.sha256(source_body).hexdigest()
    selected_digest = hashlib.sha256(selected_body).hexdigest()
    attempts = [
        AcquisitionAttempt(
            attempt_id="fixture-attempt-1",
            target_id=target["target_id"],
            attempt_number=1,
            attempt_kind="document_body",
            source="fixture_replay",
            requested_url=_PROCESSING_TARGET_URL,
            outcome="acquired",
            retryable=False,
            error_code=None,
            http_status=200,
            final_url=(
                _PROCESSING_SELECTED_URL
                if not lazy_selected
                else _PROCESSING_TARGET_URL
            ),
            started_at_utc=_PROCESSING_TIMESTAMP,
            finished_at_utc=_PROCESSING_TIMESTAMP,
            source_sha256=source_digest,
            source_byte_size=len(source_body),
            source_body_relative_path=initial_relative,
            selected_sha256=source_digest,
            selected_byte_size=len(source_body),
            selected_body_relative_path=(
                initial_relative if lazy_selected else relative_path
            ),
            selected_filename=selected_filename,
        )
    ]
    resolution = None
    if lazy_selected:
        index_body = b"<html>fixture index</html>"
        (body_dir / "index.html").write_bytes(index_body)
        index_digest = hashlib.sha256(index_body).hexdigest()
        attempts.extend(
            (
                AcquisitionAttempt(
                    attempt_id="fixture-index-2",
                    target_id=target["target_id"],
                    attempt_number=2,
                    attempt_kind="lazy_index",
                    source="fixture_replay",
                    requested_url=_PROCESSING_INDEX_URL,
                    outcome="acquired",
                    retryable=False,
                    error_code=None,
                    http_status=200,
                    final_url=_PROCESSING_INDEX_URL,
                    started_at_utc=_PROCESSING_TIMESTAMP,
                    finished_at_utc=_PROCESSING_TIMESTAMP,
                    source_sha256=index_digest,
                    source_byte_size=len(index_body),
                    source_body_relative_path="staging/index.html",
                    selected_sha256=None,
                    selected_byte_size=None,
                    selected_body_relative_path=None,
                ),
                AcquisitionAttempt(
                    attempt_id="fixture-selected-3",
                    target_id=target["target_id"],
                    attempt_number=3,
                    attempt_kind="document_body",
                    source="fixture_replay",
                    requested_url=_PROCESSING_SELECTED_URL,
                    outcome="acquired",
                    retryable=False,
                    error_code=None,
                    http_status=200,
                    final_url=_PROCESSING_TARGET_URL,
                    started_at_utc=_PROCESSING_TIMESTAMP,
                    finished_at_utc=_PROCESSING_TIMESTAMP,
                    source_sha256=selected_digest,
                    source_byte_size=len(selected_body),
                    source_body_relative_path=relative_path,
                    selected_sha256=selected_digest,
                    selected_byte_size=len(selected_body),
                    selected_body_relative_path=relative_path,
                ),
            )
        )
        resolution = TargetSlotResolution(
            resolution_schema_version="1",
            resolution_id="fixture-resolution",
            run_id=projected.run_id,
            target_id=target["target_id"],
            target_role="primary",
            target_type="primary",
            selector="exact_form_with_lazy_index",
            expected_statutory_type=target["form"],
            initial_sequence=1,
            index_document_type=target["form"],
            index_primary_designation=None,
            initial_observed_body_type=None,
            screen_kind="sgml_type",
            screen_result="unverifiable",
            evaluator_version=None,
            initial_body_sha256=source_digest,
            index_attempt_id="fixture-index-2",
            index_response_sha256=index_digest,
            index_parser_version="fixture-index-v1",
            matching_entry_ids=("fixture-entry-1",),
            selected_sequence=2,
            selected_retrieval_mode="direct_url",
            selected_url=_PROCESSING_SELECTED_URL,
            result="recovered",
        )
    final_attempt = attempts[-1]
    outcome = AcquisitionOutcome(
        target_id=target["target_id"],
        source="fixture_replay",
        status="acquired",
        attempt_count=len(attempts),
        last_attempt_id=final_attempt.attempt_id,
        error_code=None,
        retryable=False,
        source_sha256=selected_digest,
        source_byte_size=len(selected_body),
        source_body_relative_path=final_attempt.source_body_relative_path,
        selected_sha256=selected_digest,
        selected_byte_size=len(selected_body),
        body_lifecycle="staged",
        selected_body_relative_path=relative_path,
    )
    if lazy_selected:
        commit_attempts_and_update_target(
            paths.run_state_path(projected.run_id),
            attempts,
            outcome,
            resolution=resolution,
            recorded_at_utc=_PROCESSING_TIMESTAMP,
        )
    else:
        append_attempt_and_update_target(
            paths.run_state_path(projected.run_id), attempts[0], outcome
        )
    body = get_staged_body_ref(paths, projected.run_id, target["target_id"])
    return paths, ProcessingRequest(
        target_id=target["target_id"],
        accession=AccessionNumber.from_any(target["accession"]),
        form=target["form"],
        target_role=target["target_role"],
        target_type=target["target_type"],
        document_path=validate_archive_url(
            target["target_url"], target["accession"]
        ).document_path,
        selected_filename=body.selected_filename,
        source_origin=target["source_origin"],
        body=body,
        operations=(
            OperationRequest(
                operation_id="raw-identity",
                operation="raw",
                requested=True,
                support_status="supported",
                source_request_id=target["request_id"],
                capability_id="raw.selected_source",
                capability_version="v1",
                handler_id="raw_identity",
                handler_version="1",
                output_kind="raw_bytes",
            ),
            OperationRequest(
                operation_id="text-identity",
                operation="render_to_txt",
                requested=True,
                support_status="supported",
                source_request_id=target["request_id"],
                capability_id="text.plain",
                capability_version="v1",
                handler_id="normalize_document",
                handler_version="1",
                output_kind="text",
            ),
            OperationRequest(
                operation_id="xml-not-requested",
                operation="render_to_xml",
                requested=False,
                support_status="unsupported",
                source_request_id=target["request_id"],
                capability_id=None,
                capability_version=None,
                handler_id=None,
                handler_version=None,
                output_kind=None,
            ),
        ),
    )


def processing_budget_registry(
    route: DocumentRoute = DocumentRoute.TEXT,
    *,
    budget_version: str = "test-v1",
    max_input_bytes: int = 256,
    max_output_bytes: int = 256,
):
    from edgar_sec.pipelines.document_acquisition.processing.io import (
        ProcessingBudgetPolicy,
        ProcessingBudgetRegistry,
    )

    return ProcessingBudgetRegistry(
        (
            ProcessingBudgetPolicy(
                budget_version=budget_version,
                route=route,
                handler_id="normalize_document",
                handler_version="1",
                max_input_bytes=max_input_bytes,
                max_output_bytes=max_output_bytes,
                working_set_reservation_bytes=64,
            ),
        )
    )


def minimal_processing_request(
    tmp_path: Path,
    *,
    operations: tuple[Any, ...] | None = None,
    form: str = "10-K",
):
    import hashlib

    from edgar_sec.domain.identity import AccessionNumber
    from edgar_sec.pipelines.document_acquisition.paths import (
        resolve_acquisition_paths,
    )
    from edgar_sec.pipelines.document_acquisition.processing.models import (
        OperationRequest,
        ProcessingRequest,
    )
    from edgar_sec.pipelines.document_acquisition.schemas import StagedBodyRef

    paths = resolve_acquisition_paths(artifacts_root=tmp_path / "artifacts")
    run_id = "run_test"
    target_id = "target_test"
    body_path = paths.run_staging_root(run_id) / "selected.txt"
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_bytes(PROCESSING_TEST_BODY)
    digest = hashlib.sha256(PROCESSING_TEST_BODY).hexdigest()
    body = StagedBodyRef(
        run_id=run_id,
        target_id=target_id,
        path=body_path,
        sha256=digest,
        byte_size=len(PROCESSING_TEST_BODY),
        selected_filename=None,
        source_response_path=body_path,
        source_response_sha256=digest,
        source_response_byte_size=len(PROCESSING_TEST_BODY),
    )
    default_operations = (
        OperationRequest(
            operation_id="raw-test",
            operation="raw",
            requested=True,
            support_status="supported",
            source_request_id="source-test",
            capability_id="raw.selected_source",
            capability_version="v1",
            handler_id="raw_identity",
            handler_version="1",
            output_kind="raw_bytes",
        ),
        OperationRequest(
            operation_id="text-test",
            operation="render_to_txt",
            requested=True,
            support_status="supported",
            source_request_id="source-test",
            capability_id="text.plain",
            capability_version="v1",
            handler_id="normalize_document",
            handler_version="1",
            output_kind="text",
        ),
        OperationRequest(
            operation_id="xml-test",
            operation="render_to_xml",
            requested=False,
            support_status="unsupported",
            source_request_id="source-test",
            capability_id=None,
            capability_version=None,
            handler_id=None,
            handler_version=None,
            output_kind=None,
        ),
    )
    request = ProcessingRequest(
        target_id=target_id,
        accession=AccessionNumber.from_any("0000320193-23-000001"),
        form=form,
        target_role="primary",
        target_type="primary",
        document_path="filing.txt",
        selected_filename=None,
        source_origin="inventory_index",
        body=body,
        operations=default_operations if operations is None else operations,
    )
    return paths, request


def stub_processing_target_validation(
    monkeypatch: Any,
    request: Any,
    *,
    route: DocumentRoute = DocumentRoute.TEXT,
    effective_path: str = "filing.txt",
) -> None:
    import edgar_sec.pipelines.document_acquisition.processing.worker as processing

    monkeypatch.setattr(
        processing,
        "_target_row",
        lambda *_args: {
            "target_id": request.target_id,
            "target_url": _PROCESSING_TARGET_URL,
        },
    )
    monkeypatch.setattr(
        processing,
        "_effective_route",
        lambda *_args: (route, effective_path),
    )


def two_text_processing_operations(request: Any):
    from dataclasses import replace

    retry_operation = replace(
        request.operations[2],
        operation_id="text-retry",
        operation="render_to_txt",
        requested=True,
        support_status="supported",
        capability_id="text.plain",
        capability_version="v1",
        handler_id="normalize_document",
        handler_version="1",
        output_kind="text",
    )
    return replace(
        request,
        operations=(request.operations[0], request.operations[1], retry_operation),
    )


def failed_processing_operation_result(operation_id: str):
    from edgar_sec.pipelines.document_acquisition.processing.models import (
        OperationResult,
    )

    return OperationResult(
        operation_id=operation_id,
        operation_fingerprint="",
        status="failed",
        representation_id=None,
        output_sha256=None,
        output_size=None,
        handler_id=None,
        handler_version=None,
        diagnostics=(),
        staged_output=None,
    )


def processing_body_receipt(paths: Any, body: Any):
    from edgar_sec.pipelines.document_acquisition.body_handoff import (
        read_body_consumption_receipt,
    )

    return read_body_consumption_receipt(paths, body.run_id, body.target_id)


__all__ = [
    "CATALOG_FIXTURES",
    "FIXTURES",
    "TESTS_ROOT",
    "FakeResponse",
    "FakeSession",
    "FixtureCohort",
    "build_test_client",
    "build_test_http",
    "catalog_fixture_path",
    "cik_payload",
    "compiled_cohort",
    "fixture_ciks",
    "fixture_cohort",
    "fixture_path",
    "acquired_processing_request",
    "minimal_processing_request",
    "processing_budget_registry",
    "stub_processing_target_validation",
    "two_text_processing_operations",
    "failed_processing_operation_result",
    "processing_body_receipt",
    "PROCESSING_TEST_BODY",
    "historical_url",
    "load_catalog_fixture",
    "load_fixture",
    "roster_of",
    "scratch_root",
    "submissions_document",
]
