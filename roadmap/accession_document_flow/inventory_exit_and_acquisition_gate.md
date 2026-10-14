# Inventory Exit and Acquisition Entry Gate

Status checked: 2026-10-13. This is the handoff summary for inventory work and the
boundary between offline target planning and document-body acquisition. Stage
contracts remain in the linked subplans; this file records what is implemented,
what is verified, and what still gates a production handoff.

## Decision

The S8 compaction-output slice is implemented and its targeted tests pass. It verifies
the runtime logical-fingerprint gate and removes superseded rows from the compacted
output. It does **not** establish byte-identical Parquet, public inventory query parity,
or deletion of old immutable snapshot files.

S6 target planning is implemented and runs offline from a required filing-catalog plan
and optional pinned inventory snapshot. S0 does not block non-XBRL planning; XBRL requests
remain `constructed_candidate` without an availability claim. S9 projection and
`acquisition run` are implemented for matched direct/bundle targets; run performs the
supported S10 processing step inline. Production derived normalization remains disabled
by the empty processing-budget registry. Historical coverage claims remain gated by S0.

## Stage status

| Stage | Verified state | Remaining handoff work |
|---|---|---|
| [S0](subplans/S0_sec_index_audit.md) | Not complete. Current fixtures and examples do not establish stratified historical coverage. | Authorized stratified survey, portable per-accession results, and selected historical fixtures. Gates historical S3 acceptance and XBRL availability claims. |
| [S1](subplans/S1_cohort_contracts.md) | Cohort identity and validation are implemented. | No inventory-exit blocker identified. |
| [S2](subplans/S2_index_fixture_store.md) | Raw-page capture/replay and successful-case reuse are implemented. | Use it for S0 evidence; it does not replace the live survey. |
| [S3](subplans/S3_index_parser.md) | Typed parser, standard-layout fixture, and synthetic edge tests exist. | S0-era/table evidence and historical acceptance. S5 refuses failed or unrecognized page outcomes rather than publishing them. |
| [S4](subplans/S4_broker_worker.md) | Bounded, resumable worker execution is integrated into the S5 build. An offline scale simulation was reported as passed in prior work; its run report is not tracked. | Preserve a reproducible resource-validation report before operational rollout; no live SEC workload is established here. |
| [S5](subplans/S5_snapshot_publication.md) | Production build, snapshot publication, active reader/query paths, pointer-last update, and accession-scoped `scoped_mask` supersession are implemented. Relation schemas live in `schemas.py`; inventory projection/publication accept and validate pinned base snapshots. | No S5 implementation blocker identified here; the remaining S8 query/ownership/retention work is listed separately. |
| [S6](subplans/S6_target_plans.md) | Versioned target-plan generation, inventory-snapshot pinning, plan inspect/list, and stage-owned CLI/operator are implemented. | Production profile expansion and XBRL availability claims remain bounded by their evidence requirements; S12's `documents plan` alias is absent. |
| [S7a/S7b](subplans/S7a_inventory_cli.md) · [S7](subplans/S7_review.md) | Fixture lifecycle and parser review are implemented; S7c plan compare/snapshot inspect and limited S7d acquisition review are wired. | Keyed semantic parser diffs and role-assessment labels/evaluator review remain incomplete. |
| [S8](subplans/S8_vacuum.md) | Generic and inventory-relation compaction tests pass; details below. | Public-query parity, part-ownership validation, and safe transient staging cleanup remain open. Durable campaign retention uses explicit DAG tags, not automatic plan-directory discovery. |
| [S9](subplans/S9_acquisition.md) | `project`, `status`, and combined live `run` are wired; direct/bundle acquisition is bounded and serial. | Production derived normalization, family-trigger lazy-index selection, acquisition distribution adapter, and cleanup remain incomplete/gated. |
| [S10](subplans/S10_processing.md) | Per-target raw processing is integrated into `acquisition run`; TEXT identity passthrough is test-budgeted. | Production route/handler budgets are empty; Form 4 XML and S10 role evaluation remain unimplemented. |
| [S11](subplans/S11_payload_design.md) | Design only; CLI routes are gate/placeholder responses. | Durable payload snapshot publisher/query requires representative evidence and explicit design approval. |
| [S12](subplans/S12_operator_integration.md) | Root `run.py` exposes the three stage operators; manual stage sequence is available. | No integrated `documents plan`/cross-stage end-to-end quality gate. |

