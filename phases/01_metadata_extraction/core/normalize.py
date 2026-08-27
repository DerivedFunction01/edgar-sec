"""Pure normalization of SEC submissions JSON into the canonical row shape.

Deterministic, network-free functions. Rules implemented here:

- Known field-name aliases are matched case-insensitively
  (``investorWebsite``/``investorwebsite``, ``fiscalYearEnd``/``FiscalYearEnd``,
  and historical descriptor casing). Original key spellings are recorded and
  conflicting aliases are flagged instead of silently choosing one.
- ``tickers``/``exchanges`` are zipped by index into ``listings``; a length
  mismatch emits a listing with a null missing side plus a schema anomaly and
  never silently truncates either array.
- All filing-history arrays are validated to have equal lengths. On a
  mismatch, available values are emitted by index, the record is flagged with
  a schema anomaly, and the source array lengths are stored in the anomaly
  detail. Never silently truncated to the shortest array.
- An empty ``filings.recent`` object is a successful zero-filing result, not
  a fetch failure.
- List order and null-vs-empty distinctions are preserved: ``""``, ``null``,
  ``{}``, and ``[]`` are not coerced into one value.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pyarrow as pa

from .schemas import SCHEMA_VERSION, SUBMISSION_METADATA_SCHEMA

SEC_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"
SEC_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"

ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")

# Top-level keys consumed into modeled columns. Everything else lands in
# extra_fields so recognized-but-not-yet-modeled or unknown keys survive.
PROFILE_KEYS = {
    "cik",
    "entityType",
    "sic",
    "sicDescription",
    "ownerOrg",
    "insiderTransactionForOwnerExists",
    "insiderTransactionForIssuerExists",
    "name",
    "tickers",
    "exchanges",
    "ein",
    "lei",
    "description",
    "website",
    "investorWebsite",
    "category",
    "fiscalYearEnd",
    "stateOfIncorporation",
    "stateOfIncorporationDescription",
    "phone",
    "flags",
    "formerNames",
    "addresses",
    "filings",
}

ADDRESS_KEYS = [
    "street1",
    "street2",
    "city",
    "stateOrCountry",
    "zipCode",
    "stateOrCountryDescription",
    "country",
    "countryCode",
    "foreignStateTerritory",
    "isForeignLocation",
]

FILING_ARRAY_KEYS = [
    "accessionNumber",
    "filingDate",
    "reportDate",
    "acceptanceDateTime",
    "act",
    "form",
    "fileNumber",
    "filmNumber",
    "items",
    "core_type",
    "size",
    "isXBRL",
    "isInlineXBRL",
    "isXBRLNumeric",
    "primaryDocument",
    "primaryDocDescription",
]

_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def address_field(raw_key: str) -> str:
    """Map an SEC address key to its canonical snake_case field name."""
    return _CAMEL_BOUNDARY_RE.sub("_", raw_key).lower()


def add_anomaly(
    anomalies: list[dict], code: str, detail: str, source: str = ""
) -> None:
    anomalies.append({"code": code, "detail": detail, "source": source})


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def resolve_alias(
    payload: dict, aliases: list[str]
) -> tuple[str | None, Any | None, bool, list[dict]]:
    """Resolve case-insensitive known aliases.

    Returns (canonical_key, value, conflicting, anomalies). Conflicting
    aliases with different values are flagged, never silently chosen.
    """
    anomalies: list[dict] = []
    matches = [key for key in payload if key.lower() in {a.lower() for a in aliases}]
    if not matches:
        return (aliases[0], None, False, anomalies)
    canonical = next((a for a in aliases if a in matches), matches[0])
    value = payload[canonical]
    conflicting = False
    for other in matches:
        if other != canonical and payload[other] != value:
            conflicting = True
            anomalies.append(
                {
                    "code": "alias_conflict",
                    "detail": f"{canonical}={value!r} conflicts with {other}={payload[other]!r}",
                    "source": ",".join(matches),
                }
            )
    return canonical, value, conflicting, anomalies


def normalize_cik_padded(raw: Any) -> str:
    text = str(raw or "").strip()
    digits = text.zfill(10)
    return digits


def accession_normalized(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().replace("-", "")
    if not text.isdigit() or len(text) != 18:
        return None
    return text


def build_archive_url(
    cik_padded: str, accession_raw: str | None, primary_document: str | None
) -> tuple[str | None, str | None]:
    """Derive the archive URL from CIK, accession, and primary document.

    Returns (url, fallback_reason). A filing record must survive even when
    ``primaryDocument`` is null or an unusual stub; the raw API value is
    retained on the record and any fallback selection is explained by the
    returned reason instead of being applied silently.
    """
    accession_norm = accession_normalized(accession_raw)
    if accession_norm is None:
        return None, f"invalid accession {accession_raw!r}"
    cik_int = str(int(cik_padded))
    if not primary_document or not str(primary_document).strip():
        return None, "primary_document_missing"
    doc = str(primary_document).strip()
    url = f"{SEC_ARCHIVE_BASE}/{cik_int}/{accession_norm}/{doc}"
    if doc.endswith((".txt", "0001.htm")):
        return url, f"primary_document_stub:{doc}"
    return url, None


def zip_listings(tickers: Any, exchanges: Any, anomalies: list[dict]) -> list[dict]:
    """Zip tickers and exchanges by index, preserving order and duplicate
    exchange values. Length mismatches keep the longer side with a null."""
    tickers = tickers if isinstance(tickers, list) else []
    exchanges = exchanges if isinstance(exchanges, list) else []
    if len(tickers) != len(exchanges):
        add_anomaly(
            anomalies,
            "listings_length_mismatch",
            f"tickers={len(tickers)} exchanges={len(exchanges)}; missing side padded with null",
            "tickers/exchanges",
        )
    listings = []
    for index in range(max(len(tickers), len(exchanges))):
        ticker = tickers[index] if index < len(tickers) else None
        exchange = exchanges[index] if index < len(exchanges) else None
        listings.append({"ticker": ticker, "exchange": exchange})
    return listings


def normalize_address(value: Any, anomalies: list[dict], source: str) -> dict | None:
    """Normalize one address object. A missing key yields None; an empty
    object yields an all-null struct so 'not supplied' stays distinct from
    'supplied but empty'. ``isForeignLocation`` is coerced with ``to_bool``
    like the filing-history booleans."""
    if value is None:
        return None
    if not isinstance(value, dict):
        add_anomaly(
            anomalies,
            "address_not_object",
            f"unexpected type {type(value).__name__}",
            source,
        )
        return None
    unknown = [key for key in value if key not in ADDRESS_KEYS]
    if unknown:
        add_anomaly(
            anomalies,
            "unknown_address_keys",
            canonical_json(sorted(unknown)),
            source,
        )
    out = {}
    for raw_key in ADDRESS_KEYS:
        out[address_field(raw_key)] = value.get(raw_key)
    out["is_foreign_location"] = to_bool(out["is_foreign_location"])
    return out


def normalize_former_names(value: Any, anomalies: list[dict]) -> list[dict]:
    """Normalize formerNames. SEC uses arrays of [name, from, to]; objects
    are accepted defensively. Unknown shapes are flagged, not dropped."""
    if value is None:
        return []
    if not isinstance(value, list):
        add_anomaly(
            anomalies, "former_names_not_list", type(value).__name__, "formerNames"
        )
        return []
    out = []
    for index, entry in enumerate(value):
        if isinstance(entry, (list, tuple)):
            parts = list(entry) + [None] * (3 - len(entry))
            out.append({"name": parts[0], "from_date": parts[1], "to_date": parts[2]})
        elif isinstance(entry, dict):
            out.append(
                {
                    "name": entry.get("name"),
                    "from_date": entry.get("from"),
                    "to_date": entry.get("to"),
                }
            )
        else:
            add_anomaly(
                anomalies,
                "former_names_entry",
                canonical_json(entry)[:200],
                f"formerNames[{index}]",
            )
            out.append({"name": entry, "from_date": None, "to_date": None})
    return out


def normalize_items(value: Any) -> list[str]:
    """SEC provides items as a list of codes in recent history but some
    historical files use comma-joined strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value)]


