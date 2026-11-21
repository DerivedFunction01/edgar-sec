from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime

from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    get_target_state,
)
from tests.pipelines.document_acquisition.execution.runner_fixtures import (
    ACCESSION as _ACCESSION,
    BUNDLE_URL as _BUNDLE_URL,
    MemoryTransport as _MemoryTransport,
)


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
    from edgar_sec.pipelines.document_acquisition.execution.target_runner import (
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
