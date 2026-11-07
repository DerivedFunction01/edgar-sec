# `edgar_sec.domain.feeds` — Layer 1: feed event model

## Purpose

The single event vocabulary every SEC feed consumer shares: the current-filings
Atom feed, the structured-disclosure RSS feeds, and their monthly archives all
parse into `FilingEvent`, so the metadata refresh and the disclosure ledger
read the same shape instead of growing per-feed row types.

## Contracts

- **Events are as served, never canonical**: an event carries the form, company
  name, filing date, and acceptance datetime the feed served; it is not a
  submissions row and nothing a feed omits is inferred into one.
- **Identity is the normalized accession**: dedupe and joins key on the
  unhyphenated accession; per-source provenance accumulates in `sources` when
  the same accession arrives from more than one feed.
- **Acceptance is nullable and honest**: a feed that serves no acceptance
  datetime yields `None`, never a value fabricated from the filing date.
- **Parse failures are data**: a malformed entry is a `FeedParseFailure` in the
  parse outcome, never an exception that fails a run.

## Deliberate gaps

- **No feed fetching or parsing here**: transport lives in
  `edgar_sec.infra.sec_http`, parsing in `edgar_sec.engine.feeds`; this package
  only defines the records both sides agree on.
