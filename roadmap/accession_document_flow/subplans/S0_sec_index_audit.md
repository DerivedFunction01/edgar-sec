# S0 — SEC Index Evidence Survey and Fixture Selection

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S0**.
- Status: **not complete**. The offline parser baseline and capture/replay machinery
  exist, but no tracked stratified audit table or audit-selected historical fixture set
  is present. This status does not imply that a live SEC survey has been run.
- Depends on: S1 cohort projection for candidates and S2 raw-page capture/replay.
- Blocks: production parser edge rules in S3 and the XBRL availability policy in S6.
- Does not depend on: S5 inventory snapshots, S7a fixture CLI, S7b parser review
  artifacts, later S7 review surfaces, or S12 CLI artifacts.

## Current evidence and next step

- `roadmap/accession_document_flow/implementation.md` records illustrative legacy and
  modern accession examples and explicitly distinguishes them from universal coverage.
- `tests/fixtures/document_inventory_index_page.html` is the committed parser fixture;
  `tests/engine/index_pages/test_parser.py` also exercises synthetic structural cases.
- S2 capture/replay is implemented in `edgar_sec/pipelines/document_inventory/fixture_store/`;
  its offline contracts are tested under `tests/pipelines/document_inventory/fixture_store/`.
- The tracked tree contains no portable S0 audit result or audit-selected historical
  fixture manifest. The existing fixture/tests do not establish 100–200-page era/form
  coverage or a live SEC finding.
- Four workspace-local review runs have been inspected below. They are useful for
  selecting decision-tree cases, but their presence does not make the result portable
  or satisfy the raw-page integrity gate.
- Next: verify source integrity, reconstruct parser rows from captured pages, and run
  the selected cases through the relevant S6/S9 decision paths before committing a
  portable audit table and fixtures.

## Analysis plan for review runs

### Run inventory (workspace observation, 2026-10-12)

- The four `index-page-v2` runs contain 2,500, 2,500, 1,000, and 2,000 cases. The two
  2,500-case runs have identical parsed rows and observations for all shared inputs.
  The 1,000- and 2,000-case runs overlap the first by 194 and 375 input identities.
  Together these runs contain 4,931 distinct `(accession, request URL, response
  digest)` identities; run totals must not be added as unique coverage. The run IDs are
  `run-20261012_073510`, `run-20261012_081346`, `run-20261012_083608`, and
  `run-20261012_100448` respectively.
- The analyzer found a single catalog form context for every case. Its summary can
  screen direct, bundle-sequence, observed-href-unresolved, and unresolved routes, plus
  sequence/type and Form 4 path patterns. It does not execute S6 target matching or S9
  acquisition, so it identifies candidate cases rather than validating those decisions.
- In the 2,000-case run, the analyzer reports 43 sequence-1 exhibit inversions and
  3,105 sequence-2-or-3 exhibit rows. In the 1,000-case run it reports 283 Form 4
  alternative primary-path pairs. These are per-run findings, not verified strata
  counts; the runs are not yet raw-integrity checked or stratified for S0.
- Across the distinct input identities, observed `document_format` rows include
  `0001.txt` 34 times at sequence 1 and secondary `0002.txt` through `0007.txt` 19,
  11, 10, 7, 6, and 4 times respectively. The latter rows have exhibit types and
  matching sequence numbers. Review-run URL checks and fixture coverage now confirm
  accession-prefixed child leaves for positive numbered filenames beyond sequence 7,
  including a `.pdf` child. This establishes the observed `<accession>-<num>.<ext>`
  mapping for the reviewed cases; it does not make a display filename alone a locator.
  Positive `0001` links are direct when the prefixed URL is observed or constructed from
  exact catalog primary metadata. Exact primary `0000.txt`/`.htm` remain placeholder
  cases requiring observed bundle sequence evidence.
- These local outputs are parser-review evidence only. Their persisted digests do not
  establish that the stored source bytes match `response_sha256`, and no captured-page
  reconstruction has been recorded. The link-mapping finding does not support a broad
  S0 historical-parser acceptance claim.

### Hypotheses to test, not facts to assume

The superseded `roadmap/old/execution_1.md` §1.1 (lines 48–347) makes these claims from
the catalog and live header audits. S0 must test them against raw-verified review cases
and the catalog:

- H1: sequence-1 inversion (sequence-1 exhibit, a later primary) occurs mainly in
  2000–2004 and is zero after 2005. The current 2,000-case run has 43 candidate
  inversions; only raw-verified, era/form-stratified cases can adjudicate this claim.
- H2: 1993–1999 filings are monolithic bundles with no individual links.
- H3: post-2005 exhibit-like primary filenames (for example `ex99-1.htm`, `bylaw.htm`)
  are registered as the primary form type in the SEC header.
- H4: statutory exhibit regex and form-token patterns separate exhibits from ticker or
  company names. The regex and token patterns must be checked against observed
  filenames, not adopted as given.

### Steps

1. **Integrity.** For each case, confirm `response_sha256` matches the raw bytes of
   the source record. Record any mismatch between `source.inert.html` and the
   original response, since the file name suggests inert sanitization.
2. **Table reconstruction.** Re-parse each `source.inert.html` with the existing
   selectolax tree (`engine.document.html.tree`), without the production
   `parse_html_index`, and compare rows to `entries.csv` on `table_kind`,
   `row_ordinal`, `sequence`, `document_type`, `filename`, `href`, and `byte_size`.
   Any difference is either a parser regression or capture drift and must be
   recorded.
3. **Link consistency.** Check that `href`'s basename equals `filename`, that
   `archive_url` is the same-accession archive path resolved from `href`, that `/ix?doc=`
   wrappers unwrap to the archive path, and that `bundle_url` is the advertised
   `.txt` row, not a synthesized path. Classify each mismatch.
4. **Sequence versus type.** Join each accession to its S1 catalog form. For each
   case, compare the sequence-1 `document_type` with the form and family aliases. Report
   the first sequence whose type matches the form, and every case where sequence 1
   is an exhibit (`EX-*`, `GRAPHIC`, `ZIP`) while a later row matches the form.
   Separate duplicate and out-of-order sequences from displacement. Include `0001.txt`
   primary cases separately from sequence-numbered exhibits `0002.txt`–`0007.txt`; do
   not use filename alone to label a retrieval placeholder.
5. **Edge cases.** Tabulate per era: `unsafe_href` diagnostics, `bundle_url: null`,
   empty or ambiguous `filename`, duplicate filenames, duplicate or out-of-order
   sequences, zero-row tables, empty `document_label`, and cases with exhibit-like
   or form-name-like primary filenames.
6. **Era cross-tab.** Cross-tabulate steps 3–5 by era (legacy, transition, modern).
   Each hypothesis H1–H4 gets a supporting count, a counter-example list, and a
   verdict.
7. **Filing-catalog policy input.** For the final goal, quantify how many sampled
   primary documents have exhibit-like or form-name-like filenames that the current
   `filing_catalog` filters would exclude (filters are in
   `edgar_sec/domain/filing_catalog/filters.py`), and list them by era and form. This
   is the evidence for a selection-policy change that admits such filenames. The
   change itself is a later code task.

### Output and tooling

- The offline review analyzer can analyze selected review runs together and compare
  shared inputs. The review console accepts multiple run selections. Use run-level
  counts for screening; deduplicate shared input identities before reporting corpus
  totals.
- Step 1 results decide whether the rest of the analysis is trusted. Steps 2–7 do not
  start until step 1 is clean or its mismatches are explained.
- The tracked result is a sanitized portable table, decision record, and selected
  fixtures under `tests/fixtures/`, produced only after the analysis.

## Objective

Survey a stratified sample of accession `-index.html` pages, capture them with source
metadata, and publish a portable audit result plus a small set of sanitized fixtures.
The audit answers which HTML tables, fields, and edge cases a parser must handle and
whether HTML plus deterministic URL construction is sufficient to drive target planning
without runtime `index.json`.

## Inputs

- Candidate accessions projected by S1 from the broad published `filing_catalog`
  snapshot for a full live survey; a selected target plan can omit era/form coverage.
  A small committed cohort fixture is sufficient for offline tests, but not for the
  100–200-page coverage claim.
- S2's raw response capture/replay store and a rate-limited SEC broker for the live
  survey. Live surveying is an explicit research step, not a production fetch path.
- Cohort metadata from S1: `source_cik`, `accession`, `form`, `filing_date`,
  `report_date`, and contributing cohort-source identity.

## Sampling plan

Survey **100–200 pages**, stratified by era across:

| Stratum | Years | Rationale |
|---|---|---|
| Legacy | 1993–1999 | Concatenated SGML envelope; children listed without individual links; `SEQUENCE`/`TYPE` inside the bundle. |
| Transition | 2000–2004 | Historical filings may carry both individual files and an envelope; sequence order alone is not a safe primary selector. |
| Modern | 2005–present | Individual files, an envelope, and directory indexes coexist; direct links and `index.json`. |

XML-form pages are an additional coverage minimum across those date-derived strata;
they may also count toward their filing-era quota.

Stratification targets:

- Multiple forms per stratum; do not sample only `10-K`.
- Pages with both `Document Format Files` and `Data Files` tables.
- Pages with and without individual document links.
- Pages with absent, duplicated, or out-of-order sequences.
- Pages with absent, duplicated, or ambiguous filenames.
- At least one accession that appears in several source-CIK plan contexts.

Do not download XBRL ZIP bodies for this study.

## Bootstrap order

1. S1 reads a broad published `filing_catalog` snapshot and can be tested with a
   small committed cohort fixture. Do not use a selected filing plan as the survey
   frame unless it proves the required era/form coverage.
2. S2 captures and replays raw index-page response bytes; it does not parse HTML.
3. S0 selects and captures the stratified sample, inspects the saved pages with
   manual review or disposable exploratory tooling, then commits selected fixtures
   and the portable evidence table. S0 may use S7b's inert source preview once it
   exists, but does not require its parser output.
4. S3 parser work may start earlier through S7b using the typed contract and
   available fixtures; S0 runs in parallel and finalizes parser rules and acceptance
   coverage. S5 query fixtures and later S7 review surfaces follow their own contracts.

The full live survey requires a published catalog snapshot with sufficient era/form
coverage and explicit authorization for SEC requests. A unit-test fixture can validate
the bootstrap contracts but cannot substitute for the empirical survey.

## Typed audit records

The portable result separates page-level evidence from source-table-row evidence;
response size and child-file size are different fields.

```python
AuditStratum = Literal["legacy", "transition", "modern"]
AuditTableKind = Literal["document_format", "data_file"]
AuditPageStatus = Literal["parsed", "unrecognized", "parse_error"]
XbrlEvidenceKind = Literal[
    "not_tested", "constructed_only", "index_json_listed",
    "head_present", "head_missing", "probe_unsupported",
]

@dataclass(frozen=True, slots=True)
class AuditCandidate:
    accession: AccessionNumber
    source_ciks: tuple[Cik, ...]
    form: str
    filing_date: date
    is_xml_form: bool

@dataclass(frozen=True, slots=True)
class AuditSample:
    accession: AccessionNumber
    source_ciks: tuple[Cik, ...]
    form: str
    filing_date: date
    era: AuditStratum
    is_xml_form: bool

@dataclass(frozen=True, slots=True)
class XbrlEvidence:
    candidate_url: str | None
    kind: XbrlEvidenceKind
    evidence_source: str | None

@dataclass(frozen=True, slots=True)
class AuditPageRecord:
    sample: AuditSample
    source_url: str
    page_sha256: str
    response_size: int
    captured_at: datetime
    status: AuditPageStatus
    table_kinds: tuple[AuditTableKind, ...]
    bundle_url: str | None
    bundle_size: int | None
    xbrl: XbrlEvidence
    diagnostic_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class AuditEntryRecord:
    accession: AccessionNumber
    table_kind: AuditTableKind
    row_ordinal: int
    sequence: int | None
    document_type: str | None
    document_label: str | None
    description: str | None
    filename: str | None
    href: str | None
    child_size: int | None
    has_link: bool
    sequence_anomaly: Literal["missing", "duplicate", "out_of_order"] | None
    filename_ambiguous: bool

@dataclass(frozen=True, slots=True)
class AuditConclusion:
    question_id: Literal["parser_coverage", "field_ambiguity", "retrieval_mode", "xbrl_evidence"]
    finding: str
    supporting_accessions: tuple[AccessionNumber, ...]

@dataclass(frozen=True, slots=True)
class AuditDecisionRecord:
    xbrl_policy: Literal["html_only", "index_json_confirmation", "head_probe"]
    conclusions: tuple[AuditConclusion, ...]
```

