from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from edgar_sec.pipelines.document_acquisition.body_handoff import (
    BodyHandoffError,
    get_staged_body_ref,
    read_body_consumption_receipt,
    record_body_consumption_receipt,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.run_state.models import (
    WorkOrderTargetSeed,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    initialize_run_state,
)
from edgar_sec.pipelines.document_acquisition.schemas import RECEIPT_SCHEMA_VERSION

_RUN_ID = "run-handoff"
_TARGET_ID = "target-1"
_SOURCE = b"source response envelope"
_SELECTED = b"selected filing body"


def _make_run(tmp_path: Path, *, bundle: bool = False):
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id = _RUN_ID + ("-bundle" if bundle else "")
    target_id = _TARGET_ID
    initialize_run_state(
        paths.run_state_path(run_id), [WorkOrderTargetSeed(target_id, True, None)]
    )
    staging = paths.run_staging_root(run_id)
    selected_dir = staging / "selected"
    source_dir = staging / "incoming"
    selected_dir.mkdir(parents=True)
    source_dir.mkdir()
    selected_path = selected_dir / "body.bin"
    source_path = source_dir / "response.bin"
    selected_path.write_bytes(_SELECTED)
    source_path.write_bytes(_SOURCE if bundle else _SELECTED)
    source_body = _SOURCE if bundle else _SELECTED
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        connection.execute(
            "UPDATE target_state SET outcome = 'acquired', source = 'live_sec', "
            "attempt_count = 1, last_attempt_id = 'attempt-1', source_sha256 = ?, "
            "source_byte_size = ?, source_body_relative_path = ?, selected_sha256 = ?, "
            "selected_byte_size = ?, selected_body_relative_path = ? "
            "WHERE target_id = ?",
            (
                hashlib.sha256(source_body).hexdigest(),
                len(source_body),
                source_path.relative_to(paths.run_dir(run_id)).as_posix(),
                hashlib.sha256(_SELECTED).hexdigest(),
                len(_SELECTED),
                selected_path.relative_to(paths.run_dir(run_id)).as_posix(),
                target_id,
            ),
        )
    return paths, run_id, selected_path, source_path


def _receipt(paths, run_id: str, *, processing_run_id: str = "fake-process-1"):
    ref = get_staged_body_ref(paths, run_id, _TARGET_ID)
    return {
        "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
        "run_id": run_id,
        "target_id": _TARGET_ID,
        "source_response_sha256": ref.source_response_sha256,
        "selected_sha256": ref.sha256,
        "processing_run_id": processing_run_id,
        "consumed_at_utc": "2026-10-10T21:00:00Z",
    }


@pytest.mark.parametrize("bundle", [False, True])
def test_staged_body_ref_verifies_direct_and_bundle_files(tmp_path, bundle) -> None:
    paths, run_id, selected_path, source_path = _make_run(tmp_path, bundle=bundle)

    ref = get_staged_body_ref(paths, run_id, _TARGET_ID)

    assert ref.path == selected_path
    assert ref.sha256 == hashlib.sha256(_SELECTED).hexdigest()
    assert ref.byte_size == len(_SELECTED)
    assert ref.source_response_path == source_path
    assert (
        ref.source_response_sha256
        == hashlib.sha256(_SOURCE if bundle else _SELECTED).hexdigest()
    )
    assert ref.source_response_byte_size == len(_SOURCE if bundle else _SELECTED)
    assert ref.selected_filename is None


def test_staged_body_ref_allows_deleted_source_envelope(tmp_path) -> None:
    paths, run_id, _selected_path, source_path = _make_run(tmp_path, bundle=True)
    source_path.unlink()
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        connection.execute(
            "UPDATE target_state SET source_body_relative_path = NULL "
            "WHERE target_id = ?",
            (_TARGET_ID,),
        )

    ref = get_staged_body_ref(paths, run_id, _TARGET_ID)

    assert ref.source_response_path is None
    assert ref.source_response_sha256 == hashlib.sha256(_SOURCE).hexdigest()
    assert ref.source_response_byte_size == len(_SOURCE)


@pytest.mark.parametrize("corruption", ["digest", "size", "contents"])
def test_staged_body_ref_refuses_selected_identity_mismatch(
    tmp_path, corruption: str
) -> None:
    paths, run_id, selected_path, _source_path = _make_run(tmp_path)
    if corruption == "digest":
        with sqlite3.connect(paths.run_state_path(run_id)) as connection:
            connection.execute(
                "UPDATE target_state SET selected_sha256 = ? WHERE target_id = ?",
                ("0" * 64, _TARGET_ID),
            )
    elif corruption == "size":
        with sqlite3.connect(paths.run_state_path(run_id)) as connection:
            connection.execute(
                "UPDATE target_state SET selected_byte_size = selected_byte_size + 1 "
                "WHERE target_id = ?",
                (_TARGET_ID,),
            )
    else:
        selected_path.write_bytes(b"corrupted filing body")

    with pytest.raises(BodyHandoffError, match="selected body"):
        get_staged_body_ref(paths, run_id, _TARGET_ID)


def test_staged_body_ref_refuses_missing_selected_file(tmp_path) -> None:
    paths, run_id, selected_path, _source_path = _make_run(tmp_path)
    selected_path.unlink()

    with pytest.raises(BodyHandoffError, match="missing or inaccessible"):
        get_staged_body_ref(paths, run_id, _TARGET_ID)


def test_staged_body_ref_refuses_selected_symlink_and_escape(tmp_path) -> None:
    paths, run_id, selected_path, _source_path = _make_run(tmp_path)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(_SELECTED)
    selected_path.unlink()
    selected_path.symlink_to(outside)
    with pytest.raises(BodyHandoffError, match="escapes run staging|symlink"):
        get_staged_body_ref(paths, run_id, _TARGET_ID)

    selected_path.unlink()
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        connection.execute(
            "UPDATE target_state SET selected_body_relative_path = ? "
            "WHERE target_id = ?",
            ("../../outside.bin", _TARGET_ID),
        )
    with pytest.raises(BodyHandoffError, match="path is invalid"):
        get_staged_body_ref(paths, run_id, _TARGET_ID)


def test_staged_body_ref_checks_retained_source_evidence(tmp_path) -> None:
    paths, run_id, _selected_path, source_path = _make_run(tmp_path, bundle=True)
    source_path.write_bytes(b"corrupt envelope")

    with pytest.raises(BodyHandoffError, match="source response"):
        get_staged_body_ref(paths, run_id, _TARGET_ID)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("run_id", "another-run", "run target is not acquired|unable to open"),
        ("target_id", "another-target", "run target is not acquired"),
        ("source_response_sha256", "0" * 64, "receipt identity"),
        ("selected_sha256", "0" * 64, "receipt identity"),
        ("receipt_schema_version", "999", "schema version"),
        ("consumed_at_utc", "2026-10-10T21:00:00-05:00", "must use UTC"),
        ("consumed_at_utc", "not-a-time", "ISO-8601 UTC"),
    ],
)
def test_receipt_rejects_identity_schema_and_timestamp_mismatch(
    tmp_path, field: str, value: str, message: str
) -> None:
    paths, run_id, _selected_path, _source_path = _make_run(tmp_path)
    receipt = _receipt(paths, run_id)
    receipt[field] = value

    with pytest.raises(BodyHandoffError, match=message):
        record_body_consumption_receipt(paths, receipt)


