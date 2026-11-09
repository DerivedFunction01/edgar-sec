"""Cross-filing stitched series assembly for the client surface."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.assembly import StitchedSeries, assemble_series
from edgar_sec.engine.xbrl.solve.scoping import FilingRef, base_form

if TYPE_CHECKING:
    from edgar_sec.apps.client.financials_stitched import StitchedFinancials


def expand_form_families(forms: str | Sequence[str] | None) -> tuple[str, ...]:
    """Requested forms expanded to each base form plus its amendment form.

    None means no form filter: the empty tuple the fetch layer reads
    as unfiltered, never a hardcoded family list.
    """
    if forms is None:
        return ()
    if isinstance(forms, str):
        requested = (forms,)
    else:
        requested = tuple(forms)
    expanded: list[str] = []
    for form in requested:
        base = base_form(form)
        for candidate in (base, f"{base}/A"):
            if candidate not in expanded:
                expanded.append(candidate)
    return tuple(expanded)


def _pool_filings(
    filings: Iterable[FilingAggregate],
) -> tuple[list[FilingRef], list[XbrlFact], dict[str, str]]:
    """Parse the selected filings once: their refs, facts, and item types."""
    from edgar_sec.apps.client.lineages import filing_ref
    from edgar_sec.engine.xbrl.parsing.filing_parser import (
        filing_item_types,
        parse_filing_xbrl,
    )

    refs: list[FilingRef] = []
    facts: list[XbrlFact] = []
    item_types: dict[str, str] = {}
    for filing in filings:
        ref = filing_ref(filing)
        if ref is None:
            continue
        refs.append(ref)
        parsed = parse_filing_xbrl(filing)
        facts.extend(parsed.facts)
        item_types.update(filing_item_types(parsed))
    return refs, facts, item_types


def build_filing_series(
    filings: Iterable[FilingAggregate], *, cik: str
) -> StitchedSeries:
    """Assemble the stitched series over already-selected filings.

    Each filing is parsed through the per-filing path and pooled; a
    filing without a report period cannot be placed and is excluded.
    """
    refs, facts, _item_types = _pool_filings(filings)
    return assemble_series(cik, facts, refs)


def build_stitched_financials(
    filings: Iterable[FilingAggregate], *, cik: str
) -> "StitchedFinancials":
    """Assemble the series and derive its unreported discrete quarters."""
    from edgar_sec.apps.client.financials_stitched import StitchedFinancials

    refs, facts, item_types = _pool_filings(filings)
    series = assemble_series(cik, facts, refs)
    return StitchedFinancials.from_series(series, item_types)
