from __future__ import annotations

import re

_ARCHIVE_FILENAME_RE = re.compile(r"\d{4}\.[A-Za-z0-9]+", re.ASCII)

from edgar_sec.pipelines.document_planning.catalog_scope import (
    CatalogOccurrence,
    CatalogScopeAccession,
)
from edgar_sec.pipelines.document_planning.inventory_evidence import (
    InventoryEvidenceRow,
)
from edgar_sec.pipelines.document_planning.profiles import ProfileTarget


_ACCESSION = "0000899681-00-000405"


_ARCHIVE_ROOT = "https://www.sec.gov/Archives/edgar/data/898015/000089968100000405"


_INDEX_URL = f"{_ARCHIVE_ROOT}/{_ACCESSION}-index.html"


_BUNDLE_URL = f"{_ARCHIVE_ROOT}/{_ACCESSION}.txt"


def _occurrence(
    url: str | None,
    *,
    source_cik: str = "1",
    primary_document: str = "primary.htm",
) -> CatalogOccurrence:
    return CatalogOccurrence(
        occurrence_id="occ-1",
        document_locator_key="locator-1",
        source_cik=source_cik,
        primary_document=primary_document,
        document_path=primary_document,
        archive_url=url,
        document_path_source="primary_document",
        reported_size=10,
        is_xbrl=True,
        is_inline_xbrl=False,
        is_xbrl_numeric=True,
    )


def _scope(
    url: str | None,
    *,
    source_cik: str = "1",
    primary_document: str = "primary.htm",
    accession: str = "000000000124000001",
) -> CatalogScopeAccession:
    return CatalogScopeAccession(
        accession,
        "10-K",
        "2024-01-02",
        (
            _occurrence(
                url,
                source_cik=source_cik,
                primary_document=primary_document,
            ),
        ),
    )


def _dated_scope(
    form: str,
    filing_date: str,
    *,
    primary_document: str = "",
    report_date: str | None = None,
) -> CatalogScopeAccession:
    return CatalogScopeAccession(
        _ACCESSION,
        form,
        filing_date,
        (
            _occurrence(
                None,
                source_cik="898015",
                primary_document=primary_document,
            ),
        ),
        report_date,
    )


def _primary_target(selection: str | None) -> ProfileTarget:
    return ProfileTarget("primary", "primary", False, "primary:primary", selection)


def _inventory_row(
    entry: dict[str, object],
    *,
    bundle_url: str | None = None,
    vehicle: str = "index_html",
) -> InventoryEvidenceRow:
    return InventoryEvidenceRow(
        accession=_ACCESSION,
        catalog_form="10-Q",
        catalog_filing_date="2000-11-14",
        indexed=True,
        accession_row={
            "bundle_url": bundle_url,
            "bundle_size": 67488,
            "filing_cik": "1",
            "index_url": _INDEX_URL,
        },
        entry_row=entry,
        vehicle=vehicle,
    )


def _placeholder_entry(
    *, sequence: object = 1, filename: str = "0001.htm", entry_id: str = "entry-1"
) -> dict[str, object]:
    archive_filename = (
        f"{_ACCESSION}-{filename}"
        if _ARCHIVE_FILENAME_RE.fullmatch(filename)
        else filename
    )
    return {
        "entry_id": entry_id,
        "table_kind": "document_format",
        "document_type": "10-Q",
        "filename": filename,
        "archive_url": f"{_ARCHIVE_ROOT}/{archive_filename}",
        "sequence": sequence,
        "byte_size": 63833,
    }


def _data_file_entry(document_type: str, filename: str) -> dict[str, object]:
    return {
        "entry_id": f"entry-{filename}",
        "table_kind": "data_file",
        "document_type": document_type,
        "filename": filename,
        "archive_url": f"{_ARCHIVE_ROOT}/{filename}",
        "sequence": None,
        "byte_size": 100,
    }
