# Document Planning (S6): Target and Operator Specification

This specification refines [S6](../S6_target_plans.md) for implementation. S6 owns
offline, deterministic target planning from one required catalog scope and optional
inventory evidence. S0 gates claims that constructed XBRL package candidates are
available; S12 owns the later cross-stage CLI and vertical test. This work does not
integrate or replace `document_storage`.

The dependency-aware implementation sequence and module ownership are in
[plan.md](plan.md). This file owns the normative profile, matching, artifact, and
stage-local operator contract.

## 1. Inputs and package boundary

Profiles are versioned, tracked JSON under the repository's `policies/document_targets/`
directory. The package path resolver anchors that directory at the repository root;
profile files are configuration, not generated artifacts. Their filename stem is the
stable `profile_id`; each document contains `schema_version`, a human-facing `version`,
and non-empty form rules with target requests:

The profile ID is a safe single path component and must equal the file stem; discovery
is limited to direct `*.json` children of that directory. An empty directory is reported
as “no profiles configured”; malformed profile files are shown as invalid, not silently
skipped. Profile contents are parsed and digested once at plan start.

```json
{
  "profile_id": "corporate_financials",
  "schema_version": "1",
  "version": "1.0.0",
  "rules": [
    {
      "form_selector": "10-K, 20-F",
      "targets": [
        {"role": "primary", "type": "primary", "optional": false,
         "catalog_direct_selection": "submitted_primary"},
        {"role": "exhibit", "type": "EX-13", "optional": true},
        {"role": "exhibit", "type": "EX-21", "optional": true}
      ]
    },
    {
      "form_selector": "*",
      "targets": [
        {"role": "primary", "type": "primary", "optional": false}
      ]
    }
  ]
}
```

Each target declaration uses `role` and `type`; the required boolean `optional` controls
`not_filed` versus `required_missing`. No user-authored ID or selector mapping is
required. The planner derives the
downstream stable `request_id` as `"{role}:{canonical_type}"` (for example,
`exhibit:EX-21` or `package:xbrl_zip`). The same role/type may appear in mutually
exclusive form rules and has the same identity. Duplicate or overlapping role/type
targets in one effective rule are rejected; array position never contributes to
identity.

Allowed role/type pairs are `primary`/`primary`, `exhibit`/an exact `EX-*` code or
explicit prefix (`EX-*`, `EX-10.*`), `data_file`/an exact data-file type, `EX-101.*`,
or `extracted_xbrl_instance`, `graphic`/`GRAPHIC`, and `package`/`xbrl_zip`. Trim
surrounding whitespace, then validate case-sensitive type values. Reject every other
pair at profile load; do not infer role from filename or type.

Normalize comma-separated form tokens before alias resolution. Reject duplicate tokens
and duplicate normalized form rules. The most-specific matching form rule wins; `*` is
fallback-only, not merged with another rule. Reject overlapping rules of equal
specificity. Canonicalize the profile digest from sorted normalized rules and sorted
role/type targets, so JSON array order is not identity. Include `profile_id`, schema
version, and human-facing profile version in that digest. Preserve case-sensitive type
values. Fuzzy description/filename matching, arbitrary expressions, and
sequence-position guessing are not part of v1.

Every plan requires a published catalog plan as its accession scope. A named
inventory snapshot is optional evidence for resolving documents:

S6 accepts catalog-plan schema 1.3 only. That plan manifest must declare every
selected `targets/form=<escaped-form>/data.parquet` part with form, relative path,
row count, byte size, and SHA-256; S6 verifies those declarations before reading.
Schema 1.2 plans lack these payload pins and are refused as S6 scope.

| Inputs | Target scope | Locator/evidence behavior |
|---|---|---|
| Catalog plan only | Unique accessions selected by the published plan. | Primary-only profile; a validated catalog path produces `catalog_direct` / `catalog_metadata`, without index-verified document type. |
| Catalog plan + inventory snapshot | The same catalog-selected accession set. | All requests resolve against the pinned inventory only; rows use `inventory_index`. |

The catalog plan owns forms, dates, cohort/seed selection, limits, and selected
rows. S6 adds no filters or source rows. Catalog occurrences are aggregated by
canonical accession before profile matching. Conflicting catalog `form` or
`filing_date` facts refuse the plan; if a snapshot is selected, its accession
form and filing date must agree as well. A missing catalog accession in the
snapshot is `unresolved` / `accession_not_indexed` for every requested target,
regardless of optionality. There is no per-row catalog fallback. The operator
reports the unindexed count and directs the user to `inventory project`.

