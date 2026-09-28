"""Submissions normalizer parity tests.

Expectations are captured golden values from the legacy ``.v1`` normalizer run
against the same committed fixtures. A deviation here is a parity regression,
not a preference change.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.engine.submissions.builder import (
    build_submission_table,
    normalize_submissions,
)
from edgar_sec.engine.submissions.filings import (
    dedupe_filings,
    zip_filing_arrays,
)
from edgar_sec.engine.submissions.helpers import (
    accession_normalized,
    build_archive_url,
    normalize_items,
    resolve_alias,
    to_bool,
    to_int,
)
from edgar_sec.engine.submissions.profile import (
    normalize_address,
    normalize_former_names,
    zip_listings,
)
from tests.support import load_fixture as _load

_GOLDEN = {
    "cik_padded": "0000037996",
    "input_name": "cik_sec_mini.csv",
    "snapshot_id": "snap1",
    "fetched_at": "2026-01-01T00:00:00Z",
    "source_url": "https://data.sec.gov/submissions/CIK0000037996.json",
    "response_sha256": "deadbeef",
    "byte_count": 2033,
}


def _normalize(payload: dict, **overrides: Any) -> dict[str, Any]:
    kwargs = {**_GOLDEN, **overrides}
    return normalize_submissions(payload, **kwargs)


def _anomaly_codes(row: dict[str, Any]) -> set[str]:
    return {anomaly["code"] for anomaly in row["anomalies"]}


# --------------------------------------------------------------------- helpers


def test_accession_normalized_is_lenient() -> None:
    assert accession_normalized("0000037996-26-000039") == "000003799626000039"
    assert accession_normalized(None) is None
    assert accession_normalized("not-an-accession") is None
    assert accession_normalized("123") is None


def test_build_archive_url_uses_unpadded_cik_and_reasons() -> None:
    url, reason = build_archive_url("0000037996", "0000037996-26-000039", "f.htm")
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/37996/000003799626000039/f.htm"
    )
    assert reason is None

    assert build_archive_url("0000037996", "0000037996-26-000039", None)[1] == (
        "primary_document_missing"
    )
    assert build_archive_url("0000037996", None, "f.htm")[0] is None
    assert build_archive_url("0000037996", "0000037996-26-000039", "x.txt")[1] == (
        "primary_document_stub:x.txt"
    )


def test_resolve_alias_matches_case_insensitively() -> None:
    _, value, _, anomalies = resolve_alias(
        {"investorwebsite": "https://x"}, ["investorWebsite", "investorwebsite"]
    )
    assert value == "https://x"
    assert anomalies == []


def test_resolve_alias_flags_conflict() -> None:
    _, value, conflicting, anomalies = resolve_alias(
        {"fiscalYearEnd": "1231", "FiscalYearEnd": "1230"},
        ["fiscalYearEnd", "FiscalYearEnd"],
    )
    assert value == "1231"
    assert conflicting is True
    assert [a["code"] for a in anomalies] == ["alias_conflict"]


def test_to_bool_and_to_int_coercions() -> None:
    assert to_bool(1) is True
    assert to_bool(0) is False
    assert to_bool("") is None
    assert to_bool("false") is False
    assert to_bool(None) is None
    assert to_int(42) == 42
    assert to_int("42") == 42
    assert to_int("x") is None
    assert to_int(True) is None


def test_normalize_items_splits_comma_joined_history() -> None:
    assert normalize_items(["2.02", "9.01"]) == ["2.02", "9.01"]
    assert normalize_items("2.02, 9.01") == ["2.02", "9.01"]
    assert normalize_items(None) == []


def test_zip_listings_pads_and_flags() -> None:
    anomalies: list[dict] = []
    assert zip_listings(["A", "B"], ["NYSE"], anomalies) == [
        {"ticker": "A", "exchange": "NYSE"},
        {"ticker": "B", "exchange": None},
    ]
    assert [a["code"] for a in anomalies] == ["listings_length_mismatch"]


def test_normalize_address_distinguishes_absent_from_empty() -> None:
    assert normalize_address(None, [], "s") is None
    empty = normalize_address({}, [], "s")
    assert empty is not None
    assert all(value is None for value in empty.values())


def test_normalize_former_names_shapes() -> None:
    assert normalize_former_names([["A", "1950-01-01", "1960-01-01"]], []) == [
        {"name": "A", "from_date": "1950-01-01", "to_date": "1960-01-01"}
    ]
    assert normalize_former_names([{"name": "A", "from": "x", "to": "y"}], []) == [
        {"name": "A", "from_date": "x", "to_date": "y"}
    ]


# ------------------------------------------------------------- ragged handling


def test_ragged_columns_pad_to_longest_without_truncation() -> None:
    section = _load("mismatched_arrays.json")["filings"]["recent"]
    anomalies: list[dict] = []
    records = zip_filing_arrays(section, "recent", "u", anomalies, "0000123456")

    assert len(records) == 3
    assert [r["source_array_index"] for r in records] == [0, 1, 2]
    assert records[2]["filing_date"] is None
    assert records[2]["primary_document"] is None
    assert records[2]["archive_url"] is None
    assert {a["code"] for a in anomalies} == {
        "filing_array_length_mismatch",
        "primary_document_missing",
    }


def test_dedupe_keeps_first_occurrence_and_flags_conflicts() -> None:
    base = {
        "accession_number": "0000037996-08-000010",
        "accession_number_normalized": "000003799608000010",
        "form": "10-Q",
        "filing_date": "2008-01-03",
        "report_date": "2007-09-30",
        "primary_document": "a.htm",
    }
    conflict = {**base, "form": "10-K"}
    anomalies: list[dict] = []

    kept, duplicates = dedupe_filings([base, dict(base), conflict], anomalies, "cik")
    assert len(kept) == 1
    assert kept[0]["form"] == "10-Q"
    assert duplicates == 2
    assert [a["code"] for a in anomalies] == ["accession_conflict"]


# ---------------------------------------------------------- full-row goldens


def test_recent_with_history_matches_oracle_golden() -> None:
    recent = _load("recent_submissions.json")
    historical = _load("historical_submissions.json")
    row = _normalize(
        recent,
        byte_count=len(json.dumps(recent)),
        historical_payloads=[
            (
                "CIK0000037996-submissions-001.json",
                "historical",
                historical,
            )
        ],
        historical_errors=[],
    )

    assert row["status"] == "ok"
    assert row["error"] is None
    assert row["anomalies"] == []

    assert [f["accession_number"] for f in row["filings"]] == [
        "0000037996-26-000039",
        "0000037996-26-000031",
        "0000037996-08-000010",
        "0000037996-08-000004",
    ]
    assert [f["filing_date"] for f in row["filings"]] == [
        "2026-02-05",
        "2026-01-28",
        "2008-01-03",
        "2008-01-02",
    ]
    assert row["filings"][0]["archive_url"] == (
        "https://www.sec.gov/Archives/edgar/data/37996/"
        "000003799626000039/f-20251231.htm"
    )

    assert len(row["listings"]) == 4
    assert row["listings"][0] == {"ticker": "F", "exchange": "NYSE"}
    assert row["identity"]["former_names"] == [
        {"name": "FORD MOTOR CO", "from_date": "1950-01-01", "to_date": "1960-01-01"}
    ]
    assert row["extra_fields"] is None
    assert row["submission_files"] == [
        {
            "name": "CIK0000037996-submissions-001.json",
            "filing_count": 2009,
            "filing_from": "2008-01-03",
            "filing_to": "2019-05-19",
        }
    ]
    assert row["historical_files_total"] == 1
    assert row["historical_files_failed"] == 0
    assert row["historical_records_total"] == 3

    assert row["identity"]["name"] == "FORD MOTOR CO"
    assert row["classification"]["sic_code"] == "3711"
    assert row["classification"]["filer_category"] == "Large accelerated filer"
    assert row["incorporation"]["state"] == "DE"
    assert row["reporting"]["fiscal_year_end"] == "1231"
    assert row["insider_transactions"] == {
        "owner_exists": True,
        "issuer_exists": True,
    }
    assert row["addresses"]["mailing"]["city"] == "Dearborn"
    assert row["addresses"]["mailing"]["is_foreign_location"] is False
    assert row["addresses"]["business"] is not None
    assert row["identifiers"]["ein"] == "380549190"


def test_empty_contact_strings_are_preserved_not_nulled() -> None:
    recent = _load("recent_submissions.json")
    row = _normalize(recent, historical_payloads=[], historical_errors=[])
    assert row["contact"]["website"] == ""
    assert row["contact"]["investor_website"] == ""
    assert row["contact"]["description"] == ""


def test_mismatched_payload_row_matches_oracle_golden() -> None:
    row = _normalize(
        _load("mismatched_arrays.json"),
        cik_padded="0000123456",
        historical_payloads=[],
        historical_errors=[],
    )
    assert row["status"] == "ok"
    assert len(row["filings"]) == 3
    assert _anomaly_codes(row) == {
        "filing_array_length_mismatch",
        "primary_document_missing",
    }


def test_missing_recent_is_ok_with_anomaly_not_partial() -> None:
    row = _normalize(
        {"name": "NO FILINGS CO"}, historical_payloads=[], historical_errors=[]
    )
    assert row["status"] == "ok"
    assert row["filings"] == []
    assert "recent_missing" in _anomaly_codes(row)


def test_status_is_partial_with_records_and_failed_without() -> None:
    recent = _load("recent_submissions.json")
    partial = _normalize(
        recent, historical_payloads=[], historical_errors=["CIK-x.json: HTTP 404"]
    )
    assert partial["status"] == "partial"
    assert partial["error"] == "CIK-x.json: HTTP 404"

    failed = _normalize(
        {"name": "EMPTY CO"},
        historical_payloads=[],
        historical_errors=["CIK-y.json: HTTP 404"],
    )
    assert failed["status"] == "failed"


def test_non_dict_payload_yields_full_shape_failed_row() -> None:
    row = _normalize([], historical_payloads=[], historical_errors=[])
    assert row["status"] == "failed"
    assert row["error"] == "payload is not a JSON object"
    for field in SUBMISSION_METADATA_SCHEMA.names:
        assert field in row


# ------------------------------------------------------------- arrow assembly


def test_build_submission_table_conforms_to_canonical_schema() -> None:
    recent = _load("recent_submissions.json")
    row = _normalize(recent, historical_payloads=[], historical_errors=[])
    table = build_submission_table([row])

    assert table.schema.equals(SUBMISSION_METADATA_SCHEMA)
    assert table.num_rows == 1
    assert table.column("cik")[0].as_py() == "0000037996"


def test_build_submission_table_preserves_row_order() -> None:
    rows = [
        _normalize(
            {"name": f"CO {index}"},
            cik_padded=f"000000000{index}",
            historical_payloads=[],
            historical_errors=[],
        )
        for index in (3, 1, 2)
    ]
    table = build_submission_table(rows)
    assert [cik.as_py() for cik in table.column("cik")] == [
        "0000000003",
        "0000000001",
        "0000000002",
    ]


def test_build_submission_table_empty_input() -> None:
    table = build_submission_table([])
    assert table.num_rows == 0
    assert table.schema.equals(SUBMISSION_METADATA_SCHEMA)


def test_validate_row_shapes_rejects_incompatible_value() -> None:
    from edgar_sec.engine.submissions.builder import validate_row_shapes

    row = _normalize({"name": "CO"}, historical_payloads=[], historical_errors=[])
    row["byte_count"] = "not-an-int"
    with pytest.raises(ValueError, match="byte_count"):
        validate_row_shapes(row)
