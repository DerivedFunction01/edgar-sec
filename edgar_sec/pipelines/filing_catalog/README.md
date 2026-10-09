# filing_catalog — Phase 2: zero-network catalog materialization and target planning

Turns a finalized Phase 1 snapshot dataset into an immutable filing catalog and
then into immutable, content-addressed **target plans** that Phase 2.5 consumes.
It performs no network I/O at all: it is not a fetcher, and nothing in it
constructs an HTTP client.

## Purpose

Phase 2 is the first *downstream consumer* of a Phase 1 artifact and the first
zero-network pipeline: read the published Phase 1 snapshot, unnest its nested
`filings` arrays into flat document targets, and publish a selectable work order
for a future acquisition phase.

Two planning scopes with genuinely different jobs:

- **Deterministic** (`plan --scope deterministic`, the default) — a fast,
  zero-heuristic slice filtered by forms, document suffixes, a date selection,
  and an optional limit, producing the base locator projection. The date
  selection narrows which rows are *eligible*; this scope deliberately refuses
  to reason about eras or cohort balance.
- **Policy** (`plan --scope policy`) — the selection engine against a declared
  quota profile, producing the policy locator projection plus a reserve pool.
  The only scope that stratifies: era bands and a form-by-era allocation.

Status: **Complete.**

The zero-network property is proved, not asserted:
`tests/test_network_isolation.py` walks the import graph by AST from every module
of this package and asserts none reaches `edgar_sec.infra.sec_http`. A grep would
miss a re-export, an alias import, and a function-local import; all three are real
ways a network dependency creeps in.

## Contracts

**Guarantees to callers**

- **Zero network, proved structurally.** No module here imports
  `edgar_sec.infra.sec_http` or constructs a `SecHttpClient`.
- **`materialize` refuses rather than repairs.** It rejects a transient source path,
  a source column list that does not match the submissions schema exactly, an
  existing snapshot directory, and source parts that share a CIK. A Phase 1 schema
  change fails loudly instead of producing a silently truncated catalog, and an
  explicit `--artifacts` root cannot silently destroy published state.
- **`materialize` writes one target shard per source part.** Occurrence dedup is per
  shard and keyed on `source_cik`, so parts sharing a CIK are refused rather than
  repaired. Peak memory is set by the densest single part rather than by the cohort.
- **Target shards are not globally sorted, and the manifest says so.** Each shard
  is ordered by the projection key; shards follow Phase 1 source-part order, whose
  CIK ranges overlap. `sort_order: "source_part_order"` is recorded so a consumer
  cannot read one shard's ordering as a dataset-wide guarantee.
- **Publication is atomic and never partially visible.** A catalog is staged under
  the transient tree and published with a single `os.replace`; staging is removed on
  any failure.
- **Only the durable tree advances `current`.** With an explicit artifacts root the
  snapshot directory is still written atomically but the pointer is not moved, so a
  scratch directory can be planned from without disturbing published state.
- **Durable publication is CAS-backed.** A durable `materialize` stages the catalog and
  compares-and-swaps the target branch pointer under the shared publication lock
  (`--branch`, default `main`; `--expected-branch-tip` pins the branch tip expected at
  commit). A stale tip leaves the pointer unchanged. Scratch materialization (an explicit
  artifacts root) writes the snapshot but never moves the pointer.
- **`plan --catalog` selects input; it does not publish.** It is a read selector over
  published Phase 1 snapshots for later `materialize`/`plan` use. Source identity,
  inferred lineage, and scratch roots are governed by `materialize`, whose durable path
  advances the DAG catalog pointer.
- **Plan identity is a function of the request.** The same catalog and the same
  filters always resolve to the same published bundle, and an exact rerun reuses it
  instead of forking a new one. A directory that exists but describes a different
  request, is incomplete, or no longer matches its recorded selection fingerprint is
  a `PlanConflictError`, never a rewrite.