Without a snapshot, the complete normalized profile must be primary-only. This
is a separate catalog-direct mode, not an implicit fallback for hybrid plans.
`source_origin` records the locator resolver (`inventory_index` whenever a
snapshot was selected, otherwise `catalog_direct`), not the scope source or a
status.

Catalog-direct is an index-free locator mode, not a weaker way to perform the full
inventory match. A `matched` catalog-direct primary records that S6 accepted the
catalog's path; it does not prove that the body is the filing's statutory primary.
The primary target's `type` remains `primary` processing intent and its expected
statutory type is the accession's filing form. These are distinct from the SEC index's
primary designation/sequence and an observed body type. Catalog-only primary targets
must declare one `catalog_direct_selection` policy:

| Policy | S9 behavior after fetching the catalog primary link (physical sequence 1) |
|---|---|
| `submitted_primary` | Accept the submitted primary without a body-type screen or index lookup. No type evidence is written unless independently observed later. |
| `exact_form_with_lazy_index` | Screen the fetched body locally. An ASCII SGML `<TYPE>` mismatch/missing/unverifiable type, or an HTML cover evaluator that does not verify the filing form, is a suspicion trigger for a lazy index lookup. The recognized index's observed `document_type`, not sequence order or filename, selects a replacement slot. A positive HTML cover result avoids the lookup but is not an exact statutory-type assertion. |

The selector is part of the canonical profile digest and every target-plan row; it is
null for inventory-backed targets and prohibited for non-primary roles. `exact_form`
is not a supported selector. Catalog-direct planning itself remains offline and does
not inspect bytes. A transport failure does not authorize a different URL or lazy
index lookup. If a caller needs deterministic type selection without relying on the
local suspicion screen, it must publish inventory evidence and create an index-backed
plan. Calendar-era expectations are not a substitute for that evidence.

S6 is a Layer 4 pipeline. It may use `foundation`, `domain`, `infra`, and the source
pipeline's `paths.py`/`schemas.py` contracts only. The existing inventory reader is a
point/list query surface, not a bounded stream, and a direct import of
`document_inventory.snapshot.reader` or `snapshot.specs` would cross the pipeline
boundary. The inventory adapter therefore pins the selected snapshot ID and streams
through lower-layer DAG query APIs. Before implementation, S5 must expose the canonical
inventory relation names and schemas through
`edgar_sec.pipelines.document_inventory.schemas`; S6 may import that schema module and
`document_inventory.paths`, but must not copy the relation definitions. S5 updates the
inventory package layout README and mirrored schema tests when adding that module.
The adapter validates one immutable lineage and never re-reads a branch pointer between
batches.

The catalog adapter validates the selected plan manifest and its target parts before
planning. Both adapters are read-only and perform zero network requests.

## 2. Selector and target behavior

| Role | V1 `type` values and source table | Match and retrieval contract |
|---|---|---|
| `primary` | `primary`; `Document Format Files` | Match `document_type` to the accession's filing form after declared form-alias resolution. Never assume sequence 1. A matching row resolves by direct URL or, when unlinked, by exact observed bundle sequence if the bundle URL exists. Catalog-direct primaries still require a safe same-accession catalog path. Current code lacks unlinked-primary bundle parity. |
| `exhibit` | Exact `EX-13`, `EX-99`, or explicit prefix `EX-*` / `EX-10.*`; `Document Format Files` | Match the requested type only. A usable observed `archive_url`/`href` yields `direct_url`; an unlinked row yields `bundle_sequence` only when both the advertised bundle URL and observed sequence exist. |
| `data_file` | Exact data-file type, `EX-101.*`, or `extracted_xbrl_instance`; `Data Files` | The instance type matches normalized exact description `EXTRACTED XBRL INSTANCE DOCUMENT` and type `XML`; filename suffix is not a fallback. Data-file retrieval requires a usable direct URL. |
| `graphic` | `GRAPHIC`; `Document Format Files` | Match the type only. Filename extensions do not infer graphic rows. Retrieval requires a usable direct URL. |
| `package` | `xbrl_zip`; requires inventory evidence | With a validated accession bundle URL, derive the candidate by replacing `.txt` with `-xbrl.zip`; emit `constructed_candidate`, `constructed_package`, and `availability_evidence="constructed"`, with null `inventory_entry_id`, `sequence`, and `byte_size`. If no bundle URL exists, emit `unresolved`/`no_usable_bundle_url`; an unsafe URL refuses the plan. The candidate does not prove that the ZIP exists or is executable. |

