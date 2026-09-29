# Phase 2 Closure Plan

> [!IMPORTANT]
> **Status:** READY FOR IMPLEMENTATION. Decisions in §1 were confirmed on
> 2026-09-29. This document is the remediation plan; it does not itself change
> Phase 2 source code or assert that remediation is complete.
> **Trigger:** the parity audit found a malformed policy-plan output, missing
> integrity and seed-selection wiring, an unbounded hashing path, missing tests,
> and inaccurate Phase 2/Phase 2.5 contracts. `phase_2.md` currently says
> `Status: COMPLETE` and `§14.4 Outstanding: None`; those claims must be corrected
> while remediation is underway.
> **Scope:** `edgar_sec/pipelines/filing_catalog/`,
> `edgar_sec/engine/selection/`, `edgar_sec/engine/company_family/`,
> `edgar_sec/domain/filing_catalog/`, the registered foundation scanners, their
> mirrored tests, and the roadmap/package documentation named below.
> **Reference:** `.v1/phases/02_filing_extraction/` and
> `.v1/defs/filing_catalog/` are read-only comparison sources.

## 1. Confirmed Decisions

- Preserve the two occurrence-output contracts. Deterministic plans publish
  raw target rows using `TARGET_COLUMNS`; policy plans publish the
  feature-enriched occurrence rows produced by `FeatureSnapshotBuilder`.
  Remove only the redundant joined column in policy scope; do not strip policy
  features or force both scopes to `TARGET_COLUMNS`.
- Keep mandatory seed-filer selection. Load the configured seed input for
  selection and preserve a normalized seed artifact in each immutable policy
  plan so expansion is reproducible offline.
- Restore selection-fingerprint verification on plan reuse. Bump the plan
  schema/identity version and do not add a compatibility fallback for old
  bundles. Existing artifacts remain untouched; callers create plans under the
  new identity.
- Add a registered `whole-file-read` scanner for whole-file reads used as hash
  inputs, in addition to fixing the current hash sites.
- Keep the current artifact layout. Correct the documentation and test the
  paths; do not migrate or rename published artifacts.
- Close lower-severity findings through accurate documentation and deliberate-gap
  records. Do not restore the reduced operator menu or narrowed catalog
  resolution, and do not wire audit-only metadata or inventory helpers into
  production without a consumer. Remove only symbols verified obsolete.
- Do not convert the `metadata_sync/registry.py` JSON parse into a streaming
  implementation: its `read_bytes()` feeds `json.loads` and is not a hashing
  regression.

## 2. Verified Contracts and Defects

### 2.1 Occurrence partitions have scope-specific schemas

`planner.py` deterministic scope reads the catalog target rows and publishes
the raw 16-column `TARGET_COLUMNS` schema. Policy scope reads
`snapshot.occurrence_features`; `FeatureSnapshotBuilder` adds policy features
and joins, and those enriched rows are the policy plan's occurrence payload.
At `planner.py`'s policy partition query, `SELECT *` spans
`occurrence_features o JOIN selected_locator_keys s`. That projects the locator
key twice, and DuckDB writes the second as `document_locator_key_1`.

The fix is an explicit `SELECT o.*` from the existing joined relation. It keeps
all feature-enriched columns while excluding the filter-only join key. The
published policy partition schema must match its source
`occurrence_features.parquet`; it must **not** be compared to `TARGET_COLUMNS`.
The deterministic schema remains equal to `TARGET_COLUMNS`. Phase 2.5 needs the
locator work order and occurrence rows; it must document both scope-specific
shapes accurately.

The current contract test asserts containment (`column in schema.names`) and
does not compare the scope-specific occurrence files. Its name also implies
broader equivalence than it checks. Replace it with explicit per-scope schema
assertions and name tests for the contract they actually exercise.

### 2.2 `--source-manifest` passes JSON as Parquet

`catalog_job.resolve_source` parses a Phase 1 manifest into `handoff` but then
uses the manifest JSON path as `candidate`. The file-existence check succeeds;
the subsequent schema/Parquet read fails. This is a documented CLI option and a
confirmed defect omitted from the original 15-item audit.

The Phase 1 snapshot manifest provides `output_path` and `artifact_sha256`. For
an explicit manifest, resolve and validate that payload path, verify its digest
with streaming `file_sha256`, then apply the existing Parquet schema guard. A
missing path, missing required manifest field, digest mismatch, or invalid
schema must fail with `CatalogError`; never fall back to reading the JSON as
Parquet. Add a test through both `resolve_source` and the `materialize`
manifest-input path.

### 2.3 Fingerprint protection is missing from reuse

`reuse_existing_plan` checks structural presence, identity and scope. It does
not validate the selected locator set. The existing `plan_fingerprint` helper
in `expansion.py` binds plan metadata to selected locator keys, but is used for
expansion lineage rather than publication/reuse.

