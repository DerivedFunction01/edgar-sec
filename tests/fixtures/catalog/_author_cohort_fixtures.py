#!/usr/bin/env python3
"""Author the S1 cohort-observation fixture Parquet files.

Run the script to rebuild them plus the sha256 manifest used for byte-for-byte parity.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.infra.storage.parquet import DEFAULT_ROW_GROUP_SIZE

FIXTURES = Path(__file__).resolve().parent

# Column types for the synthetic part; reported_size and the xbrl flags mirror the
# real filing-target schema so schema validation against TARGET_COLUMNS is realistic.
OBSERVATION_SCHEMA = pa.schema(
    [
        ("occurrence_id", pa.string()),
        ("document_locator_key", pa.string()),
        ("source_cik", pa.string()),
        ("accession", pa.string()),
        ("form", pa.string()),
        ("filing_date", pa.string()),
        ("report_date", pa.string()),
        ("primary_document", pa.string()),
        ("document_path", pa.string()),
        ("archive_url", pa.string()),
        ("document_path_source", pa.string()),
        ("reported_size", pa.int64()),
        ("is_xbrl", pa.bool_()),
        ("is_inline_xbrl", pa.bool_()),
        ("is_xbrl_numeric", pa.bool_()),
    ]
)

OCCURRENCE_ID = "a0" * 20  # synthetic; the reader never uses these columns


# Data rows are source_id, accession, source_cik, form, filing_date, report_date tuples.
# Accession A is a co-filer group with two CIKs; one exact duplicate collapses.
GOOD_OBSERVATIONS = [
    # Accession A is a co-filer group with two CIKs; one exact duplicate collapses.
    (
        "plan-alpha",
        "000032019323000106",
        "0000320193",
        "10-K",
        "2023-02-01",
        "2022-12-31",
    ),
    (
        "plan-alpha",
        "000032019323000106",
        "0000789019",
        "10-K",
        "2023-02-01",
        "2022-12-31",
    ),
    (
        "plan-alpha",
        "000032019323000106",
        "0000320193",
        "10-K",
        "2023-02-01",
        "2022-12-31",
    ),
    # Legacy 1994 accession, one exact duplicate.
    (
        "plan-alpha",
        "000095012394000687",
        "0000950123",
        "10-K",
        "1994-03-15",
        "1993-12-31",
    ),
    (
        "plan-alpha",
        "000095012394000687",
        "0000950123",
        "10-K",
        "1994-03-15",
        "1993-12-31",
    ),
    # Same source, two CIKs, missing report dates (non-conflicting).
    ("plan-alpha", "000132680104000077", "0001326801", "8-K", "2004-12-31", ""),
    ("plan-alpha", "000132680104000077", "0001652044", "8-K", "2004-12-31", ""),
    # Single source, modern, with a report date.
    (
        "plan-alpha",
        "000020040626000016",
        "0000200406",
        "10-K",
        "2026-01-01",
        "2025-12-31",
    ),
    # One accession, three identical CIK observations from the same source.
    (
        "plan-alpha",
        "000001961705000045",
        "0000019617",
        "10-K",
        "2020-01-01",
        "2020-06-30",
    ),
    (
        "plan-alpha",
        "000001961705000045",
        "0000019617",
        "10-K",
        "2020-01-01",
        "2020-06-30",
    ),
    (
        "plan-alpha",
        "000001961705000045",
        "0000019617",
        "10-K",
        "2020-01-01",
        "2020-06-30",
    ),
    # Two observations, same CIK, one exact duplicate.
    (
        "plan-alpha",
        "000078901902000123",
        "0000789019",
        "10-K",
        "2002-05-15",
        "2002-03-31",
    ),
    (
        "plan-alpha",
        "000078901902000123",
        "0000789019",
        "10-K",
        "2002-05-15",
        "2002-03-31",
    ),
    (
        "plan-alpha",
        "000196170500000045",
        "0001961705",
        "10-K",
        "2005-01-01",
        "2004-12-31",
    ),
    (
        "plan-alpha",
        "000196170500000045",
        "0001961705",
        "10-K",
        "2005-01-01",
        "2004-12-31",
    ),
    # 18-digit accession: archive CIK is int("0000009015") = 9015, no leading zeros.
    (
        "plan-alpha",
        "000000901500000054",
        "0000000020",
        "10-K",
        "2001-01-01",
        "2000-12-31",
    ),
    (
        "plan-alpha",
        "000000901500000054",
        "0000000020",
        "10-K",
        "2001-01-01",
        "2000-12-31",
    ),
]

CONFLICTING_OBSERVATIONS = [
    # Same (accession, source_cik, cohort_source_id) with a different form -> refused.
    (
        "plan-alpha",
        "000276950120000001",
        "0002769501",
        "10-K",
        "2020-01-01",
        "2020-06-30",
    ),
    ("plan-alpha", "000276950120000001", "0002769501", "4", "2020-01-01", "2020-06-30"),
    # Different filing date for the same identity -> refused.
    (
        "plan-alpha",
        "000276950120000002",
        "0002769501",
        "10-K",
        "2020-01-01",
        "2020-06-30",
    ),
    (
        "plan-alpha",
        "000276950120000002",
        "0002769501",
        "10-K",
        "2021-01-01",
        "2020-06-30",
    ),
    # Two present report dates that disagree -> refused.
    (
        "plan-alpha",
        "000276950120000003",
        "0002769501",
        "10-K",
        "2020-01-01",
        "2020-06-30",
    ),
    (
        "plan-alpha",
        "000276950120000003",
        "0002769501",
        "10-K",
        "2020-01-01",
        "2021-06-30",
    ),
]

MALFORMED_OBSERVATIONS = [
    # Invalid accession identity -> reader raises invalid_identity.
    (
        "plan-delta",
        "not-an-accession",
        "0000000000",
        "10-K",
        "2020-01-01",
        "2020-06-30",
    ),
    # Null form -> reader raises missing_form.
    (
        "plan-delta",
        "000001961705000045",
        "0000000000",
        None,
        "2020-01-01",
        "2020-06-30",
    ),
    # Invalid ISO date -> reader raises invalid_date.
    (
        "plan-delta",
        "000001961705000045",
        "0000000000",
        "10-K",
        "2020-99-99",
        "2020-06-30",
    ),
]


def _to_py_row(row: tuple[str, str, str, str | None, str, str]) -> dict[str, object]:
    cohort_source_id, accession_raw, source_cik, form, filing_date, report_date = row
    return {
        "occurrence_id": OCCURRENCE_ID,
        "document_locator_key": OCCURRENCE_ID,
        "source_cik": source_cik,
        "accession": accession_raw,
        "form": form,
        "filing_date": filing_date,
        "report_date": report_date,
        "primary_document": "",
        "document_path": f"{accession_raw}.txt",
        "archive_url": f"https://www.sec.gov/Archives/edgar/data/1/{accession_raw}/{accession_raw}.txt",
        "document_path_source": "submission_bundle",
        "reported_size": 1024,
        "is_xbrl": False,
        "is_inline_xbrl": False,
        "is_xbrl_numeric": False,
    }


def _write_parquet(
    rows: list[tuple[str, str, str, str | None, str, str]], path: Path
) -> str:
    table = pa.Table.from_pylist(
        [_to_py_row(r) for r in rows], schema=OBSERVATION_SCHEMA
    )
    pq.write_table(
        table, path, compression="zstd", row_group_size=DEFAULT_ROW_GROUP_SIZE
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    good = _write_parquet(GOOD_OBSERVATIONS, FIXTURES / "cohort_observations.parquet")
    conflicting = _write_parquet(
        CONFLICTING_OBSERVATIONS, FIXTURES / "cohort_observations_conflicting.parquet"
    )
    malformed = _write_parquet(
        MALFORMED_OBSERVATIONS, FIXTURES / "cohort_observations_malformed.parquet"
    )
    manifest = {
        "schema_version": "1",
        "fixtures": [
            {
                "name": "cohort_observations",
                "row_count": len(GOOD_OBSERVATIONS),
                "sha256": good,
            },
            {
                "name": "cohort_observations_conflicting",
                "row_count": len(CONFLICTING_OBSERVATIONS),
                "sha256": conflicting,
            },
            {
                "name": "cohort_observations_malformed",
                "row_count": len(MALFORMED_OBSERVATIONS),
                "sha256": malformed,
            },
        ],
    }
    (FIXTURES / "cohort_observations.json.sha256").write_text(
        json.dumps(manifest, indent=2)
    )
    _write_plan_fixture(FIXTURES, GOOD_OBSERVATIONS)
    print("wrote", FIXTURES / "cohort_observations.parquet")
    print("wrote", FIXTURES / "cohort_observations_conflicting.parquet")
    print("wrote", FIXTURES / "cohort_observations_malformed.parquet")
    print("wrote", FIXTURES / "cohort_observations.json.sha256")
    print("wrote s1 plan fixture under", FIXTURES / "s1_plan")


def _write_plan_fixture(
    fixtures: Path, good: list[tuple[str, str, str, str | None, str, str]]
) -> None:
    """Write the committed plan fixture: plan.json + per-form targets/form=.../data.parquet."""
    plan_dir = fixtures / "s1_plan"
    (plan_dir / "targets" / "form=10-K").mkdir(parents=True, exist_ok=True)
    (plan_dir / "targets" / "form=8-K").mkdir(parents=True, exist_ok=True)
    ten_k = [r for r in good if r[3] == "10-K"]
    eight_k = [r for r in good if r[3] == "8-K"]
    sha10k = _write_parquet(ten_k, plan_dir / "targets" / "form=10-K" / "data.parquet")
    sha8k = _write_parquet(eight_k, plan_dir / "targets" / "form=8-K" / "data.parquet")
    plan_json = {
        "plan_id": "s1-cohort-plan",
        "catalog_id": "f259fde5d9c69335",
        "scope": "policy",
        "forms": ["10-K", "8-K"],
        "counts": {"10-K": len(ten_k), "8-K": len(eight_k)},
        "plan_schema_version": "1.2",
        "active_targets_count": len(good),
        "request_fingerprint": "0" * 64,
        "target_units": 1,
        "level": 1,
        "parent_plan_id": None,
        "policy_corpus": "corpus_f259fde5",
        "policy_fingerprint": "0" * 32,
        "seed_fingerprint": "0" * 32,
        "seed_filer_count": 0,
        "unique_locators_count": len(good),
        "selected_rows": len(good),
        "reserve_count": 0,
        "selection_policy": {"seed": "fixture-s1", "seed_cik_path": "test.csv"},
    }
    (plan_dir / "plan.json").write_text(json.dumps(plan_json, indent=2))
    (fixtures / "cohort_observations_plan_fixture.sha256").write_text(
        json.dumps({"form=10-K": sha10k, "form=8-K": sha8k}, indent=2)
    )


if __name__ == "__main__":
    main()
