# S0 — SEC Index Evidence Survey and Fixture Selection

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S0**.
- Status: evidence-gathering subplan; not the production index-parser implementation.
- Blocks: parser edge rules and XBRL availability policy in S3 and S6.
- Non-blocking: index fixture store (S2), cohort/schema contracts (S1), snapshot and review contracts (S5, S7, S12).

## Objective

Survey a stratified sample of accession `-index.html` pages, capture them with source
metadata, and publish a portable audit result plus a small set of sanitized fixtures.
The audit answers which HTML tables, fields, and edge cases a parser must handle and
whether HTML plus deterministic URL construction is sufficient to drive target planning
without runtime `index.json`.

## Inputs

- SEC as the sole live source during the survey. Normal tests remain offline and
  deterministic.
- A rate-limited `SecBroker`/`SecHttpClient` with retries, cache, and failure ledger.
  Live surveying is an explicit research step, not a production fetch path.
- The cohort fields required by the S1 contract: `source_cik`, `accession`, `form`,
  `filing_date`, `report_date`, and the contributing cohort-source identity.

## Sampling plan

Survey **100–200 pages**, stratified by era across:

| Stratum | Years | Rationale |
|---|---|---|
| Legacy | 1993–1999 | Concatenated SGML envelope; children listed without individual links; `SEQUENCE`/`TYPE` inside the bundle. |
| Transition | 2000–2004 | Historical filings may carry both individual files and an envelope; sequence order alone is not a safe primary selector. |
| Modern | 2005–present | Individual files, an envelope, and directory indexes coexist; direct links and `index.json`. |
| XML forms | any era | XSL-rendered `xsl*/.../*.xml` served as HTML. |

Stratification targets:

- Multiple forms per stratum; do not sample only `10-K`.
- Pages with both `Document Format Files` and `Data Files` tables.
- Pages with and without individual document links.
- Pages with absent, duplicated, or out-of-order sequences.
- Pages with absent, duplicated, or ambiguous filenames.
- At least one accession that appears in several co-filer CIK contexts.

Do not download XBRL ZIP bodies for this study.

## Collected per-page record

One row per sampled page:

| Field | Contract |
|---|---|
| `accession` | Canonical accession. |
| `source_url` | The resolved `-index.html` URL used. |
| `page_digest` | `file_sha256` of the exact response bytes. |
| `byte_size` | Response size in bytes. |
| `era` | Era stratum name. |
| `form` | Filing form. |
| `table_kind` | `document_format` and/or `data_file`. |
| `has_link` | Per-row: does the row advertise an individual href? |
| `sequence` | Observed sequence; note absent/duplicated/out-of-order. |
| `document_type` | Observed statutory type. |
| `description` | Observed description. |
| `filename` | Observed filename; note absent/duplicated. |
| `href` | Observed href; note absolute or relative. |
| `byte_size` | Observed child size. |
| `bundle_url` | Advertised full-submission envelope URL. |
| `bundle_size` | Advertised envelope size. |
| `xbrl_zip_url` | Deterministically constructed candidate URL. |
| `xbrl_zip_exists` | Existence evidence only (HEAD probe or `index.json` listing), never a fetched body. |
| `parser_exception` | None, or a typed parse error. |
| `unrecognized` | Whether the page's structure could not be recognized at all. |

## Audit questions

The audit must answer each question explicitly, with evidence rows supporting the
answer:

1. **One parser, all eras.** Can a single HTML parser preserve the full
   `Document Format Files` and `Data Files` tables across eras, including the legacy
   no-link case?
2. **Absent or duplicated fields.** Which fields are actually absent or duplicated
   and which rows cannot be identified by sequence or filename alone?
3. **Bundle versus direct.** Does the page advertise enough information to distinguish
   direct-file retrieval from bundle-plus-sequence retrieval?
4. **XBRL ZIP construction.** Can the `*-xbrl.zip` URL pattern be constructed
   consistently, and is its per-accession existence known at planning time? A URL
   pattern alone is not proof of package contents. If presence requires fetching the
   package, the plan records a constructed candidate rather than an observed item;
   use a rate-limited body-free probe only if SEC supports it.

## Portability requirement

Results and fixtures must be usable without re-running SEC requests:

- Tracked fixtures are minimal, sanitized, real-source-derived responses with their
  URL, digest, size, and capture metadata.
- The full survey corpus lives in a generated SQLite database under a transient path
  and is not committed; only the small portable result table and selected fixtures are
  tracked.
- The audit result is a machine-readable table plus a short decision record.

## XBRL decision record

The decision record produced by S0 states which of the following is the metadata
source of truth for package requests:

- HTML-only, with `*-xbrl.zip` as a constructed candidate whose existence is not
  asserted; or
- HTML plus a sampled `index.json` confirmation for a subset of accessions; or
- HTML plus a rate-limited HEAD probe result.

`index.json` may be used at runtime only if the audit identifies a concrete required
metadata gap that the HTML page and deterministic URL construction cannot cover.
Do not claim universal HTML coverage.

## Deliverables

1. Audit result table (tracked).
2. Selected sanitized real-page fixtures with capture metadata (tracked).
3. Query fixtures for: one accession, one filing form, child document types, and one
   co-filer accession split across plan cohorts. These validate snapshot access paths
   as well as HTML parsing.
4. XBRL decision record.
5. A short note estimating index-page parse cost and response memory for tuning the
   S4 worker budget.

## Tests

Tests remain offline and deterministic; they replay the audit result table and query
fixtures, not the live survey:

- Parse cost and response size distribution summarize across strata.
- Fixture selection covers the audit's observed shapes.
- Query fixtures validate snapshot access paths.

## Acceptance criteria

Every audit row records source URL and page digest. The sample includes:

- legacy no-link,
- 2000–2004 sequence/type disagreement cases,
- modern direct links, and
- `Data Files`.

ZIP-path conclusions distinguish URL construction from per-accession availability. If
the audit disproves HTML sufficiency for a required target, the inventory source
contract is amended before the parser is implemented.
