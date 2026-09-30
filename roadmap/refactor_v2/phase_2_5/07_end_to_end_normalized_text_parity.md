# Phase 2.5 - Plan 07: End-to-End Normalized Text Parity Gate

> **Status:** First post-implementation closure plan. This plan establishes a
> byte-exact v1 reference gate for a small, offline Phase 2.5 vertical slice. It
> does not certify parity for every v1 filing or resolve v1-state migration.
>
> **Evidence:** `.kilo/plans/phase-025-port-map.md` and
> `.kilo/plans/phase-025-inventory/CAPABILITIES.csv`.

## 1. Goal

For the same raw document bytes, locator, form, and normalization policy, run the
v1 processor and the v2 Phase 2.5 pipeline and prove that the stored
`normalized_text` is byte-for-byte identical for a small, deterministic set of
synthetic cases.

This is the first gate because the existing v2 normalization goldens pin boundary
metadata, stage order, and selected invariants, but they do not compare the v2
text to text produced by v1. The v2 fixture-mode pipeline already processes
chunk-plan JSON offline, writes a Parquet snapshot, and exposes `normalized_text`
for read-back. Use that existing path; do not block this first comparison on the
live broker or a Phase 2 bundle adapter.

Passing this plan proves only the selected synthetic cases. It does not certify
real-filing parity or declare all Phase 2.5 v1 responsibilities ported.

## 2. Equality Contract

The comparison surface is deliberately narrow and strict:

- The v1 and v2 runs receive exactly the same input bytes and equivalent locator
  fields: document path, form, accession, source CIK, and filing date where the
  case uses them.
- The compared value is the final `normalized_text` read back from the v2
  published snapshot and the final normalized text emitted by v1's
  `DefaultFilingProcessor` path.
- Encode each string as UTF-8 and compare the bytes exactly. Do not strip leading
  or trailing whitespace, normalize newlines, case-fold text, or filter known
  differences in the comparator.
- Also assert the output row belongs to the expected document locator and has an
  acceptable terminal status; a matching text attached to the wrong document is
  not a pass.
- Do not compare Parquet file bytes, physical row ordering, run timestamps, or
  non-text metadata in this plan. Those are separate storage/provenance
  contracts.
- A behavior difference is not hidden in a golden update. If a case differs,
  produce a useful unified diff and assign the difference to a specific
  capability. Change v2 behavior or obtain an explicit, documented scope
  decision before updating the expected output.

## 3. Initial Case Set

Use compact, synthetic inputs so the gate is offline, deterministic, reviewable,
and does not depend on a real SEC filing license or sanitization decision. Each
case has the source bytes, locator fields, v1-produced expected text, and a small
metadata manifest.

| case | input | behavior exercised |
| :--- | :--- | :--- |
| `synthetic_sgml_html_10k` | SGML envelope with a primary HTML 10-K and one non-selected attachment | document selection, unpacking, HTML cleanup, form normalization, snapshot read-back |
| `synthetic_ascii_reflow_10k` | ASCII 10-K with hard-wrapped prose, page labels, and a tagged table | page policy, reflow, table-byte preservation, exact output whitespace |
| `synthetic_html_cover_table_10k` | Small HTML 10-K with cover headings, checkbox glyphs, body text, and a table | cover/body boundary, form evaluation, HTML table protection, metadata-independent text equality |

These are acceptance fixtures, not examples of a representative real corpus. Add
10-Q, 8-K, financial taxonomy, delegated exhibits, and historical filing eras in
later sequential plans, based on observed failures and the declared supported
scope.

## 4. Execution Plan

### 4.1 Capture the v1 reference once

Run the v1 `DefaultFilingProcessor` locally against each synthetic input with
network disabled. Record the v1 source fingerprint, relevant processor
configuration, input SHA-256, output SHA-256, locator, and form in a case manifest.
Store the expected normalized text as UTF-8 text alongside the synthetic input.

