# S10 Exhibit and Primary-Role Assessment

## Owner and status

This is a provisional S10 diagnostic design, not an enabled classifier. It uses
[`uploads/exhibits-classification.md`](../../../uploads/exhibits-classification.md) as
research input and the current form evidence-pack APIs as implementation precedent.
The examples support a taxonomy and evaluator boundary; they do not establish
precision, recall, or production-ready rules.

## Evidence and limits

The exhibit sketch cites Regulation S-K exhibit families, sample EDGAR URLs, proposed
anchors, and false-positive notes. That is enough to propose stable concepts and test
questions. It is not yet a labeled corpus:

- The URLs and prose snippets have not been captured here as exact response fixtures
  with reproducible accession, target, and source digests. This design pass did not
  independently verify external links.
- Some examples are filing/index pages rather than a selected exhibit body. For
  example, the EX-106 examples at the sketch's lines 1452–1455 link to `-index.htm`.
- No independent human labels, negative set, issuer/time-separated holdout, or
  measured false-positive/false-negative rates are present. The sketch's coverage and
  frequency descriptions are not calibrated prevalence estimates.
- Suggested regex snippets are hypotheses, not executable rules. At least one sample
  needs syntax validation before it can be treated as code. Rules must use the
  repository regex builder where applicable and be tested against positive and
  adversarial negative fixtures.
- Regulation S-K Item 601 is only one authority and one taxonomy slice. `EX-99.*`,
  ABS exhibits, form-specific attachments, obsolete codes, and amendments have
  different conventions. The canonical list and its effective dates need verification
  against the governing source before being declared exhaustive.

The uploaded official-text extract at [`uploads/exhibits.md`](../../../uploads/exhibits.md)
is a research source, not a versioned application schema. Neither upload is imported
or parsed at runtime.

## Question and boundary

Assess the body S9 already selected: does its visible content look consistent with the
S6-planned role, or does it contain evidence that it may itself be an exhibit rather
than the requested primary report? Initial form scope is 10-K, 10-Q, and 8-K. The
assessment is separate from cover-boundary detection, companion-exhibit detection, and
S6 planning.

The evaluator is post-selection and read-only:

- It may emit `possible_primary_role_mismatch` when a planned primary has strong
  exhibit evidence, or identify an exhibit family for an S6-planned exhibit.
- It never changes `target_id`, `target_role`, `target_type`, the effective route, or
  the S10 normalization profile. It cannot fetch an index, recover a filename, create
  an S6 target, trigger a retry, or schedule an S9 request.
- `source_origin="catalog_direct"` remains weaker provenance. A suspicious body can be
  reported, but the catalog locator is not replaced and it is not silently promoted to
  index-verified evidence.
- S10 does not compare the body’s SGML `<TYPE>` to an S5 row. The selected SGML type
  remains provenance under the S9 contract; a body-level equality guarantee would
  require a versioned S6 target-plan field.

This can replace the legacy evaluator's *diagnostic role* in S10. It must not reuse
the legacy `EvaluatorDecision` execution SPI: `REFETCH_SUB_DOC` and
`SKIP_HARD_STUB` encode pipeline actions, not document evidence.

## Proposed taxonomy

Keep legal exhibit identity separate from broad content meaning and from the planned
S6 role:

```text
ExhibitTaxon
  taxon_id                 stable internal ID, not a display label
  authority                e.g. SEC Item 601, Regulation AB, form-specific
  canonical_code           e.g. EX-10.1 or a normalized family code
  parent_taxon_id          optional broader class
  content_family           contracts, governance, certification, press release, ABS data...
  title                    human-readable label
  legal_citations          versioned source citations
  effective_interval       optional start/end dates for legal/code changes
  aliases                  filing-type and caption variants
  applicability            supported forms/contexts; descriptive, not an allowlist
  evidence_pack_id         optional versioned detector pack
  coverage_status          proposed, reviewed, or unsupported
```

`EX-10.*`-style families can group multiple legal subitems; `EX-99.*` should retain
numbered subtypes where evidence supports them rather than collapsing every item into
one meaning. Non-Item-601 labels may use another authority namespace. Reserved,
unknown, malformed, and not-yet-reviewed codes remain representable. Do not encode the
sketch's unverified “tier” frequency claims as taxonomy fields.

An initial *candidate* top level could distinguish `periodic_primary` (10-K/10-Q),
`current_report_primary` (8-K), `regulatory_exhibit`, `structured_data`, `paper_stub`,
and `unknown`. Candidate exhibit branches for evidence collection include
organizational documents (EX-3), securities instruments (EX-4), material contracts
(EX-10), subsidiary lists (EX-21), certifications (EX-31/32), broad/press-release
attachments (EX-99.*), and structured/ABS or sector disclosures (EX-101/102/103,
EX-95/96). These are sampling strata, not an approved complete or mutually exclusive
catalog. One document can have legal and content-family labels; keep them as separate
dimensions rather than force every attachment into one prose class.