Catalog-only planning accepts only `role="primary", type="primary"` requests;
each such target requires `catalog_direct_selection` with one of the two supported
values. Any other profile is rejected before output. Duplicate occurrences for one
accession are aggregated. Conflicting catalog primary paths, unsafe URLs, or
URLs outside the same accession directory refuse catalog-only planning. A
catalog accession with no usable primary produces one `unresolved` row with
`status_reason="no_usable_primary_path"` and
`availability_evidence="catalog_metadata"`.

The selector named `primary` is request intent. In inventory-backed plans, S6
compares the filing form with the S5 index row's observed `document_type`; the
selected sequence is only its retrieval locator. Do not conflate the profile's
`target_type`, the index row's type, and the SGML child's `<TYPE>`. S9 records the
selected SGML header as acquisition provenance; it does not reopen S5 or cross-check
the header against the index row. The plan therefore selects from an observed index
declaration but does not independently verify the selected body's type. Such a
cross-check requires carrying the observed type in a versioned target-plan contract.

When an inventory snapshot is selected, catalog path fields do not provide
locators or fallback evidence. The profile rule is selected using the catalog
form; a form or filing-date disagreement with the indexed accession refuses
the whole plan before publication.

All plan locators use the archive acceptance contract consumed by S9's acquisition
commands and the shared
`domain.sec_urls.SEC_ARCHIVE_BASE`/`parse_archive_url` contract:

- Require HTTPS and exact host `www.sec.gov`; reject user information, explicit ports,
  query strings, and fragments.
- Require path `/Archives/edgar/data/{filing_cik}/{accession_without_hyphens}/...`.
  The unpadded numeric `filing_cik` must equal the accession's first ten digits as an
  integer, and the normalized path accession must equal the requested accession.
- Reject empty/dot path segments, decoded `.`/`..`, encoded slash/backslash, literal
  backslashes, and control characters. Direct-document paths may contain safe nested
  segments beneath the accession directory.
- A bundle URL must name the canonical hyphenated-accession `.txt` file directly under
  that directory. A constructed XBRL candidate must retain the same host and directory.

For inventory entries, use the source-derived `archive_url` where present; otherwise
resolve the observed `href` against the filing's archive directory. Validate each
candidate locator selected by the profile before publication; unrelated unselected rows
do not supply target locators. Any malformed, unsafe, or cross-accession candidate
refuses the entire plan rather than silently falling back. Use
`bundle_sequence` only for an unlinked eligible entry with a real sequence and validated
bundle URL; never infer sequence from row order. A single matching row with neither
usable direct nor bundle retrieval is `unresolved`, not matched or absent.

Outcome rules:

- `matched`: one type-matching candidate with a usable locator; emit one row.
- `ambiguous`: multiple type-matching candidates for one request; emit one row per
  candidate and never choose one. A candidate without a usable locator keeps a null URL
  and `status_reason="no_usable_retrieval_locator"`.
- `not_filed`: an optional inventory request has no candidate for an accession present
  in the successfully published S5 `accessions` relation. S5 includes only recognized
  `parsed`/`parsed_empty` page outcomes. Set evidence to `index_html`.
- `required_missing`: a required inventory request has no candidate on such a page.
- `unresolved`: one type-matching inventory candidate has no usable retrieval locator,
  an XBRL package request has no bundle URL, a catalog-only primary has no usable path,
  or a catalog-scope accession is absent from the selected snapshot. Use
  `no_usable_retrieval_locator`, `no_usable_bundle_url`, `no_usable_primary_path`, or
  `accession_not_indexed` respectively. S5 refuses failed/unrecognized pages, so do not
  infer this status for those pages.
- `constructed_candidate`: the requested XBRL ZIP locator was constructed without
  availability evidence. It is never an executable `matched` row in v1.

