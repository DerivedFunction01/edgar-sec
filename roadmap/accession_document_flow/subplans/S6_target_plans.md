# S6 — Target Profiles and Separate Target-Plan Artifacts

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S6**.
- Status: profile-based target plans remain design-only; existing filing-catalog
  locator plans are a partial foundation, not this contract's implementation.
- Depends on S1 cohort contracts and S5 inventory relation schemas for inventory-backed
  planning. S0's XBRL decision gates any claim that a constructed package candidate is
  available or executable; the rest of the profile/plan contract can be implemented
  while XBRL outcomes remain `constructed_candidate`.
- The stage-owned `planning` CLI and interactive operator are part of S6. S12's
  integrated `documents plan` alias and cross-stage operator are non-blocking.
- Non-blocking: S7 review and S9–S10 acquisition/processing.

## Current tracked-code audit (2026-10-09)

- **Status: partially implemented foundation; this subplan is not complete.** `filing_catalog` publishes deterministic and policy locator plans, but those plans do not implement profile rules, target request IDs, per-target outcomes, or the inventory/catalog source union defined here.
- **Evidence:** [`filing_catalog/planner.py`](../../../edgar_sec/edgar_sec/pipelines/filing_catalog/planner.py), [`filing_catalog/publication.py`](../../../edgar_sec/edgar_sec/pipelines/filing_catalog/publication.py), and their mirrored planner/publication tests cover the existing locator-plan contract. [`domain/filing_catalog/schemas.py`](../../../edgar_sec/edgar_sec/domain/filing_catalog/schemas.py) defines its distinct schema.
- **Next step:** move the S5 relation contract to its permitted pipeline `schemas.py`,
  then implement the role/type profile loader, bounded inventory/catalog adapters, and
  source-pinned bundle publication with mirrored tests.

## Objective

Publish versioned profile artifacts and deterministic target plans from one explicit
local source: an immutable inventory snapshot or a filing-catalog plan. Target intent
never enters the inventory and planning never triggers network work. The catalog-direct
mode is a primary-document hint source, not an index observation.

## Profile grammar

Versioned, tracked JSON profiles under the repository's `policies/document_targets/`
directory, resolved from the repository root by the package paths module. Keep these
configuration files separate from generated plans. Each file stem is the stable profile
identity. The v1 grammar:

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

Rules are resolved as follows:

- A target declaration contains `role`, `type`, and `optional`; no user-authored
  `request_id` or selector mapping is required. The planner derives the stable downstream
  `request_id` as `"{role}:{canonical_type}"` (for example, `exhibit:EX-21`). The same
  role/type can recur in mutually exclusive form rules; duplicate or overlapping
  role/type targets within one effective rule are rejected. Array position is never
  identity.
- Profiles are selective and pull-based: authors declare only desired document targets
  rather than enumerating all statutory forms or exhibits. Wildcard `form_selector: "*"`
  matches any filing form.
- Comma-separated form selectors are first split into individual form tokens, and
  `resolve_alias(form)` is called on **each individual form**; the alias owner does
  not accept un-split comma-delimited strings.
- Semantic canonicalization: form tokens are stripped of whitespace and alias-resolved;
  duplicate tokens/rules are rejected. Profile digest input sorts normalized rules and
  role/type targets, so JSON array order is not identity. It includes profile ID,
  schema version, and profile version. Trim type whitespace and preserve case.
- The most-specific matching rule wins; `*` is a fallback, not merged with others.
- Overlapping rules at the same specificity are rejected.
- Primary selection matches the filing form (and its declared canonical aliases)
  against observed `document_type`; it never assumes sequence 1.
- V1 role/type pairs are `primary`/`primary`, `exhibit`/exact or supported `EX-*` type,
  `data_file`/exact or `EX-101.*` type or `extracted_xbrl_instance`, `graphic`/`GRAPHIC`,
  and `package`/`xbrl_zip`. Unsupported role/type pairs fail profile validation.
- Package requests such as `xbrl_zip` have an explicit `type` and produce a
  `constructed_candidate` without inventing an inventory entry.
- Filename/description fuzzy matching and arbitrary selector expressions are out of
  scope.

Profile normalization produces a canonical digest used to pin planning runs.

## Target-plan artifact

Target intent and match outcomes belong in a separate immutable bundle pinned to one
resolved source:

```text
{artifacts_root}/document_planning/plans/{plan_id}/plan.json
{artifacts_root}/document_planning/plans/{plan_id}/targets/part-00000.parquet
```

