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


def classify_linkbase(
    doc_type: str, filename: str, description: str
) -> LinkbaseType | None:
    """Classify a document entry into a recognized linkbase type.

    Uses strict document type, filename suffix, and description guards;
    ambiguous entries return None.
    """
    dt = doc_type.strip().upper()
    fn = filename.strip().lower()
    desc = description.strip().upper()

    if dt == "EX-101.CAL" or fn.endswith("_cal.xml"):
        return LinkbaseType.CALCULATION
    if "CALCULATION LINKBASE" in desc:
        return LinkbaseType.CALCULATION

    if dt == "EX-101.PRE" or fn.endswith("_pre.xml"):
        return LinkbaseType.PRESENTATION
    if "PRESENTATION LINKBASE" in desc:
        return LinkbaseType.PRESENTATION

    if dt == "EX-101.DEF" or fn.endswith("_def.xml"):
        return LinkbaseType.DEFINITION
    if "DEFINITION LINKBASE" in desc:
        return LinkbaseType.DEFINITION

    if dt == "EX-101.LAB" or fn.endswith("_lab.xml"):
        return LinkbaseType.LABEL
    if "LABEL LINKBASE" in desc:
        return LinkbaseType.LABEL

    if dt == "EX-101.SCH" or fn.endswith(".xsd"):
        return LinkbaseType.SCHEMA
    if "TAXONOMY EXTENSION SCHEMA" in desc:
        return LinkbaseType.SCHEMA

    if dt == "EX-101.INS" or fn.endswith("_htm.xml"):
        return LinkbaseType.INSTANCE
    if "EXTRACTED XBRL INSTANCE" in desc:
        return LinkbaseType.INSTANCE

    if fn.endswith("-xbrl.zip") or fn.endswith("_xbrl.zip"):
        return LinkbaseType.PACKAGE

    return None


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
    return classify_linkbase(
        entry.document_type or "",
        entry.filename or "",
        entry.description or "",
    )


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
