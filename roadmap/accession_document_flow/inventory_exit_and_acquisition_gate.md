# Inventory Exit and Acquisition Entry Gate

Status checked: 2026-10-08. This is the handoff summary for inventory work and the
boundary between offline target planning and document-body acquisition. Stage
contracts remain in the linked subplans; this file records what is implemented,
what is verified, and what still gates a production handoff.

## Decision

The S8 compaction-output slice is implemented and its targeted tests pass. It verifies
the runtime logical-fingerprint gate and removes superseded rows from the compacted
output. It does **not** establish byte-identical Parquet, public inventory query parity,
or deletion of old immutable snapshot files.

S6 target planning can start now as an offline feature. S0 does not block non-XBRL
planning; XBRL requests remain `constructed_candidate` without an availability claim.
S9 work-order and streaming code can start after the S6 row/source contract is fixed
and can use local fixture plans. Production body acquisition must wait for a validated
S6 bundle and source-specific retrieval evidence. Broad historical acquisition remains
gated by S0.

## Stage status

| Stage | Verified state | Remaining handoff work |
|---|---|---|
| [S0](subplans/S0_sec_index_audit.md) | Not complete. Current fixtures and examples do not establish stratified historical coverage. | Authorized stratified survey, portable per-accession results, and selected historical fixtures. Gates historical S3 acceptance and XBRL availability claims. |
| [S1](subplans/S1_cohort_contracts.md) | Cohort identity and validation are implemented. | No inventory-exit blocker identified. |
| [S2](subplans/S2_index_fixture_store.md) | Raw-page capture/replay and successful-case reuse are implemented. | Use it for S0 evidence; it does not replace the live survey. |
| [S3](subplans/S3_index_parser.md) | Typed parser, standard-layout fixture, and synthetic edge tests exist. | S0-era/table evidence and historical acceptance. S5 refuses failed or unrecognized page outcomes rather than publishing them. |
| [S4](subplans/S4_broker_worker.md) | Bounded, resumable worker execution is integrated into the S5 build. An offline scale simulation was reported as passed in prior work; its run report is not tracked. | Preserve a reproducible resource-validation report before operational rollout; no live SEC workload is established here. |
| [S5](subplans/S5_snapshot_publication.md) | Production build, snapshot publication, active reader/query paths, and pointer-last update are implemented. The reader accepts an immutable `snapshot_id` pin for named reads. | Decide whether direct prior-entry-ID supersession mapping remains a required contract; scoped masking currently supplies active-query semantics only. |
| [S6](subplans/S6_target_plans.md) | Detailed design exists; no `document_planning` implementation is present. | Implement source validation/pinning, profiles, matching, immutable bundle publication, and offline tests. The inventory adapter must not repeatedly resolve a moving `current` pointer. |
| [S7a/S7b](subplans/S7a_inventory_cli.md) · [S7b](subplans/S7b_parser_review_bootstrap.md) | Fixture lifecycle and parser-review artifact generation exist. | Keyed field-level parser comparison and S7c/S7d review surfaces remain incomplete; these are not prerequisites to start S6. |
| [S8](subplans/S8_vacuum.md) | Generic and inventory-relation compaction tests pass; details below. | Public-query parity, part-ownership validation, and safe transient staging cleanup remain open. Durable campaign retention uses explicit DAG tags, not automatic plan-directory discovery. |

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
2. `document_planning` (S6) reads exactly one immutable inventory snapshot or catalog
   plan and publishes target intent without network access or source mutation.
3. `document_acquisition` (S9–S10) consumes the target bundle to fetch and process
   selected bodies. S10 belongs to this package; no separate `document_processing`
   package is introduced.

This corrects the older “two independent pipelines” grouping: the handoff has three
package owners, but they form a dependency chain rather than three independent data
producers.

The supplied S6 design is aligned with the detailed subplan as follows:

- A profile may provide `request_id` or derive it only from an unambiguous primary,
  document-type, or package-type selector. No positional defaults; reject collisions.
- A plan consumes one source kind. Hybrid source precedence and fallback are not
  inferred. Catalog-direct plans are primary-only and never synthesize inventory rows.
