"""Synthetic selection snapshots: the committed catalog fixture is far too
small to make a family cap bind, so selector tests build their own in the
on-disk shape `source` reads.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.engine.selection.policy import EraBand, SelectionPolicy
from edgar_sec.engine.selection.source import OCCURRENCE_COLUMNS, POOL_COLUMNS

# Type-faithful to what the builder writes, so a synthetic snapshot cannot hide a bug.
_BOOL_COLUMNS = frozenset({"has_revival_gap"})
_INT_COLUMNS: dict[str, pa.DataType] = {
    "reported_size": pa.int64(),
    "report_year": pa.int32(),
}

_LOCATOR_DEFAULTS: dict[str, Any] = {
    "document_locator_key": "loc",
    "form": "10-K",
    "form_family": "10-K",
    "era": "modern",
    "suffix": "htm",
    "xbrl_state": "inline_xbrl",
    "size_band": "median",
    "sic_code": "3571",
    "owner_org_presence": "no_org",
    "foreign_status": "domestic",
    "foreign_country_code": None,
    "entity_type": "operating",
    "filer_category_primary": "Accelerated Filer",
    "lifecycle_class": "right_censored_active",
    "has_revival_gap": False,
    "locator_class": "single",
    "stub_suspect": "false",
    "company_family": "example",
    "reported_size": 500_000,
    "report_year": 2020,
    "representative_cik": "0000000001",
}

_OCCURRENCE_BOOL_COLUMNS = frozenset({"is_xbrl", "is_inline_xbrl", "is_xbrl_numeric"})

# Written but unread by the pool projection, so a document_path filter binds.
_EXTRA_LOCATOR_COLUMNS: dict[str, Any] = {
    "filing_date": "2021-03-01",
    "report_date": "2020-12-31",
    "primary_document": "doc.htm",
    "document_path": "doc.htm",
    "archive_url": "https://www.sec.gov/Archives/edgar/data/1/a/doc.htm",
    "document_path_source": "primary_document",
    "representative_accession": "0000000000-20-000001",
}

_OCCURRENCE_DEFAULTS: dict[str, Any] = {
    "occurrence_id": "occ",
    "document_locator_key": "loc",
    "source_cik": "0000000001",
    "accession": "0000000001-20-000001",
    "form": "10-K",
    "filing_date": "2021-03-01",
    "report_date": "2020-12-31",
    "primary_document": "doc.htm",
    "document_path": "doc.htm",
    "archive_url": "https://www.sec.gov/Archives/edgar/data/1/a/doc.htm",
    "document_path_source": "primary_document",
    "reported_size": 500_000,
    "is_xbrl": True,
    "is_inline_xbrl": True,
    "is_xbrl_numeric": True,
    "sic_code": "3571",
    "owner_org_presence": "no_org",
    "foreign_status": "domestic",
    "foreign_country_code": None,
    "state_of_incorporation": "DE",
    "entity_type": "operating",
    "filer_category_primary": "Accelerated Filer",
}


def _schema(
    columns: Sequence[str], bools: frozenset[str], ints: dict[str, pa.DataType]
) -> pa.Schema:
    return pa.schema(
        [
            (
                column,
                pa.bool_() if column in bools else ints.get(column, pa.string()),
            )
            for column in columns
        ]
    )


def _rows(
    columns: Sequence[str],
    defaults: dict[str, Any],
    overrides: Iterable[dict[str, Any]],
    bools: frozenset[str],
    ints: dict[str, pa.DataType],
) -> pa.Table:
    rows = list(overrides)
    data = {
        column: [row.get(column, defaults[column]) for row in rows]
        for column in columns
    }
    return pa.table(data, schema=_schema(columns, bools, ints))


def write_snapshot(
    snapshot_dir: Path,
    locators: Sequence[dict[str, Any]],
    occurrences: Sequence[dict[str, Any]] | None = None,
) -> Path:
    """Write a minimal feature snapshot the candidate source can read."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    if occurrences is None:
        occurrences = [
            {
                **{
                    key: value
                    for key, value in locator.items()
                    if key in _OCCURRENCE_DEFAULTS
                },
                "occurrence_id": f"occ-{locator['document_locator_key']}",
                "document_locator_key": locator["document_locator_key"],
            }
            for locator in locators
        ]
    locator_columns = (*POOL_COLUMNS, *_EXTRA_LOCATOR_COLUMNS)
    locator_defaults = {**_LOCATOR_DEFAULTS, **_EXTRA_LOCATOR_COLUMNS}
    pq.write_table(
        _rows(locator_columns, locator_defaults, locators, _BOOL_COLUMNS, _INT_COLUMNS),
        snapshot_dir / "locator_features.parquet",
    )
    pq.write_table(
        _rows(
            OCCURRENCE_COLUMNS,
            _OCCURRENCE_DEFAULTS,
            occurrences,
            _OCCURRENCE_BOOL_COLUMNS,
            {"reported_size": pa.int64()},
        ),
        snapshot_dir / "occurrence_features.parquet",
    )
    return snapshot_dir


def make_locator(
    index: int,
    *,
    company_family: str = "example",
    cik: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Build one locator row with a stable, unique key."""
    return {
        "document_locator_key": f"loc-{index:04d}",
        "company_family": company_family,
        "representative_cik": cik or f"{index:010d}",
        **overrides,
    }


@pytest.fixture
def snapshot_dir(tmp_path: Path) -> Path:
    """Four families of five locators, every locator a distinct signature: the cap
    never binds here, so a shortfall means something else.
    """
    locators = [
        make_locator(
            index,
            company_family=f"family{index % 4}",
            sic_code=f"357{index % 10}",
            era=("legacy" if index % 2 == 0 else "modern"),
        )
        for index in range(20)
    ]
    return write_snapshot(tmp_path / "snapshot", locators)


@pytest.fixture
def selection_policy() -> SelectionPolicy:
    return SelectionPolicy(
        corpus_id="test_corpus",
        forms=["10-K"],
        era_bands=[
            EraBand(name="legacy", end_year=2010),
            EraBand(name="modern", start_year=2010),
        ],
        base_content_units=6,
        reserve_size=2,
        seed_cik_path="__absent__",
    )


def make_dominant_snapshot(root: Path, *, others: int) -> Path:
    """The independents are numbered from 100 because ``write_snapshot`` keys rows by
    locator key; an overlap would silently drop three of the twelve.
    """
    locators = [make_locator(index, company_family="megacorp") for index in range(12)]
    locators += [
        make_locator(
            100 + index,
            company_family=f"small{index}",
            sic_code=f"100{index}",
        )
        for index in range(others)
    ]
    return write_snapshot(root, locators)


@pytest.fixture
def dominant_family_snapshot(tmp_path: Path) -> Path:
    """Twelve of one group, plus twelve independent companies."""
    return make_dominant_snapshot(tmp_path / "dominant", others=12)
