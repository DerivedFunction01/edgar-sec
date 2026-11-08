# Earnings-exhibit extraction drive — Step 7 held-out record

Run 2026-11-08, compute on Colab High-RAM (lilac-reef-93 and ruby-anchor-64,
caller secforms:nw15; ruby-meteor-98 Standard never used; no session started,
acquired, or released). Code: branch impl/nw-item15-earnings at f96994d2
(final detail pass overlay tar SHA-256
5dd659f8424a12f6f5b20335b62cd5d9ab651e01a4f47e9a9c0e89766d1fabd5,
hash-verified on-session). Extraction at 8 workers on-session.

## Findings

1. **Held-out coverage is full.** 260 filings — every Step 6 corpus filing
   not in the 7-specimen fixture set — extracted and compared against the
   Step 6 record's measured expectations (effective exhibit, per-table
   inventory and roles, headline figures). Two legs: 147 filings on lilac,
   then the 113 whose index fetches SEC rate-limited (HTTP 429) on ruby's
   separate egress via the governed SecHttpClient (index errors: 0).
2. **Deterministic classes meet the record exactly.** Headline figures:
   statement-table locus 51/51 exact, summary-table locus 2/2 exact
   (label + value as printed). Table counts match for every exhibit-bearing
   filing (81 html-tables, 18 no-tables, 1 text-or-positioned, 18 6-K).
   Exhibit identity matches 117/118 (see divergence 1).
3. **Review-signal classes behave as scoped.** 6-K: tables 18/18 extracted,
   headline figures served 0/18 (IFRS vocabulary posture). No-EX-99
   filings: 142/142 honest absence (`no_ex99_exhibit`). Prose/partial-locus
   filings serve no headline; every unextracted remainder is accounted by a
   named signal — headline_not_extracted 28, no_statement_tables 25,
   text_exhibit 9, sixk_headline_vocabulary 8, exhibit_fallback 1 in the
   merged drive. Fallback geometries: zero in the drive, matching the
   record's zero — no table was dropped unaccounted.
4. **Table indices are exhibit-local positions.** The first drive pass
   flagged 9 filings on table roles; the cause was index provenance — the
   extractor served the geometry machinery's `table_index` (which skips
   numbers) while the record inventories by enumeration position, so every
   table after a skip misaligned. Fixed in f96994d2 (positions key tables,
   fallback signals, and headline source rows); all 9 filings then match
   on tables, roles (as sets), and headlines exactly.

## Divergences from the Step 6 record

1. **0001144204-15-062073 (8-K): record artifact, not an extractor miss.**
   The record's `effective_exhibit` is `tex99-1logo.jpg` (an image, 0
   tables); the extractor serves the filing's actual EX-99.1,
   `v423396_ex99-1.htm`, with its 12 tables. The measurement's exhibit
   choice, not the extraction, diverges.
2. **Fixture manifest correction (landed with the build):** the PDF
   specimen 0001279569-24-000173's `effective_exhibit` read `ex991.htm`
   while its stored payload is `ex991.pdf`; corrected in the manifest.

## Venue notes

- The task brief's caller string `secforms-nw15` is refused by the caller
  registry; the governed lane form `secforms:nw15` was used.
- An unthrottled parallel fetch leg drew SEC HTTP 429 on lilac's egress;
  the governed-client leg on ruby completed the set with zero index
  errors. A redundant governed leg on lilac also completed (4 errors).
- Local gate: `check.py tests/engine/forms tests/apps/client` — 424
  passed, all scanners clean (plus the current-family taxonomy tests).
