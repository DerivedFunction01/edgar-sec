import json
from pathlib import Path

from conftest import imp

normalize = imp("phases.01_metadata_extraction.core.normalize")

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def base_kwargs(cik="0000037996", **overrides):
    kwargs = {
        "cik_padded": cik,
        "input_name": "FORD",
        "snapshot_id": "snap-1",
        "fetched_at": "2026-08-27T00:00:00Z",
        "source_url": f"https://data.sec.gov/submissions/CIK{cik}.json",
        "byte_count": 1234,
        "historical_payloads": [],
        "historical_errors": [],
        "response_sha256": "deadbeef",
    }
    kwargs.update(overrides)
    return kwargs


def test_profile_structs_and_alias_casing():
    row = normalize.normalize_submissions(
        load("recent_submissions.json"), **base_kwargs()
    )
    assert row["status"] == "ok"
    assert row["identity"]["name"] == "FORD MOTOR CO"
    assert row["classification"]["sic_code"] == "3711"
    assert row["classification"]["filer_category"] == "Large accelerated filer"
    assert row["reporting"]["fiscal_year_end"] == "1231"
    assert row["contact"]["investor_website"] == ""
    assert row["incorporation"]["state"] == "DE"
    assert row["identifiers"]["ein"] == "380549190"
    assert row["identifiers"]["lei"] is None  # null preserved, not coerced
    assert row["contact"]["description"] == ""  # empty string preserved
    assert row["insider_transactions"] == {"owner_exists": True, "issuer_exists": True}


def test_former_names_from_array_form():
    row = normalize.normalize_submissions(
        load("recent_submissions.json"), **base_kwargs()
    )
    assert row["identity"]["former_names"] == [
        {"name": "FORD MOTOR CO", "from_date": "1950-01-01", "to_date": "1960-01-01"}
    ]


def test_addresses_supplied_but_empty_vs_missing():
    row = normalize.normalize_submissions(
        load("recent_submissions.json"), **base_kwargs()
    )
    # business is supplied but empty: all-null struct, not None
    assert row["addresses"]["business"] is not None
    assert row["addresses"]["business"]["city"] is None
    # mailing is fully supplied
    assert row["addresses"]["mailing"]["city"] == "Dearborn"

    payload = load("recent_submissions.json")
    del payload["addresses"]["mailing"]
    row2 = normalize.normalize_submissions(payload, **base_kwargs())
    assert row2["addresses"]["mailing"] is None  # not supplied


def test_listings_zip_preserves_duplicates_and_order():
    row = normalize.normalize_submissions(
        load("recent_submissions.json"), **base_kwargs()
    )
    assert row["listings"] == [
        {"ticker": "F", "exchange": "NYSE"},
        {"ticker": "F-PB", "exchange": "NYSE"},
        {"ticker": "F-PC", "exchange": "NYSE"},
        {"ticker": "F-PD", "exchange": "NYSE"},
    ]


def test_listings_length_mismatch_pads_with_null_and_flags():
    payload = load("recent_submissions.json")
    payload["tickers"] = ["F", "F-PB", "F-PC", "F-PD", "F-PE"]
    row = normalize.normalize_submissions(payload, **base_kwargs())
    assert row["listings"][4] == {"ticker": "F-PE", "exchange": None}
    codes = {a["code"] for a in row["anomalies"]}
    assert "listings_length_mismatch" in codes


def test_filings_are_zipped_records_with_provenance():
    row = normalize.normalize_submissions(
        load("recent_submissions.json"), **base_kwargs()
    )
    assert len(row["filings"]) == 2
    first = row["filings"][0]
    assert first["accession_number"] == "0000037996-26-000039"
    assert first["accession_number_normalized"] == "000003799626000039"
    assert first["form"] == "10-K"
    assert first["items"] == ["10-K"]
    assert first["is_xbrl"] is True
    assert first["size"] == 3380161
    assert first["source_section"] == "recent"
    assert first["source_array_index"] == 0
    assert first["archive_url"] == (
        "https://www.sec.gov/Archives/edgar/data/37996/000003799626000039/f-20251231.htm"
    )


def test_items_string_is_split():
    row = normalize.normalize_submissions(
        load("recent_submissions.json"), **base_kwargs()
    )
    assert row["filings"][1]["items"] == ["2.02", "9.01"]


def test_empty_recent_is_successful_zero_filings():
    payload = load("recent_submissions.json")
    payload["filings"] = {
        "recent": {
            "accessionNumber": [],
            "filingDate": [],
            "reportDate": [],
            "acceptanceDateTime": [],
            "act": [],
            "form": [],
            "fileNumber": [],
            "filmNumber": [],
            "items": [],
            "core_type": [],
            "size": [],
            "isXBRL": [],
            "isInlineXBRL": [],
            "isXBRLNumeric": [],
            "primaryDocument": [],
            "primaryDocDescription": [],
        },
        "files": [],
    }
    row = normalize.normalize_submissions(payload, **base_kwargs())
    assert row["status"] == "ok"
    assert row["filings"] == []