`captured_at` is UTC; the portable table serializes it as an ISO-8601 timestamp.
`AuditPageRecord` has one row per sampled response. `AuditEntryRecord` has one
row per source table row; its key is `(accession, table_kind, row_ordinal)`. The
ordinal is zero-based among body rows. The page digest is SHA-256 of the exact
response bytes. `XbrlEvidence` never
asserts package contents: only `index_json_listed` or a successful body-free
probe is observed availability evidence; `constructed_only` is just a URL.

The portable audit result is `AuditPageRecord[]` plus `AuditEntryRecord[]` and
the decision record. Captured response bytes live in selected fixtures or the
transient survey store, not in the tabular result.

## Operation shapes

```python
select_audit_sample(
    candidates: Iterable[AuditCandidate],
    quotas: Mapping[AuditStratum, int],
    *,
    minimum_xml_pages: int,
) -> tuple[AuditSample, ...]

record_audit_page(
    sample: AuditSample,
    source_url: str,
    response_bytes: bytes,
    captured_at: datetime,
    xbrl_evidence: XbrlEvidence,
) -> tuple[AuditPageRecord, tuple[AuditEntryRecord, ...]]

summarize_audit(
    pages: Iterable[AuditPageRecord],
    entries: Iterable[AuditEntryRecord],
) -> AuditDecisionRecord
```

These are audit-artifact operations, not a production fetch or parser API. S0 starts
after raw pages can be captured and replayed through S2. It may use manual inspection
or disposable exploratory extraction to record evidence; that exploratory work is
not the production `parse_html_index` implementation and must not freeze parser rules
before the survey is complete.
`AuditCandidate` is an accession-level catalog projection. The date-derived era
quotas must sum to 100–200 pages; XML-form coverage is an additional minimum and
may overlap those quotas, but the final unique sample may not exceed 200 pages.
Selection consumes unique accession candidates from a streamed snapshot projection
and retains only the bounded per-era winners. It ranks by SHA-256 of canonical
`[era, accession]` within each era and fills the XML minimum from remaining XML
candidates using the same order; it refuses impossible coverage. It does not
materialize the full catalog or all candidate accessions in memory.
`record_audit_page` records
parse status and observations but does not probe XBRL packages; any probe result
is supplied as explicit evidence. The four `question_id` values map to the four
audit questions above, and each conclusion cites the accessions supporting it.

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
3. Parser-focused sanitized page fixtures covering the observed source-page shapes.
   Snapshot query fixtures belong to S5/S12, after the query and publication contracts
   exist; they are not an S0 prerequisite or deliverable.
4. XBRL decision record.
5. A short note estimating index-page parse cost and response memory for tuning the
   S4 worker budget.

## Tests

Tests remain offline and deterministic; they replay committed audit evidence, not the
live survey:

- Parse cost and response size distribution summarize across strata.
- Fixture selection covers the audit's observed shapes.
- Candidate selection is deterministic and refuses impossible era/XML coverage.

## Acceptance criteria

Every audit row records source URL and page digest. Raw page bytes are already
available from S2 replay; S0 publishes its portable audit result and selected page
fixtures without requiring a production parser or review-artifact run. The sample
includes:

- legacy no-link,
- 2000–2004 sequence/type disagreement cases,
- modern direct links, and
- `Data Files`.

ZIP-path conclusions distinguish URL construction from per-accession availability. If
the audit disproves HTML sufficiency for a required target, the inventory source
contract is amended before the parser is implemented.

## Acquisition-handoff findings to validate

Exploratory review runs found these acquisition-sensitive cases. They are not yet a
portable stratified S0 result, and no child URL was live-probed; treat the counts and
URL availability as provisional until the audit fixtures and status evidence are
committed.

- **Archive CIK is not a reliable derivation from the source CIK or accession prefix.**
  Captured rows include same-accession paths whose archive CIK differs from the index
  URL's CIK; one legacy complete-submission link also used a third CIK. The index parser
  currently requires `archive_cik == source_archive.archive_cik` in
  `edgar_sec/engine/index_pages/parser.py`, while planning and lazy index selection
  repeat that scope check. Acquisition URL validation must be reconciled with these
  observed SEC links: preserve a validated observed URL when its origin and accession
  match, and continue rejecting unsafe paths. Do not synthesize a different-CIK child
  or bundle URL merely from the accession. Record live status/redirect evidence for
  representative cases before changing the archive-CIK policy.
