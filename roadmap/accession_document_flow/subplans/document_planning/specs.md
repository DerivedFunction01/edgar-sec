# Document Planning (S6): Target and Operator Specification

This specification refines [S6](../S6_target_plans.md) for implementation. S6 owns
offline, deterministic target planning from exactly one pinned source. S0 gates claims
that constructed XBRL package candidates are available; S12 owns the later cross-stage
CLI and vertical test. This work does not integrate or replace `document_storage`.

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
        {"role": "primary", "type": "primary", "optional": false},
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

V1 accepts exactly one source per plan:

| Source kind | Immutable identity | Target scope |
|---|---|---|
| `inventory_snapshot` | Named S5 snapshot ID | Observed primary, exhibit, data-file, and graphic entries; constructed package candidates. |
| `catalog_plan` | Published filing-catalog plan ID | Primary direct targets only. |

There is no cohort filter or cohort seeding in S6 v1. Inventory snapshots already
represent the source cohort; catalog-direct planning uses its selected catalog plan.
Hybrid inputs and separate cohort filtering require a later explicit source contract.
`source_origin` is row provenance (`inventory_index` or `catalog_direct`), not a status.

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
| `primary` | `primary`; `Document Format Files` | Match `document_type` to the accession's filing form after declared form-alias resolution. Never assume sequence 1. A catalog primary must resolve to a safe same-accession archive path. |
| `exhibit` | Exact `EX-13`, `EX-99`, or explicit prefix `EX-*` / `EX-10.*`; `Document Format Files` | Match the requested type only. A usable observed `archive_url`/`href` yields `direct_url`; an unlinked row yields `bundle_sequence` only when both the advertised bundle URL and observed sequence exist. |
| `data_file` | Exact data-file type, `EX-101.*`, or `extracted_xbrl_instance`; `Data Files` | The instance type matches normalized exact description `EXTRACTED XBRL INSTANCE DOCUMENT` and type `XML`; filename suffix is not a fallback. Data-file retrieval requires a usable direct URL. |
| `graphic` | `GRAPHIC`; `Document Format Files` | Match the type only. Filename extensions do not infer graphic rows. Retrieval requires a usable direct URL. |
| `package` | `xbrl_zip`; inventory source only | With a validated accession bundle URL, derive the candidate by replacing `.txt` with `-xbrl.zip`; emit `constructed_candidate`, `constructed_package`, and `availability_evidence="constructed"`, with null `inventory_entry_id`, `sequence`, and `byte_size`. If no bundle URL exists, emit `unresolved`/`no_usable_bundle_url`; an unsafe URL refuses the plan. The candidate does not prove that the ZIP exists or is executable. |

`catalog_plan` accepts only `role="primary", type="primary"` requests. Any other role/type
is rejected before output. Duplicate catalog occurrences for an accession are
aggregated deterministically. Conflicting primary paths, unsafe URLs, or URLs outside
the same accession directory refuse the entire plan; never select an arbitrary path.
A catalog accession with no usable primary produces one `unresolved` row with
`status_reason="no_usable_primary_path"` and `availability_evidence="catalog_metadata"`.

All plan locators use the same archive acceptance contract as S9a and the shared
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
  an XBRL package request has no bundle URL, or a catalog primary has no usable path.
  Use `no_usable_retrieval_locator`, `no_usable_bundle_url`, or
  `no_usable_primary_path` respectively. S5 refuses failed/unrecognized pages, so do
  not infer this status for those pages.
- `constructed_candidate`: the requested XBRL ZIP locator was constructed without
  availability evidence. It is never an executable `matched` row in v1.

For inventory observations, `availability_evidence` is `index_html`; for usable catalog
primary metadata it is `catalog_metadata`; for an XBRL ZIP candidate it is
`constructed`. Use `none` only when no source evidence supports a locator. `status_reason`
is null for ordinary matches; absence/refusal reasons are stable machine-readable codes,
including `no_matching_entry`, `no_usable_retrieval_locator`, `no_usable_bundle_url`,
`no_usable_primary_path`, and `constructed_not_verified`.

The constructed XBRL URL is the accession's SEC archive URL with `.txt` replaced by
`-xbrl.zip`. S0 remains the authority for any later availability policy. The inventory
never inserts a synthetic row into its published relations.

## 3. Plan bundle and deterministic identity

Use the configured artifact root and the shared plan filename so generic plan discovery
can read the bundle:

```text
{artifacts_root}/document_planning/plans/{plan_id}/
├── plan.json
└── targets/part-00000.parquet
```

Additional `part-NNNNN.parquet` files are allowed; paths are relative, sorted, unique,
and listed in `plan.json`. A zero-row plan has an empty parts list. Sort rows by
`(accession, request_id, inventory_entry_id, status)` and write one 128,000-row group per
part (only the final part may be smaller), using zstd. This fixes part boundaries while
bounding memory; do not materialize the source universe or all target rows in Python.

The normalized profile digest includes profile ID/version/schema version and canonical
rules.
The source digest covers the validated immutable source manifest and the declared part
digests needed to establish the selected query scope; validate the bytes of each source
part read. For inventory, the resolved tip and all applicable lineage/part declarations
are pinned together. For catalog plans, validate the plan manifest and its referenced
parts; a locator fingerprint alone is insufficient.

`matcher_version` changes whenever form normalization, role/type matching, URL
validation, `request_id` derivation, or outcome classification changes. Bump the target
schema version for a serialized schema change and bump one of these versions for any
output-affecting write-format change.

Derive `plan_id` as `dplan_` plus the first 32 lowercase hex characters of SHA-256 over
canonical JSON containing exactly:

```json
{
  "target_schema_version": 1,
  "matcher_version": "target-matcher-v1",
  "profile_digest": "...",
  "source_kind": "inventory_snapshot",
  "source_id": "...",
  "source_digest": "..."
}
```

