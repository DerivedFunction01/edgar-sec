"""Validate individual target rows against their partition and plan pins."""

from __future__ import annotations

from typing import Any

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import accession_hyphenated, validate_archive_url
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.pipelines.document_acquisition.plan_projection.target_contract import (
    TargetPlanError,
)

_STATUSES = frozenset(
    {
        "matched",
        "not_filed",
        "required_missing",
        "ambiguous",
        "unresolved",
        "constructed_candidate",
    }
)
_RETRIEVAL_MODES = frozenset(
    {"direct_url", "bundle_sequence", "bundle_scan", "constructed_package", "none"}
)
_SELECTORS = frozenset({"submitted_primary", "exact_form_with_lazy_index"})


def _validate_url(url: object, accession: str, *, bundle: bool) -> str:
    if not isinstance(url, str) or not url or url != url.strip():
        raise TargetPlanError("matched target is missing a valid SEC URL")
    try:
        accession_number = AccessionNumber(accession)
        archive = validate_archive_url(url, accession_number)
    except ValueError as error:
        raise TargetPlanError(
            "target URL is outside the accession's SEC archive"
        ) from error
    if (
        bundle
        and archive.document_path
        != f"{accession_hyphenated(str(accession_number))}.txt"
    ):
        raise TargetPlanError(
            "bundle URL is not the accession's canonical submission file"
        )
    return url


def _validate_row(
    row: dict[str, Any],
    plan_id: str,
    has_inventory_pin: bool,
    form: str,
) -> None:
    if row["form"] != form:
        raise TargetPlanError("target row form disagrees with its partition")
    try:
        accession = AccessionNumber(row["accession"])
    except (TypeError, ValueError) as error:
        raise TargetPlanError("target row has an invalid accession") from error
    if row["target_id"] != canonical_hash(
        [
            plan_id,
            row["accession"],
            row["request_id"],
            row["inventory_entry_id"],
            row["status"],
        ]
    ):
        raise TargetPlanError("target row ID does not match its identity")
    if row["status"] not in _STATUSES:
        raise TargetPlanError("target row has an unsupported status")
    if row["source_origin"] not in {"inventory_index", "catalog_direct"}:
        raise TargetPlanError("target row has an unsupported source origin")
    if row["retrieval_mode"] not in _RETRIEVAL_MODES:
        raise TargetPlanError("target row has an unsupported retrieval mode")
    if row["catalog_direct_selection"] not in (None, *_SELECTORS):
        raise TargetPlanError("target row has an unsupported pinned selector")
    if has_inventory_pin:
        if row["source_origin"] != "inventory_index":
            raise TargetPlanError(
                "inventory-pinned plan contains a non-inventory target"
            )
    elif (
        row["source_origin"] != "catalog_direct"
        or row["target_role"] != "primary"
        or row["target_type"] != "primary"
    ):
        raise TargetPlanError(
            "null inventory pin is valid only for catalog-only primary targets"
        )
    sequence = row["sequence"]
    if sequence is not None and (
        isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0
    ):
        raise TargetPlanError("target sequence must be a positive integer")
    size = row["byte_size"]
    if size is not None and (
        isinstance(size, bool) or not isinstance(size, int) or size < 0
    ):
        raise TargetPlanError("target byte_size must be a non-negative integer")
    if row["retrieval_mode"] in {"direct_url", "bundle_sequence", "bundle_scan"}:
        if row["target_url"] is not None:
            _validate_url(
                row["target_url"],
                str(accession),
                bundle=row["retrieval_mode"] != "direct_url",
            )
        if row["status"] == "matched" and row["target_url"] is None:
            raise TargetPlanError("matched target is missing its SEC URL")
        if (
            row["status"] == "matched"
            and row["retrieval_mode"] == "bundle_sequence"
            and sequence is None
        ):
            raise TargetPlanError(
                "bundle_sequence target is missing its positive sequence"
            )
        if row["retrieval_mode"] == "bundle_scan" and sequence is not None:
            raise TargetPlanError("bundle_scan target must not carry a sequence")