For inventory observations, `availability_evidence` is `index_html`; for usable catalog
primary metadata it is `catalog_metadata`; for an XBRL ZIP candidate it is
`constructed`. Use `none` only when no source evidence supports a locator. `status_reason`
is null for ordinary matches; absence/refusal reasons are stable machine-readable codes,
including `no_matching_entry`, `no_usable_retrieval_locator`, `no_usable_bundle_url`,
`no_usable_primary_path`, `accession_not_indexed`, and `constructed_not_verified`.

The constructed XBRL URL is the accession's SEC archive URL with `.txt` replaced by
`-xbrl.zip`. S0 remains the authority for any later availability policy. The inventory
never inserts a synthetic row into its published relations.

## 3. Plan bundle and deterministic identity

Use the configured artifact root and the shared plan filename so generic plan discovery
can read the bundle:

```text
{artifacts_root}/document_planning/plans/{plan_id}/
├── plan.json
└── targets/form=<escaped-form>/part-00000.parquet
```

Parts are relative, sorted, unique, and listed in `plan.json`; numbering starts at
`part-00000.parquet` within each form partition. A zero-row plan has an empty parts
list. Reuse `filing_catalog.paths.form_partition_name` for Hive directory names and
reject collisions among selected form values. Sort within each partition by
`(accession, request_id, inventory_entry_id, status)` and write one 128,000-row
group per part (only the final part in a partition may be smaller), using zstd.
This fixes part boundaries while bounding memory; do not materialize the source
universe or all target rows in Python. This is S6's own part layout; filing-catalog
plans currently store `targets/form=<escaped-form>/data.parquet`.

The normalized profile digest includes profile ID/version/schema version and canonical
rules.
The source digest covers the validated immutable source manifest and the declared part
digests needed to establish the selected query scope; validate the bytes of each source
part read. For catalog plans, require version 1.3 and its declared `target_parts`;
the selection fingerprint alone does not pin target payloads. For inventory, the
resolved tip and all applicable lineage/part declarations are pinned together.

`matcher_version` changes whenever form normalization, role/type matching, URL
validation, `request_id` derivation, or outcome classification changes. Bump the target
schema version for a serialized schema change and bump one of these versions for any
output-affecting write-format change.

Derive `plan_id` as `dplan_` plus the first 32 lowercase hex characters of SHA-256 over
canonical JSON containing exactly these fields:

```json
{
  "target_schema_version": 1,
  "matcher_version": "target-matcher-v1",
  "profile_digest": "...",
  "catalog_plan_id": "...",
  "catalog_plan_digest": "...",
  "inventory_snapshot_id": "... or null",
  "inventory_snapshot_digest": "... or null"
}
```

No current-pointer text, wall-clock time, output count, or row
order outside the canonical sort contributes to identity. When `current` is
selected, resolve it once and record its immutable snapshot ID/digest. Reusing the
same ID is allowed only when both input pins, manifest payload, and every output
part digest agree; otherwise refuse without replacing the published bundle.

`plan.json` contains `plan_id`, `target_schema_version`, `matcher_version`, profile ID
and version/digest, both explicit source pins, target-row count, counts by status,
origin, and stable reason, distinct accession coverage counts, and ordered part
records (`path`, `form`, `rows`, `sha256`). Counts are target rows unless named
as accession coverage; status counts sum to the total target-row count.
`plan_digest` is SHA-256 of canonical manifest content with the `plan_digest`
field omitted. Do not include a volatile creation timestamp in this digest.

Publish into a sibling staging directory. Validate schema, counts, ordering, hashes, and
manifest identity before atomically renaming the complete bundle into place. An existing
identical bundle is returned as-is; a partial/corrupt or divergent bundle is refused.
Plan discovery uses `domain.plan.discovery`/`PlanEnvelope` (`plan.json` and non-empty
`plan_id`); a custom envelope is unnecessary unless a human-readable description is
needed.

## 4. Target relation schema

Each row has these fields, with nullability as shown:

