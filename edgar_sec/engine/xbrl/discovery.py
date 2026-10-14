"""Pure classifier identifying XBRL linkbases and data files from index entries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from edgar_sec.domain.document_inventory.models import (
    InventoryEntry,
    ParsedIndexPage,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.sec_urls import archives_url


class LinkbaseType(StrEnum):
    """Recognized XBRL taxonomy and instance components."""

    CALCULATION = "calculation"
    PRESENTATION = "presentation"
    DEFINITION = "definition"
    LABEL = "label"
    SCHEMA = "schema"
    INSTANCE = "instance"
    PACKAGE = "package"


@dataclass(frozen=True, slots=True)
class DiscoveredLinkbase:
    """One discovered linkbase or instance file from a filing index."""

    accession: AccessionNumber
    cik: Cik
    linkbase_type: LinkbaseType
    document_type: str
    filename: str
    archive_url: str
    byte_size: int | None
    sequence: int | None
    description: str | None


def classify_linkbase_entry(entry: InventoryEntry) -> LinkbaseType | None:
    """Classify an inventory entry into a recognized linkbase type."""
    doc_type = (entry.document_type or "").strip().upper()
    filename = (entry.filename or "").strip().lower()
    description = (entry.description or "").strip().upper()

    if doc_type == "EX-101.CAL" or filename.endswith("_cal.xml"):
        return LinkbaseType.CALCULATION
    if "CALCULATION LINKBASE" in description:
        return LinkbaseType.CALCULATION

    if doc_type == "EX-101.PRE" or filename.endswith("_pre.xml"):
        return LinkbaseType.PRESENTATION
    if "PRESENTATION LINKBASE" in description:
        return LinkbaseType.PRESENTATION

    if doc_type == "EX-101.DEF" or filename.endswith("_def.xml"):
        return LinkbaseType.DEFINITION
    if "DEFINITION LINKBASE" in description:
        return LinkbaseType.DEFINITION

    if doc_type == "EX-101.LAB" or filename.endswith("_lab.xml"):
        return LinkbaseType.LABEL
    if "LABEL LINKBASE" in description:
        return LinkbaseType.LABEL

    if doc_type == "EX-101.SCH" or filename.endswith(".xsd"):
        return LinkbaseType.SCHEMA
    if "TAXONOMY EXTENSION SCHEMA" in description:
        return LinkbaseType.SCHEMA

    if doc_type == "EX-101.INS" or filename.endswith("_htm.xml"):
        return LinkbaseType.INSTANCE
    if "EXTRACTED XBRL INSTANCE" in description:
        return LinkbaseType.INSTANCE

    if filename.endswith("-xbrl.zip") or filename.endswith("_xbrl.zip"):
        return LinkbaseType.PACKAGE

    return None


def extract_filing_linkbases(
    parsed_page: ParsedIndexPage,
    cik: Cik,
) -> tuple[DiscoveredLinkbase, ...]:
    """Extract and resolve all linkbases from a parsed index page."""
    discovered: list[DiscoveredLinkbase] = []
    seen_keys: set[tuple[str, str]] = set()

    for entry in parsed_page.entries:
        lb_type = classify_linkbase_entry(entry)
        if lb_type is None or not entry.filename:
            continue

        key = (lb_type.value, entry.filename.lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)

        url = entry.archive_url or archives_url(
            cik,
            parsed_page.accession.normalized,
            entry.filename,
        )
        discovered.append(
            DiscoveredLinkbase(
                accession=parsed_page.accession,
                cik=cik,
                linkbase_type=lb_type,
                document_type=entry.document_type or lb_type.value,
                filename=entry.filename,
                archive_url=url,
                byte_size=entry.byte_size,
                sequence=entry.sequence,
                description=entry.description,
            )
        )

    return tuple(
        sorted(discovered, key=lambda lb: (lb.linkbase_type.value, lb.filename))
    )
