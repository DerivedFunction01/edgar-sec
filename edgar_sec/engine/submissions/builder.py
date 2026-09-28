"""Canonical submission_metadata row assembly and Arrow schema conformance."""

from __future__ import annotations

from typing import Any

import pyarrow as pa

from edgar_sec.domain.submissions.schemas import (
    SCHEMA_VERSION,
    SUBMISSION_METADATA_SCHEMA,
)

from .filings import dedupe_filings, normalize_submission_files, zip_filing_arrays
from .helpers import add_anomaly, canonical_json, resolve_alias, to_bool
from .profile import (
    PROFILE_KEYS,
    normalize_address,
    normalize_former_names,
    zip_listings,
)

_SUBMISSION_FILE_FIELDS = ("name", "filing_count", "filing_from", "filing_to")

__all__ = ["build_submission_table", "normalize_submissions", "validate_row_shapes"]


def validate_row_shapes(row: dict) -> None:
    """Fail fast on any value that would not fit the declared Arrow schema."""
    for field in SUBMISSION_METADATA_SCHEMA:
        value = row.get(field.name)
        if value is None:
            continue
        try:
            pa.array([value], type=field.type)
        except (pa.ArrowInvalid, pa.ArrowTypeError, pa.ArrowNotImplementedError) as exc:
            raise ValueError(
                f"row field '{field.name}' does not match schema: {exc}"
            ) from exc


def _failed_row(
    *,
    cik_padded: str,
    input_name: str,
    snapshot_id: str,
    fetched_at: str,
    source_url: str,
    error: str,
    byte_count: int,
) -> dict:
    """Terminal failed row carrying every schema field.

    One row is emitted per requested CIK including failures, so completion is
    determinable from the data rather than from queue state.
    """
    return {
        "cik": cik_padded,
        "snapshot_id": snapshot_id,
        "fetched_at": fetched_at,
        "source_url": source_url,
        "response_sha256": "",
        "byte_count": byte_count,
        "schema_version": SCHEMA_VERSION,
        "status": "failed",
        "error": error,
        "anomalies": [],
        "extra_fields": None,
        "identity": {"name": None, "former_names": []},
        "classification": {
            "entity_type": None,
            "sic_code": None,
            "sic_description": None,
            "owner_org": None,
            "filer_category": None,
        },
        "identifiers": {"ein": None, "lei": None},
        "contact": {
            "phone": None,
            "website": None,
            "investor_website": None,
            "description": None,
        },
        "incorporation": {"state": None, "state_description": None},
        "reporting": {"fiscal_year_end": None},
        "insider_transactions": {"owner_exists": None, "issuer_exists": None},
        "addresses": {"mailing": None, "business": None},
        "listings": [],
        "filings": [],
        "submission_files": [],
        "input_name": input_name,
        "input_fingerprint": "",
        "chunk_id": None,
        "historical_files_total": 0,
        "historical_files_failed": 0,
        "historical_records_total": 0,
    }