No current-pointer text, cohort ID, wall-clock time, output count, or row order outside
the canonical sort contributes to identity. Reusing the same ID is allowed only when
the validated input identity, manifest payload, and every output part digest agree;
otherwise refuse without replacing the published bundle.

`plan.json` contains `plan_id`, `target_schema_version`, `matcher_version`, profile ID
and version/digest, `source_kind`, `source_id`, `source_digest`, target-row count,
counts for every status, and the ordered part records (`path`, `rows`, `sha256`).
Counts are target rows, not accessions or requests, and their sum equals the total row
count. `plan_digest` is SHA-256 of canonical manifest content with the `plan_digest`
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

For every `matched` row, `retrieval_mode` and `target_url` identify a usable retrieval
path. An `ambiguous` row keeps the locator and source entry for that candidate. A
`constructed_candidate` is explicitly non-executable until a future policy says
otherwise. These rows are self-contained for S9; acquisition does not reopen the source
snapshot or catalog plan.

## 5. Streaming, path, and import rules

The inventory adapter resolves `current` once at the command boundary, displays and
stores that immutable snapshot ID, validates its catalog/lineage, and compiles the S5
relations using infra DAG APIs. It streams ordered accessions and entries in bounded
cursor batches, left-joining entries. S5 publishes `accessions` rows only from recognized
`parsed`/`parsed_empty` outcomes, so an accession with no entries is a valid absence
case. The adapter applies the selected profile rule per accession and writes target rows
incrementally. It never mutates inventory data.

Import only lower-layer DAG/storage APIs plus the source pipeline's permitted
`paths.py`/`schemas.py` contracts. Do not import a sibling `reader.py`, `snapshot.specs`,
operator, or command module. Do not use direct environment access, hardcoded `.artifacts`
paths, fixed worker/thread counts, or `document_storage` imports.

## 6. CLI and interactive operator

The package CLI supports `plan`, `inspect`, and `status`; register the package in `run.py`
under the `planning` entry. S12 may later expose the same planner as `documents plan`,
but that integrated alias and vertical gate do not block the stage-owned S6 CLI/operator.

```text
python run.py planning plan --inventory <snapshot-id|current> --profile-id <id>
python run.py planning plan --catalog-plan <plan-id> --profile-id <id>
python run.py planning inspect --plan-id <plan-id>
python run.py planning status
```

`plan` requires exactly one source argument and a profile ID discovered under the
configured policy root; arbitrary profile paths are not accepted. `current` is accepted
only as an input selection; resolve it once before scanning and persist the resolved ID.
CLI calls are offline and need no network-consent prompt. Invalid source IDs, malformed profiles,
source digest mismatches, unsafe locators, and divergent bundle reuse fail explicitly.

The interactive operator uses `build_menu`, `prompt_paginated_choice`, `prompt_text`,
and `operator_entrypoint` from
[`foundation/runtime/interactive.py`](../../../../edgar_sec/foundation/runtime/interactive.py),
following the discovery and command-delegation patterns of the
[filing-catalog operator](../../../../edgar_sec/pipelines/filing_catalog/operator.py)
and the state/header and cancellation patterns of the
[metadata-sync operator](../../../../edgar_sec/pipelines/metadata_sync/operator.py).
The `run.py` `planning` entry exposes these numeric actions:

1. **Plan targets** — choose a profile, choose one source kind, then select a published
   catalog plan or a named inventory snapshot. The picker is paginated/filterable and
   shows IDs and known row counts; selecting `current` resolves it once and displays the
   resulting snapshot ID before execution. There is no cohort picker.
2. **Inspect a plan** — choose a discovered target plan and report validated source
   pins, row/status counts, and part digests; malformed bundles are reported, not
   repaired.
3. **List plans and profiles** — show discovered IDs, profile versions, and published
   target plans without scanning source rows.
0 returns to the launcher's exit action.

The operator remembers only the last profile, source, and plan as session defaults and
shows them in the menu header. Blank menu input re-renders; picker cancellation returns
without work; invalid profile/source selections are re-prompted or cancelled through
the shared helpers. Planning is offline, so there is no network confirmation. After a
plan is published, report its exact plan ID and status counts; do not automatically
enter acquisition or another pipeline.

## 7. Mirrored tests and acceptance

Add one mirrored module per source module under `tests/pipelines/document_planning/`.
Offline tests must cover:

- profile schema, derived `request_id`, form aliases, wildcard precedence,
  equal-specificity overlap, exact role/type grammar, and overlapping-target refusal;
- pinned inventory source reading across batches with pointer movement during a run,
  source digest verification, no snapshot mutation, and no network calls;
- catalog primary validation, duplicate aggregation, same-accession path checks, and
  refusal of non-primary requests; rejection of non-HTTPS URLs, alternate hosts,
  queries/fragments, unsafe path components, and archive paths for another accession;
- each status/evidence combination, ambiguous-per-candidate rows, missing locators,
  optional/required absence, constructed-only XBRL candidates, and no sequence guessing;
- stable plan/target IDs, target-row count reconciliation, digest verification,
  atomic publication, identical reuse, divergent/corrupt reuse refusal, and bounded
  output batches;
- CLI validation and operator discovery, paging/filtering, cancel/no-op behavior,
  command delegation, and invalid-input recovery.

Acceptance requires two-source parity of Arrow schema, distinct `source_origin`, pinned
input IDs/digests, deterministic immutable bundles, zero network, and zero mutation of
source artifacts. XBRL candidates remain non-executable pending S0 evidence. S7 review,
S9/S10 implementation, S12 integrated UX, and `document_storage` decommissioning are
not S6 acceptance conditions.