An assessment result is distinct from the taxonomy entry:

```text
DocumentRoleAssessment
  schema_version
  evaluator_version
  taxonomy_version
  expected_role            copied from the pinned target
  expected_type            copied from the pinned target; not body truth
  observed_kind            primary_report, exhibit, structured_data, paper_stub, unknown
  exhibit_taxon_id         nullable
  disposition              consistent, possible_role_mismatch, insufficient_evidence
  supporting_signal_ids    stable rule IDs and bounded text positions
  contradicting_signal_ids stable rule IDs and bounded text positions
```

Do not emit a floating-point confidence until a held-out corpus calibrates it. An
ordinal evidence label or a deterministic set of matching signals is explainable and
does not masquerade as a probability.

## Evidence packs

Use immutable, versioned evidence packs, one per supported family or role question.
`domain.forms.common.models.BodyEvidencePack` is specifically a form body-anchor
contract (`structural_headings`, `semantic_headings`, vocabulary, and exclusions), not
an exhibit taxonomy; do not overload it with exhibit identities. Its
`derive_lexical_pack()` already converts configured phrases/terms into a
`foundation.text.evidence.LexicalEvidencePack`. Reuse that pattern or scorer for signal
extraction, but the existing tier score/confidence is heuristic and is not calibrated
classifier confidence. The exhibit assessment therefore needs its own result contract
and S10 diagnostic mapping.

Each pack records:

- eligible filing forms, expected S6 role/type, and supported text representations;
- direct opening-caption signals, supporting legal/content phrases, structural cues,
  and explicit contradictory/negative cues;
- the bounded text window and normalization view it consumes;
- positive, hard-negative, and ambiguous fixture IDs with annotator provenance;
- pack and taxonomy version, plus any regulatory effective interval.

Prefer discriminating combinations over a single phrase. “EXHIBIT 10.1” plus a
contract-specific heading is stronger than a reference to an agreement in a 10-K
paragraph. A body mention of an exhibit, a table of contents, or a cover-page item
must not be treated as proof that the whole selected body is an exhibit.

## S10 placement and behavior

The assessment runs after route-specific text is available and before the transient
`ProcessingResult` is finalized. HTML and normalized text use the same text produced by
the role-selected normalizer; flat ASCII `.txt` may provide its unchanged ASCII view.
Only an already-materialized bounded opening view is inspected. XML, binary, paper,
unknown, and unsupported form families initially return no assessment, not a guessed
class. The evaluator does not retain another full-text copy.

For a planned primary, compare primary-report signals with exhibit-family signals. For
a planned exhibit, compare its declared target type with exhibit evidence. Absence of
signals yields `insufficient_evidence`, not “primary”. An exhibit-like result appends a
diagnostic and assessment to S10 metadata; it does not change normalization or
processing status. `ProcessingResult.processor_fingerprint` includes evaluator,
evidence-pack, and taxonomy versions whenever assessment is enabled.

Candidate owner, pending corpus review: a leaf module under `engine.document` for
scoring plus a small domain-owned taxonomy contract only after stable IDs and aliases
are confirmed. The engine evaluator accepts primitive context/text values and imports
no S9 pipeline models.

## Evidence gate before enabling rules

1. Verify the supported exhibit-code list and legal citations against dated SEC/CFR
   sources; record code aliases and changes rather than inferring them from filenames.
2. Capture exact selected source bytes into the S9 fixture format. Label target role,
   form, accession, selected document, observed index `document_type` when available,
   and reviewed visible-content class. Distinguish index pages from child documents.
3. Include difficult negatives: primary 10-K/10-Q/8-K text that mentions exhibits,
   exhibits with generic titles, XSL renderings, XHTML/XML, image/PDF attachments,
   paper stubs, and filings with unusual or missing captions.
4. Partition evaluation by issuer and accession/time so near-duplicate documents do not
   leak across tuning and holdout sets. Report per-form and per-family confusion counts,
   especially false exhibit calls on primary reports; do not report a pooled score
   alone.
5. Review rule hits and misses before enabling any pack. Begin in diagnostic-only
   shadow mode. Activation thresholds and supported families require a recorded
   acceptance decision after the evidence review.

## Non-goals

- Inferring or acquiring EX-13, EX-99, or any other companion absent from the S6 plan.
- Replacing S5 index `document_type`, S6 role/type planning, or source provenance with
  text heuristics.
- Claiming an exhaustive Item 601 taxonomy, legal interpretation, or calibrated
  confidence from the current upload.
- Applying the evaluator to PDF/image bytes, XML data, or every SEC form by default.
