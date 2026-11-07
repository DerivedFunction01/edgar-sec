# `edgar_sec.engine.feeds` — Layer 3: feed client and parsers

## Purpose

The shared feed core the current-filings refresh and the structured-disclosure
ledger both ride: one client that fetches SEC feed pages through the injected
`SecHttpClient`, and pure parsers that turn Atom (getcurrent) and RSS 2.0
(structured feeds and monthly archives) payloads into domain `FilingEvent`s.

## Contracts

- **One core, per-source parsers**: item 6 and item 7 share this client and
  event model; no consumer grows its own feed fetch or parse code.
- **Parsers are pure over payload bytes**: each carries a parser fingerprint and
  the payload digest in its outcome; a malformed entry is a recorded parse
  failure in that outcome, never a raised run failure.
- **Streaming iteration, key-only state**: the current-filings walk fetches,
  parses, and yields one page at a time; dedupe state is the set of accession
  keys already yielded, never held events or payloads, and monthly archives are
  parsed one file at a time.
- **Explicit stop conditions**: a walk stops on an empty page, on a page
  entirely at-or-before the caller's acceptance bound, or at the page cap from
  `sec.feeds.max_pages`.
- **Acceptance bounds are applied client-side**: the feed's filing-date bound
  is never trusted alone, because after-hours filings are deemed filed the
  next business day.

## Deliberate gaps

- **No cross-month dedupe state**: dedupe across archive months is decided
  store-side by the ledger pipeline at publish, not held in this layer.
- **No polling or scheduling**: this is a client, not a daemon; cadence wiring
  belongs to callers.
