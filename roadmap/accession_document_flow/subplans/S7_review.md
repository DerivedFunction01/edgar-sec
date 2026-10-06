# S7 — Index and Target-Plan Review Surfaces

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S7**.
- Status: review-API design; offline, source-first comparison built from fixtures and
  published artifacts.
- Depends on: S2 index fixture store, S3 parser, S5 snapshot, S6 target plans.
- Non-blocking: S9/S10 acquisition/processing review, S12 CLI.

## Objective

Provide offline `review-artifacts`, `review`, and snapshot `inspect` APIs for
source-page parse output, target plans, and saved manifests. Add CLI routes only for
these review capabilities and basic snapshot/plan lookup; do not build the interactive
wizard here.

## Review surfaces

- **Index review artifacts** replay an index-page fixture through a chosen parser
  version. Each case presents the source URL/digest, a safe inert view of the source
  page, the parsed accession metadata, and the ordered observed rows. The source
  digest and parser version are included in `manifest.jsonl`.
- **Index review comparison** compares two parser runs by accession/table/row
  identity and reports added, removed, or changed type, sequence, description,
  filename, href, size, and bundle metadata. The raw page remains the evidence;
  rendering does not load active remote links.
- **Target-plan review** compares matched, not-filed, ambiguous, unresolved, and
  constructed outcomes separately. A profile change cannot look like an inventory
  change; differences are keyed by request/accession and inventory-entry identity,
  not by profile role alone.
- **Snapshot inspect** reads a pinned published snapshot only, reporting its layout,
  part manifest, and counts per form/year partition.

## Review output shapes

```text
{artifacts_root}/document_inventory/review-runs/{review_id}/
  manifest.jsonl
  cases/{accession}/source.inert.html
  cases/{accession}/observations.json
  cases/{accession}/entries.csv
{artifacts_root}/document_planning/review-runs/{review_id}/
  manifest.jsonl
  target-plan-diff.json
{artifacts_root}/document_processing/review-runs/{review_id}/
  manifest.jsonl
  cases/{target_id}/source.inert.html
  cases/{target_id}/normalized.txt
  cases/{target_id}/processing.json
```

For non-HTML or non-text results, the corresponding preview or normalized-text file
is absent; `processing.json` always records the route and result status. Each
`manifest.jsonl` row pins fixture ID, source URL/digest, accession or target ID,
snapshot/plan ID when applicable, parser/processor fingerprint, result status, and
digests for generated review files. Raw source bytes stay in the fixture DB; HTML
previews render source links as inert text and do not load remote resources.

## Command contracts

- All review outputs refuse a non-empty destination.
- One bad case is reported and does not erase successful case outputs.
- The command returns nonzero when any selected case failed.
- Review runs are reproducible from fixture ID plus selected accession/target IDs and
  parser/processor identity.

## CLI routes

Initial CLI routes are review-capability oriented:

```text
inventory review-artifacts --fixture <id> --output <dir>
inventory review --base <dir> --new <dir>
inventory inspect --snapshot <id>
inventory inspect --accession <accession>
```

Later stages add their own review routes; `index.json` parsing, a broader `status`
command, and the interactive wizard are not part of this stage.

## Tests

- Deterministic manifests: the same fixture + parser version reproduces identical
  output digests.
- Safe source rendering: links are inert text; no active remote loads occur.
- No active remote loads: network instrumentation confirms zero HTTP requests during
  review.
- Row-level base/new differences: added, removed, and changed rows are reported with
  the affected fields.
- Target-outcome distinctions: matched, not-filed, ambiguous, unresolved, and
  constructed outcomes are compared separately.
- Empty selection refusal: an empty case selection is rejected.
- One-case failure behavior: a single failed case does not erase successful cases.
- Non-empty output refusal: a pre-existing destination directory is rejected.
- Snapshot inspect against a pinned snapshot returns layout and counts without fetch.
- Compare reports differences keyed by request/accession/entry identity, not role.
- Review output does not depend on profile roles.
- Review outputs do not write to the future payload store.

## Acceptance criteria

Offline `review-artifacts`, `review`, and snapshot `inspect` APIs serve source-page
parse output, target plans, and saved manifests. CLI routes are limited to review
capabilities and basic snapshot/plan lookup. The interactive operator is a later UX
decision, not part of this stage.
