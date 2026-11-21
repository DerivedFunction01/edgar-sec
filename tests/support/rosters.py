"""Roster and submission-metadata fixture builders for tests."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa

from edgar_sec.pipelines.metadata_sync.core.roster import Roster, write_roster_rows
from tests.support.fixtures import catalog_fixture_path
from tests.support.scratch import _make_scratch_dir


def roster_of(
    ciks: Iterable[str], names: Iterable[str] = (), *, name: str = "cohort.parquet"
) -> Roster:
    """Prefer a test's own ``tmp_path`` when the path matters to the assertion."""
    cik_list = tuple(ciks)
    name_list = tuple(names) or ("",) * len(cik_list)
    if len(name_list) != len(cik_list):
        raise ValueError("roster_of needs one name per CIK")
    scratch = _make_scratch_dir("edgar-test-cohort-")
    roster, _digest = write_roster_rows(
        list(zip(cik_list, name_list, strict=True)),
        scratch / name,
    )
    return roster


def era_submission_metadata(destination: Path) -> Path:
    """Copy the committed catalog fixture with pre-2005 filings appended.

    Its rows pin the candidate window's edges and a co-filer group.
    """
    import pyarrow.parquet as pq

    table = pq.read_table(catalog_fixture_path("sample_submission_metadata.parquet"))
    filings = table.column("filings").to_pylist()
    template = filings[0][0]
    appended: dict[str, list[dict[str, Any]]] = {}

    for cik, accession, filing_date, form, primary_document in ERA_FILINGS:
        row = dict(template)
        row.update(
            accession_number=accession,
            accession_number_normalized=accession.replace("-", ""),
            filing_date=filing_date,
            report_date="",
            acceptance_datetime=f"{filing_date}T16:30:00.000Z",
            form=form,
            file_number="",
            film_number="",
            items=[],
            core_type="",
            size=None,
            is_xbrl=None,
            is_inline_xbrl=None,
            is_xbrl_numeric=None,
            primary_document=primary_document,
            primary_doc_description=primary_document,
            archive_url="",
            source_section="recent",
            source_array_index=len(appended.get(cik, ())) + 900,
        )
        appended.setdefault(cik, []).append(row)

    patched = [
        list(filings[index]) + appended.get(str(table.column("cik")[index].as_py()), [])
        for index in range(table.num_rows)
    ]
    pq.write_table(
        table.set_column(
            table.schema.get_field_index("filings"), "filings", pa.array(patched)
        ),
        destination,
    )
    return destination


#: ``(cik, accession, filing_date, form, primary_document)``. The first two rows are
#: co-filers of one document with agreeing dates; the rest pin the window's edges.
ERA_FILINGS: tuple[tuple[str, str, str, str, str], ...] = (
    ("0000320193", "0000320193-02-000123", "2002-05-15", "10-K", "ex21.txt"),
    ("0000789019", "0000320193-02-000123", "2002-05-15", "10-K", "ex21.txt"),
    ("0001326801", "0001326801-04-000077", "2004-12-31", "8-K", "ex99.txt"),
    ("0001652044", "0001652044-01-000011", "2000-01-01", "10-K", "annual-report.htm"),
    ("0000019617", "0000019617-05-000045", "2005-06-01", "10-K", "ex99.txt"),
)


__all__ = [
    "ERA_FILINGS",
    "era_submission_metadata",
    "roster_of",
]