- **A plan bundle is complete when it matches its recorded manifest.** That requires
  every required file, the seed sidecar for a policy plan, and a match between the
  on-disk partition set and the one recorded in `plan.json`, so a legitimately empty
  plan remains complete while a bundle that lost a shard is rejected. Schema 1.3
  plans also verify each selected target part's row count, byte size, and SHA-256.
- **A zero-row plan is still structurally complete and reusable.** The `targets/`
  directory and `locator_groups.parquet` are always written.
- **Cohort inputs are content-bound and fail closed.** Deterministic `--cohort`
  planning semi-joins target `source_cik` values to the cohort's integer CIKs, and
  includes the resolved cohort id and dataset digest in plan identity. Policy
  `--seed-cohort` uses its dataset rows instead of the configured seed CSV and
  fingerprints both the normalized seeds and cohort provenance. Missing, unreadable,
  count-inconsistent, or digest-mismatched cohort datasets fail planning; an empty
  deterministic cohort selects zero targets.
- **Policy plans consume immutable, pre-published family indexes.** The active index
  must belong to the active SEC universe, match the current rule fingerprint, and
  pass dataset digest and Parquet schema checks. Its id participates in plan identity;
  planning never builds or refreshes the taxonomy.
- **One row per document locator.** Grouping is on `document_locator_key` alone,
  with representative columns chosen by a total order, so the representative is
  deterministic even when co-filers share a locator.
- **Form filters are exact allowlists.** A form is selected only when it is named
  verbatim, so an amendment variant such as `10-K/A` is selected by listing it
  explicitly; `--forms 10-K` never reaches `10-K/A`.
- **The date filter is one selection, not separate bounds.** Per-field date flags are
  a `TypeError` at the signature: the selection is one union over `report_date`.
- **Expansion retains 100% of the parent, and checks compatibility first.** The
  child's selection runs with the parent's keys as `parent_active_keys`, so they are
  in the exclusion set before any candidate pool is drawn; a mismatched scope,
  catalog, corpus, form set, seed set, schema version, or selection fingerprint fails
  before selection rather than after an expensive feature build.
- **`status` reads the DAG database only.** It never opens a Parquet payload, never
  materializes a catalog, and never contacts the network, so it stays cheap enough
  for a menu loop. The one Parquet reader is `auto_policy`, a separate command-time
  derivation.
- **Identifiers are validated as path segments.** `safe_identifier` rejects any
  character outside `[A-Za-z0-9_.-]`, so a caller-supplied catalog id can never
  escape the tree it is resolved against.
- **Progress goes to stderr, result to stdout.** `_emit_progress` writes to
  `sys.stderr` so `... | jq` works; mixing a human-readable trace into stdout would
  corrupt the payload.
- **Resource limits are not parameters.** `materialize` accepts no `threads`,
  `memory_limit`, or batch size: `connect()` derives resource limits from the
  cgroup-aware `derive_resources()`, and the source part is the unit of work. Heap is
  reclaimed between the profile and target passes and between target shards.

**Obligations callers place on this package**

- Publish a Phase 1 snapshot before materializing. With no explicit source, the
  Phase 1 `current` pointer resolves the dataset and `CatalogError` is raised if
  nothing is published.
- Treat a published catalog or plan bundle as permanent. To change one, remove it
  deliberately; the code will not do it for you and will not repair it in place.
- Do not expect a `run` command. There is none: nothing in this phase performs
  network work, so Phase 1's resumable-chunk lifecycle has no analogue here.
- For `plan --scope policy`, supply exactly one of `--policy PATH` or
  `--auto-policy`. A policy plan built from an assumed quota profile would be
  indistinguishable from a deliberate one in the published `plan.json`.
- Publish the official universe and its family index before policy planning. Use the
  cohort pipeline's family-index command; planning refuses missing, stale, or corrupt
  indexes rather than building them on demand.
- Cohort records and datasets must be available under the same `--artifacts` root
  used for planning. Use `--cohort` only with deterministic scope and
  `--seed-cohort` only with policy scope; seed cohorts replace, rather than merge
  with, policy-configured seed CSV rows.