The manifest pins `plan_id`, exactly one source kind/ID/digest, canonical profile digest,
target schema version, matcher version, target-row counts, and ordered part records with
digests. Derive `plan_id` from the canonical profile digest, source kind and immutable
source identity/digest, schema version, and matcher version; reject divergent reuse of
the resulting bundle ID. The source digest covers the validated source manifest and
part digests needed to establish the selected query scope, and the bytes of every part
read by the planner. Stream output in bounded batches; additional parts use consecutive
`part-NNNNN.parquet` names. Use `plan.json` for compatibility with generic
`PlanEnvelope` discovery. The target table emits one row per candidate entry; an
unmatched request emits one row with null `inventory_entry_id`, and an ambiguous request
emits one row per conflicting candidate. Sort rows by
`(accession, request_id, inventory_entry_id, status)` and emit one
128,000-row zstd row group per part (only the final part may be smaller) so part
boundaries are deterministic and writes remain bounded. Its v1 fields:

| Field | Arrow type | Contract |
|---|---|---|
| `target_id` | `string` | SHA-256 of canonical JSON `[plan_id, accession, request_id, inventory_entry_id, status]`; preserve null as JSON null. |
| `accession` | `string` | Accession in the selected source that matches the resolved form rule. |
| `request_id` | `string` | Planner-derived identity `"{role}:{canonical_type}"`; never user-authored. |
| `target_role` | `string` | Intent: `primary`, `exhibit`, `data_file`, `graphic`, or `package`. |
| `target_type` | `string` | Canonical profile type, such as `primary`, `EX-21`, `GRAPHIC`, or `xbrl_zip`. |
| `optional` | `bool` | Whether no match is a valid outcome. |
| `inventory_entry_id` | `string`, nullable | Observed source row; null for constructed candidates or no match. |
| `status` | `string` | Outcome status: `matched`, `not_filed`, `required_missing`, `ambiguous`, `unresolved`, or `constructed_candidate`. |
| `status_reason` | `string`, nullable | Stable reason code for a non-match or source-specific refusal. |
| `source_origin` | `string` | Provenance: `inventory_index` (default) or `catalog_direct`. |
| `retrieval_mode` | `string` | `direct_url`, `bundle_sequence`, `constructed_package`, or `none`. |
| `target_url` | `string`, nullable | Exact retrieval locator: observed child href for `direct_url`, advertised accession bundle URL for `bundle_sequence`, or constructed candidate URL. |
| `sequence` | `int32`, nullable | Observed sequence for `bundle_sequence`; null otherwise. Never guessed. |
| `byte_size` | `int64`, nullable | Source-observed size; unknown for constructed candidates. |
| `availability_evidence` | `string` | `index_html`, `catalog_metadata`, `constructed`, or `none`. |

Matching and outcome rules:

- **Status vs. Provenance**: `catalog_direct` belongs in `source_origin`, not in `status`.
- **Catalog-direct scope**: this source supports primary-only profiles and direct archive URLs. An envelope/stub path, missing primary, or non-primary selector is refused/unresolved; it is never passed off as an index match.
- **Absence vs. unresolved**: Use `not_filed` or `required_missing` only when a
  recognized page has no type-matching row for the optional or required target. One
  matching inventory row without a usable locator is `unresolved` with
  `no_usable_retrieval_locator`; a catalog primary without a safe path is
  `unresolved` with `no_usable_primary_path`. Multiple type-matching rows are
  `ambiguous`, even if a candidate lacks a locator; retain each row and never choose.
  S5 refuses publication of failed/unrecognized pages, so an inventory-backed plan
  cannot emit outcomes for those pages. Adding per-accession parse-failure outcomes
  requires a persisted S5 page-status relation.
- S5 publishes accession facts only from recognized `parsed` or `parsed_empty` outcomes;
  presence in the pinned `accessions` relation establishes the page result needed to
  distinguish `not_filed`/`required_missing` from unknown failure.
- **Candidate packages**: A requested XBRL ZIP path derived from a validated accession
  bundle URL remains a `constructed_candidate`; without a bundle URL the request is
  `unresolved` with `no_usable_bundle_url`. The candidate is not executable unless S0
  establishes empirical per-accession availability.
