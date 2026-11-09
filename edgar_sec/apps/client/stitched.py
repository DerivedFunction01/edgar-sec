"""Cross-filing stitched series assembly for the client surface."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.engine.xbrl.solve.assembly import StitchedSeries, assemble_series
from edgar_sec.engine.xbrl.solve.scoping import base_form


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


def build_filing_series(
    filings: Iterable[FilingAggregate], *, cik: str
) -> StitchedSeries:
    """Assemble the stitched series over already-selected filings.

    Each filing is parsed through the per-filing path and pooled; a
    filing without a report period cannot be placed and is excluded.
    """
    from edgar_sec.apps.client.lineages import filing_ref
    from edgar_sec.engine.xbrl.parsing.filing_parser import parse_filing_xbrl

    refs = []
    facts = []
    for filing in filings:
        ref = filing_ref(filing)
        if ref is None:
            continue
        refs.append(ref)
        facts.extend(parse_filing_xbrl(filing).facts)
    return assemble_series(cik, facts, refs)
