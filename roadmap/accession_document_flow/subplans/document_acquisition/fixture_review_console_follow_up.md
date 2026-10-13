# Acquisition Fixtures & Review Console Follow-up

## Objective

Align the acquisition fixture/review console with the implemented
`document_inventory` fixture/review console: retain an active published plan in the
session; create and fill plan-associated fixtures; discover fixtures; generate,
compare, and analyze review runs offline. Preserve acquisition's exact-attempt evidence
capture and internal fixture-byte verification. Do not carry forward a separate
user-facing replay/export action.

This follow-up is limited to local fixture and review workflows. Evidence means the
captured fixture records and review artifacts derived from them. The only confirmation
prompt covers retaining local fixture evidence; it is not approval for any other
acquisition operation.

No acquisition fixtures exist on disk. This is a clean rewrite: define the new store
contract directly and remove obsolete acquisition fixture paths. Do not add migration,
legacy readers, compatibility aliases, or dual-version behavior.

## Current behavior

The acquisition operator has a dedicated fixture/review submenu. It creates an empty
fixture store, captures a selected run/target/attempt into it, lists fixture cases,
replays one captured selected body to a new caller-chosen path, generates review
artifacts, and compares review runs. Fill and replay ask default-no confirmations.
`review audit` is a fail-closed placeholder. The console has no active-plan selection,
does not bind a fixture to a published S6 plan, and does not analyze review runs.

Inventory's shared review console selects a published plan, creates/fills fixtures
against that plan, discovers fixtures, generates review artifacts, compares runs,
analyzes runs offline, and can switch the active plan. Use this as the interaction
pattern, not as a reason to treat an acquisition response fixture as an inventory
parser-input fixture.

## Fixture verification and review generation

Review generation already materializes and verifies fixture bytes internally, so a
second public replay action is unnecessary for the fixture/review workflow. Keep the
internal verification/materialization primitive; omit a console action that writes the
body to a user-selected path.

- **Fixture verification** reads the recorded response evidence, resolves the selected
  document body in temporary space, and checks its digest and size against fixture
  identity. It is an internal integrity step, not a user export operation.
- **Review generation** selects one or more fixture cases and creates a review-run
  directory. For each case it verifies the fixture body, validates the associated
  acquisition run and pinned work order, processes the run's staged body using its
  requested operations, and writes a manifest plus per-case processing-review
  artifacts. It reports fixture-verification failures separately from processing
  errors; it does not export body bytes to a caller-selected path.

Review generation therefore depends on the associated acquisition run and its staged
body remaining available. A standalone raw-body export would be a different feature;
add it only if there is a concrete user workflow that needs a file outside the review
artifacts.

## Target console

```text
Document Acquisition Fixtures & Review Console
  1. Create local fixture from active plan
  2. Fill fixture from acquisition evidence (confirmation required)
  3. List discovered fixtures
  4. Generate review artifacts from fixture
  5. Compare two review runs (diff & summary)
  6. Analyze review runs (offline)
  s. Switch active plan
  0. Exit
```

Keep top-level acquisition actions unchanged. Snapshot and cleanup operations remain
outside the fixture/review console.

## Contracts

1. **Active plan:** Discover validated published S6 target plans using the owning plan
   discovery service. Selection is session-local and retained until switched or the
   console exits. Switching plans does not mutate an existing fixture or review run.
2. **Plan-pinned fixture:** Creating a fixture requires the active plan and records its
   plan ID, schema version, and canonical input digest. A fixture's plan pin is
   immutable. Filling it may capture only an exact recorded attempt from a run
   projected from that pinned plan; no HTTP request or attempt reconstruction occurs.
3. **Rewrite-only fixture store:** Define one current fixture manifest/store contract
   with an immutable plan pin. No on-disk acquisition fixtures exist, so do not add
   legacy readers, migrations, compatibility aliases, or dual-version paths. Replace
   obsolete CLI and operator fixture paths rather than preserving their behavior.
4. **Fill confirmation:** Show the chosen fixture, plan, run, target, attempt, and byte
   cap before asking default-no consent to retain local response evidence. Declining
   performs no append. The confirmation applies only to storing the selected local
   evidence.
5. **Fixture listing:** Discover fixtures deterministically and show the plan pin,
   capture count, case count, and relevant capture status. Listing remains read-only and
   does not decompress or hash response BLOBs beyond the store's normal integrity
   checks.