- **A present `href` may not address a document.** Legacy rows can carry an archive CIK
  directory href with no filename or child URL while a complete-submission bundle and
  positive sequence are available. S6 now recognizes only exact SEC CIK/accession
  directory paths as non-document locators. For a profile-matched exhibit it retains
  the observed sequence and uses the observed bundle URL, validated against the pinned
  index URL's archive CIK; without bundle/sequence evidence it remains unresolved. Tests
  cover numbered children `0002.txt`–`0007.txt`, directory-only fallback, absent bundle,
  and refusal of an external directory URL. The parser's `unsafe_href` diagnostic and
  cross-CIK live reachability still require raw-page audit evidence.
- **Sequence names are not target roles.** In the 2,000-case review run, the analyzer
  reports 3,105 `EX-*`, `GRAPHIC`, or `ZIP` `Document Format` rows at sequences 2 or 3;
  overlapping run totals are not unique coverage. In one 8-K, `0001.txt` is the
  form row and `0002.txt`/`0003.txt` are EX-2.1/EX-2.2 with direct links; an inversion
  case has exhibit sequence 1 and the form row at sequence 12. Planning must match
  `document_type` to the declared target type, preserve the observed sequence, and use
  the observed direct URL or bundle sequence. Do not broaden the primary-placeholder
  allowlist (`0000.*`/`0001.*`) to treat `0002.*`/`0003.*` as primary; profile-declared
  exhibits are separate acquisition targets. The 2,000-case run reports 43 candidate
  sequence-1 exhibit/later-form cases; this does not establish an era-stratified rate.
- **Form 4 index rows expose two sequence-1 sources.** In the latest 1,000-page review
  run, 363 cases are Form 4. In 283, two `Document Format` rows both have sequence 1
  and type `4`: a display name ending in `.html` links to `xslF345X01`–`xslF345X06`/
  `*.xml`, while a display name ending in `.xml` links to the accession-root `*.xml`.
  Both match S6's current primary-by-form predicate, so the plan sees two candidates
  and reports ambiguity. The XSL `.xml` path is the rendered HTML route described in
  the acquisition-policy plan; the flat sibling is a separate XML source. The run also
  has 21 `.htm`/`.html` href rows: 11 sequence-1 Form 4 rows and 10 other rows. Audit
  which source the filing intends to acquire; do not infer response type from suffix,
  equate the sibling XML with an XSL render, or construct one locator from the other.
  Form 4 XML translation remains unsupported until a family transform is registered.
- **A direct 404 is not currently recoverable by generic fallback.** S9 records a
  direct-target 404 as `http_not_found`; the lazy-index path is bounded to its declared
  catalog-direct primary policy and does not start on transport failure. Therefore
  inventory-to-acquisition planning must not turn an unvalidated filename or source CIK
  into a fetch URL. Before marking a target executable, verify that its direct URL is an
  observed, accession-scoped document URL, or that both its bundle URL and positive
  sequence are observed. Keep missing/unsafe locator outcomes unresolved; any 404
  recovery policy must be explicit and preserve the failed attempt rather than hiding
  bad input.
- **Alias matching is consistent at recovery.** S6 and catalog-direct lazy index
  selection now normalize both the expected form and observed `document_type` through
  the shared form-family alias registry. The lazy-selector test covers the historical
  `10-K405` alias for `10-K`; an unrelated form remains `not_filed` or
  `required_missing` by request optionality.
- **Separate locator shape from reachability.** Display filenames can differ from the
  href basename for rendered XML/HTML pairs. Do not use basename equality alone as a
  404 or bad-link verdict. For selected suspicious rows, compare the raw captured href,
  resolved archive path, accession, and a bounded response/status result. Inert-preview
  href preservation is run-version-dependent: earlier previews omitted anchors, while
  the latest 1,000-page run preserves them. Compare preview hrefs with raw-page hrefs
  rather than assuming previews from different runs are equivalent.

Before S0 acceptance, reconcile the inventory/output-path figures above with the current
review evidence, commit the portable row-level audit, and exercise the cases above
through parser → S5 inventory → S6 target plan → S9 work order. Include direct, bundle
sequence, directory-only href, alternate archive CIK, duplicate sequence, and failed
direct-fetch cases; assert that no stage invents a child path from `0001`/`0002` labels.
