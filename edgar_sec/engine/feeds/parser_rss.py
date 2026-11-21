"""Pure RSS 2.0 parser for the structured-disclosure feeds and archives.

Live feeds and monthly archives serve one item shape; the two adapters differ
only in the source id they stamp. Acceptance is served as an ET wall-clock
stamp and is normalized to UTC.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from edgar_sec.domain.feeds.models import (
    SOURCE_MONTHLY_ARCHIVE,
    FeedParseFailure,
    FeedParseOutcome,
    FilingEvent,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.sec_urls import STRUCTURED_FEED_FILES
from edgar_sec.foundation.hashing import sha256_bytes

PARSER_FINGERPRINT = "feed-rss-v1"

_EDGAR = "{https://www.sec.gov/Archives/edgar}"
_EASTERN = ZoneInfo("America/New_York")


def _child_text(item: ET.Element, name: str) -> str:
    filing = item.find(f"{_EDGAR}xbrlFiling")
    if filing is None:
        return ""
    child = filing.find(f"{_EDGAR}{name}")
    return (child.text or "").strip() if child is not None else ""


def _acceptance(item: ET.Element) -> datetime | None:
    stamp = _child_text(item, "acceptanceDatetime")
    if stamp:
        parsed = datetime.strptime(stamp, "%Y%m%d%H%M%S")
        return parsed.replace(tzinfo=_EASTERN).astimezone(UTC)
    pub_date = (item.findtext("pubDate") or "").strip()
    if pub_date:
        parsed = parsedate_to_datetime(pub_date)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_EASTERN)
        return parsed.astimezone(UTC)
    return None


def _item_event(item: ET.Element, source: str) -> FilingEvent:
    accession = _child_text(item, "accessionNumber")
    cik = _child_text(item, "cikNumber")
    filing_date = _child_text(item, "filingDate")
    if not accession or not cik or not filing_date:
        raise ValueError("item lacks an accession, CIK, or filing date")
    return FilingEvent(
        accession=AccessionNumber.from_any(accession),
        cik=Cik.from_raw(cik),
        form=_child_text(item, "formType"),
        company_name=_child_text(item, "companyName"),
        filing_date=datetime.strptime(filing_date, "%m/%d/%Y").date(),
        acceptance_datetime=_acceptance(item),
        link=(item.findtext("link") or "").strip(),
        sources=(source,),
    )


def parse_rss_feed(payload: bytes, source: str) -> FeedParseOutcome:
    """Parse one RSS payload under ``source``; malformed items become failures."""
    events: list[FilingEvent] = []
    failures: list[FeedParseFailure] = []
    try:
        context = ET.iterparse(io.BytesIO(payload), events=("end",))
        index = 0
        for _event, element in context:
            if element.tag != "item":
                continue
            try:
                events.append(_item_event(element, source))
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


def parse_live_feed(payload: bytes, feed: str) -> FeedParseOutcome:
    """Parse one live structured-disclosure feed, stamped with its feed id."""
    if feed not in STRUCTURED_FEED_FILES:
        raise ValueError(f"unknown structured-disclosure feed: {feed!r}")
    return parse_rss_feed(payload, feed)


def parse_archive_month(payload: bytes, year: int, month: int) -> FeedParseOutcome:
    """Parse one monthly archive payload under the archive source id."""
    if not 1 <= int(month) <= 12:
        raise ValueError(f"month must be in 1..12, got {month!r}")
    return parse_rss_feed(payload, SOURCE_MONTHLY_ARCHIVE)


__all__ = [
    "PARSER_FINGERPRINT",
    "parse_archive_month",
    "parse_live_feed",
    "parse_rss_feed",
]