def test_historical_records_combined_with_source_provenance():
    historical = load("historical_submissions.json")
    row = normalize.normalize_submissions(
        load("recent_submissions.json"),
        **base_kwargs(
            historical_payloads=[
                (
                    "https://data.sec.gov/submissions/CIK0000037996-submissions-001.json",
                    "CIK0000037996-submissions-001.json",
                    historical,
                )
            ]
        ),
    )
    sections = [f["source_section"] for f in row["filings"]]
    assert sections.count("recent") == 2
    assert sections.count("CIK0000037996-submissions-001.json") == 2
    historical_record = row["filings"][2]
    assert historical_record["form"] == "10-Q"
    assert historical_record["filing_date"] == "2008-01-03"
    assert row["submission_files"] == [
        {
            "name": "CIK0000037996-submissions-001.json",
            "filing_count": 2009,
            "filing_from": "2008-01-03",
            "filing_to": "2019-05-19",
            "url": "https://data.sec.gov/submissions/CIK0000037996-submissions-001.json",
        }
    ]
    assert row["historical_records_total"] == 3


def test_duplicate_accessions_deduped_and_conflicts_flagged():
    row = normalize.normalize_submissions(
        load("recent_submissions.json"),
        **base_kwargs(
            historical_payloads=[
                ("url", "hist.json", load("historical_submissions.json"))
            ]
        ),
    )
    # historical fixture repeats accession 0000037996-08-000010 with identical content
    normalized = [f["accession_number_normalized"] for f in row["filings"]]
    assert len(normalized) == len(set(normalized))
    assert row["historical_records_total"] == 3  # before dedupe


def test_conflicting_duplicate_metadata_is_flagged():
    historical = load("historical_submissions.json")
    historical["form"] = ["10-Q", "10-K", "99-CHANGED"]
    row = normalize.normalize_submissions(
        load("recent_submissions.json"),
        **base_kwargs(historical_payloads=[("url", "hist.json", historical)]),
    )
    codes = {a["code"] for a in row["anomalies"]}
    assert "accession_conflict" in codes


def test_mismatched_array_lengths_never_truncate():
    row = normalize.normalize_submissions(
        load("mismatched_arrays.json"), **base_kwargs(cik="0000123456")
    )
    codes = {a["code"] for a in row["anomalies"]}
    assert "filing_array_length_mismatch" in codes
    assert len(row["filings"]) == 3  # longest array wins, shorter sides null
    missing_doc = row["filings"][2]
    assert missing_doc["primary_document"] is None
    assert missing_doc["archive_url"] is None
    detail = next(
        a for a in row["anomalies"] if a["code"] == "filing_array_length_mismatch"
    )
    assert "primaryDocument" in detail["detail"]


def test_primary_document_missing_is_recorded_not_guessed():
    payload = load("recent_submissions.json")
    payload["filings"]["recent"]["primaryDocument"] = [None, ""]
    row = normalize.normalize_submissions(payload, **base_kwargs())
    assert row["filings"][0]["archive_url"] is None
    codes = {a["code"] for a in row["anomalies"]}
    assert "primary_document_missing" in codes


def test_stub_primary_document_recorded_with_reason():
    payload = load("recent_submissions.json")
    payload["filings"]["recent"]["primaryDocument"] = [
        "000003799626000039.txt",
        "b.htm",
    ]
    row = normalize.normalize_submissions(payload, **base_kwargs())
    codes = {a["code"] for a in row["anomalies"]}
    assert "primary_document_stub" in codes
    assert row["filings"][0]["primary_document"] == "000003799626000039.txt"


def test_unknown_top_level_keys_captured_in_extra_fields():
    payload = load("recent_submissions.json")
    payload["someFutureField"] = {"a": 1}
    row = normalize.normalize_submissions(payload, **base_kwargs())
    extra = json.loads(row["extra_fields"])
    assert extra["someFutureField"] == {"a": 1}


def test_alias_conflict_flagged_not_silently_chosen():
    payload = load("recent_submissions.json")
    payload["FiscalYearEnd"] = "0630"
    row = normalize.normalize_submissions(payload, **base_kwargs())
    conflicts = [a for a in row["anomalies"] if a["code"] == "alias_conflict"]
    assert conflicts and "0630" in conflicts[0]["detail"]


def test_historical_error_marks_row_partial():
    row = normalize.normalize_submissions(
        load("recent_submissions.json"),
        **base_kwargs(
            historical_errors=["CIK0000037996-submissions-001.json: status 503"]
        ),
    )
    assert row["status"] == "partial"
    assert row["historical_files_failed"] == 1
    assert "status 503" in row["error"]


def test_empty_payload_without_error_is_zero_filing_ok():
    row = normalize.normalize_submissions({}, **base_kwargs())
    assert row["status"] == "ok"
    assert row["filings"] == []


def test_failed_row_is_terminal_with_error():
    row = normalize.normalize_submissions(
        {},
        **base_kwargs(
            historical_errors=["CIK0000000001-submissions-001.json: retries exhausted"],
        ),
    )
    assert row["status"] == "failed"
    assert "retries exhausted" in row["error"]