| Field | Arrow type | Contract |
|---|---|---|
| `target_id` | string | SHA-256 of canonical JSON array `[plan_id, accession, request_id, inventory_entry_id, status]`; preserve JSON null, never substitute an empty string. |
| `accession` | string | Requested accession. |
| `form` | string | Canonical filing form from the catalog plan; it selects profile rules and the output partition. |
| `filing_date` | string | Catalog filing date retained for downstream filtering and audit. |
| `request_id` | string | Planner-derived identity `"{role}:{canonical_type}"`; not authored in the profile. |
| `target_role` | string | `primary`, `exhibit`, `data_file`, `graphic`, or `package`. |
| `target_type` | string | Canonical profile type, such as `primary`, `EX-21`, `GRAPHIC`, or `xbrl_zip`. |
| `optional` | bool | Whether the profile permits an absent target. |
| `inventory_entry_id` | nullable string | Exact inventory row for observed candidates; null for catalog-direct, constructed, and no-candidate rows. |
| `status` | string | `matched`, `not_filed`, `required_missing`, `ambiguous`, `unresolved`, or `constructed_candidate`. |
| `status_reason` | nullable string | Stable reason code for absence, refusal, or unverified construction. |
| `source_origin` | string | `inventory_index` or `catalog_direct`. |
| `retrieval_mode` | string | `direct_url`, `bundle_sequence`, `constructed_package`, or `none`. |
| `target_url` | nullable string | Validated exact URL for acquisition; null when no safe candidate exists. |
| `sequence` | nullable int32 | Observed sequence required for bundle extraction; otherwise null. |
| `byte_size` | nullable int64 | Source-observed size; null when unknown. |
| `availability_evidence` | string | `index_html`, `catalog_metadata`, `constructed`, or `none`. |
| `catalog_direct_selection` | nullable string | `submitted_primary` or `exact_form_with_lazy_index` on catalog-direct primary rows; null otherwise. |

For every `matched` row, `retrieval_mode` and `target_url` identify a usable retrieval
path. An `ambiguous` row keeps the locator and source entry for that candidate. A
`constructed_candidate` is explicitly non-executable until a future policy says
otherwise. An accession missing from the selected snapshot has one unresolved row
per profile request, reason `accession_not_indexed`, `source_origin="inventory_index"`,
and `availability_evidence="none"`; optionality does not alter this epistemic
unknown. These rows are self-contained for S9; acquisition does not reopen the source
snapshot or catalog plan.

## 5. Streaming, path, and import rules

The catalog adapter validates the published plan, streams its selected target
parts, aggregates rows by canonical accession, and checks consistent form and
filing date. With inventory evidence, the inventory adapter resolves `current`
once at the command boundary, displays and stores that immutable snapshot ID,
validates its catalog/lineage, and compiles S5 relations using infra DAG APIs.
It semi-joins only catalog-scope accessions against the snapshot, streams in
bounded cursor batches, and left-joins observed entries. S5 publishes
`accessions` rows only from recognized `parsed`/`parsed_empty` outcomes, so an
accession present there with no entries is a valid absence case. An accession
not present in the relation is not evidence of absence and is
`accession_not_indexed`. The adapter never mutates inventory data.

Import only lower-layer DAG/storage APIs plus the source pipeline's permitted
`paths.py`/`schemas.py` contracts. Do not import a sibling `reader.py`, `snapshot.specs`,
operator, or command module. Do not use direct environment access, hardcoded `.artifacts`
paths, fixed worker/thread counts, or `document_storage` imports.

## 6. CLI and interactive operator

The package CLI supports `plan`, `inspect`, and `status`; register the package in `run.py`
under the `planning` entry. S12 may later expose the same planner as `documents plan`,
but that integrated alias and vertical gate do not block the stage-owned S6 CLI/operator.

```text
python run.py planning plan --catalog-plan <plan-id> [--inventory <snapshot-id|current>] --profile-id <id>
python run.py planning inspect --plan-id <plan-id>
python run.py planning status
```

`plan` requires `--catalog-plan`; `--inventory` is optional and a profile ID must
be discovered under the configured policy root. Arbitrary profile paths are not
accepted. Without `--inventory`, reject profiles containing any non-primary
target. `current` is accepted only as an input selection; resolve it once before
scanning and persist the resolved ID. CLI calls are offline and need no
network-consent prompt. Invalid IDs, malformed profiles, source digest
mismatches, metadata disagreements, unsafe locators, and divergent bundle reuse
fail explicitly. Without `--inventory`, the plan report states that catalog
primary locators are not index-verified and companion targets are unavailable.

