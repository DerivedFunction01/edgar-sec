"""Facts store: ingest, CRC carry-forward on re-ingest, per-CIK reads."""

from __future__ import annotations

import io
import json
import zipfile as zipfile_module
from pathlib import Path

from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore
from edgar_sec.pipelines.metadata_sync.companyfacts import (
    COMPANYFACTS_BULK_SOURCE_ID,
)
from edgar_sec.pipelines.metadata_sync.facts_store import (
    facts_for_concept,
    ingest_facts_archive,
    read_facts_for_cik,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths

URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"


def _member(entity: str, value: int, *, accession: str = "a1") -> bytes:
    payload = {
        "entityName": entity,
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "val": value,
                                "end": "2024-09-28",
                                "accn": accession,
                                "form": "10-K",
                                "filed": "2024-11-01",
                                "fy": 2024,
                                "fp": "FY",
                            }
                        ]
                    }
                },
                "Liabilities": {
                    "units": {
                        "USD": [
                            {
                                "val": value // 2,
                                "end": "2024-09-28",
                                "accn": accession,
                                "form": "10-K",
                                "filed": "2024-11-01",
                                "fy": 2024,
                                "fp": "FY",
                            }
                        ]
                    }
                },
            }
        },
    }
    return json.dumps(payload).encode("utf-8")


def _store_archive(root: Path, members: dict[str, bytes], name: str) -> object:
    buffer = io.BytesIO()
    with zipfile_module.ZipFile(buffer, "w") as archive:
        for member_name, payload in members.items():
            archive.writestr(member_name, payload)
    staging = root / name
    staging.write_bytes(buffer.getvalue())
    store = BulkArchiveStore(root / "bulk")
    return store.put_file(COMPANYFACTS_BULK_SOURCE_ID, staging, source_url=URL)


def test_ingest_then_reingest_carries_unchanged_members_forward(
    tmp_path: Path,
) -> None:
    paths = resolve_metadata_paths(tmp_path)
    first = _store_archive(
        tmp_path,
        {
            "CIK0000000020.json": _member("Twenty", 100),
            "CIK0000320193.json": _member("Apple", 300),
        },
        "first.zip",
    )
    outcome = ingest_facts_archive(paths, first, workers=1)

    assert outcome.member_count == 2
    assert outcome.normalized_members == 2
    assert outcome.carried_members == 0
    assert outcome.removed_members == 0
    assert outcome.fact_rows == 4
    assert outcome.archive_sha == first.sha256

    twenty_before = read_facts_for_cik(paths.facts_store_file, 20)
    assert [fact.value for fact in twenty_before] == [100.0, 50.0]
    assert {fact.archive_sha for fact in twenty_before} == {first.sha256}

    second = _store_archive(
        tmp_path,
        {
            "CIK0000000020.json": _member("Twenty", 100),
            "CIK0000320193.json": _member("Apple", 999, accession="a2"),
        },
        "second.zip",
    )
    outcome = ingest_facts_archive(paths, second, workers=1)

    assert outcome.normalized_members == 1
    assert outcome.carried_members == 1
    assert outcome.removed_members == 0
    assert outcome.fact_rows == 4

    carried = read_facts_for_cik(paths.facts_store_file, "0000000020")
    assert carried == twenty_before
    changed = read_facts_for_cik(paths.facts_store_file, 320193)
    assert [fact.value for fact in changed] == [999.0, 499.0]
    assert {fact.archive_sha for fact in changed} == {second.sha256}
    assert {fact.accession for fact in changed} == {"a2"}


def test_reingest_removes_ciks_absent_from_the_new_archive(tmp_path: Path) -> None:
    paths = resolve_metadata_paths(tmp_path)
    first = _store_archive(
        tmp_path,
        {
            "CIK0000000020.json": _member("Twenty", 100),
            "CIK0000320193.json": _member("Apple", 300),
        },
        "first.zip",
    )
    ingest_facts_archive(paths, first, workers=1)

    second = _store_archive(
        tmp_path,
        {"CIK0000320193.json": _member("Apple", 300)},
        "second.zip",
    )
    outcome = ingest_facts_archive(paths, second, workers=1)

    assert outcome.removed_members == 1
    assert outcome.carried_members == 1
    assert outcome.fact_rows == 2
    assert read_facts_for_cik(paths.facts_store_file, 20) == ()


def test_read_api_serves_one_concept_locally(tmp_path: Path) -> None:
    paths = resolve_metadata_paths(tmp_path)
    reference = _store_archive(
        tmp_path,
        {"CIK0000320193.json": _member("Apple", 300)},
        "only.zip",
    )
    ingest_facts_archive(paths, reference, workers=1)

    facts = facts_for_concept(
        paths.facts_store_file, 320193, "us-gaap", "Assets", unit="USD"
    )
    assert len(facts) == 1
    fact = facts[0]
    assert fact.cik == 320193
    assert fact.value == 300.0
    assert fact.end == "2024-09-28"
    assert fact.fiscal_year == 2024
    assert facts_for_concept(paths.facts_store_file, 320193, "us-gaap", "Nope") == ()
    assert read_facts_for_cik(paths.facts_store_file, 999999) == ()