def to_bool(value: Any) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0", ""):
            return False if lowered else None
    return None


def to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def zip_filing_arrays(
    section: dict,
    source_section: str,
    source_file: str,
    anomalies: list[dict],
    cik_padded: str = "",
) -> list[dict]:
    """Zip one SEC filing-history column-oriented array set into record
    objects, one per index.

    Equal array lengths are validated first; on a mismatch the available
    values are emitted by index with null padding, a schema anomaly records
    the source array lengths, and no array is silently truncated.
    """
    lengths = {}
    for key in FILING_ARRAY_KEYS:
        value = section.get(key)
        lengths[key] = len(value) if isinstance(value, list) else 0
    distinct = set(lengths.values())
    mismatch = len(distinct) > 1

    unknown = [key for key in section if key not in FILING_ARRAY_KEYS]
    if unknown:
        add_anomaly(
            anomalies,
            "unknown_filing_array_keys",
            canonical_json(sorted(unknown)),
            source_section,
        )

    if mismatch:
        add_anomaly(
            anomalies,
            "filing_array_length_mismatch",
            canonical_json(lengths),
            source_section,
        )

    records: list[dict] = []
    row_count = max(lengths.values()) if lengths else 0
    for index in range(row_count):

        def pick(key: str, _index: int = index) -> Any:
            values = section.get(key)
            if not isinstance(values, list) or _index >= len(values):
                return None
            return values[_index]

        accession_raw = pick("accessionNumber")
        primary_document = pick("primaryDocument")
        archive_url, fallback_reason = build_archive_url(
            cik_padded, accession_raw, primary_document
        )
        record = {
            "accession_number": accession_raw,
            "accession_number_normalized": accession_normalized(accession_raw),
            "filing_date": pick("filingDate"),
            "report_date": pick("reportDate"),
            "acceptance_datetime": pick("acceptanceDateTime"),
            "act": pick("act"),
            "form": pick("form"),
            "file_number": pick("fileNumber"),
            "film_number": pick("filmNumber"),
            "items": normalize_items(pick("items")),
            "core_type": pick("core_type"),
            "size": to_int(pick("size")),
            "is_xbrl": to_bool(pick("isXBRL")),
            "is_inline_xbrl": to_bool(pick("isInlineXBRL")),
            "is_xbrl_numeric": to_bool(pick("isXBRLNumeric")),
            "primary_document": primary_document,
            "primary_doc_description": pick("primaryDocDescription"),
            "archive_url": archive_url,
            "source_section": source_section,
            "source_file": source_file,
            "source_array_index": index,
        }
        if fallback_reason:
            add_anomaly(
                anomalies,
                fallback_reason.split(":")[0],
                f"index {index}: {fallback_reason}",
                f"{source_section}#{accession_raw}",
            )
        if mismatch and record["accession_number_normalized"] is None:
            add_anomaly(
                anomalies,
                "accession_unusable",
                f"index {index}: accession {accession_raw!r} is not a valid SEC accession",
                source_section,
            )
        records.append(record)
    return records


