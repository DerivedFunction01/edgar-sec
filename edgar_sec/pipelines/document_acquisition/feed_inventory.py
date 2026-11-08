"""Streaming inventory extraction from SEC Feed daily tarballs.

Bundles are read one at a time from the tar stream; only a bounded header
segment of each bundle is read, and nothing is extracted to disk.
"""

from __future__ import annotations

import re
import tarfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from edgar_sec.domain.identity import AccessionNumber

_HEADER_READ_BYTES = 65536

_LISTING_HREF_RE = re.compile(r'href="([^"]+\.nc\.tar\.gz)"')
_UNIT_DATE_RE = re.compile(r"(\d{4})(\d{2})(\d{2})\.nc\.tar\.gz$")
_ACCESSION_RE = re.compile(r"^ACCESSION NUMBER:\s*(\S+)", re.MULTILINE)
_FORM_RE = re.compile(
    r"^(?:CONFORMED SUBMISSION TYPE|FORM TYPE):\s*(.+?)\s*$", re.MULTILINE
)
_FILED_RE = re.compile(r"^FILED AS OF DATE:\s*(\d{4})(\d{2})(\d{2})", re.MULTILINE)
_CIK_RE = re.compile(r"^CENTRAL INDEX KEY:\s*(\d+)", re.MULTILINE)

#: The Feed's own bundle format: SGML tag-value headers in flat ``.nc``
#: members. The colon-header form above is the per-filing text rendering;
#: both are served shapes, so both parse.
_SGML_ACCESSION_RE = re.compile(r"<ACCESSION-NUMBER>\s*([^\s<]+)")
_SGML_FORM_RE = re.compile(r"<TYPE>\s*([^\s<]+)")
_SGML_FILED_RE = re.compile(r"<FILING-DATE>\s*(\d{4})(\d{2})(\d{2})")
_SGML_CIK_RE = re.compile(r"<CIK>\s*(\d+)")

#: Tarball members that carry submission bundles; anything else in the
#: tarball (correspondence files, directories) is not a bundle.
_BUNDLE_SUFFIXES = (".nc", ".txt")


@dataclass(frozen=True, slots=True)
class FeedUnit:
    """One per-day Feed tarball unit named by a directory listing."""

    day: date
    filename: str


@dataclass(frozen=True, slots=True)
class FeedInventoryRecord:
    """One SGML bundle inventoried from a Feed tarball."""

    accession: str
    cik: str
    form: str
    filing_date: date
    feed_date: date
    bundle_id: str
    archive_sha256: str


@dataclass(frozen=True, slots=True)
class BundleInventory:
    """The inventory outcome of one streamed tarball."""

    records: tuple[FeedInventoryRecord, ...]
    malformed_bundles: int


def parse_listing_units(listing_text: str) -> tuple[FeedUnit, ...]:
    """Enumerate the per-day tarball units named by one listing page."""
    units: dict[str, FeedUnit] = {}
    for match in _LISTING_HREF_RE.finditer(listing_text):
        filename = match.group(1).rsplit("/", 1)[-1]
        date_match = _UNIT_DATE_RE.search(filename)
        if date_match is None:
            continue
        year, month, day = (int(part) for part in date_match.groups())
        try:
            unit_day = date(year, month, day)
        except ValueError:
            continue
        units[filename] = FeedUnit(day=unit_day, filename=filename)
    return tuple(units[name] for name in sorted(units))


def _parse_colon_header(header_text: str) -> tuple[str, str, str, date] | None:
    """Parse the colon-field SEC header form; ``None`` when incomplete."""
    accession_match = _ACCESSION_RE.search(header_text)
    form_match = _FORM_RE.search(header_text)
    filed_match = _FILED_RE.search(header_text)
    cik_match = _CIK_RE.search(header_text)
    if not (accession_match and form_match and filed_match and cik_match):
        return None
    try:
        accession = AccessionNumber.from_any(accession_match.group(1)).raw
        filing_date = date(
            int(filed_match.group(1)),
            int(filed_match.group(2)),
            int(filed_match.group(3)),
        )
    except ValueError:
        return None
    return (
        accession,
        cik_match.group(1).zfill(10),
        form_match.group(1),
        filing_date,
    )


def _parse_sgml_header(header_text: str) -> tuple[str, str, str, date] | None:
    """Parse the SGML tag-value header form; ``None`` when incomplete."""
    accession_match = _SGML_ACCESSION_RE.search(header_text)
    form_match = _SGML_FORM_RE.search(header_text)
    filed_match = _SGML_FILED_RE.search(header_text)
    cik_match = _SGML_CIK_RE.search(header_text)
    if not (accession_match and form_match and filed_match and cik_match):
        return None
    try:
        accession = AccessionNumber.from_any(accession_match.group(1)).raw
        filing_date = date(
            int(filed_match.group(1)),
            int(filed_match.group(2)),
            int(filed_match.group(3)),
        )
    except ValueError:
        return None
    return (
        accession,
        cik_match.group(1).zfill(10),
        form_match.group(1),
        filing_date,
    )


def parse_bundle_header(header_text: str) -> tuple[str, str, str, date] | None:
    """Parse one bundle's SEC header, in either served header form."""
    parsed = _parse_colon_header(header_text)
    if parsed is not None:
        return parsed
    return _parse_sgml_header(header_text)


def iter_bundle_headers(tarball_path: Path) -> Iterator[tuple[str, str]]:
    """Yield ``(bundle_id, header_text)`` per SGML bundle, streamed."""
    with open(tarball_path, "rb") as handle:
        with tarfile.open(fileobj=handle, mode="r|gz") as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith(_BUNDLE_SUFFIXES):
                    continue
                stream = tar.extractfile(member)
                if stream is None:
                    continue
                header = stream.read(_HEADER_READ_BYTES)
                yield member.name, header.decode("utf-8", errors="replace")


def inventory_tarball(
    tarball_path: Path, *, feed_date: date, archive_sha256: str
) -> BundleInventory:
    """Inventory every parseable SGML bundle in one tarball, streamed."""
    records: list[FeedInventoryRecord] = []
    malformed = 0
    for bundle_id, header_text in iter_bundle_headers(tarball_path):
        parsed = parse_bundle_header(header_text)
        if parsed is None:
            malformed += 1
            continue
        accession, cik, form, filing_date = parsed
        records.append(
            FeedInventoryRecord(
                accession=accession,
                cik=cik,
                form=form,
                filing_date=filing_date,
                feed_date=feed_date,
                bundle_id=bundle_id,
                archive_sha256=archive_sha256,
            )
        )
    return BundleInventory(records=tuple(records), malformed_bundles=malformed)


__all__ = [
    "BundleInventory",
    "FeedInventoryRecord",
    "FeedUnit",
    "inventory_tarball",
    "iter_bundle_headers",
    "parse_bundle_header",
    "parse_listing_units",
]