def test_receipt_is_idempotent_and_conflicts_are_refused(tmp_path) -> None:
    paths, run_id, _selected_path, _source_path = _make_run(tmp_path)
    receipt = _receipt(paths, run_id)

    recorded = record_body_consumption_receipt(paths, receipt)
    assert recorded == receipt
    assert record_body_consumption_receipt(paths, receipt) == recorded
    assert read_body_consumption_receipt(paths, run_id, _TARGET_ID) == recorded

    conflict = _receipt(paths, run_id, processing_run_id="fake-process-2")
    with pytest.raises(BodyHandoffError, match="conflicting immutable"):
        record_body_consumption_receipt(paths, conflict)


def test_receipt_read_refuses_missing_corrupt_and_symlink_sidecars(tmp_path) -> None:
    paths, run_id, _selected_path, _source_path = _make_run(tmp_path)
    assert read_body_consumption_receipt(paths, run_id, _TARGET_ID) is None
    receipt = _receipt(paths, run_id)
    destination = paths.body_consumption_receipt_path(
        run_id, _TARGET_ID, receipt["selected_sha256"]
    )
    destination.parent.mkdir(parents=True)
    destination.write_text("{bad json", encoding="utf-8")
    with pytest.raises(BodyHandoffError, match="corrupt"):
        read_body_consumption_receipt(paths, run_id, _TARGET_ID)

    destination.unlink()
    destination.write_bytes(b"\xff")
    with pytest.raises(BodyHandoffError, match="corrupt"):
        read_body_consumption_receipt(paths, run_id, _TARGET_ID)

    destination.unlink()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    destination.symlink_to(outside)
    with pytest.raises(BodyHandoffError, match="unsafe"):
        read_body_consumption_receipt(paths, run_id, _TARGET_ID)


def test_staged_body_ref_requires_acquired_target(tmp_path) -> None:
    paths, run_id, _selected_path, _source_path = _make_run(tmp_path)
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        connection.execute(
            "UPDATE target_state SET outcome = 'pending' WHERE target_id = ?",
            (_TARGET_ID,),
        )

    with pytest.raises(BodyHandoffError, match="not acquired"):
        get_staged_body_ref(paths, run_id, _TARGET_ID)
