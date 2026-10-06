# S6 — Target Profiles and Separate Target-Plan Artifacts

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S6**.
- Status: intent layer design; profiles live as tracked JSON, target plans as
  separate immutable bundles pinned to a named snapshot.
- Depends on: S0 XBRL decision, S5 snapshot, S1 cohort contracts.
- Non-blocking: S7 review, S9–S10 acquisition/processing, S12 CLI.

## Objective

Publish versioned profile artifacts and deterministic target plans from one explicit
local source: an immutable inventory snapshot or a filing-catalog plan. Target intent
never enters the inventory and planning never triggers network work. The catalog-direct
mode is a primary-document hint source, not an index observation.

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
        {"request_id": "annual_report", "role": "exhibit", "selector": {"document_type": "EX-13"}, "optional": true},
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

- Every target **must declare an explicit, stable `request_id`**; it is never omitted
  or auto-generated.
- Comma-separated form selectors are first split into individual form tokens, and
  `resolve_alias(form)` is called on **each individual form**; the alias owner does
  not accept un-split comma-delimited strings.
- Semantic canonicalization: form tokens are stripped of whitespace and alias-resolved.
  Selectors are not case-folded indiscriminately (e.g. case-sensitive document types
  or exhibit codes preserve standard statutory case).
- The most-specific matching rule wins; `*` is a fallback, not merged with others.
- Overlapping rules at the same specificity are rejected.
- Primary selection matches the filing form (and its declared canonical aliases)
  against observed `document_type`; it never assumes sequence 1.
- Package requests such as `xbrl_zip` have an explicit selector kind and produce a
  `constructed_candidate` without inventing an inventory entry.
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

The manifest pins `plan_id`, exactly one source artifact kind/ID/digest, the optional
`inventory_snapshot_id` or `catalog_plan_id`, canonical profile/request digest,
target-plan schema version, target-matching implementation version, and counts by
outcome. The target table is one row per requested selector outcome per accession and
matched entry. Its v1 fields:

| Field | Arrow type | Contract |
|---|---|---|
| `target_id` | `string` | SHA-256 of `[plan_id, accession, request_id, inventory_entry_id, outcome]`. |
| `accession` | `string` | Accession requested by the cohort. |
| `request_id` | `string` | Stable selector/rule identity from the profile. |
| `target_role` | `string` | Intent: `primary`, `exhibit`, `data_file`, or `package`. |
| `selector` | `string` | Requested form/type/name selector. |
| `optional` | `bool` | Whether no match is a valid outcome. |
| `inventory_entry_id` | `string`, nullable | Observed source row; null for constructed candidates or no match. |
| `status` | `string` | Outcome status: `matched`, `not_filed`, `required_missing`, `ambiguous`, `unresolved`, or `constructed_candidate`. |
| `status_reason` | `string`, nullable | Stable reason code for a non-match or source-specific refusal. |
| `source_origin` | `string` | Provenance: `inventory_index` (default) or `catalog_direct`. |
| `retrieval_mode` | `string` | `direct_url`, `bundle_sequence`, `constructed_package`, or `none`. |
| `target_url` | `string`, nullable | Observed/resolved href or convention-derived candidate URL. |
| `sequence` | `int32`, nullable | Required for bundle extraction; never guessed. |
| `byte_size` | `int64`, nullable | Source-observed size; unknown for constructed candidates. |
| `availability_evidence` | `string` | `index_html`, `catalog_metadata`, `constructed`, or `none`. |

Matching and outcome rules:

- **Status vs. Provenance**: `catalog_direct` belongs in `source_origin`, not in `status`.
- **Catalog-direct scope**: this source supports primary-only profiles and direct archive URLs. An envelope/stub path, missing primary, or non-primary selector is refused/unresolved; it is never passed off as an index match.
- **`not_filed` vs. `unresolved`**: Use `not_filed` **only** when a recognized, complete
  index page has no matching row for an optional target. An unrecognized or unavailable
  page produces `unresolved`, never evidence that the filing omitted the document.
- **Candidate packages**: A constructed XBRL ZIP path derived from accession rules
  remains a `constructed_candidate` unless S0 establishes empirical proof of
  per-accession availability.
- An unlinked row needs both an advertised bundle URL and a sequence to become a
  `bundle_sequence` target.

## Planner interface and pluggable sources

```python
@dataclass(frozen=True, slots=True)
class InventoryPlanSource:
    snapshot_id: str

@dataclass(frozen=True, slots=True)
class CatalogPlanSource:
    catalog_plan_id: str

TargetPlanSource = InventoryPlanSource | CatalogPlanSource

def plan_targets(
    source: TargetPlanSource,
    profile_path: Path,
    plan_id: str,
) -> PlanBundle: ...
```

The selected source artifact is pinned by ID and digest in the plan manifest. The
inventory adapter reads one named snapshot; the catalog adapter reads one published
catalog plan and emits only validated primary direct URLs. Both produce the exact same
target schema. `catalog_direct` rows have null `inventory_entry_id`, set
`availability_evidence="catalog_metadata"`, and pin the catalog plan; they do not add
synthetic entries or mutate an inventory snapshot. A catalog row is executable only
when its primary path resolves under the same accession's SEC archive directory and
is not a submission-envelope or paper stub. A missing/stub primary is `unresolved`
with `status_reason="no_usable_primary_path"`; an unsafe or cross-accession URL
refuses the plan before output. The catalog adapter rejects a profile containing
non-primary selectors before writing a plan.

V1 plans take exactly one source. Hybrid source precedence/deduplication is deferred;
combining inventory and catalog inputs without an explicit per-target policy could emit
duplicate or contradictory primary targets. Inventory-backed plans remain fully offline
and immutable, and catalog-backed plans likewise make zero HTTP requests.

## Tests

- Each inventory-source request matches only inventory rows; catalog-source requests
  use catalog rows only for primary-direct targets.
- Catalog-direct plans accept only primary selectors and validated direct archive paths; they never synthesize inventory rows.
- Stable `request_id` is validated on all rules; missing ID is rejected.
- Comma-separated form selectors are split and resolved per-token via `resolve_alias`.
- One snapshot serves several plan IDs without HTTP.
- Primary resolution refuses sequence-only guesses.
- Multiple primary matches remain explicit `ambiguous`.
- Missing optional targets produce `not_filed` only on recognized pages.
- Unrecognized or parse-failed pages produce `unresolved`, never `not_filed`.
- Required failures are distinct (`required_missing`).
- `source_origin` is recorded distinctly from match `status`.
- The planner does not mutate the source snapshot.
- The XBRL construction/status follows the S0 decision.
- Overlapping same-specificity rules are rejected; `*` rules are fallback-only.
- Plan digests are stable for identical profile+snapshot input.
- `target_id` is reproducible from its canonical components.
- A changed profile yields a new target bundle, not an inventory change.
- Zero `document_storage` imports.

## Acceptance criteria

Profiles are versioned JSON in `policies/document_targets/` with mandatory `request_id`,
canonical per-form alias resolution, and canonical digests; targeting is deterministic
from exactly one pinned inventory snapshot or catalog plan; and plan bundles are
immutable and source-pinned. Outcomes cleanly separate match status from source
provenance. Catalog-direct targets do not create fake inventory rows.
