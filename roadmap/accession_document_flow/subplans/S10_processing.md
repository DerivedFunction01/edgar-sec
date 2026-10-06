# S10 — Processing Contract, Processor Versions, and Document Review

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S10**.
- Status: byte-to-representation processing and review layer; consumes acquisition
  fixtures offline.
- Depends on: S9 acquisition fixture store, S3 parser (form/route dispatch), S7 review.
- Non-blocking: S11 payload design gate.

## Objective

Define a pure byte-to-representation processor interface with deterministic
fingerprints, form/route dispatch, bounded process-pool execution, and fixture-backed
review with base/new comparison. Persist review evidence, not published document rows.

## Contract

```text
class Processor:
    def process(selected_bytes, route, form) -> ProcessingResult
    def fingerprint(self) -> str
```

The processor accepts the selected bytes plus content route and form, then returns a
representation, output text/bytes, status, stage diagnostics, and a processor
fingerprint. Reuse existing lower-layer normalization APIs when their contract fits;
do not import the `document_storage` pipeline. Store no normalized content in
inventory or target-plan artifacts.

Routes are dispatched by content type/form:

- HTML/iXBRL -> HTML normalization + text extraction.
- XML -> XML validation + structure extraction.
- Binary PDF -> PDF extraction.
- Unrecognized -> explicit `unrecognized` status with the detected mime type.

## Determinism and versioning

- Identical processor inputs produce identical outputs.
- A processor fingerprint encodes the implementation version plus any nondeterministic
  configuration; a fingerprint change breaks comparison.
- Comparison runs only when fingerprints match.
- Bounded process pool for CPU-heavy document-body processing; each task is one
  document.

## Review artifacts

Replay captured acquisition fixtures; record source and output digests, processor
fingerprint and stage diagnostics, and compare outputs across processor versions. It
runs no network requests and writes only review artifacts, not the future published
payload store. Review output shapes follow the stage-7 contract under
`{artifacts_root}/document_processing/review-runs/{review_id}/`.

## Acceptance behavior

- A bad document does not hide successful cases.
- Binary and unrecognized routes are explicit, not silently normalized.
- Stage diagnostics are bounded in size.
- Review outputs are reproducible from fixture ID, target ID, and processor identity.

## Tests

- Offline worker and review parity.
- Identical processor inputs produce identical outputs.
- Processor fingerprint changes prevent false comparison.
- Binary and unrecognized routes are explicit.
- Review records source/output hashes and stage diagnostics.
- One bad document does not hide successful cases.
- Deterministic output under repeated runs.
- Fingerprint stability across process boundaries.
- Form/route dispatch selects the correct handler.
- No `document_storage` pipeline imports.
- No network requests during review.
- Bounded diagnostics do not grow with input size.
- A stale fingerprint is rejected by the comparison API.
- Normalized output is transient; only digests persist in plan artifacts.

## Acceptance criteria

A pure byte-to-representation processor interface, deterministic processor fingerprint,
form/route dispatch, and a bounded process pool for CPU-heavy document-body
processing. Review artifacts and base/new comparison run from acquisition fixtures.
Existing engine normalizers are reused where their contract fits, without depending on
`document_storage` pipeline modules. Review evidence is persisted, not published
document rows.