Restore a stored selection fingerprint for newly published plans and verify it
on reuse by reading the published locator keys and recomputing the fingerprint.
The fingerprint protects selection identity; it is **not** a digest of every
Parquet byte in the bundle. Keep this boundary explicit in tests and docs.
Centralize the shared fingerprint helper in a pipeline module usable by both
publication and expansion without a circular import. Bump
`TARGET_PLAN_SCHEMA_VERSION`, which is part of plan identity. A bundle for the
new version that lacks or fails the fingerprint is rejected; do not silently
upgrade or accept legacy bundles in code.

### 2.4 Seed selection and feature-cache identity

`plan_policy` and `expand` accept `seed_filers`, and `DeficitSelector` has a
mandatory-seed phase, but the CLI does not load or pass a seed set. Expansion
therefore fingerprints an empty set and rejects a seeded parent. Separately,
`FeatureSnapshotBuilder` reads `SelectionPolicy.seed_cik_path` to create company
family boundaries. That source content must also be pinned: a changed CSV must
not reuse a feature snapshot with stale family assignments.

Use the policy's configured seed input as the single source. Normalize it once
per plan, pass that normalized set to both selection and family-index
construction, and publish the CIK, name, and selection metadata in the immutable
`seed_filers.csv` sidecar. Do not reopen the external CSV
after normalization. Include its content fingerprint in plan identity and
feature-snapshot cache identity. Persist the same sidecar in expanded child
plans; expansion reads and verifies the parent sidecar, not the original CSV.
Preserve the current missing-file fallback to profile-derived family data,
record an empty selection seed set in that case, and make the absence visible in
plan metadata. The existing `load_seed_cik_csv` sibling-name fallback remains
part of source resolution. No new CLI seed-path flag is needed: planning reads
the path configured by the selection policy, and expansion inherits the
published seed set.

This concerns selector seed filers, not just the separate use of
`seed_cik_path` to build company-family boundaries. The persisted input must
retain `name` for `CompanyFamilyIndex` as well as `seed_group`, `coverage_tags`,
and `notes` used by selection.

### 2.5 Hashing and scanner scope

`catalog_job.py` hashes the Phase 1 source and materialized Parquet shards with
`hashlib.sha256(path.read_bytes())`. Replace both with
`foundation.hashing.file_sha256`; digests must remain identical and peak memory
must be bounded. Do not change `metadata_sync/registry.py`'s JSON parse.

Add a registered `whole-file-read` scanner that detects `read_bytes()` used as
the input to a hash operation. Include its module, `ALL_SCANNERS` registration,
mirrored scanner test, and the scanner list entry required by `AGENTS.md` §5.
Test that it catches the catalog hash form without flagging the JSON parser use.

### 2.6 Actual path layout

`FilingCatalogPaths.snapshots_root` and `.plans_root` both return
`catalog_root`. Catalog snapshots and plan bundles are direct children of
`filing_catalog/`; feature snapshots are separately written under
`filing_catalog/snapshots/<feature-id>/` by `FeatureSnapshotBuilder`. The
`paths.py` module docstring's `snapshots/<catalog_id>` and `plans/<plan_id>`
claims are inaccurate. Do not claim that the feature `snapshots/` directory is
absent, and do not migrate paths for this documentation finding.

### 2.7 Remaining audit findings and intended disposition

| Finding | Disposition |
| :--- | :--- |
| `expansion_metadata.json` and `selection_report.json` have no production machine reader | Keep as audit artifacts; document their audit-only role. Do not add a consumer solely to eliminate the finding. |
| `inventory.py`/`check_floor_feasibility` has no production wiring | Keep the library capability if still useful; correct README language so it is not presented as an automatic pre-run gate. Record the deliberate integration gap. |
| Orphan-symbol list | Remove `resolve_catalog_manifest` if the call-site audit confirms catalog path resolution will remain narrowed. Retain test oracles such as `era_of`, internal helpers, and public inspection/path helpers that still have a clear role. No blanket deletion pass. |
| `catalog.row_group_size` is read by materialization only | Narrow the setting description to the behavior it controls. The audit suggested an environment override for parity; this closure deliberately excludes that new configuration behavior. |
| Operator exposes three menu actions versus v1's five | Document the reduction and the CLI alternatives. Do not restore menu actions without a concrete user need. |
| Catalog resolution accepts fewer forms than v1 | Keep the narrowed id/`current` behavior; document it and remove only the obsolete resolver helper. |
| Phase 2.5 input contract names nonexistent files/schema | Correct the master contract and any linked subplan references to the actual published bundle and scope-specific occurrence schemas. |

Two audit evidence statements also need correction in the closure record:

- `read_bytes()` does occur at `metadata_sync/registry.py`; that JSON parse is
  not a hash-memory defect.
- The test census lists `paths.py` and `operator.py` as `IMPORTED`, not with a
  blank test field. The real gap is absence of dedicated mirrored test files.

## 3. Implementation Order

1. **Pin the two published occurrence contracts with tests.** For deterministic
   plans assert `TARGET_COLUMNS`; for policy plans assert equality with the
   feature snapshot's occurrence schema and assert the duplicate
   `document_locator_key_1` is absent. Demonstrate the policy test fails against
   the current `SELECT *` join.