- An unlinked row needs both an advertised bundle URL and a sequence to become a
  self-contained `bundle_sequence` target; store the bundle URL in `target_url` so S9
  does not need to reopen the inventory snapshot. A single row without any usable
  locator is unresolved, not absent.

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
    profile_id: str,
    *,
    paths: DocumentPlanningPaths | None = None,
) -> PlanBundle: ...
```

The selected source artifact is pinned by ID and digest in the plan manifest. The
inventory adapter resolves and validates one immutable snapshot tip before reading; it
must not re-read a moving `current` pointer between batches. S6 cannot import the
inventory reader directly under the pipeline boundary, and its point/list query API is
not the bounded source stream required here. Use lower-layer DAG query APIs with the
inventory relation schema contract exposed through
`edgar_sec.pipelines.document_inventory.schemas`; do not copy the relation definitions
from S5. The catalog adapter reads one published catalog
plan and emits only validated primary direct URLs. Both produce the exact same target
schema. `catalog_direct` rows have null `inventory_entry_id`, set
`availability_evidence="catalog_metadata"`, and pin the catalog plan; they do not add
synthetic entries or mutate an inventory snapshot. A catalog row is executable only
when its primary path resolves under the same accession's SEC archive directory and
is not a submission-envelope or paper stub. A missing/stub primary is `unresolved`
with `status_reason="no_usable_primary_path"`; an unsafe or cross-accession URL
refuses the plan before output. The catalog adapter rejects a profile containing
non-primary role/type targets before writing a plan.
Duplicate catalog occurrences for one accession must be aggregated deterministically;
conflicting primary paths refuse the plan rather than selecting an arbitrary row.

V1 plans take exactly one source. Hybrid source precedence/deduplication is deferred;
combining inventory and catalog inputs without an explicit per-target policy could emit
duplicate or contradictory primary targets. Inventory-backed plans remain fully offline
and immutable, and catalog-backed plans likewise make zero HTTP requests.

## Tests

- Each inventory-source request matches only inventory rows; catalog-source requests
  use catalog rows only for primary-direct targets.
- Catalog-direct plans accept only the `primary`/`primary` role/type pair and validated
  direct archive paths; they never synthesize inventory rows.
- Direct, bundle, constructed, and catalog locators share the HTTPS `www.sec.gov`
  accession-path validation contract; unsafe components, queries, and foreign paths
  refuse plan publication.
- The planner derives `request_id` from canonical role/type; duplicate or overlapping
  types in one effective form rule are rejected.
- Comma-separated form selectors are split and resolved per-token via `resolve_alias`.
- One snapshot serves several plan IDs without HTTP.
- Primary resolution refuses sequence-only guesses.
- Multiple type matches emit one explicit `ambiguous` row per candidate, even when one
  candidate has no locator; no candidate is selected implicitly.
- A single matching row without a usable locator is `unresolved`, not `not_filed`.
- Missing optional targets produce `not_filed` only on recognized pages.
- Failed or unrecognized inventory pages cannot appear in a published S5 snapshot; adding
  per-accession `unresolved` outcomes requires a persisted S5 page-status relation.
- Required failures are distinct (`required_missing`).
- `source_origin` is recorded distinctly from match `status`.
- The planner does not mutate the source snapshot.
- XBRL remains `constructed_candidate` with constructed-only evidence until S0 establishes
  per-accession availability; this does not block non-XBRL planning.
- A missing bundle URL makes an XBRL package request `unresolved`; unsafe bundle URLs
  refuse publication.
- Graphic matching uses `document_type="GRAPHIC"`; filename extensions do not infer a
  graphic target. Extracted XBRL instances require the exact normalized description
  marker as well as `document_type="XML"`.
- Overlapping same-specificity rules are rejected; `*` rules are fallback-only.
- Plan IDs/digests are stable for identical profile, immutable source bundle, schema, and
  matcher inputs; divergent reuse of one plan ID is refused.
- `target_id` is reproducible from its canonical components.
- A changed profile yields a new target bundle, not an inventory change.
- Zero `document_storage` imports.

## Acceptance criteria

Profiles are versioned JSON in the repository's `policies/document_targets/` directory
with canonical role/type targets, per-form alias resolution, and canonical digests;
targeting is deterministic from exactly one pinned inventory snapshot or catalog plan;
plan bundles are
immutable and source-pinned. Outcomes cleanly separate match status from source
provenance. Catalog-direct targets do not create fake inventory rows.

The stage-owned CLI and operator are included in S6: `python run.py planning` offers
profile/source discovery, plan inspection, and plan listing using the shared interactive
helpers. The later S12 `documents plan` command and integrated pipeline wizard remain
separate. See [the detailed target and operator specification](document_planning/specs.md).