6. **Review generation:** Select a discovered fixture and optional capture/target
   filters. Verify the fixture-selected body in temporary space, validate its run and
   pinned work order, and generate artifacts through the acquisition review adapter.
   Generation is offline; it does not capture evidence, mutate the fixture, or export
   body bytes to a user-selected file.
7. **Comparison:** Select two validated acquisition review runs, compute the existing
   case-level diff, and display its summary. Do not compare acquisition runs through
   Inventory's schema-specific parser analyzer.
8. **Offline analysis:** Replace the `review audit` placeholder with a review-run
    analysis command/menu action. Validate selected run manifests and output digests,
    report acquisition-specific processing and fixture-verification outcomes, plus
    stable per-run aggregates. Make zero network calls. Keep it read-only with respect
    to fixtures and review runs; write a separate analysis result only when an explicit
    output path is selected.
9. **Evidence boundary:** Fixture/review acceptance is based on local provenance,
    integrity, and review-output validation. Do not require evidence or approval from
    another acquisition workflow to use this console.

## Implementation sequence

1. Define and test the new fixture manifest/store around the immutable S6 plan pin.
   Pin the plan's stable ID, schema version, and input digest; validate that a fill run
   carries the same plan identity. Replace the old acquisition fixture contract without
   a migration or compatibility layer.
2. Adapt the shared review console pattern for acquisition plan discovery, fixture
   selection, plan switching, list, generate, compare, and offline analysis. Reuse
   `ReviewMenuConfig`/`run_review_menu` only where its adapter contract preserves the
   acquisition-specific store and exact-attempt semantics. Keep fixture replay
   verification internal; do not add a user-facing replay/export action.
3. Add the acquisition `review analyze` command service and deterministic output
   schema. Analysis consumes validated acquisition review artifacts only; it must not
   reuse Inventory parser finding rules or access captured body BLOBs unnecessarily.
4. Update the operator console and command documentation. Remove the misleading
   `review audit` placeholder, expose `Analyze review runs (offline)`, and ensure the
   selected active plan is used consistently for create/fill without changing an
   already-pinned fixture.
5. Add mirrored tests for new-store creation, plan switching and retention, plan
   mismatch refusal, fill-confirmation decline/accept paths, deterministic listing,
   fixture-body verification, review generation, comparison, offline analysis, and
   zero-network behavior. Do not add old-schema compatibility tests. Run focused
   acquisition checks; do not run `check.py --all` unless requested.

## Run/process lifecycle boundary

`combined_run_follow_up.md` separately owns merging acquisition and processing into
one resumable run command and operator action. This follow-up makes none of those
run/process CLI or operator changes and does not combine fixture creation/fill with run
execution. Review generation remains an offline fixture/review action; adapt its
internal processing call to the combined per-target service if needed, without adding a
second processing coordinator.

## Affected surfaces

- `edgar_sec/pipelines/document_acquisition/operator.py` and its mirrored operator
  tests.
- Acquisition fixture manifest validation, discovery, capture/fill services, and
  mirrored fixture-store tests.
- `edgar_sec/pipelines/document_acquisition/commands/review.py`, the review adapter,
  review-run analysis, CLI wiring, and mirrored review tests.
- `roadmap/accession_document_flow/subplans/document_acquisition/fixtures/index.md`,
  `operator.md`, `cli_inventory.md`, and the acquisition review command contract.

Do not edit the frozen
`roadmap/accession_document_flow/subplans/document_inventory/follow_up_run_plan.md`.
Do not implement fixture-to-run projection, snapshot or payload publication, snapshot
status, distribution, cleanup, discard, or production normalization budgets in this
work.

## Acceptance

- The console has an active-plan workflow and the common Inventory fixture/review
  actions, while retaining acquisition's exact-attempt evidence checks.
- Newly created fixtures are immutably pinned to the selected published S6 plan;
  filling refuses runs from another plan. The new format has no legacy reader or
  migration path.
- Within this console, fill is the only confirmation-gated local evidence operation;
  declined confirmation causes no mutation. Review generation and analysis operate on
  validated local artifacts without a separate approval checkpoint.
- The console has no standalone replay/export action. Review generation retains
  internal fixture-body verification and does not produce a caller-selected raw-body
  file.
- Review comparison and analysis validate inputs, produce deterministic summaries,
  and make no network calls. Analysis does not mutate fixture or review-run inputs.
- No snapshot/payload publishing, receipt, staging, cleanup, or discard behavior is
  added.
