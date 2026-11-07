"""Pure Atom parser for the getcurrent current-filings feed.

Form, company, and CIK come from the entry title; filing date and accession
come from the summary; the entry ``updated`` stamp is the acceptance datetime.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime

from edgar_sec.domain.feeds.models import (
    SOURCE_CURRENT_FILINGS,
    FeedParseFailure,
    FeedParseOutcome,
    FilingEvent,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.foundation.text.dates import ISO_DATE_RE

PARSER_FINGERPRINT = "feed-atom-v1"

_ATOM = "{http://www.w3.org/2005/Atom}"
_TITLE_RE = re.compile(
    r"^(?P<form>.+?) - (?P<company>.*) \((?P<cik>\d+)\) \((?P<role>[^)]+)\)$"
)
_FILED_LABEL_RE = re.compile(r"Filed:</b>\s*")
_ACCESSION_RE = re.compile(r"AccNo:</b>\s*([0-9][0-9-]*)")


def _text(entry: ET.Element, name: str) -> str:
    child = entry.find(f"{_ATOM}{name}")
    return (child.text or "").strip() if child is not None else ""


def _entry_event(entry: ET.Element, source: str) -> FilingEvent:
    title = _text(entry, "title")
    match = _TITLE_RE.match(title)
    if match is None:
        raise ValueError(f"entry title does not parse: {title!r}")
    summary = _text(entry, "summary")
    label = _FILED_LABEL_RE.search(summary)
    filed = ISO_DATE_RE.search(summary, label.end()) if label is not None else None
    accession = _ACCESSION_RE.search(summary)
    if filed is None or accession is None:
        raise ValueError("entry summary lacks a filing date or accession")
    updated = _text(entry, "updated")
    acceptance: datetime | None = None
    if updated:
        parsed = datetime.fromisoformat(updated)
        acceptance = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
        acceptance = acceptance.astimezone(UTC)
    link = ""
    for link_element in entry.findall(f"{_ATOM}link"):
        link = link_element.get("href", "")
        if link:
            break
    return FilingEvent(
        accession=AccessionNumber.from_any(accession.group(1)),
        cik=Cik.from_raw(match.group("cik")),
        form=match.group("form").strip(),
        company_name=match.group("company").strip(),
        filing_date=date.fromisoformat(filed.group(0)),
        acceptance_datetime=acceptance,
        link=link,
        sources=(source,),
    )


def parse_atom_feed(
    payload: bytes, source: str = SOURCE_CURRENT_FILINGS
) -> FeedParseOutcome:
    """Parse one getcurrent Atom page; malformed entries become failures."""
    events: list[FilingEvent] = []
    failures: list[FeedParseFailure] = []
    try:
        context = ET.iterparse(io.BytesIO(payload), events=("end",))
        index = 0
        for _event, element in context:
            if element.tag != f"{_ATOM}entry":
                continue
            try:
                events.append(_entry_event(element, source))
            except ValueError as error:
                failures.append(FeedParseFailure(source, index, str(error)))
            index += 1
            element.clear()
    except ET.ParseError as error:
        failures.append(
            FeedParseFailure(source, -1, f"malformed feed payload: {error}")
        )
    return FeedParseOutcome(
        source=source,
        events=tuple(events),
        failures=tuple(failures),
        payload_sha256=sha256_bytes(payload),
        parser_fingerprint=PARSER_FINGERPRINT,
    )


__all__ = ["PARSER_FINGERPRINT", "parse_atom_feed"]
