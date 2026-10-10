from __future__ import annotations

import uuid
from typing import Literal

from edgar_sec.engine.index_pages.parser import PARSER_FINGERPRINT
from edgar_sec.pipelines.document_acquisition.index_selection import IndexSelection
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    TargetSlotResolution,
)
from edgar_sec.infra.sec_http.streaming import StreamedResponse

_RESOLUTION_SCHEMA_VERSION = "1"


def build_resolution(
    row: dict[str, object],
    initial: StreamedResponse,
    index_attempt: AcquisitionAttempt,
    index_response: StreamedResponse | None,
    selection: IndexSelection | None,
    result: str,
    *,
    screen_kind: Literal["none", "sgml_type", "html_cover"] = "html_cover",
    screen_result: Literal[
        "not_run", "form_match", "type_mismatch", "unverifiable"
    ] = "unverifiable",
    observed_body_type: str | None = None,
) -> TargetSlotResolution:
    entry = selection.entry if selection is not None else None
    return TargetSlotResolution(
        resolution_schema_version=_RESOLUTION_SCHEMA_VERSION,
        resolution_id=uuid.uuid4().hex,
        run_id=str(row["run_id"]),
        target_id=str(row["target_id"]),
        target_role=row["target_role"],
        target_type=row["target_type"],
        selector="exact_form_with_lazy_index",
        expected_statutory_type=str(row["form"]),
        initial_sequence=1,
        index_document_type=entry.document_type if entry else None,
        index_primary_designation=None,
        initial_observed_body_type=observed_body_type,
        screen_kind=screen_kind,
        screen_result=screen_result,
        evaluator_version=None,
        initial_body_sha256=initial.sha256,
        index_attempt_id=index_attempt.attempt_id,
        index_response_sha256=index_response.sha256 if index_response else None,
        index_parser_version=PARSER_FINGERPRINT if selection is not None else None,
        matching_entry_ids=selection.matching_entry_ids if selection else (),
        selected_sequence=entry.sequence if entry else None,
        selected_retrieval_mode=selection.retrieval_mode if selection else None,
        selected_url=selection.selected_url if selection else None,
        result=result,
    )


def screen_sgml_type(
    observed: str | None, expected: str
) -> Literal["form_match", "type_mismatch", "unverifiable"]:
    if observed is None:
        return "unverifiable"
    try:
        observed_ascii = observed.encode("ascii")
        expected_ascii = expected.encode("ascii")
    except UnicodeEncodeError:
        return "unverifiable"
    return "form_match" if observed_ascii == expected_ascii else "type_mismatch"
