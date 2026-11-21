from __future__ import annotations

import re
from dataclasses import asdict

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.exhibits import (
    DocumentRoleAssessment,
    ExhibitIdentity,
)
from edgar_sec.engine.forms.plugins.exhibit_selection import (
    PROBE_CHAR_BOUND,
    evaluate_exhibit_body,
)
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.pipelines.document_acquisition.processing.models import (
    OperationResult,
    ProcessingRequest,
)

_EXHIBIT_CODE = re.compile(r"EX(?:HIBIT\s+|-?)([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)


def assess_exhibit_processing(
    request: ProcessingRequest,
    results: tuple[OperationResult, ...],
    route: DocumentRoute,
    effective_path: str,
) -> tuple[DocumentRoleAssessment | None, str | None]:
    if request.target_role != "exhibit":
        return None, None
    match = _EXHIBIT_CODE.fullmatch(request.target_type.strip())
    if match is None:
        return None, None
    text_results = [
        result
        for result in results
        if next(
            (
                operation.operation
                for operation in request.operations
                if operation.operation_id == result.operation_id
            ),
            None,
        )
        == "render_to_txt"
    ]
    if len(text_results) != 1:
        return None, None
    result = text_results[0]
    output = result.staged_output
    if (
        result.status != "available"
        or output is None
        or output.representation != "text_normalized"
        or not result.output_sha256
    ):
        return None, None
    try:
        with output.path.open("r", encoding="utf-8", newline="") as stream:
            text = stream.read(PROBE_CHAR_BOUND)
    except (OSError, UnicodeError):
        return None, None

    form = resolve_alias(request.form) or request.form.strip().upper()
    identity = ExhibitIdentity("reg_s_k_item_601", match.group(1))
    assessment = evaluate_exhibit_body(
        text,
        filing_form=form,
        expected_type=request.target_type,
        expected_identity=identity,
    )
    if assessment is None:
        return None, None
    fingerprint = canonical_hash(
        {
            "diagnostic_version": 1,
            "target_id": request.target_id,
            "accession": str(request.accession),
            "form": form,
            "target_role": request.target_role,
            "target_type": request.target_type,
            "source_sha256": request.body.sha256,
            "operation_fingerprint": result.operation_fingerprint,
            "normalized_output_sha256": result.output_sha256,
            "route": route.value,
            "effective_path": effective_path,
            "assessment": asdict(assessment),
        }
    )
    return assessment, fingerprint