def normalize_submissions(
    payload: dict,
    *,
    cik_padded: str,
    input_name: str,
    snapshot_id: str,
    fetched_at: str,
    source_url: str,
    byte_count: int,
    historical_payloads: list[tuple[str, str, dict | None]],
    historical_errors: list[str],
    response_sha256: str = "",
    input_fingerprint: str = "",
    chunk_id: int | None = None,
) -> dict[str, Any]:
    """Build one canonical ``submission_metadata`` row from a submissions payload.

    ``historical_payloads`` holds ``(source_file, source_section, payload)``
    tuples. ``historical_errors`` carries terminal failures for historical
    files, which are required inputs rather than best-effort extras.
    """
    anomalies: list[dict] = []
    if not isinstance(payload, dict):
        return _failed_row(
            cik_padded=cik_padded,
            input_name=input_name,
            snapshot_id=snapshot_id,
            fetched_at=fetched_at,
            source_url=source_url,
            error="payload is not a JSON object",
            byte_count=byte_count,
        )

    known_lower = {key.lower() for key in PROFILE_KEYS}
    extra_fields = {
        key: value
        for key, value in payload.items()
        if key not in PROFILE_KEYS and key.lower() not in known_lower
    }

    _, name, _, name_anoms = resolve_alias(payload, ["name"])
    anomalies.extend(name_anoms)
    _, entity_type, _, _ = resolve_alias(payload, ["entityType"])
    _, investor_site, _, investor_anoms = resolve_alias(
        payload, ["investorWebsite", "investorwebsite"]
    )
    anomalies.extend(investor_anoms)
    _, fiscal_year_end, _, fiscal_anoms = resolve_alias(
        payload, ["fiscalYearEnd", "FiscalYearEnd"]
    )
    anomalies.extend(fiscal_anoms)

    filings_section = payload.get("filings")
    if filings_section is not None and not isinstance(filings_section, dict):
        add_anomaly(
            anomalies,
            "filings_not_object",
            type(filings_section).__name__,
            "filings",
        )
        filings_section = {}
    if filings_section is None:
        filings_section = {}

    recent = filings_section.get("recent")
    if recent is None:
        recent = {}
        add_anomaly(
            anomalies,
            "recent_missing",
            "filings.recent is absent; treated as zero filings",
            "filings.recent",
        )
    elif not isinstance(recent, dict):
        add_anomaly(
            anomalies,
            "recent_not_object",
            type(recent).__name__,
            "filings.recent",
        )
        recent = {}

    records = zip_filing_arrays(recent, "recent", source_url, anomalies, cik_padded)
    submission_files = normalize_submission_files(
        filings_section.get("files"), anomalies
    )

    historical_records_total = 0
    for source_file, source_section, hist_payload in historical_payloads:
        if not isinstance(hist_payload, dict):
            add_anomaly(
                anomalies,
                "historical_payload_not_object",
                type(hist_payload).__name__,
                source_section,
            )
            continue
        hist_records = zip_filing_arrays(
            hist_payload, source_section, source_file, anomalies, cik_padded
        )
        historical_records_total += len(hist_records)
        records.extend(hist_records)

    records, _duplicates = dedupe_filings(records, anomalies, cik_padded)

    addresses = payload.get("addresses")
    if addresses is not None and not isinstance(addresses, dict):
        add_anomaly(
            anomalies, "addresses_not_object", type(addresses).__name__, "addresses"
        )

    error = "; ".join(historical_errors) if historical_errors else None
    if error and records:
        status = "partial"
    elif error:
        status = "failed"
    else:
        status = "ok"

    row = {
        "cik": cik_padded,
        "snapshot_id": snapshot_id,
        "fetched_at": fetched_at,
        "source_url": source_url,
        "response_sha256": response_sha256,
        "byte_count": byte_count,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "error": error,
        "anomalies": anomalies,
        "extra_fields": canonical_json(extra_fields) if extra_fields else None,
        "identity": {
            "name": name,
            "former_names": normalize_former_names(
                payload.get("formerNames"), anomalies
            ),
        },
        "classification": {
            "entity_type": entity_type,
            "sic_code": payload.get("sic"),
            "sic_description": payload.get("sicDescription"),
            "owner_org": payload.get("ownerOrg"),
            "filer_category": payload.get("category"),
        },
        "identifiers": {"ein": payload.get("ein"), "lei": payload.get("lei")},
        "contact": {
            "phone": payload.get("phone"),
            "website": payload.get("website"),
            "investor_website": investor_site,
            "description": payload.get("description"),
        },
        "incorporation": {
            "state": payload.get("stateOfIncorporation"),
            "state_description": payload.get("stateOfIncorporationDescription"),
        },
        "reporting": {"fiscal_year_end": fiscal_year_end},
        "insider_transactions": {
            "owner_exists": to_bool(payload.get("insiderTransactionForOwnerExists")),
            "issuer_exists": to_bool(payload.get("insiderTransactionForIssuerExists")),
        },
        "addresses": {
            "mailing": normalize_address(
                addresses.get("mailing") if isinstance(addresses, dict) else None,
                anomalies,
                "addresses.mailing",
            ),
            "business": normalize_address(
                addresses.get("business") if isinstance(addresses, dict) else None,
                anomalies,
                "addresses.business",
            ),
        },
        "listings": zip_listings(
            payload.get("tickers"), payload.get("exchanges"), anomalies
        ),
        "filings": records,
        "submission_files": [
            {field: entry.get(field) for field in _SUBMISSION_FILE_FIELDS}
            for entry in submission_files
        ],
        "input_name": input_name,
        "input_fingerprint": input_fingerprint,
        "chunk_id": chunk_id,
        "historical_files_total": len(submission_files),
        "historical_files_failed": len(historical_errors),
        "historical_records_total": historical_records_total,
    }
    validate_row_shapes(row)
    return row


def build_submission_table(rows: list[dict[str, Any]]) -> pa.Table:
    """Assemble normalized row dicts into a schema-conforming Arrow Table."""
    if not rows:
        return SUBMISSION_METADATA_SCHEMA.empty_table()
    for row in rows:
        validate_row_shapes(row)
    return pa.Table.from_pylist(rows, schema=SUBMISSION_METADATA_SCHEMA)
