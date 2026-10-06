# S3 — Pure HTML Index Parser

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S3**.
- Status: typed contract and first structural parser pass are implemented against the
  standard SEC filing-page fixture.
- Depends on: S2's exact-byte fixture reader for replay. S7b supplies the iterative
  review loop; S0 evidence is required to finalize era/table rules and acceptance.
- Non-blocking: S1 cohort schema, S2 capture store, S4 broker+pool, S5 snapshot.

## Objective

Parse a raw `-index.html` response into child rows from `Document Format Files` and
`Data Files`, plus separate full-submission bundle metadata. The parser is pure,
stateless, and offline: no
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

`IndexPageInput`, parse-result records, diagnostics, `InventoryEntry`, and
`inventory_entry_id` are defined in `edgar_sec.domain.document_inventory.models`.
`parse_html_index` and `PARSER_FINGERPRINT` are owned by
`edgar_sec.engine.index_pages.parser`; the parser depends on domain records and the
generic HTML-tree engine API, never on a pipeline.

The parser computes `page_sha256` over the exact response bytes and calls S1's
`inventory_entry_id` for each child row. That function hashes canonical JSON for
`[str(accession), table_kind, row_ordinal, page_sha256]`. `row_ordinal` is zero-based
among source body rows within a table. The full-submission row is not a child entry;
its source ordinal is still counted while it populates separate bundle metadata.
Diagnostics keep at most 32 items with detail truncated to 256 characters;
`suppressed_count` records omitted items. A recognized child-empty table yields zero
entries rather than `UnrecognizedIndexPage`. No matching tables yields
`UnrecognizedIndexPage`; unsupported decoding yields `IndexParseFailure`. There is no
per-accession row-count cap: every child body row is returned, including rows without
links and duplicate filenames/sequences.

`PARSER_FINGERPRINT` in `edgar_sec.engine.index_pages.parser` is a stable
parser-implementation identity recorded by parser review artifacts and snapshot run
intent. Increment it whenever parsing semantics change; it is not derived from current
source-file bytes.

## Implementation and review loop

The initial parser uses a committed sanitized standard-layout fixture. S7b builds the
offline preview and parser-review command around pinned response bytes so subsequent
parser changes are comparable. S0 runs in parallel and supplies the era/table matrix;
the first pass is not final coverage or acceptance.

## Parsing rules

- Parse with the existing selectolax-backed `engine.document.html.tree.parse_html`,
  not regular expressions. Identify tables by their `summary` or preceding section
  label, then map columns by normalized header text (`Seq`, `Description`, `Document`,
  `Type`, `Size`). A plausible but unlabelled table is diagnostic only.
- Emit one child entry per body row, keyed by `(table_kind, row_ordinal)`; the first
  source body row has ordinal zero. Exclude only the `Complete submission text file`
  envelope row from child entries while retaining its ordinal and extracting bundle
  metadata.
- `href` is the original attribute value: `None` means no `href` attribute and an
  empty string remains an observed empty attribute; `has_link` is therefore exactly
  `href is not None` in the audit model.
- Do not filter rows by document type, extension, file size, or target relevance.
- Preserve row order and observed values; do not infer missing fields. Decode HTML
  entities and collapse runs of whitespace in text fields while preserving case.
- `document_label` is the full visible Document-cell text; `filename` is the first
  link's visible filename where present.
- Parse sequence and size only as non-negative integers; invalid or absent values become
  null and produce a diagnostic. Duplicate/out-of-order sequences and duplicate filenames
  are retained and diagnosed, never repaired.
- Validate href origin: resolve relative links against the source page and accept only
  a same-accession SEC archive path. For SEC `/ix?doc=...` links, validate the single
  `doc` query path and promote that archive path to `archive_url`; keep the observed
  wrapper value in `href`. Out-of-tree hrefs remain recorded and are diagnosed.
- Extract the full-submission URL and size from its advertised table row; never guess
  or synthesize the `.txt` path when the page does not advertise it.
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

- Exact uncompressed response bytes served by the S2 read-only fixture reader, or live
  survey responses recorded during S0; both are wrapped with the accession and exact
  source URL.
- The audit's table-discovery matrix supplies era-specific header names and column
  positions.

## Tests

The committed [standard-layout fixture](../../../tests/fixtures/document_inventory_index_page.html)
and later sanitized real-page fixtures from the S0 audit cover:

- missing sequence,
- duplicated sequence,
- duplicate filename,
- a page with hundreds of source rows, with every row returned,
- absent link,
- relative and absolute href,
- inline-XBRL `/ix?doc=` href unwrapped to the validated same-accession archive path,
- advertised full-submission row extracted as bundle metadata but excluded from child entries,
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
- table parsing uses the existing selectolax-backed engine API, not regex matching,
- an unrecognized page returns `unrecognized` rather than `parsed` with an empty list,
- diagnostics remain bounded for adversarial input,
- stable entry ordering independent of parser traversal order.

## Acceptance criteria

`parse_html_index(IndexPageInput)` returns all document/data-file rows and separate
bundle metadata with no network, SQLite, profile, `document_storage`, or snapshot
imports. Unknown or unsupported page structure is typed as unrecognized rather than a
successful empty result. The parser is fully exercised against sanitized real-page
fixtures for every audit case.
