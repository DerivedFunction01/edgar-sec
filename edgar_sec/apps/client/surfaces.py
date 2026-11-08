"""Feed-ledger, search, and earnings surfaces of the Edgar facade.

Thin delegations over the feeds ledger reader, the live EFTS client,
the local text index, and the earnings-exhibit extractor, composed
into ``Edgar`` by inheritance.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from edgar_sec.apps.client.companyfacts import CompanyFacts
    from edgar_sec.apps.client.efts import EftsCapture, EftsQuery, EftsSearchResult
    from edgar_sec.apps.client.feeds import FeedEventsResult
    from edgar_sec.apps.client.frames import FrameResult
    from edgar_sec.domain.identity import Cik
    from edgar_sec.domain.document.aggregate import FilingAggregate
    from edgar_sec.engine.forms.earnings.models import EarningsExhibitResult
    from edgar_sec.infra.sec_http.client import SecHttpClient


class FeedSearchSurfaces:
    """Feed-ledger reads and search surfaces hosted by the ``Edgar`` facade."""

    artifacts_root: Path | None
    sec_client: SecHttpClient

    def frames(
        self,
        taxonomy: str,
        tag: str,
        unit: str,
        period: str,
    ) -> "FrameResult":
        """Fetch one SEC frame's cross-company aggregates for a concept.

        Cross-check only: rows are SEC aggregates carrying the frame
        identity as provenance, never per-filing facts.
        """
        from edgar_sec.apps.client.frames import fetch_frame

        return fetch_frame(taxonomy, tag, unit, period, client=self.sec_client)

    def company_facts(self, cik: str | int | "Cik") -> "CompanyFacts":
        """Fetch one company's full SEC facts document, as reported.

        Cross-check only: rows are the SEC's own reported values with
        per-point provenance, never per-filing parsed facts.
        """
        from edgar_sec.apps.client.companyfacts import fetch_company_facts

        return fetch_company_facts(cik, client=self.sec_client)

    def feed_events(
        self,
        *,
        forms: Sequence[str] | str = (),
        sources: Sequence[str] | str = (),
        filed_from: date | str | None = None,
        filed_to: date | str | None = None,
        limit: int | None = None,
    ) -> "FeedEventsResult":
        """Structured-disclosure events from the published feeds ledger.

        Read-only: an unstored ledger is reported as absence
        (``ledger_present`` is False), never repaired with a live fetch.
        """
        from edgar_sec.apps.client.feeds import read_feed_events

        return read_feed_events(
            self.artifacts_root,
            forms=(forms,) if isinstance(forms, str) else tuple(forms),
            sources=(sources,) if isinstance(sources, str) else tuple(sources),
            filed_from=filed_from,
            filed_to=filed_to,
            limit=limit,
        )

    def full_text_search(
        self,
        query: EftsQuery | None = None,
        *,
        text: str = "",
        forms: Sequence[str] = (),
        ciks: Sequence[str | int] = (),
        tickers: Sequence[str] = (),
        items: Sequence[str] = (),
        startdt: str | None = None,
        enddt: str | None = None,
        sec_syntax: str | None = None,
        max_hits: int | None = None,
        exhaustive: bool = False,
    ) -> EftsSearchResult:
        """Search the SEC full-text index live; nothing is persisted.

        Accepts an ``EftsQuery`` or query parts; tickers resolve to CIKs.
        ``exhaustive`` date-slices past the ceiling, requiring a date pair.
        """
        from edgar_sec.apps.client.efts import (
            EftsQuery,
            full_text_search,
            search_all,
        )

        resolved_ciks = tuple(str(c) for c in ciks)
        for ticker in tickers:
            from edgar_sec.apps.client.resolver import resolve_entity_profile

            profile = resolve_entity_profile(ticker, self.artifacts_root)
            if profile.cik.value == 1 and profile.name == str(ticker):
                raise ValueError(f"unresolved ticker: {ticker!r}")
            resolved_ciks += (profile.cik.to_10digit(),)
        if query is None:
            query = EftsQuery(
                text=text,
                forms=tuple(str(f) for f in forms),
                ciks=resolved_ciks,
                items=tuple(str(i) for i in items),
                startdt=startdt,
                enddt=enddt,
                sec_syntax=sec_syntax,
            )
        elif resolved_ciks:
            query = EftsQuery(
                text=query.text,
                forms=query.forms,
                ciks=tuple(query.ciks) + resolved_ciks,
                items=query.items,
                startdt=query.startdt,
                enddt=query.enddt,
                sec_syntax=query.sec_syntax,
            )
        if exhaustive:
            return search_all(query, client=self.sec_client, exhaustive=True)
        return full_text_search(query, client=self.sec_client, max_hits=max_hits)

    def capture_full_text_search(
        self,
        query: EftsQuery,
        *,
        exhaustive: bool = False,
    ) -> EftsCapture:
        """Run a search and write its explicit capture artefact.

        The only persistence path for a search: a plain
        ``full_text_search`` call writes nothing.
        """
        from edgar_sec.apps.client.efts import capture_full_text_search

        return capture_full_text_search(
            query,
            client=self.sec_client,
            artifacts_root=self.artifacts_root,
            exhaustive=exhaustive,
        )

    def search_documents(
        self,
        query: str,
        *,
        mode: str = "bm25",
        accessions: tuple[str, ...] = (),
        ciks: tuple[int, ...] = (),
        forms: tuple[str, ...] = (),
        date_from: str | None = None,
        date_to: str | None = None,
        attachment_scope: str = "all_documents",
        limit: int = 50,
    ):  # noqa: ANN202 - SearchResult is imported lazily to keep facade light
        """Search our acquired holdings through the materialized text index.

        Every result carries a coverage block; a scoped target absent from
        the corpus is reported not-in-corpus, never as a plain no-match.
        """
        from edgar_sec.apps.client.text_search import search_documents

        return search_documents(
            query,
            mode=mode,
            artifacts_root=self.artifacts_root,
            accessions=accessions,
            ciks=ciks,
            forms=forms,
            date_from=date_from,
            date_to=date_to,
            attachment_scope=attachment_scope,
            limit=limit,
        )

    def earnings_exhibit(self, filing: "FilingAggregate") -> "EarningsExhibitResult":
        """Extract one current-report filing's earnings exhibit.

        Returns the exhibit identity, its structured tables, its headline
        figures, and a review signal for everything not structured.
        """
        from edgar_sec.engine.forms.earnings.extraction import (
            extract_earnings_exhibit,
        )

        return extract_earnings_exhibit(filing)
