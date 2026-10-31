from __future__ import annotations

import hashlib
import io

from edgar_sec.pipelines.document_acquisition.fixture_store.capture import (
    create_fixture as _create_fixture,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import FixturePlanPin
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    append_fixture_lazy_index,
    append_fixture_case,
    initialize_fixture as _initialize_fixture,
)

FIXTURE_PLAN_PIN = FixturePlanPin("plan_fixture_test", "a" * 64, 1)


def initialize_test_fixture(paths, fixture_id: str):
    return _initialize_fixture(paths, fixture_id, FIXTURE_PLAN_PIN)


def create_test_fixture(paths, fixture_id: str, plan_pin: FixturePlanPin):
    return _create_fixture(fixture_id, plan_pin, paths=paths)


def append_test_case(
    paths,
    fixture_id: str,
    target_id: str,
    body: bytes,
    *,
    capture_id: str = "capture-1",
    pin: FixturePlanPin = FIXTURE_PLAN_PIN,
    max_body_bytes: int | None = None,
    inventory_entry_id: str | None = None,
    selection_source: str = "planned_source",
    index_sha256: str | None = None,
    source_origin: str = "inventory_index",
    filing_date: str | None = "2024-01-31",
    report_date: str | None = None,
):
    capture = {
        "capture_id": capture_id,
        "target_plan_id": pin.target_plan_id,
        "target_plan_digest": pin.target_plan_digest,
        "target_plan_schema_version": pin.target_plan_schema_version,
        "captured_at_utc": "2026-10-14T00:00:00Z",
    }
    case = {
        "capture_id": capture_id,
        "target_id": target_id,
        "inventory_entry_id": inventory_entry_id,
        "selection_source": selection_source,
        "index_sha256": index_sha256,
        "accession": "0000123456-24-000001",
        "form": "4",
        "request_id": f"request-{target_id}",
        "target_role": "primary",
        "target_type": "primary",
        "source_origin": source_origin,
        "retrieval_mode": "direct_url",
        "target_url": "https://www.sec.gov/Archives/edgar/data/123456/000012345624000001/form4.htm",
        "sequence": None,
        "selected_filename": "form4.htm",
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "byte_size": len(body),
        "filing_date": filing_date,
        "report_date": report_date,
    }
    return append_fixture_case(
        paths,
        fixture_id,
        capture,
        case,
        io.BytesIO(body),
        max_body_bytes=len(body) if max_body_bytes is None else max_body_bytes,
    )


def append_test_lazy_index(paths, fixture_id: str, body: bytes):
    return append_fixture_lazy_index(
        paths,
        fixture_id,
        "0000123456-24-000001",
        "https://www.sec.gov/Archives/edgar/data/123456/000012345624000001/0000123456-24-000001-index.html",
        io.BytesIO(body),
        max_body_bytes=len(body),
    )