The interactive operator uses `build_menu`, `prompt_paginated_choice`, `prompt_text`,
and `operator_entrypoint` from
[`foundation/runtime/interactive.py`](../../../../edgar_sec/foundation/runtime/interactive.py),
following the discovery and command-delegation patterns of the
[filing-catalog operator](../../../../edgar_sec/pipelines/filing_catalog/operator.py)
and the state/header and cancellation patterns of the
[metadata-sync operator](../../../../edgar_sec/pipelines/metadata_sync/operator.py).
The `run.py` `planning` entry exposes these numeric actions:

1. **Plan targets** — choose the catalog plan that defines accession scope; choose
   either “catalog metadata only” or “use inventory evidence”; when evidence is
   selected, choose a named snapshot or `current`; then choose a compatible profile.
   Each picker is paginated/filterable. Catalog choices distinguish distinct
   accession counts from catalog locator-row counts; snapshot choices show the
   immutable snapshot ID and its known accession count.
    Display the resolved snapshot ID and a read-only coverage preflight (scoped,
    indexed, and unindexed accessions) before plan publication. The preflight
    points users to `inventory project` when accessions are unindexed. It does not
    fetch, project, or mutate either source. The operator asks before publishing
    the immutable target plan, with a default-no response; the explicit CLI command
    does not prompt. In catalog-metadata-only mode, state that only the catalog path
    is validated: document type is not index-verified, companions are not planned,
    and S10 cover processing cannot recover a misidentified link.
2. **Inspect a plan** — choose a discovered target plan and report validated source
   pins, coverage, row/status/origin/reason counts, and part digests; malformed
   bundles are reported, not repaired.
3. **List plans and profiles** — show discovered IDs, profile versions, and published
   target plans without scanning source rows.
0 returns to the launcher's exit action.

The operator remembers the last profile, catalog plan, evidence mode, resolved
snapshot, and output plan as session defaults and shows those pins in the menu
header. Blank menu input re-renders; picker cancellation returns without work;
invalid profile/source selections are reported and can be changed without
silently switching evidence mode. Catalog-only mode offers only primary-only
profiles and preserves the same evidence-limit warning on confirmation. Planning is
offline, so there is no network confirmation. After a plan is published, report its
exact plan ID, input pins, coverage, and status counts; do not automatically project
inventory, enter acquisition, or start another pipeline. Keep this operator under its own
`planning` launcher entry; do not replace or renumber Inventory menu actions.

## 7. Mirrored tests and acceptance

Add one mirrored module per source module under `tests/pipelines/document_planning/`.
Offline tests must cover:

- profile schema, derived `request_id`, form aliases, wildcard precedence,
  equal-specificity overlap, exact role/type grammar, and overlapping-target refusal;
- catalog scope streaming, duplicate accession aggregation, form/date conflict refusal,
  stable catalog pins, and zero source mutation/network;
- pinned inventory evidence reading across batches with pointer movement during a run,
  source digest verification, form/date disagreement refusal, missing-accession
  classification, no snapshot mutation, and no network calls;
- catalog-only primary validation, same-accession path checks, and refusal of
  non-primary profiles; rejection of non-HTTPS URLs, alternate hosts,
  queries/fragments, unsafe path components, and archive paths for another accession;
- no index fetch, body inspection, filename/type inference, or target substitution in
  catalog-only mode, including when the catalog path resembles an exhibit;
- each status/evidence combination, `accession_not_indexed` independent of optionality,
  ambiguous-per-candidate rows, missing locators,
  optional/required absence, constructed-only XBRL candidates, and no sequence guessing;
- stable plan/target IDs, target-row count reconciliation, digest verification,
  atomic publication, identical reuse, divergent/corrupt reuse refusal, and bounded
  output batches;
- CLI validation and operator discovery, paging/filtering, explicit evidence-mode selection,
  coverage preflight, cancel/no-op behavior, no implicit pipeline chaining, command
  delegation, and invalid-input recovery.

Acceptance requires catalog-only and catalog-plus-inventory parity of Arrow schema,
the catalog-selected accession scope in both modes, correct `source_origin`, explicit
catalog and optional snapshot pins/digests, deterministic immutable bundles, zero
network, and zero source mutation. XBRL candidates remain non-executable pending S0
evidence. S7 review, S9/S10 implementation, S12 integrated UX, and
`document_storage` decommissioning are not S6 acceptance conditions.
