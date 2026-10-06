# S6 — Target Profiles and Separate Target-Plan Artifacts

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S6**.
- Status: intent layer design; profiles live as tracked JSON, target plans as
  separate immutable bundles pinned to a named snapshot.
- Depends on: S0 XBRL decision, S5 snapshot, S1 cohort contracts.
- Non-blocking: S7 review, S9–S10 acquisition/processing, S12 CLI.

## Objective

Publish versioned profile artifacts and deterministic target plans that consume a
named immutable inventory snapshot. Target intent never enters the inventory and
never triggers network work.

## Profile grammar

Versioned JSON artifacts under `policies/document_targets/`, with one file per
profile and stable identity via filename. The v1 grammar:

```json
{
  "profile_id": "corporate_financials",
  "schema_version": "1",
  "version": "1.0.0",
  "rules": [
    {
      "form_selector": "10-K, 20-F",
      "targets": [
        {"request_id": "primary", "role": "primary", "selector": {"kind": "primary"}, "optional": false},
        {"role": "exhibit", "selector": {"document_type": "EX-13"}, "optional": true},
        {"request_id": "subsidiaries", "role": "exhibit", "selector": {"document_type": "EX-21"}, "optional": true}
      ]
    },
    {
      "form_selector": "*",
      "targets": [
        {"request_id": "primary", "role": "primary", "selector": {"kind": "primary"}, "optional": false}
      ]
    }
  ]
}
```

Rules are resolved as follows:

- Comma-separated form selectors are resolved through the existing form-alias owner.
- The most-specific matching rule wins; `*` is a fallback, not merged with others.
- Overlapping rules at the same specificity are rejected.
- The v1 document-type selector is exact after whitespace normalization and case
  folding.
- Primary selection matches the filing form (and its declared canonical aliases)
  against observed `document_type`; it never assumes sequence 1.
- Package requests such as `xbrl_zip` have an explicit selector kind and may produce
  a constructed candidate without inventing an inventory entry.
- Filename/description fuzzy matching and arbitrary selector expressions are out of
  scope.

Profile normalization produces a canonical digest used to pin planning runs.

## Target-plan artifact

Target intent and match outcomes belong in a separate bundle pinned to the resolved
snapshot:

```text
{artifacts_root}/document_planning/plans/{plan_id}/manifest.json
{artifacts_root}/document_planning/plans/{plan_id}/targets.parquet
```

The manifest pins `plan_id`, `inventory_snapshot_id`, canonical profile/request
digest, target-plan schema version, target-matching implementation version, and
counts by outcome. The target table is one row per requested selector outcome per
accession and matched entry. Its v1 fields:

| Field | Arrow type | Contract |
|---|---|---|
| `target_id` | `string` | SHA-256 of `[plan_id, accession, request_id, inventory_entry_id, outcome]`. |
| `accession` | `string` | Accession requested by the cohort. |
| `request_id` | `string` | Stable selector/rule identity from the profile. |
| `target_role` | `string` | Intent: `primary`, `exhibit`, `data_file`, or `package`. |
| `selector` | `string` | Requested form/type/name selector. |
| `optional` | `bool` | Whether no match is a valid outcome. |
| `inventory_entry_id` | `string`, nullable | Observed source row; null for constructed candidates or no match. |
| `status` | `string` | `matched`, `not_filed`, `required_missing`, `ambiguous`, `unresolved`, or `constructed_candidate`. |
| `retrieval_mode` | `string` | `direct_url`, `bundle_sequence`, `constructed_package`, or `none`. |
| `target_url` | `string`, nullable | Observed/resolved href or convention-derived candidate URL. |
| `sequence` | `int32`, nullable | Required for bundle extraction; never guessed. |
| `byte_size` | `int64`, nullable | Source-observed size; unknown for constructed candidates. |
| `availability_evidence` | `string` | `index_html`, `constructed`, or `none`. |

Matching rules:

- An absent optional selector is represented in the plan, never synthesized as an
  inventory row.
- A primary selector matches form/type evidence, not sequence 1; zero or multiple
  primary matches are explicit `unresolved`/`ambiguous`.
- An unlinked row needs both an advertised bundle URL and a sequence to become a
  `bundle_sequence` target.
- The `*-xbrl.zip` path is derived from accession and archive rules only after the
  S0 audit establishes the rule; without per-accession existence evidence the row is
  a `constructed_candidate`.
- No tier bypass from catalog `primary_document` hints.

## Planner interface

```text
plan_targets(snapshot_id, profile_path, plan_id) -> PlanBundle
```

The planner reads the named snapshot only, never writes it, and makes no HTTP
requests. The same snapshot serves several plan IDs. A profile change produces a new
target bundle without touching the snapshot.

## Tests

- Each profile request matches only inventory rows.
- One snapshot serves several plan IDs without HTTP.
- Primary resolution refuses sequence-only guesses.
- Multiple primary matches remain explicit.
- Missing optional targets appear only in the plan.
- Required failures are distinct (`required_missing` vs `not_filed`).
- The planner does not mutate the source snapshot.
- The XBRL construction/status follows the S0 decision.
- Overlapping same-specificity rules are rejected.
- `*` rules are fallback-only, never merged.
- Comma-separated selectors resolve through the form-alias owner.
- Plan digests are stable for identical profile+snapshot input.
- `target_id` is reproducible from its canonical components.
- A changed profile yields a new target bundle, not an inventory change.
- No `document_storage` imports.

## Acceptance criteria

Profiles are versioned JSON in `policies/document_targets/` with normalization and
canonical digests; form-family resolution goes through the existing forms alias
owner; targeting is deterministic from a named inventory snapshot; and plan bundles
are immutable and pinned to the resolved snapshot ID. Profiles express primary,
exhibit/data-file selectors, optionality, and package requests. No tier bypass occurs
from catalog `primary_document` hints.