## S8 verification and corrected claim

The targeted command passed **6 tests** with formatting, lint, and all 14 policy
scanners clean:

```text
.venv/bin/python check.py tests/infra/storage/dag/test_compaction.py tests/pipelines/document_inventory/snapshot/test_specs.py
```

The verified tests are:

- `test_compact_lineage_scoped_mask_purging` in
  `tests/infra/storage/dag/test_compaction.py`.
- `test_inventory_relations_compaction_parity` in
  `tests/pipelines/document_inventory/snapshot/test_specs.py`.

They run compaction through its internal logical-fingerprint gate and inspect the
compacted Parquet rows: refreshed entries replace earlier entries in the compacted
output while other accessions remain. They do not hash or compare Parquet files, call
the public inventory query APIs on both sides, or delete the old source snapshot. The
claim is therefore **logical-content gate plus compacted-output filtering**, not
“byte-identical” files or full query parity.

The generic DAG retention path starts from catalog branches and tags, accepts explicit
caller-supplied snapshot IDs, and preserves lineage/checkpoint roots. It does not scan
`document_planning/plans/`. A source ID/digest in a plan manifest proves provenance,
not retention. If a campaign must preserve its source snapshot, an operator can create
a DAG tag; S6 plan publication remains read-only and does not create tags. The DAG
collector removes unreachable snapshot directories; tests do not yet establish
cross-manifest physical-part reference safety. `min_age_seconds` is accepted by the
retention API but is not applied. Transient run cleanup and TTL/lease checks are a
separate, unfinished operation.

## Reconciled S6 contract

The flow is three stage-owned pipeline packages connected by immutable artifacts:

1. `document_inventory` (S0–S5) publishes observed accession/index facts.
2. `document_planning` (S6) reads a required filing-catalog plan for accession scope and
   an optional immutable inventory snapshot for document evidence, then publishes target
   intent without network access or source mutation.
3. `document_acquisition` (S9–S10) consumes the target bundle to fetch and process
   selected bodies. S10 belongs to this package; no separate `document_processing`
   package is introduced.

This corrects the older “two independent pipelines” grouping: the handoff has three
package owners, but they form a dependency chain rather than three independent data
producers.

The supplied S6 design is aligned with the detailed subplan as follows:

- Profile targets declare `role`, `type`, and `optional`; the planner derives the stable
  downstream `request_id` from canonical role/type. No user-maintained ID mapping or
  positional identity; reject duplicate/overlapping role/type targets in one rule.
- Every plan pins a catalog scope; an optional inventory snapshot is its sole locator
  source when selected. Missing snapshot accessions are unresolved, never resolved from
  catalog paths. Without a snapshot, profiles are primary-only and catalog-direct rows
  never synthesize inventory entries. A catalog-direct match validates the supplied
  path, not its index-declared document type. Each catalog-direct primary pins either
  `submitted_primary` or the retained `exact_form_with_lazy_index` selector field. The
  latter is not current runtime authority: current projections emit no family-trigger
  IDs/versions and S9 refuses lazy recovery without them. A future selector change must
  pin reviewed trigger evidence. S10 never fetches an index or repairs a locator. Neither
  selector changes the immutable S6 plan or creates an S5 inventory entry.
- S6 pins the catalog plan and optional inventory snapshot IDs/digests, validates source
  relation parts and plan identity, and streams pinned snapshot lineage through the
  lower-layer DAG reader. Shared S5/S6 relation contracts live in `schemas.py`; the
  direct cross-pipeline schema import is the permitted boundary, not a remaining move.