The committed v2 test must not import `.v1` or invoke v1 at test time. `.v1` is
not tracked in the v2 checkout; reference capture is a one-time, reviewable step,
and the captured text plus source/input fingerprints are the test oracle.

### 4.2 Run through the v2 fixture pipeline

Use the existing `run_document_storage` fixture-mode path with one deterministic
chunk and one document per case. Seed the fixture payload using existing test
storage helpers; do not add a production fixture-population command here. Write
all run and snapshot artifacts under pytest `tmp_path`.

The test should read the published snapshot through the established test/storage
read path, select the row by `document_locator_key`, verify a successful status,
and compare `normalized_text.encode("utf-8")` with the captured v1 bytes.

Add a CLI smoke case for the current fixture command shape:

```text
python run.py documents run --plan <single-chunk-plan.json> --fixture <fixture-id> --workers 1 --run-id <fixed-test-id>
```

The smoke case verifies that the existing user-facing fixture command reaches
the same processor and publishes the text that the parity test compares. This
plan intentionally uses the current chunk-plan JSON interface. Consuming the
published Phase 2 bundle is the next integration plan.

### 4.3 Keep test artifacts self-describing

Store cases under `tests/fixtures/document_storage/v1_parity/`. Each case
manifest records:

- Case ID, form, locator fields, and expected representation.
- Input and expected-text SHA-256 values.
- The v1 source files and fingerprints used to capture the reference.
- The page-artifact and normalization policy used for both runs.
- Any fields intentionally excluded from byte comparison and why.

Use `tests/pipelines/document_storage/test_normalized_text_v1_parity.py` for the
pipeline-level test. Keep test cases offline and deterministic; do not dirty the
repository with generated runs or snapshots.

## 5. Acceptance Criteria

- All three initial cases run through the v2 fixture-mode pipeline without
  network access.
- Each v2 snapshot contains exactly one expected document row for its locator,
  and its normalized text matches the v1 reference bytes exactly.
- A second run with the same case input and processor settings produces the same
  normalized-text bytes.
- A mismatch fails with a case ID, expected/actual SHA-256, and a readable text
  diff; the test does not rewrite goldens automatically.
- No v1 imports, real SEC documents, credentials, live HTTP requests, or v1
  SQLite-to-v2 Parquet conversion are introduced into the default test suite.
- Targeted tests pass, then run `.venv/bin/python check.py --fast`.

## 6. Follow-On Sequence

The first parity slice should lead to sequential plans, not a renewed broad
inventory. Create each later plan from concrete failures in this gate and the
current capability register:

1. **Plan 08 - Published Phase 2 handoff and CLI.** Replace or adapt the current
   chunk-plan entry path so Phase 2.5 can validate and consume the published Phase
   2 bundle; preserve an offline fixture mode and rejection tests.
2. **Plan 09 - Normalization fidelity by supported form.** Address only the
   demonstrated output deltas: form/year context, page artifacts, taxonomies,
   page-marker sequence behavior, table geometry, and other contracts required
   for the supported form set.
3. **Plan 10 - Live acquisition and operational route.** Decide and implement
   broker lifecycle, production cache reads, rate pacing versus in-flight
   concurrency, and maintenance commands after the offline output contract is
   stable.
4. **Plan 11 - Real-filing parity and migration (conditional).** Proceed only
   after provenance/licensing approval and an explicit decision about whether v1
   run state must be resumed.

## 7. Explicit Non-Goals

- Declaring full Phase 2.5 complete after three synthetic examples.
- Porting all 246 reachable `defs/*` modules or every v1 fixture/review tool.
- Claiming byte parity for real filing eras while M6.3/M6.4 data policy is
  deferred.
- Translating existing v1 SQLite chunk databases, caches, or snapshots into v2
  Parquet. If existing-run resumption is required, approve a separate migration
  design first.
- Wiring the ASCII/HTML renderer merely because it exists in the reachable tree;
  first establish a required production caller and an output contract.
