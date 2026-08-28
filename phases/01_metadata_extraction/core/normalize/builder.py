"""Canonical submission record assembly and schema validation."""

from __future__ import annotations

from typing import Any

from defs.storage import pa

from ..schemas import SCHEMA_VERSION, SUBMISSION_METADATA_SCHEMA
from .filings import (
    dedupe_filings,
    normalize_submission_files,
    zip_filing_arrays,
)
from .helpers import (
    add_anomaly,
    canonical_json,
    resolve_alias,
    to_bool,
)
from .profile import (
    PROFILE_KEYS,
    normalize_address,
    normalize_former_names,
    zip_listings,
)


def validate_row_shapes(row: dict) -> None:
    """Fail fast on values that would not fit the declared Arrow schema."""
    for field in SUBMISSION_METADATA_SCHEMA:
        field_name = field.name
        value = row.get(field_name)
        if value is None:
            continue
        field_type = field.type
        try:
            pa.array([value], type=field_type)
        except (pa.ArrowInvalid, pa.ArrowTypeError, pa.ArrowNotImplementedError) as exc:
            raise ValueError(
                f"row field '{field_name}' does not match schema: {exc}"
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
    """Terminal failed row: one row per requested CIK, including failures,
    so completion can be determined from data rather than queue state."""
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
) -> dict:
    """Build one canonical ``submission_metadata`` row (as a plain dict with
    Arrow-compatible values) from the top-level submissions JSON plus any
    fetched historical payloads.

    ``historical_payloads`` is a list of ``(source_file, source_section,
    payload)`` tuples. ``historical_errors`` carries terminal failures for
    historical files (required inputs, not best effort).
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

    extra_fields: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in PROFILE_KEYS and key.lower() not in {
            p.lower() for p in PROFILE_KEYS
        }:
            extra_fields[key] = value

    _, name, _, name_anoms = resolve_alias(payload, ["name"])
    anomalies.extend(name_anoms)
    _, entity_type, _, _ = resolve_alias(payload, ["entityType"])
    sic = payload.get("sic")
    sic_description = payload.get("sicDescription")
    owner_org = payload.get("ownerOrg")
    filer_category = payload.get("category")

    payload.get("flags")
    _, investor_site, _, investor_anoms = resolve_alias(
        payload, ["investorWebsite", "investorwebsite"]
    )
    anomalies.extend(investor_anoms)
    _, fiscal_year_end, _, fy_anoms = resolve_alias(
        payload, ["fiscalYearEnd", "FiscalYearEnd"]
    )
    anomalies.extend(fy_anoms)

    state = payload.get("stateOfIncorporation")
    state_description = payload.get("stateOfIncorporationDescription")
    phone = payload.get("phone")
    website = payload.get("website")
    description = payload.get("description")
    ein = payload.get("ein")
    lei = payload.get("lei")

    owner_exists = to_bool(payload.get("insiderTransactionForOwnerExists"))
    issuer_exists = to_bool(payload.get("insiderTransactionForIssuerExists"))

    listings = zip_listings(payload.get("tickers"), payload.get("exchanges"), anomalies)
    former_names = normalize_former_names(payload.get("formerNames"), anomalies)

    addresses = payload.get("addresses")
    mailing_raw = addresses.get("mailing") if isinstance(addresses, dict) else None
    business_raw = addresses.get("business") if isinstance(addresses, dict) else None
    if addresses is not None and not isinstance(addresses, dict):
        add_anomaly(
            anomalies, "addresses_not_object", type(addresses).__name__, "addresses"
        )

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
    if not isinstance(recent, dict):
        add_anomaly(
            anomalies, "recent_not_object", type(recent).__name__, "filings.recent"
        )
        recent = {}

    recent_file_url = source_url
    records = zip_filing_arrays(
        recent, "recent", recent_file_url, anomalies, cik_padded
    )

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

    records, _duplicate_count = dedupe_filings(records, anomalies, cik_padded)

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
        "identity": {"name": name, "former_names": former_names},
        "classification": {
            "entity_type": entity_type,
            "sic_code": sic,
            "sic_description": sic_description,
            "owner_org": owner_org,
            "filer_category": filer_category,
        },
        "identifiers": {"ein": ein, "lei": lei},
        "contact": {
            "phone": phone,
            "website": website,
            "investor_website": investor_site,
            "description": description,
        },
        "incorporation": {"state": state, "state_description": state_description},
        "reporting": {"fiscal_year_end": fiscal_year_end},
        "insider_transactions": {
            "owner_exists": owner_exists,
            "issuer_exists": issuer_exists,
        },
        "addresses": {
            "mailing": normalize_address(mailing_raw, anomalies, "addresses.mailing"),
            "business": normalize_address(
                business_raw, anomalies, "addresses.business"
            ),
        },
        "listings": listings,
        "filings": records,
        "submission_files": submission_files,
        "input_name": input_name,
        "input_fingerprint": "",
        "chunk_id": None,
        "historical_files_total": len(submission_files),
        "historical_files_failed": len(historical_errors),
        "historical_records_total": historical_records_total,
    }
    validate_row_shapes(row)
    return row


__all__ = ["normalize_submissions", "validate_row_shapes"]
