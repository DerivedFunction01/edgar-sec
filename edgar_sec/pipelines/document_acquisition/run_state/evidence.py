from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    TargetSlotResolution,
)
from edgar_sec.pipelines.document_acquisition.run_state.models import (
    AttemptEvidenceGroup,
    _acquisition_attempt_from_row,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    RunStateError,
    _connect,
    _require_schema,
    _url_value,
)

_ATTEMPT_COLUMNS = """attempt_id, target_id, attempt_number, attempt_kind, source,
    requested_url, outcome, retryable, error_code, http_status, final_url,
    started_at_utc, finished_at_utc, source_sha256, source_byte_size,
    source_body_relative_path, selected_sha256, selected_byte_size,
    selected_body_relative_path"""
_GET_ATTEMPT = (
    f"SELECT {_ATTEMPT_COLUMNS} FROM attempts WHERE target_id = ? AND attempt_id = ?"
)
_GET_ATTEMPT_BY_NUMBER = (
    f"SELECT {_ATTEMPT_COLUMNS} FROM attempts "
    "WHERE target_id = ? AND attempt_number = ?"
)
_LIST_ATTEMPTS = (
    f"SELECT {_ATTEMPT_COLUMNS} FROM attempts "
    "WHERE target_id = ? ORDER BY attempt_number"
)
_GET_RESOLUTIONS_FOR_INDEX = """SELECT resolution_id, resolution_schema_version, target_id,
    selector, expected_statutory_type, initial_sequence, screen_kind, screen_result,
    evaluator_version, initial_body_sha256, index_attempt_id, index_response_sha256,
    index_parser_version, matching_entry_ids_json, selected_sequence,
    selected_retrieval_mode, selected_url, result, recorded_at_utc
FROM target_slot_resolutions WHERE target_id = ? AND index_attempt_id = ?"""


def _resolution_from_row(row: tuple[object, ...]) -> TargetSlotResolution:
    try:
        matching_ids = json.loads(row[13])
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid persisted resolution matching-entry IDs") from error
    if (
        not isinstance(matching_ids, list)
        or any(
            not isinstance(entry_id, str) or not entry_id for entry_id in matching_ids
        )
        or len(matching_ids) != len(set(matching_ids))
    ):
        raise ValueError("invalid persisted resolution matching-entry IDs")

    def text(value: object, name: str, *, optional: bool = False) -> str | None:
        if optional and value is None:
            return None
        if not isinstance(value, str) or not value:
            raise ValueError(f"invalid persisted resolution field: {name}")
        return value

    def digest(value: object, name: str, *, optional: bool = False) -> str | None:
        result = text(value, name, optional=optional)
        if result is not None and (
            len(result) != 64
            or any(character not in "0123456789abcdef" for character in result)
        ):
            raise ValueError(f"invalid persisted resolution field: {name}")
        return result

    schema_version = text(row[1], "resolution_schema_version")
    resolution_id = text(row[0], "resolution_id")
    target_id = text(row[2], "target_id")
    selector = text(row[3], "selector")
    expected_type = text(row[4], "expected_statutory_type")
    screen_kind = text(row[6], "screen_kind")
    screen_result = text(row[7], "screen_result")
    initial_hash = digest(row[9], "initial_body_sha256")
    index_attempt_id = text(row[10], "index_attempt_id")
    result = text(row[17], "result")
    text(row[18], "recorded_at_utc")
    evaluator_version = text(row[8], "evaluator_version", optional=True)
    index_response_hash = digest(row[11], "index_response_sha256", optional=True)
    index_parser_version = text(row[12], "index_parser_version", optional=True)
    selected_url = text(row[16], "selected_url", optional=True)
    selected_sequence = row[14]
    selected_mode = row[15]

    if schema_version != "1":
        raise ValueError("unsupported target-slot resolution schema version")
    if selector != "exact_form_with_lazy_index":
        raise ValueError("invalid persisted resolution field: selector")
    if row[5] != 1:
        raise ValueError("invalid persisted resolution field: initial_sequence")
    if screen_kind not in {"none", "sgml_type", "html_cover"}:
        raise ValueError("invalid persisted resolution field: screen_kind")
    if screen_result not in {"not_run", "form_match", "type_mismatch", "unverifiable"}:
        raise ValueError("invalid persisted resolution field: screen_result")
    if selected_sequence is not None and (
        isinstance(selected_sequence, bool)
        or not isinstance(selected_sequence, int)
        or selected_sequence < 1
    ):
        raise ValueError("invalid persisted resolution field: selected_sequence")
    if selected_mode not in {None, "direct_url", "bundle_sequence"}:
        raise ValueError("invalid persisted resolution field: selected_retrieval_mode")
    if result not in {
        "accepted_sequence_1",
        "recovered",
        "not_filed",
        "required_missing",
        "ambiguous",
        "failed",
    }:
        raise ValueError("invalid persisted resolution field: result")
    selected_fields = (selected_sequence, selected_mode, selected_url)
    if any(value is None for value in selected_fields) != all(
        value is None for value in selected_fields
    ):
        raise ValueError("inconsistent persisted selected-document resolution")

    return TargetSlotResolution(
        resolution_schema_version=schema_version,
        resolution_id=resolution_id,
        run_id=None,
        target_id=target_id,
        target_role=None,
        target_type=None,
        selector=selector,
        expected_statutory_type=expected_type,
        initial_sequence=row[5],
        index_document_type=None,
        index_primary_designation=None,
        initial_observed_body_type=None,
        screen_kind=screen_kind,
        screen_result=screen_result,
        evaluator_version=evaluator_version,
        initial_body_sha256=initial_hash,
        index_attempt_id=index_attempt_id,
        index_response_sha256=index_response_hash,
        index_parser_version=index_parser_version,
        matching_entry_ids=tuple(matching_ids),
        selected_sequence=selected_sequence,
        selected_retrieval_mode=selected_mode,
        selected_url=selected_url,
        result=result,
    )