- Do not widen `plan()` with policy-only parameters. `selection_policy_path`,
  `seed_cik_path`, `parent_plan_dir`, and `target_units` are absent from that
  signature by design; they reappear with the policy scope and with expansion.
- Do not treat a shortfall as a failure of a fresh plan. A fresh policy plan
  publishes whatever the corpus could supply, reporting the shortfall in
  `underfilled_floors`. Only an *expansion* is refused for failing to reach
  `target_units`.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `dag` | Snapshot DAG operations | `[--root]`, `[--json]` |
| `expand` | scale a policy plan while retaining every parent locator | `--parent-plan`, `--target-units`, `[--artifacts]` |
| `materialize` | build a catalog snapshot from a Phase 1 snapshot | `[--source]`, `[--source-snapshot]`, `[--source-artifacts]`, `[--artifacts]`, `[--branch]` |
| `plan` | publish a deterministic or policy-driven target plan | `--catalog`, `[--scope]`, `[--policy]`, `[--auto-policy]`, `[--cohort]`, `[--seed-cohort]`, `[--artifacts]`, `[--forms]`, `[--suffixes]`, `[--dates]`, `[--limit]` |
| `status` | report published catalogs and plans from the DAG catalog | `[--artifacts]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
# Materialize a catalog from a Phase 1 snapshot
python run.py filing-catalog materialize --source-snapshot 2024-01-15T120000Z

# Plan a deterministic target list
python run.py filing-catalog plan --catalog --scope deterministic --forms 10-K --dates 2023-01-01..2023-12-31 --limit 100

# Plan a policy-driven target list
python run.py filing-catalog plan --catalog --scope policy --auto-policy --cohort curated

# Expand a policy plan to meet target units
python run.py filing-catalog expand --parent-plan plan-2024-01-15 --target-units 500

# View current catalog state
python run.py filing-catalog status
```

### Artifact layout

