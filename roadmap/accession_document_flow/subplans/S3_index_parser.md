# S3 — Pure HTML Index Parser

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S3**.
- Status: pure input/output contract; table-discovery and column-variant rules are
  finalized from the S0 stratified audit.
- Depends on: S0 evidence for parser scenarios and XBRL evidence labeling; the S2
  fixture store for captured page bytes.
- Non-blocking: S1 cohort schema, S2 capture store, S4 broker+pool, S5 snapshot.

## Objective

Parse a raw `-index.html` response into all `Document Format Files` and `Data Files`
rows plus separate bundle metadata. The parser is pure, stateless, and offline: no
network, no SQLite, no profile, no `document_storage`, and no snapshot imports.
Unknown or unsupported page structure is typed as unrecognized rather than returned as a
successful empty result.

## Typed interface

The parser needs the accession and source index URL as context: without them it
cannot derive stable entry IDs or decide whether a relative link remains inside
the accession archive. The URL and exact bytes are inputs, not side effects.

```python
@dataclass(frozen=True, slots=True)
class IndexPageInput:
    accession: AccessionNumber
    source_url: str
    response_bytes: bytes

@dataclass(frozen=True, slots=True)
class ParserDiagnostic:
    code: Literal[
        "unknown_table", "missing_column", "missing_sequence", "invalid_sequence",
        "duplicate_sequence", "out_of_order_sequence", "duplicate_filename",
        "invalid_size", "unsafe_href", "malformed_html", "unsupported_encoding",
    ]
    row_key: tuple[Literal["document_format", "data_file"], int] | None
    detail: str

@dataclass(frozen=True, slots=True)
class ParserDiagnostics:
    items: tuple[ParserDiagnostic, ...]
    suppressed_count: int

@dataclass(frozen=True, slots=True)
class ParsedIndexPage:
    accession: AccessionNumber
    source_url: str
    page_sha256: str
    entries: tuple[InventoryEntry, ...]
    bundle_url: str | None
    bundle_size: int | None
    xbrl_candidate_url: str | None
    diagnostics: ParserDiagnostics

@dataclass(frozen=True, slots=True)
class UnrecognizedIndexPage:
    accession: AccessionNumber
    source_url: str
    page_sha256: str
    diagnostics: ParserDiagnostics

@dataclass(frozen=True, slots=True)
class IndexParseFailure:
    accession: AccessionNumber
    source_url: str
    page_sha256: str
    diagnostic: ParserDiagnostic

IndexParseOutcome = ParsedIndexPage | UnrecognizedIndexPage | IndexParseFailure

parse_html_index(page: IndexPageInput) -> IndexParseOutcome
```

The parser computes `page_sha256` over the exact response bytes and calls S1's
`inventory_entry_id` for each row. That function hashes canonical JSON for
`[str(accession), table_kind, row_ordinal, page_sha256]`. `row_ordinal` is zero-based
among body rows within a table. Diagnostics keep
at most 32 items with detail truncated to 256 characters; `suppressed_count`
records omitted items. `ParsedIndexPage` may have zero entries only when a
recognized table is genuinely empty. No matching tables yields
`UnrecognizedIndexPage`; decoding/structural failure yields `IndexParseFailure`.
There is no per-accession row-count cap: every body row in both recognized tables
is returned, including rows without links and duplicate filenames/sequences.

## Parsing rules

- Discover `Document Format Files` and `Data Files` tables independently. A table whose
  header does not match either name is a candidate table; its presence changes
  diagnostics but does not create an entry.
- Emit one entry per body row, keyed by `(table_kind, row_ordinal)`; the first body
  row has ordinal zero, regardless of the source table's header rows.
- `href` is the original attribute value: `None` means no `href` attribute and an
  empty string remains an observed empty attribute; `has_link` is therefore exactly
  `href is not None` in the audit model.
- Do not filter rows by document type, extension, file size, or target relevance.
- Preserve row order and observed values; do not infer missing fields. Decode HTML
  entities and collapse runs of whitespace in text fields while preserving case.
- Parse sequence and size only as non-negative integers; invalid or absent values become
  null and produce a diagnostic. Duplicate/out-of-order sequences and duplicate filenames
  are retained and diagnosed, never repaired.
- Validate href origin: an `archive_url` is constructed only for same-accession SEC
  archive paths. Any href escaping the accession archive namespace is recorded but not
  promoted to `archive_url`; out-of-tree hrefs are flagged in diagnostics.
- Resolve bundle metadata from the page's advertised envelope URL and size, subject to
  the same-accession URL rule.
- Construct `xbrl_candidate_url` only when the audited URL rule applies. The candidate
  carries no existence claim; S0's decision record owns availability policy.

## Row-identity rules

- Sequence and filename are not keys. A row is identified by `(table_kind, row_ordinal)`
  for merge stability.
- Absent, duplicated, or out-of-order sequences are preserved as observations, not
  repaired.
- A row whose filename or type cannot be read is still emitted with nullable fields,
  because sequence/order can disambiguate it during bundle extraction.

## Error and refusal behavior

- No matching index tables returns `UnrecognizedIndexPage`, never a parsed empty page.
- Unsupported byte decoding or structural failure returns `IndexParseFailure`; malformed
  but recoverable HTML may parse with a `malformed_html` diagnostic.
- An absolute or relative href is retained verbatim. `archive_url` is populated only
  after URL resolution confirms the same scheme, host, and accession archive directory
  as `source_url`; unsafe links remain in `href` and produce a diagnostic.

## Inputs

- S2-captured response bytes served through read-only replay, or live survey responses
  recorded during S0; both are wrapped with the accession and exact source URL.
- The audit's table-discovery matrix supplies era-specific header names and column
  positions.

## Tests

Sanitized real-page fixtures from the S0 audit:

- missing sequence,
- duplicated sequence,
- duplicate filename,
- a page with hundreds of source rows, with every row returned,
- absent link,
- relative and absolute href,
- escaped text,
- missing and invalid size,
- `Data Files` table,
- empty table,
- unknown table,
- unsafe/out-of-tree href,
- malformed HTML,
- unrecognized page structure.

Additional tests:

- identical inputs produce identical entries and diagnostics,
- `parse_html_index` has no network, SQLite, profile, or snapshot dependencies,
- an unrecognized page returns `unrecognized` rather than `parsed` with an empty list,
- diagnostics remain bounded for adversarial input,
- stable entry ordering independent of parser traversal order.

## Acceptance criteria

`parse_html_index(IndexPageInput)` returns all document/data-file rows and separate
bundle metadata with no network, SQLite, profile, `document_storage`, or snapshot
imports. Unknown or unsupported page structure is typed as unrecognized rather than a
successful empty result. The parser is fully exercised against sanitized real-page
fixtures for every audit case.