2. **Fix the policy projection.** Change the policy target query to `SELECT o.*`
   while retaining the join predicate and stable ordering. Do not compare the
   deterministic and policy occurrence schemas to each other.
3. **Repair manifest source resolution.** Resolve the Phase 1 manifest's
   `output_path`, verify `artifact_sha256` with `file_sha256`, preserve existing
   schema validation, and add `resolve_source` plus CLI-path tests.
4. **Replace whole-file hashes and enforce the rule.** Convert the two
   `catalog_job.py` call sites, add hash-equivalence/bounded-memory tests, then
   add and register the scanner with its mirrored tests and `AGENTS.md` entry.
5. **Pin seed inputs and restore selection.** Load and normalize the configured
   seed input once; persist it in policy plan bundles; pass it to selection and
   company-family construction; include its fingerprint in plan and feature
   snapshot identities; have expansion inherit the parent sidecar and preserve
   the parent-locator retention invariant. Add a seeded plan-to-expansion test.
6. **Restore plan fingerprint verification.** Add the selection fingerprint to
   newly published plans, validate it in `reuse_existing_plan` and expansion,
   remove fallback recomputation for plans lacking it, and bump the plan schema
   identity version. Test changed locator keys, a missing fingerprint under the
   new version, and successful reuse of an intact bundle.
7. **Fill mirrored test gaps.** Add `test_paths.py` and `test_operator.py`; move
   operator-specific assertions out of `test_cli.py`. Add an independent-root
   policy rebuild test comparing ordered selection and published bundle
   fingerprints. Keep the deterministic ordering and idempotent-reuse tests
   separately named for their actual guarantees.
8. **Correct docs and record deliberate gaps.** Update filing-catalog README,
   Phase 2 status/closure record, Phase 2.5 master and affected subplans,
   `gap_register.md`, and any root README contract reference. Add a link to this
   closure plan from `phase_2.md`. Remove stale test
   and scanner counts rather than replacing them with new hard-coded totals.
   Update the filing-catalog, selection, and company-family package READMEs
   where their public contracts or deliberate gaps change; update the root
   README contract/layout reference if it describes the Phase 2 handoff.
   Correct the path layout, fingerprint guarantee, source-manifest behavior,
   occurrence schemas, operator/catalog-resolution reductions, inventory scope,
   audit-only artifacts, and row-group setting scope.
9. **Run the quality gate** and review the final source/documentation diff.

Steps 1–3 are the first correctness tranche. Steps 5–6 depend on the plan schema
version change and must land with their serialization/tests. Documentation must
describe verified behavior after all code changes, not planned intent.

## 4. Required Tests and Validation

- Deterministic `targets/form=*/data.parquet` schema equals `TARGET_COLUMNS`.
- Policy target schema equals its feature snapshot occurrence schema; it
  preserves feature fields and has no duplicate/suffixed locator key.
- The policy schema test fails before the projection fix.
- Explicit source manifest resolves the Parquet payload named by `output_path`,
  verifies its digest and schema, and rejects missing, modified, or malformed
  inputs as `CatalogError`.
- Hash replacements produce the same SHA-256 values as before and do not buffer
  the full Parquet file. The scanner catches a hash fed by `read_bytes()` and
  does not flag the JSON parser call.
- A plan built with seeds contains a normalized seed sidecar; expansion consumes
  that exact sidecar, preserves all parent locators, and does not depend on the
  original CSV remaining at its old path.
- Changing seed content changes the plan and feature-snapshot identities; it
  cannot reuse stale family features.
- Changed published locator keys fail the selection-fingerprint check; intact
  bundles reuse; old-schema plans are not accepted as new-schema plans.
- Two independent artifact roots produce identical policy selection and bundle
  fingerprints. Reuse/idempotence tests remain separate and do not stand in for
  a rebuild test.
- Dedicated path and operator tests live at the mirrored package path. The
  operator tests verify the existing three-action contract, not v1 parity.
- `.venv/bin/python check.py` passes, including scanner tests and the full suite.

## 5. Definition of Done

- No published policy occurrence partition contains `document_locator_key_1`;
  the deterministic and policy outputs each satisfy their own documented schema.
- A Phase 1 source manifest is a working, digest-verified input to materialize;
  the JSON manifest itself is never treated as Parquet.
- Seed selection is wired, its normalized input is immutable with the plan,
  expansion inherits it, and feature snapshot identity includes its fingerprint.
- New plan bundles carry and verify a selection fingerprint. No legacy fallback
  or shim is added; the schema/identity version changes.
- Catalog Parquet hashing is streaming, with the new scanner registered and
  documented. The unrelated JSON `read_bytes()` call remains untouched.
- Missing mirrored tests and independent-root policy determinism coverage are
  added.
- Phase 2 no longer claims completion while work is outstanding. Stale hard-
  coded test/scanner totals and all verified Phase 2/Phase 2.5 contract errors
  are corrected.
- Lower-severity scope reductions are either documented as deliberate gaps or
  removed only where a symbol is proven obsolete; no unused production feature
  is added just to make the audit table shorter.
- `.venv/bin/python check.py` passes.
