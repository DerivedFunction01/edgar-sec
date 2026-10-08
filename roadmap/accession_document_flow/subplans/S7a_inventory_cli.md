# S7a — Inventory CLI and Fixture Lifecycle

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S7a**.
- Status: fixture create/fill/list CLI and launcher integration are implemented.
- Depends on S1 cohort projection, S2 index-fixture storage, and loading a published
  `filing_catalog` plan bundle.
- Mirrored evidence: `tests/pipelines/document_inventory/test_cli.py`,
  `tests/pipelines/document_inventory/test_review_adapter.py`, and
  `tests/pipelines/document_inventory/fixture_store/test_capture.py`.
- S7b parser review artifacts are also implemented. S0 evidence gathering proceeds
  independently and remains a gate for final parser acceptance.

## Objective

Provide the command and launcher surface to capture published `filing_catalog` plan
cohorts into an offline-reviewable index fixture. S3's initial parser pass can use the
committed standard-layout fixture independently of S0's final audit. The fixture owns
captured pages and source provenance; later list, replay, and review use the fixture
alone.

## Minimal command surface

```text
inventory fixture create --fixture <fixture-id> --catalog-plan <plan-id>
    [--limit <n>] [--artifacts <root>] [--json]

inventory fixture fill --fixture <fixture-id> --catalog-plan <plan-id>
    [--limit <n>] [--artifacts <root>] [--json]

inventory fixture list [--artifacts <root>] [--json]
```

- `--catalog-plan` is a published plan ID, resolved below the same artifacts root
  selected by `--artifacts`; it is not a caller-supplied path. `--limit` is a
  deterministic smoke-run cap. Do not expose `--workers` until capture actually uses
  bounded parallel work; the current `capture_index_pages` walks work items serially.
- `create` validates the plan, refuses a pre-existing fixture ID, creates the store,
  and performs the initial capture. Successful pages are retained if other accessions
  fail; the command returns nonzero when any selected capture fails.
- `fill` requires an existing fixture and adds the selected plan contribution. New
  response bodies are keyed by request URL plus response SHA-256, so changed pages
  append rather than replace old evidence when fetched. Existing successful accession/URL
  responses are reused; failed accessions are recorded and can be retried. There is no
  explicit refresh operation for recapturing an existing success.
- `list` reports fixture ID, manifest/store status, page/accession/membership counts,
  and recorded source-plan contributions without opening a catalog plan.
- The S7b command surface is `inventory review generate`; generic run comparison is
  available as `inventory review compare`.

Resolve and validate the plan bundle only during create/fill. Each contribution records
its plan ID, catalog ID, plan schema/scope, and stable request fingerprint; no absolute
source path is persisted or required for replay. Additional fills extend the provenance
record, including cohort membership when a response body is reused. The inventory
manifest uses the common foundation fixture envelope, with these fields and the store
schema/counts under its pipeline-owned `details` object. The appendable lifecycle and
atomic manifest update are implemented in the S2 fixture store.

## Interactive launcher

`run.py` already registers the `inventory` entry. `python run.py inventory` enters the
inventory module's menu; explicit arguments continue to dispatch as commands. The
menu is a prompt adapter over the same typed operations and offers:

1. Create/capture a fixture from a catalog plan.
2. Fill/extend a fixture from a catalog plan.
3. List fixtures and show their local manifest status.
0. Exit the inventory menu. The root launcher currently returns after dispatching a
   pipeline selected from its own menu; S7a does not change that shared behavior.

The review menu is a thin prompt adapter over shared typed operations; it does not
duplicate plan loading, capture, or fixture-store logic. Changing `run.py` to resume its
root menu is not required for S7a.

## Fixture identity and independence

The fixture is the durable evidence boundary. It stores page bytes keyed by request URL
and per-response SHA-256, accession/source-CIK memberships, capture results, fixture
schema version, and source-plan contribution provenance. The external catalog plan's file
path or continued existence is never a replay prerequisite. The source plan may be
extended or deleted after capture; the fixture remains listable, replayable, and
reviewable from its own files.

The current list/replay path validates the manifest, schema, SQLite integrity, row
counts, and selected decompressed responses against their response digests. It does not
hash the entire database or cryptographically detect membership/provenance edits that
preserve database validity and counts. A whole-database integrity digest is not part of
the implemented contract.

## Boundaries

- `cli.py` parses options, selects paths, dispatches, and renders text/JSON summaries;
  S1/S2 own cohort and fixture behavior.
- Capture/fill uses the shared SEC broker. Capture is currently serial, so this slice
  has no `--workers`; adding bounded parallel work is separate. Review and replay are
  offline and never require the originating catalog plan.
- A failed capture is reported per accession; successful pages remain committed and
  a later fill can retry missing cases. The command returns nonzero when any selected
  capture failed. Partial and zero-success creates remain listable and fillable.
- Fixture capture remains S0/S7 research tooling, not the S4 production inventory
  worker's persistence path.

## Tests and validation

- CLI tests cover fixture command parsing/dispatch, required arguments, list output,
  and JSON formatting. Fixture-store tests cover capture, reuse, overlapping
  provenance, partial results, and retry behavior.
- Delete/move the originating plan after capture; list, replay, and review must still
  work from the fixture alone.
- The existing `run.py` launcher entry and inventory operator menu are reused rather
  than duplicated.
- Fixture listing and replay must not resolve the catalog plan. Replay verifies the
  selected decompressed page bytes against the response digest. Run mirrored tests and
  `.venv/bin/python check.py --fast`.

When implemented, update `document_inventory/README.md`, the parent `pipelines/README.md`,
`edgar_sec/README.md`, and root README command/layout references for the supported
fixture CLI. Keep the package docs at the contract boundary and link to the CLI module.

## Verified lifecycle decisions and remaining limits

- Fixture IDs are caller-selected and required by create/fill.
- Fill reuses successful accession/URL responses, retries recorded failures, and adds
  cohort membership for a new contribution even when its response is reused. There is
  no explicit refresh operation for recapturing an existing successful accession/URL.
- Contributions record plan ID, catalog ID, scope, plan schema version, and request
  fingerprint; source paths and a separate source-snapshot fingerprint are not recorded.
- Listing and replay validate SQLite structure/integrity and selected response digests;
  there is no whole-database digest or cryptographic protection for membership metadata.
- Capture commits page/member updates per accession. The manifest records an in-progress
  contribution; an interrupted capture is reported as `interrupted` and can be retried.
- A plan with zero successful captures remains a listable partial fixture, covered by
  `tests/pipelines/document_inventory/fixture_store/test_capture.py`.

## Acceptance

A user can explicitly create, fill, and list local index fixtures from published
catalog-plan IDs using either `run.py inventory` or CLI arguments. Fixture replay and
S7b parser review use captured fixture data without resolving source plan bundles.
S7a owns this CLI/fixture lifecycle and S7b consumes the fixture API and S3 types.