The published layout is in the
[root README](../../../README.md#filing-catalog-pipeline-zero-network); three
facts are specific to this package:

- **Catalog snapshots and plan bundles live in separated roots.**
  `filing_catalog/snapshots/<catalog_id>/`, `filing_catalog/snapshots/catalog.sqlite`,
  and `filing_catalog/plans/<plan_id>/`, so a reader can tell a snapshot from a plan by
  name.
- **Feature snapshots share the `snapshots/` filesystem root but are not catalog
  nodes.** Catalog discovery returns only records in `catalog.sqlite`; feature-cache
  reuse remains owned by the selection engine.
- **Bundle contents are scope-specific.** `targets/form=<FORM>/data.parquet` is the
  *occurrence* surface: a deterministic plan writes the raw catalog target rows,
  exactly `TARGET_COLUMNS`; a policy plan writes the feature-enriched occurrence
  rows it selected from. `locator_groups.parquet` is the scope-independent *work
  order*. The occurrences are not interchangeable between scopes.

### `materialize`

`resolve_source` picks the Phase 1 dataset by an explicit Parquet path, an explicit
snapshot id, or the `current` pointer. Snapshot ids resolve only through the Phase 1
DAG catalog; relation order and digests come from its SQLite records, not folder scans.

`catalog_id` is the Phase 1 `snapshot_id` when the handoff supplies one, otherwise a
digest over the source dataset's identity and this package's schema versions.

The catalog is built one source part at a time, and each part's occurrences are
written to its own `filing_targets/part-NNNNN.parquet`. The DAG node records output
relations, schema versions, form counts, and source provenance in SQLite. Staging is
published before the durable DAG record is advanced; no JSON snapshot sidecar is
written or used to classify snapshot folders.

Sharding bounds peak memory to the densest single part instead of the whole cohort,
and it adds one precondition: because occurrence dedup is per shard, source parts
sharing a CIK are refused rather than repaired.

### `plan` and `plan_policy`

Both derive a `request` dict, hash it to a `plan_id`, ask `reuse_existing_plan`
whether the bundle is already published (raising on a conflict), and only then
enter `staged_plan_bundle`.

An optional deterministic cohort is resolved from the cohort catalog under the
planning artifacts root. Its stored relative path is resolved by `CohortPaths`, its
dataset digest and catalog row counts are checked, and a bound semi-join compares
`try_cast(source_cik AS BIGINT)` with `try_cast(cik_padded AS BIGINT)`. Policy seed
cohorts follow the same input checks; their `cik_padded` rows become `SeedFiler`
records with `seed_group="cohort"`, cohort-name coverage tags, and cohort provenance
notes. Both cohort id and dataset digest enter the request before its identity is
computed. Omitting these flags retains the existing unfiltered and configured-seed
behavior.

The deterministic scope discovers the available forms *after* applying the form,
suffix, and date filters, writes one `targets/form=<FORM>/data.parquet` per form
ordered by document locator, applies `limit` within the ordered subquery, and always
writes `locator_groups.parquet`. The policy scope builds a feature snapshot over the
catalog's target and profile files, runs the quota selector, loads the selected and
reserve keys into temp tables, and writes the policy locator projection and the
reserve pool. Both write `plan.json` and `selection_report.json`, stamping
`plan_fingerprint` from the locator groups the bundle actually holds.

The deterministic scope's date selection is a *date selection* over `report_date`:
`--dates` takes one comma-separated union of absolute intervals and recurring
calendar periods. The grammar, its canonical form, and its persisted
representation live in `domain.filing_catalog.filters`; both the CLI and the wizard
go through that one parser. Consequences worth knowing:

- The **normalized** clauses, not the caller's spelling, enter the request, so two
  spellings of one selection resolve to one published plan rather than forking
  near-duplicate bundles.
- An empty selection is no date predicate at all and keeps rows whose
  `report_date` is unreadable; a nonempty one cannot place such a row and excludes
  it. Form discovery runs the date predicate too, so a form excluded only by date
  publishes no partition rather than an empty one.
- The filter runs on a parsed `DATE` column the planner projects once into a
  `catalog_dated` view, so the predicate does not re-parse `report_date` per
  reference. Partitions project `TARGET_COLUMNS` by name rather than taking that
  view's shape — selecting it would publish a column no consumer declared.

### What a policy plan publishes

A policy's **date selection** uses the same grammar `--dates` uses, over
`report_date`, and is enforced by the selection engine rather than applied to the
published rows afterwards. The engine's stage order, its per-stage guarantees, and
the era-band, seed-manifest, and determinism contracts it owns are in
`engine/selection/README.md`. What the planner in this package adds:

- **Era bands are resolved before the request is hashed and written into
  `plan.json`.** An empty `era_bands` list means *derived*, not unstratified: the
  planner resolves bands from the report years the policy's own forms and date
  selection can reach, so no band is empty by construction. A selection matching no
  dated row falls back to the catalog's own year range rather than a synthetic one.
  Because the published plan embeds its *resolved* policy, expansion compares a
  derived-band draft against those bands leniently, so editing strata produces a new
  root plan rather than an expansion.
- **`form_era_allocation`** records per-cell `available`/`selected`/`shortfall` plus
  the `equal_quota` and `unallocated` totals, so a plan never claims a target it
  could not meet.
- **`inventory_feasibility`** reports, per declared floor and composite, how many
  locators the corpus held against how many the policy asked for. It is advisory and
  cannot fail a fresh plan: a shortfall is still reported in `underfilled_floors` and
  the plan publishes. Each known reason for declining to check is reported as
  `checked: false`; an unexpected error still propagates, because a snapshot that
  cannot be read is a broken run rather than a shortfall.
- **`seed_filers.csv`** is the normalized seed set, loaded once before anything
  consumes it, so a plan cannot disagree with itself about which registrants are
  mandatory. Its fingerprint participates in the plan identity. Expansion reads the
  set from the **parent's published sidecar**, not the configured CSV, so a child
  reproduces its parent's selection even if the original file has moved, been
  edited, or been deleted.

### `expand`

Expansion gates run in order: the parent's scope is checked before anything else;
`selection_policy` must be embedded in the parent's `plan.json`; the schema and
fingerprint gate re-runs; `target_units` below the parent's selected locator count
is a contraction and is refused; the child policy derives from the **parent's
embedded policy** rather than the caller's draft, so the child inherits the era
bands the parent was stratified under and reuses its feature snapshot; and a child
whose `unique_locators_count` falls short of `target_units` publishes nothing.

Lineage keys are written last, as a rewrite of an already-published `plan.json`,
because lineage is a function of the selection the plan just recorded. That rewrite
is atomic and only ever gains keys, and it carries the stamped `plan_fingerprint`
with it.

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
```text
{artifacts_root}/
├── filing_catalog/  # Root of the published catalog dataset.
│   ├── plans/  # Root of published target-plan bundles.
│   │   └── {plan_id}/  # Directory holding one immutable target-plan bundle.
│   │       └── seed_filers.csv  # The plan's normalized seed sidecar, published with a policy plan.
│   ├── policies/  # Root of published selection policies.
│   └── snapshots/  # Root of published catalog snapshot directories, and of the pointer.
│       ├── {catalog_id}/  # Directory holding one immutable catalog snapshot.
│       │   ├── filing_targets/  # Directory holding the sharded filing-target dataset.
│       │   └── company_profiles.parquet  # Deduplicated registrant profile dataset for one snapshot.
│       └── catalog.sqlite  # SQLite DAG catalog database for published catalog snapshots.
└── transient/
    └── filing_catalog/
        └── {catalog_id}/  # Staging directory for one catalog, never published.
```
<!-- AUTOGEN:PATHS:END -->

## Deliberate gaps

- **`locator_groups.parquet` does not scale past a mid-sized plan.** Known defect,
  not a design choice. Planning a full-corpus catalog fails with
  `OutOfMemoryException` at the locator copy, identically with and without a date
  selection. The determinism the grouping buys — a representative chosen by a total
  order rather than by scan order — is worth keeping; the untried remedy is narrowing
  the aggregate to colliding keys, which changes the collapse rule's implementation
  but not its output, and needs equality tests against the current query first. Until
  then, a large deterministic plan must be narrowed with `--forms`, `--dates`, or
  `--limit`.
- **Selection feature snapshots are not catalogued.** Their content-addressed cache
  records remain separate from the catalog DAG and are not discovered as filing
  catalogs.
- **Target shards are not globally sorted, and no consumer can make them so
  without a full re-sort.** Restoring a dataset total order would mean one sort
  over the whole occurrence set, which is the memory ceiling this layout exists to
  avoid; `plan` imposes its own order per form partition instead.
- **No chunk workers, no resume, no partial progress.** There is nothing to fetch
  here. If fetching is ever needed, it must be a new pipeline rather than a `run`
  command added here.
- **The wizard cannot target a non-default artifacts root.** The registered
  `artifacts.root` setting is the single authority.
- **`selection_report.json` is an audit artifact.** No production machine reads it or
  the feasibility prediction inside it; they exist for a human reviewing a run.
- **Selection identity and payload integrity are separate.** `plan_fingerprint`
  covers selected locator keys; schema 1.3 adds `target_parts` digests for the
  selected occurrence Parquet files. Other sidecars remain governed by their own
  schema and validation contracts.
- **A fresh policy plan tolerates an underfilled quota; an expansion does not.**
  A first plan reflects a corpus; an expansion is a promise the caller made.
- **A deterministic plan cannot be expanded.** It is a slice, not a selection, so
  there is nothing to extend.
- **Catalog references accept an id or `current`, not a path.** A snapshot outside
  the configured artifacts root requires pointing the root at its parent.
- **No cross-plan lineage traversal.** `plan.json` records `parent_plan_id`, so the
  link is present, but resolving a multi-generation chain means reading the parents
  yourself.
- **No snapshot, plan, or policy deletion command.** Nothing here prunes the catalog
  tree; immutability is enforced by refusing, and pruning is a manual act.
