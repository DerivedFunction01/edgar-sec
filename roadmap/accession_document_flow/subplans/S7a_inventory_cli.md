# S7a — Inventory CLI and Fixture Lifecycle

## Owner and status

- Frontloaded CLI/fixture slice of S7; this subplan is a draft for independent
  refinement before implementation.
- Depends on S1 cohort projection, S2 index-fixture storage, and loading a published
  `filing_catalog` plan bundle.
- `run.py` already registers `inventory`; its `cli.py` routes are still placeholders.
- Must land before S7b parser review artifacts; together S7a/S7b unblock S3 parser
  implementation. S0 evidence gathering proceeds independently.

## Objective

Provide the smallest working command and launcher surface to capture published
`filing_catalog` plan cohorts into an offline-reviewable index fixture. S7a precedes
S7b; S3's initial parser pass can use the committed standard-layout fixture before
S7b is complete. The fixture owns captured pages and source
provenance; later list, replay, and review use the fixture alone.

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
  append rather than replace old evidence. Failed accessions are recorded and can be
  retried. The exact recapture/skip policy is unresolved below.
- `list` reports fixture ID, manifest/store status, page/accession counts, recorded
  source-plan provenance, and last-fill summary without opening a catalog plan.
- The later S7b command surface adds `inventory review-artifacts`; parser-run diff is
  optional and can follow once artifact output exists.

Resolve and validate the plan bundle only during create/fill. Record each contribution's
plan ID, catalog ID, plan schema/scope, and stable request fingerprint in the fixture
manifest; do not persist an absolute source path or treat the plan as a replay dependency.
Additional fills extend the provenance record rather than replace its prior entries.
Whether source-CIK/cohort membership is unique per plan contribution must be fixed
with the store write semantics: current `capture_index_pages` does not record a new
membership when its response row already exists, and can therefore lose new provenance
for an overlapping plan. The current manifest records cohort source IDs but not the
catalog plan ID or its request fingerprint, so plan-level provenance must be added.
The current `publish_index_fixture` also refuses an already-published manifest; a fill
after publication mutates the database without a supported republish path and makes the
old whole-file digest stale. The appendable manifest lifecycle must be resolved before
the CLI can safely expose fill.

## Interactive launcher

`run.py` already registers the `inventory` entry. `python run.py inventory` enters the
inventory module's menu; explicit arguments continue to dispatch as commands. The
menu is a prompt adapter over the same typed operations and offers:

1. Create/capture a fixture from a catalog plan.
2. Fill/extend a fixture from a catalog plan.
3. List fixtures and show their local manifest status.
0. Exit the inventory menu. The root launcher currently returns after dispatching a
   pipeline selected from its own menu; S7a does not change that shared behavior.

S7b adds parser review-artifacts and, if retained, review comparison choices. The menu
is a thin prompt adapter over the same typed operations; it does not duplicate plan
loading, capture, or fixture-store logic. Changing `run.py` to resume its root menu is
not required for S7a.

## Fixture identity and independence

The fixture is the durable evidence boundary. It stores page bytes keyed by request URL
and per-response SHA-256, accession/source-CIK memberships, capture results, fixture
schema version, and source-plan/snapshot provenance. The external catalog plan's file
path or continued existence is never a replay prerequisite. The source plan may be
extended or deleted after capture; the fixture remains listable, replayable, and
reviewable from its own files.

**Recommendation: do not require `database_sha256` for fixture listing or replay.**
Current list/replay hashes the entire SQLite file on each call using `read_bytes()`,
then replay independently validates the selected decompressed response against its
URL+response digest. That makes reads scale with the whole store and materializes the
database in memory. Retain schema validation, manifest/count reconciliation, and
per-response digest checks; S7b pins fixture ID/revision plus each selected response
digest. This does not detect edits to membership/provenance rows that preserve counts.
Whether metadata tamper evidence is a required fixture guarantee remains an explicit
question; if it is, choose a streaming revision-integrity scheme and its validation
frequency rather than re-reading the whole database for every case.

## Boundaries

- `cli.py` parses options, selects paths, dispatches, and renders text/JSON summaries;
  S1/S2 own cohort and fixture behavior.
- Capture/fill uses the shared SEC broker. Capture is currently serial, so this slice
  has no `--workers`; adding bounded parallel work is separate. Review and replay are
  offline and never require the originating catalog plan.
- A failed capture is reported per accession; successful pages remain committed and
  a later fill can retry missing cases. The command returns nonzero when any selected
  capture failed. A partial create remains listable and fillable; whether a plan with
  no successful pages is a valid fixture or a failed create is unresolved.
- Fixture capture remains S0/S7 research tooling, not the S4 production inventory
  worker's persistence path.

## Tests and validation

- Parser/dispatch tests cover create, fill, list, JSON summaries, invalid fixture IDs,
  plan-ID resolution, and `--artifacts` path selection.
- Offline fake-broker tests cover create refusing an existing ID, extension from a
  second plan, overlapping accession/source-CIK membership, partial capture, retry,
  and the selected fill/refresh rule.
- Delete/move the originating plan after capture; list, replay, and review must still
  work from the fixture alone.
- CLI and `run.py` menu tests verify the same operations are reachable both explicitly
  and interactively; the existing launcher entry is reused rather than duplicated.
- Fixture listing and replay must not resolve the catalog plan. Replay verifies the
  selected decompressed page bytes against the response digest. Run mirrored tests and
  `.venv/bin/python check.py --fast`.

When implemented, update `document_inventory/README.md`, the parent `pipelines/README.md`,
`edgar_sec/README.md`, and root README command/layout references for the supported
fixture CLI. Keep the package docs at the contract boundary and link to the CLI module.

## Refinement questions

1. **Recommended:** require the caller to choose `--fixture <id>`; do not derive IDs
   from plans, since one fixture can accumulate several source contributions.
2. **Recommended:** fill skips already-successful accession/URL captures, retries
   recorded failures, and adds missing plan membership even when its response row is
   already stored. Add an explicit refresh route only if changed-source recapture is
   needed. Current code instead fetches every work item on every call and does not add
   new membership when an existing response is reused. Which policy is required for
   the first CLI release?
3. **Recommended:** record per contribution the immutable plan ID, `catalog_id`, scope,
   plan schema version, and `request_fingerprint`; omit source paths. Is the plan's
   catalog ID plus request fingerprint sufficient provenance, or must the fixture also
   pin a separately resolved source-snapshot fingerprint?
4. **Recommended:** remove the whole-database digest as a required list/replay check;
   retain per-response SHA-256 and structural/count validation. Is tamper evidence for
   fixture membership/provenance rows required strongly enough to justify a streamed
   whole-revision digest and its full-file read cost?
5. Should manifest progress be atomically updated per successful capture batch or only
   after the command? Successful page commits must survive interruption, and a later
   fill must resume a partial fixture. What status should `list` report after an
   interrupted create/fill?
6. Is a source plan with zero successful captures a valid empty/partial fixture, or
   should create fail and leave no listable fixture?

## Acceptance

A user can explicitly create, fill, and list local index fixtures from published
catalog-plan IDs using either `run.py inventory` or CLI arguments. Fixture replay and
S7b parser review remain functional after source plan bundles are removed. S7a lands
before S7b review-artifacts; S3's initial standard-layout parser pass can proceed from
the committed fixture while S7b is built. S7a owns this CLI/fixture lifecycle and S7b
consumes the fixture API and S3 types.
