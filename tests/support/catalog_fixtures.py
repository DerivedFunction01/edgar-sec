"""Authored filing-catalog fixtures, generated at resolve time.

The sample submission metadata and its expected outputs are authored
here as row data; tests/support materializes them into a temp dir.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import tempfile
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.foundation.runtime.settings.parquet import DEFAULT_ROW_GROUP_SIZE

GENERATED_CATALOG_FIXTURES = (
    "cik_sample.csv",
    "expected_company_profiles.csv",
    "expected_filing_targets.csv",
    "sample_submission_metadata.parquet",
)

CIK_SAMPLE = (
    ("0000320193", "APPLE FIXTURE INC"),
    ("0000789019", "MICROSOFT FIXTURE CORP"),
    ("0001326801", "META FIXTURE PLATFORMS"),
    ("0001652044", "ALPHABET FIXTURE INC"),
    ("0001045810", "NVIDIA FIXTURE CORP"),
    ("0000019617", "JPMORGAN FIXTURE CHASE"),
)

# Filing spec: accession, filing_date, report_date, form, size, xbrl
# (True/False for all three flags, None for all null), primary document.
_APPLE_FILINGS = (
    (
        "0000320193-23-000106",
        "2023-11-03",
        "2023-09-30",
        "10-K",
        91234,
        True,
        "aapl-20230930.htm",
    ),
    (
        "0000320193-24-000021",
        "2024-02-02",
        "2023-12-30",
        "10-Q",
        None,
        None,
        "aapl-20231230.htm",
    ),
    (
        "0000320193-24-000099",
        "2024-05-10",
        "",
        "8-K",
        4096,
        False,
        "form8k20240510.htm",
    ),
    ("0000320193-24-000077", "2024-04-11", "", "8-K", 2048, False, None),
)
_MICROSOFT_FILINGS = (
    (
        "0000320193-23-000106",
        "2023-11-03",
        "2023-06-30",
        "10-K",
        88123,
        True,
        "msft-20230630.htm",
    ),
    ("0000320193-24-000077", "2024-04-11", "", "8-K", 2048, False, None),
)
_META_FILINGS = (
    (
        "0001326801-24-000010",
        "2024-03-08",
        "",
        "10-K/A",
        99001,
        True,
        "meta-20231231.htm",
    ),
    (
        "0001326801-24-000011",
        "2024-05-16",
        "",
        "10-KT",
        77002,
        True,
        "meta-transition-20231231.htm",
    ),
    (
        "0001326801-99-000012",
        "1999-06-01",
        "",
        "10-KSB",
        55003,
        None,
        "meta-sb-1998.htm",
    ),
    (
        "0001326801-24-000013",
        "2024-06-11",
        "",
        "8-K/A",
        33004,
        None,
        "form8ka20240611.htm",
    ),
)
_ALPHABET_FILINGS = (
    ("0001652044-24-000030", "2024-02-07", "2023-12-31", "10-K", None, True, None),
    ("0001652044-24-000031", "2024-04-25", "2024-03-31", "10-Q", 12005, True, "   "),
)
_JPM_FILINGS = (
    (
        "0000019617-24-000040",
        "2024-02-29",
        "2023-12-31",
        "10-K",
        66006,
        True,
        "jpm-20231231.htm",
    ),
)


def _missing(index: int, source: str) -> dict[str, str]:
    return {
        "code": "primary_document_missing",
        "detail": f"index {index}: primary_document_missing",
        "source": source,
    }


# Row spec: cik, name, status, error, response sha256, input fingerprint,
# fetched_at, input_name, historical files failed, anomalies, filings.
_SAMPLE_ROWS = (
    (
        "0000320193",
        "APPLE FIXTURE INC",
        "ok",
        None,
        "2868c13af99c02ee73164889411a55e30926673596d33928a7e2f1043fcf6295",
        "4976cf1be0d7c3229ebed720ea60229841b437714e497e82f456de74f33eaf29",
        "2026-03-01T00:00:00Z",
        "cik_sample.csv",
        0,
        (_missing(3, "recent#0000320193-24-000077"),),
        _APPLE_FILINGS,
    ),
    (
        "0000789019",
        "MICROSOFT FIXTURE CORP",
        "ok",
        None,
        "13667654f1236bbeedd9c681329b1c3f9c9f9f778e89b4ae68e7047be1c3a9b0",
        "0ed509daa8de1678ec623c44adf0a7d00f3746f005a6426e937cd756be0ff779",
        "2026-03-01T00:00:00Z",
        "cik_sample.csv",
        0,
        (_missing(1, "recent#0000320193-24-000077"),),
        _MICROSOFT_FILINGS,
    ),
    (
        "0001326801",
        "META FIXTURE PLATFORMS",
        "ok",
        None,
        "df03141ca407a0b69607ffd35ef96c82a853957461469f7b7892bf930739771a",
        "2f94f666bcef608ef76acbf113b8d56d4302da19a3ed5631e3e6c892c6a9df47",
        "2026-03-01T00:00:00Z",
        "cik_sample.csv",
        0,
        (),
        _META_FILINGS,
    ),
    (
        "0001652044",
        "ALPHABET FIXTURE INC",
        "ok",
        None,
        "30f1be94180e82d80805fa3167a5b9e50b37998ee1b4b86d252f27c207c2217e",
        "80be9ec1c3ef08d139f3c2d3abbcc9fd1687267a7b0937fe98bea5b4eaee0b21",
        "2026-03-01T00:00:00Z",
        "cik_sample.csv",
        0,
        (
            _missing(0, "recent#0001652044-24-000030"),
            _missing(1, "recent#0001652044-24-000031"),
        ),
        _ALPHABET_FILINGS,
    ),
    (
        "0001045810",
        None,
        "failed",
        "payload is not a JSON object",
        "",
        "",
        "2026-03-01T00:00:00Z",
        "cik_sample.csv",
        0,
        (),
        (),
    ),
    (
        "0000019617",
        "JPMORGAN FIXTURE CHASE",
        "partial",
        "CIK0000019617-submissions-002.json: HTTP 404",
        "992a08baf05063f72e22d50ee1cb3fdd78239bdcac779e5357dfbf39361c8898",
        "979c33bfff7892b4922b42b0fe6567c787d1388d90b376dc97745bce3c5d88bb",
        "2026-03-01T00:00:00Z",
        "cik_sample.csv",
        1,
        (),
        _JPM_FILINGS,
    ),
    (
        "0000320193",
        "APPLE FIXTURE INC",
        "ok",
        None,
        "2868c13af99c02ee73164889411a55e30926673596d33928a7e2f1043fcf6295",
        "60bb38bb7753435c32ac12658f8c42c2fc4e48c167308270775b813f80563f43",
        "2026-03-08T00:00:00Z",
        "cik_sample.csv#2026-03-08",
        0,
        (_missing(3, "recent#0000320193-24-000077"),),
        _APPLE_FILINGS,
    ),
)

_EXPECTED_PROFILES_CSV = """\
cik,snapshot_id,fetched_at,input_name,input_fingerprint,status,entity_name,sic_code,entity_type,state_of_incorporation,listing_count,filing_count,profile_schema_version
0000019617,catalog-fixture-0001,2026-03-01T00:00:00Z,cik_sample.csv,979c33bfff7892b4922b42b0fe6567c787d1388d90b376dc97745bce3c5d88bb,partial,JPMORGAN FIXTURE CHASE,3571,operating,DE,1,1,1.0.0
0000320193,catalog-fixture-0001,2026-03-08T00:00:00Z,cik_sample.csv#2026-03-08,60bb38bb7753435c32ac12658f8c42c2fc4e48c167308270775b813f80563f43,ok,APPLE FIXTURE INC,3571,operating,DE,1,4,1.0.0
0000789019,catalog-fixture-0001,2026-03-01T00:00:00Z,cik_sample.csv,0ed509daa8de1678ec623c44adf0a7d00f3746f005a6426e937cd756be0ff779,ok,MICROSOFT FIXTURE CORP,3571,operating,DE,1,2,1.0.0
0001045810,catalog-fixture-0001,2026-03-01T00:00:00Z,cik_sample.csv,,failed,,,,,0,0,1.0.0
0001326801,catalog-fixture-0001,2026-03-01T00:00:00Z,cik_sample.csv,2f94f666bcef608ef76acbf113b8d56d4302da19a3ed5631e3e6c892c6a9df47,ok,META FIXTURE PLATFORMS,3571,operating,DE,1,4,1.0.0
0001652044,catalog-fixture-0001,2026-03-01T00:00:00Z,cik_sample.csv,80be9ec1c3ef08d139f3c2d3abbcc9fd1687267a7b0937fe98bea5b4eaee0b21,ok,ALPHABET FIXTURE INC,3571,operating,DE,1,2,1.0.0
"""

_EXPECTED_TARGETS_CSV = """\
occurrence_id,document_locator_key,source_cik,accession,form,filing_date,report_date,primary_document,document_path,archive_url,document_path_source,primary_exhibit_like,reported_size,is_xbrl,is_inline_xbrl,is_xbrl_numeric
1cd6b3ab04926e940d0a0ae103f3187713abd73533cc7687f6983ed84788b395,8f3d6b0cb0e579357316ec47787e096a8a42db7f50b42bd4679c8ad8392de9c9,0000019617,000001961724000040,10-K,2024-02-29,2023-12-31,jpm-20231231.htm,jpm-20231231.htm,https://www.sec.gov/Archives/edgar/data/19617/000001961724000040/jpm-20231231.htm,primary_document,False,66006,True,True,True
46ff7701a266c7b897c8656da59c49b8109008f7dfa616771a532ac7feef5043,ba47a0abceba922847a3a3344e77e82f00bcde662b83392ba7f81242287655ca,0000320193,000032019323000106,10-K,2023-11-03,2023-09-30,aapl-20230930.htm,aapl-20230930.htm,https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm,primary_document,False,91234,True,True,True
d8bd0b4129f91c2dbce3ee1e9ec59c2179c67b74d4a59f6fbf0765a396d1220f,16d9be86ef4e3a942d44eba662ecb510ea47cd402bd95c3a5a0a507f790ca26b,0000320193,000032019324000021,10-Q,2024-02-02,2023-12-30,aapl-20231230.htm,aapl-20231230.htm,https://www.sec.gov/Archives/edgar/data/320193/000032019324000021/aapl-20231230.htm,primary_document,False,0,False,False,False
0675dc4af4dcf32d00572414ff4fc128da77f77288b89bc1793e7aea5e60bbcc,adb47ef4c06e3eb4b8bc97757e5ef34cb0ccd2eb95788aab08f7df9c533ae79a,0000320193,000032019324000077,8-K,2024-04-11,,,0000320193-24-000077.txt,https://www.sec.gov/Archives/edgar/data/320193/000032019324000077/0000320193-24-000077.txt,submission_bundle,False,2048,False,False,False
3d0a092d60e8460b456475b9186554f2c374c24133f3381d98c6b66f81834262,4bf71a4f62560066f492522410f5c02278decaa87d0f6c8b4db8b603c6be1b9c,0000320193,000032019324000099,8-K,2024-05-10,,form8k20240510.htm,form8k20240510.htm,https://www.sec.gov/Archives/edgar/data/320193/000032019324000099/form8k20240510.htm,primary_document,False,4096,False,False,False
8f99ff6abb4d8478328efa0be2dc64ccd579c0e7a01f1787cdea51546df57128,c2a4c48f5436f8ef2863ba3fc3f64b5902a68ad9e669244f5671b6fcd03f3059,0000789019,000032019323000106,10-K,2023-11-03,2023-06-30,msft-20230630.htm,msft-20230630.htm,https://www.sec.gov/Archives/edgar/data/789019/000032019323000106/msft-20230630.htm,primary_document,False,88123,True,True,True
c8fc4eb1ae58146e081a579507a857037f2f97ac650651c165a0564d2cdae79a,adb47ef4c06e3eb4b8bc97757e5ef34cb0ccd2eb95788aab08f7df9c533ae79a,0000789019,000032019324000077,8-K,2024-04-11,,,0000320193-24-000077.txt,https://www.sec.gov/Archives/edgar/data/789019/000032019324000077/0000320193-24-000077.txt,submission_bundle,False,2048,False,False,False
d3a15f1f7b863d293b30ceff7a47a162d9773b3b451368f18bf550076147a7bc,22088d89a17f76eb9ba24bf27db0c7946e2e2806a9a73edc8a845cbf159e3f61,0001326801,000132680124000010,10-K/A,2024-03-08,,meta-20231231.htm,meta-20231231.htm,https://www.sec.gov/Archives/edgar/data/1326801/000132680124000010/meta-20231231.htm,primary_document,False,99001,True,True,True
f18e7aa53afe3fbc6d89a79796f10a1775aa3f39d9a1e5e7f71c2a1464b6577d,9bb96b5000a0357b009b69e40e72c2c3009e4a2fe751d6e239e2a0c9daa212be,0001326801,000132680124000011,10-KT,2024-05-16,,meta-transition-20231231.htm,meta-transition-20231231.htm,https://www.sec.gov/Archives/edgar/data/1326801/000132680124000011/meta-transition-20231231.htm,primary_document,False,77002,True,True,True
74c9cc7172334123a2baaa6a4db0c1f37c40067627987cb09d45b3fbe05475dd,edbf912734e17f2c5064ccea6df03525939fd9cf51f253a2767b4a864c336b95,0001326801,000132680124000013,8-K/A,2024-06-11,,form8ka20240611.htm,form8ka20240611.htm,https://www.sec.gov/Archives/edgar/data/1326801/000132680124000013/form8ka20240611.htm,primary_document,False,33004,False,False,False
4d52eec58fc574edff75fd54e2498cd8c8791f7bab66535fe05f46b9e46c89ea,89ddcaa90df9b7e5d41bf53a271a2822246ef85f63742fd8fc0e93a12b8d1053,0001326801,000132680199000012,10-KSB,1999-06-01,,meta-sb-1998.htm,meta-sb-1998.htm,https://www.sec.gov/Archives/edgar/data/1326801/000132680199000012/meta-sb-1998.htm,primary_document,False,55003,False,False,False
59490d5ef11ff03f5e0b9a61a2c56f135fffcdf7fc2101c1c2ab47eee5981b4b,779dc12e0b7103b181724fed138a4df82915c29324b8ddacea33b5c34d5c0d9e,0001652044,000165204424000030,10-K,2024-02-07,2023-12-31,,0001652044-24-000030.txt,https://www.sec.gov/Archives/edgar/data/1652044/000165204424000030/0001652044-24-000030.txt,submission_bundle,False,0,True,True,True
a269a4323fd4d4abba80ec5c1f7cc3de6fa86499ec3afac9ee19e69ec0ee645f,97018fb3105e88085b0423c2975905d1c1cf4d68890e4bbebb4ecc0822530d5c,0001652044,000165204424000031,10-Q,2024-04-25,2024-03-31,,0001652044-24-000031.txt,https://www.sec.gov/Archives/edgar/data/1652044/000165204424000031/0001652044-24-000031.txt,submission_bundle,False,12005,True,True,True
"""


def _filing(cik: str, index: int, spec: tuple) -> dict[str, Any]:
    accession, filing_date, report_date, form, size, xbrl, primary = spec
    normalized = accession.replace("-", "")
    source_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    archive_url = None
    if primary is not None and primary.strip():
        archive_url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{normalized}/{primary}"
        )
    return {
        "accession_number": accession,
        "accession_number_normalized": normalized,
        "filing_date": filing_date,
        "report_date": report_date,
        "acceptance_datetime": f"{filing_date}T16:30:00.000Z",
        "act": "33",
        "form": form,
        "file_number": "001-00001",
        "film_number": "26123456",
        "items": [],
        "core_type": "",
        "size": size,
        "is_xbrl": xbrl,
        "is_inline_xbrl": xbrl,
        "is_xbrl_numeric": xbrl,
        "primary_document": primary,
        "primary_doc_description": primary if primary is not None else "",
        "archive_url": archive_url,
        "source_section": "recent",
        "source_file": source_url,
        "source_array_index": index,
    }


def _address() -> dict[str, None]:
    return {
        "street1": None,
        "street2": None,
        "city": None,
        "state_or_country": None,
        "zip_code": None,
        "state_or_country_description": None,
        "country": None,
        "country_code": None,
        "foreign_state_territory": None,
        "is_foreign_location": None,
    }


def _sample_row(spec: tuple) -> dict[str, Any]:
    (
        cik,
        name,
        status,
        error,
        sha,
        fingerprint,
        fetched_at,
        input_name,
        hist_failed,
        anomalies,
        filings,
    ) = spec
    failed = name is None
    return {
        "cik": cik,
        "snapshot_id": "catalog-fixture-0001",
        "fetched_at": fetched_at,
        "source_url": f"https://data.sec.gov/submissions/CIK{cik}.json",
        "response_sha256": sha,
        "byte_count": 4096,
        "schema_version": "1.0.0",
        "status": status,
        "error": error,
        "anomalies": list(anomalies),
        "extra_fields": None,
        "identity": {"name": name, "former_names": []},
        "classification": {
            "entity_type": None if failed else "operating",
            "sic_code": None if failed else "3571",
            "sic_description": None if failed else "Electronic Computers",
            "owner_org": None if failed else "",
            "filer_category": None if failed else "Large Accelerated Filer",
        },
        "identifiers": {
            "ein": None if failed else "000000000",
            "lei": None if failed else "",
        },
        "contact": {
            "phone": None,
            "website": None if failed else "",
            "investor_website": None if failed else "",
            "description": None if failed else f"{name} fixture registrant",
        },
        "incorporation": {
            "state": None if failed else "DE",
            "state_description": None if failed else "Delaware",
        },
        "reporting": {"fiscal_year_end": None if failed else "0930"},
        "insider_transactions": {"owner_exists": None, "issuer_exists": None},
        "addresses": (
            {"mailing": None, "business": None}
            if failed
            else {"mailing": _address(), "business": _address()}
        ),
        "listings": (
            [] if failed else [{"ticker": f"T{cik[-4:]}", "exchange": "Nasdaq"}]
        ),
        "filings": [_filing(cik, i, f) for i, f in enumerate(filings)],
        "submission_files": [],
        "input_name": input_name,
        "input_fingerprint": fingerprint,
        "chunk_id": None,
        "historical_files_total": 0,
        "historical_files_failed": hist_failed,
        "historical_records_total": 0,
    }


def _write_csv(path: Path, header: tuple, rows: tuple) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def write_catalog_fixtures(root: Path) -> Path:
    """Write the four generated catalog fixtures into ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    _write_csv(root / "cik_sample.csv", ("cik", "name"), CIK_SAMPLE)
    (root / "expected_company_profiles.csv").write_text(
        _EXPECTED_PROFILES_CSV, encoding="utf-8"
    )
    (root / "expected_filing_targets.csv").write_text(
        _EXPECTED_TARGETS_CSV, encoding="utf-8"
    )
    table = pa.Table.from_pylist(
        [_sample_row(spec) for spec in _SAMPLE_ROWS],
        schema=SUBMISSION_METADATA_SCHEMA,
    )
    pq.write_table(
        table,
        root / "sample_submission_metadata.parquet",
        compression="zstd",
        row_group_size=DEFAULT_ROW_GROUP_SIZE,
    )
    return root


def catalog_fixture_dir() -> Path:
    """Materialize the generated catalog fixtures, keyed by this module."""
    digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
    root = Path(tempfile.gettempdir()) / "edgar-catalog-fixtures" / digest
    if not (root / "sample_submission_metadata.parquet").is_file():
        write_catalog_fixtures(root)
    return root


__all__ = [
    "GENERATED_CATALOG_FIXTURES",
    "catalog_fixture_dir",
    "write_catalog_fixtures",
]
