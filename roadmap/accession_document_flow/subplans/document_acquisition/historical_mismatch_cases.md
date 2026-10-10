# Historical Mismatch Test Cases

No tracked sanitized pre-2011 fixture currently joins submission metadata, an SGML
envelope, index rows, and filing cover text. `tests/fixtures/historical_submissions.json`
provides metadata only; `tests/fixtures/document_storage/exhibit_primary.sgm` has
consistent 2002 types and a placeholder body; `tests/fixtures/catalog/expected_filing_targets.csv`
has metadata-only targets. Keep these as partial evidence, not as historical mismatch
fixtures.

Future fixtures should cover pre-2011 Form 8-K and Form 10-K filings. Keep these two
classes separate: a disagreement between submission/document metadata is not the same
evidence as cover text that contradicts otherwise matching metadata. This note records
test dimensions, not a claim that a family-aware identity evaluator exists.

## Submission/document metadata mismatches

Vary the pinned filing form, outer submission form, SGML child `<TYPE>`, child sequence,
and available index `document_type`/sequence evidence. Include 8-K and 10-K cases where
the outer form and child `<TYPE>` disagree, and distinguish that from cases where they
agree. Where lazy index resolution is under test, vary unique, absent, and duplicate
exact-form index rows.

Assert that each source's observed form and sequence remain distinguishable; the pinned
S6 form is not rewritten from a child header; and any slot assignment uses exact index
type evidence rather than sequence or filename resemblance. `target_type` is intent,
not an expected SGML `<TYPE>`. Do not require metadata-mismatch checks for post-2011
filings.

## Cover-text mismatches

Keep submission and document metadata mutually consistent, then vary the historical
body's cover evidence so it conflicts with the pinned 8-K or 10-K form. Include HTML
covers and flat-text covers where available; vary which form the cover names and whether
the fixture contains family-specific evidence already owned by the form packages.

Assert that the cover text/result remains distinct from submission, child-header, and
index metadata. A cover discrepancy may be recorded as suspicion evidence, but must not
by itself relabel the pinned form or establish/select a statutory document type. Do not
assert a specific family inference unless a separately specified evaluator is under
test.

See [the S9 historical fixture scope](plan.md#historical-form-mismatch-fixtures),
[catalog-direct recovery](decision_tree.md#catalog-direct-primary-selectors-and-lazy-recovery),
and [the S6/S9 type-evidence model](schemas.md#physical-slot-and-type-evidence-model).
