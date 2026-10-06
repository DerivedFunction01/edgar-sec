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

These are audit-artifact operations, not a production fetch or parser API.
`AuditCandidate` is an accession-level catalog projection. The date-derived era
quotas must sum to 100–200 pages; XML-form coverage is an additional minimum and
may overlap those quotas, but the final unique sample may not exceed 200 pages.
Selection ranks candidates by SHA-256 of canonical `[era, accession]` within each
era and fills the XML minimum from remaining XML candidates using the same order;
it refuses impossible coverage.
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
3. Query fixtures for: one accession, one filing form, child document types, and one
   accession with source-CIK associations split across plan cohorts. These validate snapshot access paths
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