- The source digest must cover the validated manifest and every source part used by the
  planner. The existing catalog-plan fingerprint alone does not prove those bytes.
  The inventory reader pins one immutable snapshot ID per call, so the S6 adapter
  can resolve a single tip for the whole plan run.
- `plan_id` must be deterministic from profile digest, source kind/identity/digest,
  schema version, and matcher version. Divergent reuse of the same plan ID is refused.
- The plan's `unresolved` status cannot represent a failed/unrecognized inventory page
  today: S5 refuses to publish those pages. `not_filed` is valid only for an accession
  represented by a successfully published, recognized page with no matching optional
  row. Per-accession parse-failure outcomes require a new S5 page-status relation.
- Multiple candidate entries for one request are emitted as separate `ambiguous` rows;
  catalog duplicate occurrences are aggregated deterministically, and conflicting
  primary paths refuse publication.
- Keep XBRL as `constructed_candidate` with constructed-only evidence until S0
  establishes per-accession availability. S0 gates that claim, not basic S6 work.

The root roadmap, design overview, and retirement map now use the same three-package
ownership and semantic `request_id` rule as the S6 subplan.

## Gates for acquisition

### Begin S6 planning implementation

- Keep v1 planning offline and single-source; do not add hybrid fallback.
- The named-snapshot reader path exists; add full source-part digest validation
  and deterministic plan identity before publishing inventory-backed plans.
- Publish `manifest.json` and `targets.parquet` as an atomic immutable bundle with
  schema, count, and digest validation. Reusing a plan ID with different inputs fails.
- Test primary/exhibit/data-file matching, no sequence guessing, `not_filed` versus
  `required_missing`, per-candidate `ambiguous`, catalog-direct refusal, and
  constructed-only XBRL outcomes offline.

### Begin S9 implementation

- Freeze the S6 target row/source contract and make a validated local plan bundle
  available. Build adapters and transport against fixtures; no S0 live survey is needed
  to develop the generic streaming transport.
- Direct retrieval requires a validated same-accession URL. Bundle retrieval requires
  the source accession's advertised bundle URL and an observed sequence; S6 stores the
  exact bundle URL in `target_url`, so S9 need not reopen the snapshot. Never infer a
  sequence from position or catalog order.
- A plan manifest pins source provenance but does not keep its source snapshot alive.
  The immutable target bundle is self-contained for S9. If an audit or future re-planning
  campaign needs the source retained, arrange an explicit DAG tag.

### Enable production body acquisition

- Complete S0 for the historical eras/forms to be claimed, or explicitly constrain the
  rollout to a parser-accepted source population. Do not interpret missing page data as
  `not_filed`.
- Ensure S6 resolved and validated the exact named snapshot when producing the plan, and
  settle whether refresh supersession needs a direct prior-entry-ID mapping beyond
  current scoped-mask behavior. S9 consumes target rows rather than re-reading S5.
- Keep snapshot pruning separate from planning and acquisition. Before enabling
  concurrent vacuum and long-lived runs, verify part ownership and implement transient
  staging cleanup that checks active run locks/leases before TTL removal.

## Remaining work, ordered by dependency

1. Implement S6 source validation and target-plan publication; its catalog-direct branch
   can proceed independently of S0, and the inventory-backed branch can use the
   reader's named-snapshot pin.
2. Run the authorized S0 survey and publish durable audit evidence; use it to finalize
   S3 coverage and XBRL availability policy.
3. Decide and either implement or explicitly remove the S5 direct supersession-ID
   mapping requirement.
4. Add canonical inventory query parity and verify node-local part ownership for S8;
   add transient staging lease/TTL cleanup as a distinct maintenance operation.
5. Implement S9 against immutable S6 bundles, then gather representative acquisition
   and S10 processing evidence before the S11 payload-store decision.

S7c/S7d review and S12 end-to-end operator integration follow their source artifacts;
they improve auditability but do not block offline S6 development. `document_storage`
remains frozen until the separate S11 replacement and retirement gates pass.