- `plan_id` must be deterministic from profile digest, required catalog plan ID/digest,
  nullable inventory snapshot ID/digest, schema version, and matcher version. Divergent
  reuse of the same plan ID is refused.
- The plan's `unresolved` status cannot represent a failed/unrecognized inventory page
  today: S5 refuses to publish those pages. `not_filed` is valid only for an accession
  represented by a successfully published, recognized page with no matching optional
  row. Per-accession parse-failure outcomes require a new S5 page-status relation.
- A catalog-scope accession absent from the selected snapshot is `unresolved` /
  `accession_not_indexed`, even for an optional target; missing index evidence is not a
  recognized page with no matching row.
- Multiple candidate entries for one request are emitted as separate `ambiguous` rows;
  catalog duplicate occurrences are aggregated deterministically. Conflicting catalog
  primary paths refuse catalog-only publication; with inventory evidence, catalog
  paths are not locator inputs.
- Keep XBRL as `constructed_candidate` with constructed-only evidence until S0
  establishes per-accession availability. S0 gates that claim, not basic S6 work.

The root roadmap, design overview, and retirement map use the same three-package
ownership and derived role/type identity as the S6 subplan.

## Current handoff and production gates

### S6 planning (implemented)

- Use `python run.py planning plan --catalog-plan <id> --inventory <snapshot-id|current>
  --profile-id <id>` to publish the immutable target plan. It performs no network request.
- The catalog plan defines accession scope. A supplied inventory snapshot is the sole
  locator source; an absent accession is unresolved and receives no catalog fallback.
- `planning inspect`, `planning status`, and `planning compare` are implemented stage-CLI
  routes. Compare is not a separate interactive-menu action.

### S9/S10 manual run path

- Project with `acquisition project --plan-id <id>`, inspect with `acquisition status`,
  then execute live network work with `acquisition run --run-id <id>`.
- The combined run processes supported operations for acquired targets under the same
  lock. Production-derived normalization is still blocked by an empty route/handler
  budget registry; unsupported/unbudgeted operations fail closed.
- Only matched targets with supported direct or advertised bundle-sequence locators
  execute. Ordinary direct failures do not switch to bundle retrieval. Current work-order
  projections do not pin lazy-index triggers, so that recovery path is refused.

Fixture fill is separate local evidence capture; bundle/lazy response groups require
`--retain-response-evidence` at acquisition. Review generate/compare/analyze is offline
and depends on the acquisition run and staged body. It does not publish S11 payloads.

### Broader production rollout

- Complete S0 for the historical eras/forms to be claimed, or explicitly constrain the
  rollout to a parser-accepted source population. Do not interpret missing page data as
  `not_filed`.
- Ensure S6 resolved and validated the exact named snapshot when producing the plan.
  Verify that S5 `scoped_mask` hides refreshed parent entries at the new tip while the
  pinned old tip remains readable. S9 consumes target rows rather than re-reading S5.
- Keep snapshot pruning separate from planning and acquisition. Before enabling
  concurrent vacuum and long-lived runs, verify part ownership and implement transient
  staging cleanup that checks active run locks/leases before TTL removal.

## Remaining work, ordered by dependency

1. Populate production route/handler budgets and validate supported derived processors;
   keep Form 4 XML and family-trigger lazy recovery disabled until their contracts and
   evidence exist.
2. Run the authorized S0 survey to finalize historical S3 acceptance and XBRL
   availability claims.
3. Complete S8 public-query parity, physical part-ownership validation, age-based
   retention, and active-run-safe transient staging cleanup.
4. Gather representative S9/S10 evidence and resolve the S11 payload schema/approval
   gate before implementing durable acquisition publication.
5. Implement the S12 integrated cross-stage quality gate. Stage-owned commands already
   support a manual run; the root launcher has no single `documents plan` workflow.

The acquisition distribution adapter is also unimplemented; the inventory and generic
distribution code do not constitute an acquisition adapter. The legacy
`document_storage` runtime is retired.