def dedupe_filings(
    records: list[dict], anomalies: list[dict], source: str
) -> tuple[list[dict], int]:
    """Deduplicate by normalized accession and detect conflicting metadata
    rather than silently choosing an arbitrary row. First occurrence wins;
    duplicates with identical content are dropped quietly, conflicts are
    recorded. Returns (unique_records, duplicate_count)."""
    seen: dict[str, dict] = {}
    out: list[dict] = []
    duplicates = 0
    for record in records:
        key = record.get("accession_number_normalized")
        if key is None:
            out.append(record)  # unusable accessions are kept and flagged upstream
            continue
        existing = seen.get(key)
        if existing is None:
            seen[key] = record
            out.append(record)
            continue
        duplicates += 1
        comparable = ("form", "filing_date", "report_date", "primary_document")
        differing = {
            field: (existing.get(field), record.get(field))
            for field in comparable
            if existing.get(field) != record.get(field)
        }
        if differing:
            add_anomaly(
                anomalies,
                "accession_conflict",
                canonical_json(differing),
                f"{source}#{key}",
            )
    return out, duplicates


def normalize_submission_files(files: Any, anomalies: list[dict]) -> list[dict]:
    """Normalize the historical submissions-file descriptors, handling the
    case variants FilingCount/FilingFrom/FilingTo."""
    if files is None:
        return []
    if not isinstance(files, list):
        add_anomaly(anomalies, "files_not_list", type(files).__name__, "filings.files")
        return []
    aliases = {
        "name": ["name"],
        "filing_count": ["FilingCount", "filingCount"],
        "filing_from": ["FilingFrom", "filingFrom"],
        "filing_to": ["FilingTo", "filingTo"],
    }
    out = []
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            add_anomaly(
                anomalies,
                "file_descriptor_not_object",
                canonical_json(entry)[:200],
                f"filings.files[{index}]",
            )
            continue
        record = {}
        for field, keys in aliases.items():
            values = [entry[key] for key in keys if key in entry]
            if not values:
                record[field] = None
            else:
                record[field] = values[0]
                if any(v != values[0] for v in values):
                    add_anomaly(
                        anomalies,
                        "alias_conflict",
                        f"{field}: {canonical_json(values)}",
                        f"filings.files[{index}]",
                    )
        record["filing_count"] = to_int(record["filing_count"])
        record["url"] = (
            f"{SEC_SUBMISSIONS_BASE}/{record['name']}" if record["name"] else None
        )
        out.append(record)
    return out


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


def sha256_of(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


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