def get_attempt_evidence_group(
    database_path: Path, target_id: str, initial_attempt_id: str
) -> AttemptEvidenceGroup | None:
    connection = _connect(Path(database_path), readonly=True)
    try:
        _require_schema(connection)
        initial_row = connection.execute(
            _GET_ATTEMPT, (target_id, initial_attempt_id)
        ).fetchone()
        if initial_row is None:
            return None
        initial = _acquisition_attempt_from_row(initial_row)
        if initial.attempt_kind != "document_body":
            raise RunStateError(
                "initial evidence attempt is not a document-body attempt"
            )

        following_row = connection.execute(
            _GET_ATTEMPT_BY_NUMBER,
            (target_id, initial.attempt_number + 1),
        ).fetchone()
        if following_row is None or following_row[3] != "lazy_index":
            return AttemptEvidenceGroup(initial, None, None, None)
        lazy_index = _acquisition_attempt_from_row(following_row)
        resolution_rows = connection.execute(
            _GET_RESOLUTIONS_FOR_INDEX, (target_id, lazy_index.attempt_id)
        ).fetchall()
        if len(resolution_rows) != 1:
            raise RunStateError(
                "lazy-index attempt has no unique target-slot resolution"
            )
        try:
            resolution = _resolution_from_row(resolution_rows[0])
        except ValueError as error:
            raise RunStateError(str(error)) from error
        try:
            _url_value(resolution.selected_url, "selected_url", required=False)
        except ValueError as error:
            raise RunStateError(
                "invalid persisted resolution field: selected_url"
            ) from error
        if (
            resolution.target_id != target_id
            or resolution.index_attempt_id != lazy_index.attempt_id
            or initial.source_sha256 is None
            or resolution.initial_body_sha256 != initial.source_sha256
        ):
            raise RunStateError(
                "lazy-index resolution does not match its initial attempt"
            )

        selected = None
        if resolution.selected_url is not None:
            selected_row = connection.execute(
                _GET_ATTEMPT_BY_NUMBER,
                (target_id, initial.attempt_number + 2),
            ).fetchone()
            if selected_row is not None and selected_row[5] == resolution.selected_url:
                selected = _acquisition_attempt_from_row(selected_row)
                if selected.attempt_kind != "document_body":
                    raise RunStateError(
                        "selected response attempt is not a document-body attempt"
                    )
        return AttemptEvidenceGroup(initial, lazy_index, selected, resolution)
    finally:
        connection.close()


def list_target_attempts(
    database_path: Path, target_id: str
) -> list[AcquisitionAttempt]:
    connection = _connect(Path(database_path), readonly=True)
    try:
        _require_schema(connection)
        return [
            _acquisition_attempt_from_row(row)
            for row in connection.execute(_LIST_ATTEMPTS, (target_id,))
        ]
    finally:
        connection.close()


__all__ = ["get_attempt_evidence_group", "list_target_attempts"]
