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
  zero-heuristic slice on exactly five filters (`forms`, `amendment`,
  `document_suffixes`, `dates`, `limit`), producing an **8-column** locator
  projection. `dates` narrows which rows are *eligible*; it deliberately refuses
  to reason about eras or cohort balance.
- **Policy** (`plan --scope policy`) — the Stage B selection engine against a
  declared quota profile, producing an **18-column** locator projection plus a
  reserve pool. The only scope that stratifies: era bands and a form-by-era
  allocation.

Status: **Phase 2, complete.** `roadmap/refactor_v2/phase_2.md` records
"Milestones 0–9 done. Stage A (M0–M4) and Stage B (M5–M9) both implemented."

The zero-network property is proved, not asserted:
`tests/test_network_isolation.py` walks the import graph by AST from every module
of this package and asserts none reaches `edgar_sec.infra.sec_http`. A grep would
miss a re-export, an alias import, and a function-local import; all three are real
ways a network dependency creeps in.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Docstring only. No re-exports, per AGENTS.md §1.2. |
| `cli.py` | The four commands, policy resolution, and the stdout/stderr split. |
| `operator.py` | Interactive wizard over `cmd_materialize` / `cmd_plan` / `cmd_expand` / `cmd_status`, with discovery-driven catalog and parent-plan selection. |
| `catalog_job.py` | `materialize()`: one Phase 1 snapshot in, one immutable catalog out, behind three guards. |
| `planner.py` | `plan()` (five filters, 8 columns) and `plan_policy()` (quota profile, resolved era bands, form-by-era allocation, 18 columns). |
| `expansion.py` | Parent validation, child derivation, and the 100%-retention invariant. |
| `publication.py` | Content-addressed plan ids, staged bundles, the selection fingerprint, and the reuse-or-conflict policy. |
| `discovery.py` | Manifest-only catalog/plan/policy enumeration and `current` resolution. |
| `paths.py` | `FilingCatalogPaths` and the artifact-name constants. |

## Contracts

**Guarantees to callers**

- **Zero network, proved structurally.** No module here imports
  `edgar_sec.infra.sec_http` or constructs a `SecHttpClient`.
- **`materialize` refuses a transient Phase 1 work unit.** A source path with a
  `chunks`, `checkpoints`, or `workers` component is rejected, so a resumability
  checkpoint can never be mistaken for a finalized snapshot.
- **`materialize` refuses a schema-mismatched source.** The source column list
  must equal `SUBMISSION_METADATA_SCHEMA.names` *exactly*, and the error reports
  `missing=` and `unexpected=` separately, so a Phase 1 schema change fails
  loudly instead of producing a silently truncated catalog.
- **`materialize` refuses to overwrite a published snapshot** in *both*
  publication modes, not only the durable one — v1 enforced it only on the durable
  path, so an explicit `--artifacts` root could silently destroy a published
  snapshot.
- **`materialize` writes one target shard per source part, and refuses source
  parts that share a CIK.** Occurrence dedup is per shard and keyed on
  `source_cik`; a CIK spanning two parts would publish one `occurrence_id` into
  two shards. Peak memory is set by the densest single part rather than by the
  cohort.
- **Target shards are not globally sorted, and the manifest says so.** Each shard
  is ordered by the projection key; shards follow Phase 1 source-part order, whose
  CIK ranges overlap. `sort_order: "source_part_order"` is recorded so a consumer
  cannot read one shard's ordering as a dataset-wide guarantee.
- **Publication is atomic and never partially visible.** A catalog is staged
  under the transient tree and published with a single `os.replace`; a plan
  bundle is staged as a *sibling* of its destination precisely so `os.replace`
  stays on one filesystem, and the staging directory is removed on any failure.
- **Only the durable tree advances `current`.** With an explicit artifacts root
  the snapshot directory is still written atomically but the pointer is not moved,
  so a scratch directory can be planned from without disturbing published state.
- **Plan identity is a function of the request.** `plan_identity` hashes the
  canonicalized request payload, so the same catalog and the same filters always
  resolve to the same published bundle and an exact rerun reuses it instead of
  forking a new one.
- **A diverging published bundle is a conflict, never a rewrite.**
  `reuse_existing_plan` returns `None` when nothing is published, the published
  plan when it satisfies the request, and raises `PlanConflictError` when a
  directory exists but describes a different request, is incomplete, or no longer
  matches its recorded selection fingerprint.
- **A plan bundle is complete when it matches its own recorded counts.**
  `plan_bundle_complete` requires every entry of `REQUIRED_PLAN_FILES`, requires
  the seed sidecar for a policy plan, and compares the on-disk `form=*` partition
  set against the `counts` in `plan.json`. v1 used `any(glob('form=*/data.parquet'))`,
  which reported a legitimately empty plan as incomplete; the correction also
  catches a bundle that lost a shard.
- **A zero-row plan is still structurally complete and reusable.** The `targets/`
  directory and `locator_groups.parquet` are always written, and when no
  partition matches the locator query runs over `WHERE false` against the catalog
  view, so the file is schema-correct at zero rows.
- **One row per document locator.** Grouping is on `document_locator_key` alone,
  with representative columns chosen by `arg_min` over a total order, so the
  representative is deterministic. v1 selected `DISTINCT` over *all* columns
  including `source_cik`, so two co-filers sharing one locator produced two rows
  and `unique_locators_count` over-counted.
- **The `amendment` filter is actually applied**, and it participates in *form
  discovery*, so a filter that removes a form removes its partition instead of
  writing an empty one. v1 validated the value, recorded it, and never filtered on
  it, so `--amendment original` silently behaved like `both`.
- **`plan()` accepts exactly five filters**, one of which is a date selection.
  Per-field date flags (`start_date`, `end_date`, `filing_date`) are still a
  `TypeError` at the signature: the selection is one union over `report_date`, and
  a caller passing a single bound expects a half-specified interval that no
  grammar here accepts.
- **Expansion retains 100% of the parent.** The child's selection runs with the
  parent's keys as `parent_active_keys`, so they are in the exclusion set before
  any candidate pool is drawn.
- **Parent compatibility is checked before selection, not after.** A mismatched
  scope, catalog, corpus, form set, seed set, schema version, or selection
  fingerprint fails immediately rather than after an expensive feature build.
- **`status` reads manifests only.** It never opens a Parquet payload, never
  materializes a catalog, and never contacts the network, so it stays cheap enough
  for a menu loop. The one Parquet reader is `auto_policy`, a separate
  command-time derivation.
- **Identifiers are validated as path segments.** `safe_identifier` rejects any
  character outside `[A-Za-z0-9_.-]`, so a caller-supplied catalog id can never
  escape the tree it is resolved against.
- **Progress goes to stderr, result to stdout.** `_emit_progress` writes to
  `sys.stderr` so `... | jq` works; mixing a human-readable trace into stdout
  would corrupt the payload.
- **Resource limits are not parameters.** `materialize` accepts no `threads` or
  `memory_limit`: `connect()` derives them from the cgroup-aware
  `derive_resources()`, and re-exposing them as arguments invites the hardcoded
  allocations the `resource-allocation` scanner exists to block. There is no batch
  size parameter either — the Phase 1 part is the unit of work, and a knob that
  appears to bound staging but does not is worse than none. Heap is reclaimed
  between the profile and target passes and between target shards.

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
- Do not widen `plan()` with policy-only parameters. `selection_policy_path`,
  `seed_cik_path`, `parent_plan_dir`, and `target_units` are absent from that
  signature by design; they reappear with the policy scope and with expansion.
- Do not treat a shortfall as a failure of a fresh plan. A fresh policy plan
  publishes whatever the corpus could supply, reporting the shortfall in
  `underfilled_floors`. Only an *expansion* is refused for failing to reach
  `target_units`.

## Public surface

| Symbol | Module |
| :--- | :--- |
| `materialize`, `resolve_source`, `CatalogError`, `TRANSIENT_SOURCE_PARTS`, `FALLBACK_POLICY_VERSION` (`"1.1.0"`) | `catalog_job` |
| `plan`, `plan_policy`, `SCOPE_DETERMINISTIC`, `SCOPE_POLICY` | `planner` |
| `expand`, `prepare_parent`, `validate_parent`, `validate_parent_schema`, `validate_target`, `ExpansionLineage`, `ParentPlanError`, `read_expansion_metadata` | `expansion` |
| `plan_identity`, `plan_fingerprint`, `plan_locator_keys`, `plan_bundle_complete`, `reuse_existing_plan`, `staged_plan_bundle`, `publish_plan_bundle`, `write_plan_documents`, `PlanConflictError`, `TARGET_PLAN_SCHEMA_VERSION` (`"1.2"`) | `publication` |
| `discover_catalogs`, `discover_plans`, `discover_policies`, `current_catalog_id`, `resolve_catalog_reference`, `policy_search_dirs`, `auto_policy`, `status` | `discovery` |
| `FilingCatalogPaths`, `resolve_filing_catalog_paths`, `safe_identifier`, `form_partition_name`, `form_partition_dir`, `target_part_name`, `PIPELINE_DIR`, `SNAPSHOTS_DIR_NAME`, `PLANS_DIR_NAME`, `CURRENT_ALIAS`, `REQUIRED_PLAN_FILES`, and every artifact-name constant | `paths` |
| `build_operator_menu` — four `MenuAction` entries | `operator` |
| `build_parser`, `main`, `cmd_materialize`, `cmd_plan`, `cmd_expand`, `cmd_status` | `cli` |

Three notes on the surface:

- `TARGET_PLAN_SCHEMA_VERSION` is `1.1`. Bundles published under `1.0` carry
  neither the seed sidecar nor the selection fingerprint and are **not** accepted
  as `1.1` bundles; `validate_parent_schema` refuses them rather than adapting
  them, and a conflicting directory is a `PlanConflictError`.
- `plan_fingerprint` binds a plan's identity to its *selection* — the ordered
  locator keys — so two runs that requested the same thing but selected
  differently do not share a fingerprint. Publication stamps it into `plan.json`
  and `reuse_existing_plan` refuses a bundle whose locator groups no longer match.
  It deliberately does not cover the bytes of every Parquet in the bundle.
- The artifact names are declared once, in `paths.py`, because "a literal
  repeated in two modules is how a rename desynchronizes a writer from its
  reader". Phase 2.5 binds to this layout, which makes them a cross-package
  contract rather than an internal detail.

## Command surface

Entry point: `python run.py filing-catalog <command>`. With no argument the
operator wizard opens; with an argument `cli.main` dispatches. Worked transcripts
are in the [root README](../../../README.md#5-filing-catalog-pipeline-zero-network).

| Subcommand | Flags | Returns |
| :--- | :--- | :--- |
| `materialize` | `--source` (one Parquet part, treated as a one-part dataset), `--source-manifest` (Phase 1 snapshot manifest; its declared parts are resolved and verified), `--artifacts` | 0 with the manifest JSON on stdout, or 1 on `CatalogError` with `error: <msg>` on stderr. |
| `plan` | `--catalog` (**required**), `--scope` (`deterministic` default; choices `deterministic`, `policy`), `--policy`, `--auto-policy`, `--artifacts`, `--forms` (nargs `*`), `--amendment` (`both` default; choices `both`, `original`, `amendments`), `--suffixes` (nargs `*`), `--dates` (one comma-separated union; blank selects every date), `--limit` | 0 with the plan document on stdout, or 1 on `PlanConflictError`, `ValueError`, or `OSError`. |
| `expand` | `--parent-plan` (**required**, a published policy plan directory), `--target-units` (**required**, int), `--artifacts` | 0 with the child plan document, or 1 on `PlanConflictError`, `ParentPlanError`, `ValueError`, or `OSError`. |
| `status` | `--artifacts` | 0, with the published-state JSON on stdout. |

`--artifacts` is a root override on every subcommand; empty means
`resolve_paths().artifacts_root`. There is deliberately **no `run` subcommand** and
no `--output-root` flag.

`filing_catalog/cli.py` has **no top-level `try`/`except`** — unlike the other two
pipelines, which wrap their dispatch. Each command function catches its own errors,
prints `error: <msg>` to stderr, and returns 1; `main` returns
`int(parsed.func(parsed))` and nothing else, and a bad flag is `argparse`'s exit 2.
`ParentPlanError` subclasses `ValueError`, so a plan-expansion refusal is caught by
the same handler as a bad flag. `_load_policy` raises before any work starts: both
`--policy` and `--auto-policy` is "pass either --policy or --auto-policy, not
both", neither is "--scope policy requires --policy PATH or --auto-policy".

`run.py` dispatches through `runpy.run_module(..., run_name="__main__")`, and the
pipeline's own `sys.exit(main())` raises `SystemExit` through that boundary, so the
process exit code does propagate: `0` on success, `1` on a handled error, `2` on a
bad flag.

The wizard's five actions cover `status`, `materialize`, deterministic `plan`,
`plan --scope policy`, and `expand`. The catalog for a plan and the parent plan for
an expansion are chosen by number from what is published, with the pointer-resolved
catalog offered as the default, so neither a catalog id nor a plan directory has to
be typed from memory.

**The policy action creates or runs a draft; it never invents one.** It lists the
valid policy documents under `policies/` with their forms, unit count, date
selection, and whether they declare era bands or derive them. A blank answer writes
a catalog-derived all-forms draft, prints its path, and returns **without planning**
— New and Run are separate decisions, and auto-selecting the first draft would
publish a plan nobody chose from a profile they may not have read. A number runs
that draft; a number outside the list is re-asked rather than falling through to
New, so a typo cannot silently become a new draft.

**The wizard never asks for an artifacts root.** Every action resolves through
`resolve_filing_catalog_paths()`, which is the configured project root — the
`artifacts.root` setting read by `resolve_paths()`. That setting is the one authority
for the root (see the root README on `ARTIFACTS_ROOT` and `.env`), and all four
subcommands carry `--artifacts` for a deliberate override. The prompt used to be asked
per action, which duplicated that authority and was asked before the catalog listing
the root determines. `document_storage` is the matching precedent: its menu resolves
once from `resolve_paths()` and its CLI exposes no root flag at all.

### Artifact layout

The published layout is in the
[root README](../../../README.md#5-filing-catalog-pipeline-zero-network); three
facts are specific to this package:

- **Catalog snapshots, plan bundles, and the pointer are three siblings**, shaped
  like Phase 1's: `filing_catalog/snapshots/<catalog_id>/`,
  `filing_catalog/snapshots/current/pointer.json`, and
  `filing_catalog/plans/<plan_id>/`. An earlier revision put both kinds directly
  under `filing_catalog/` and justified the shared namespace by noting that a
  catalog id and a plan id are both 24-character content digests and could only
  collide through a hash collision. The reasoning was sound and the trade was
  wrong: nothing in the published tree let a reader tell a snapshot from a plan by
  name, and the artifacts root stopped resembling every other pipeline's.
  `tests/pipelines/filing_catalog/test_paths.py` pins the separated roots.
- **The feature snapshot shares `snapshots/` with catalog snapshots, and is
  identified by manifest rather than by name.** `FeatureSnapshotBuilder.snapshot_dir`
  returns `output_root / "snapshots" / canonical_hash(payload)[:32]`, and
  `plan_policy` passes `output_root=paths.catalog_root`. Two different kinds of
  snapshot therefore sit in one directory, which is a deliberate gap rather than
  an oversight — see deliberate gaps below. `discover_catalogs` requires
  `snapshot.manifest.json` in an entry, so a feature directory
  (`feature_snapshot.json`) is skipped, and the ids cannot collide: a catalog id
  is 24 hex characters, a feature digest 32.
- **Bundle contents are scope-specific.** `targets/form=<FORM>/data.parquet` is the
  *occurrence* surface: a deterministic plan writes the raw catalog target rows,
  exactly `TARGET_COLUMNS`; a policy plan writes the feature-enriched occurrence
  rows it selected from. `locator_groups.parquet` is the scope-independent *work
  order*. The asymmetry is deliberate and pinned separately in
  `tests/pipelines/filing_catalog/test_phase25_contract.py`; the occurrences are
  not interchangeable between scopes.

### `materialize`

`resolve_source` picks the Phase 1 dataset by three converging routes — an
explicit Parquet path (a one-part dataset), an explicit snapshot manifest, or the
`current` pointer — then the three guards run in order: not transient, schema
exactly matches, target directory not already published. A manifest is metadata,
not data, so it is never handed to the Parquet reader: the ordered part list is read
from the manifest, never by globbing a directory, and every part is verified
against the digest the manifest records before any Parquet is read. A missing,
tampered, or digest-mismatched part raises `CatalogError`. A snapshot published
before the multipart contract carries a single `output_path`/`artifact_sha256` pair
and resolves through the same reader as a one-part dataset.

`catalog_id` is the Phase 1 `snapshot_id` when the handoff supplies one, otherwise
`sha256([source_hash, SOURCE_SCHEMA_VERSION, SCHEMA_VERSION,
FALLBACK_POLICY_VERSION])[:24]`, where `source_hash` is the handoff's
`parts_digest` or a digest over the resolved part digests — an id must identify
the dataset, not one file of it.

Inside one DuckDB connection it builds a temp view over the whole part list and
runs `build_profile_query` to write `company_profiles.parquet`; after `reclaim()`
it reconnects and walks the ordered source parts, running `build_part_unnest_query`
over **one part at a time** and writing each result to its own
`filing_targets/part-NNNNN.parquet`, reclaiming between parts. The manifest
records `manifest_kind`, `catalog_id`/`snapshot_id`, the source part list and
digests, all three schema versions (`schema_version`, `target_schema_version`,
`profile_schema_version`), profile and target row counts, `target_columns`,
accumulated `form_counts`, per-shard metadata (path, index, originating source
part, row count, SHA-256), `target_part_count`, `sort_order`, and `pipeline`. The
manifest is written into staging, `os.replace` publishes, and only then — and only
for the durable tree — is `current/pointer.json` written.

#### Why the target pass is sharded, and why there is no batch-size knob

Each Phase 1 registrant row carries its whole filing history as a nested
`filings` array — a single CIK in the current snapshot holds 167,865 of them — so
the cohort's 13.8M occurrences arrive as 40,914 very large nested values. Two
things follow.

The unnest must be **uncorrelated**. `LATERAL (SELECT UNNEST(t.filings))` is
rewritten by DuckDB into a delim join whose `DELIM_SCAN` pins the entire nested
value of every source row before emitting anything; that pin does not spill, so
it exhausts the memory limit on a part list that streams fine when unnested as
`UNNEST(filings)` in a select list. The shape and its plan are both pinned by
`tests/infra/storage/test_duckdb_catalog.py`.

The unnest must be **bounded**. Reading every part in one query makes peak memory
a function of the cohort rather than of a part, so each part is unnested alone and
written to its own shard. Peak usage is now set by the densest single part.

There was once a `catalog.source_batch_size` setting, `--batch-size` flag, and
`source_batch_size` manifest field, described as "registrant rows staged into
DuckDB per batch". They only ever validated the number and copied it into the
manifest — nothing batched on it, so an operator watching memory climb would tune
it and see nothing change. All three are gone; the Phase 1 part is the unit of
work.

#### Shard ordering is per shard, and the manifest says so

Each shard is sorted by `(source_cik, accession, document_path)`, but the shards
are concatenated in Phase 1 **source-part order**, and Phase 1 publishes parts in
`sort_order: "chunk_order"` whose CIK ranges overlap. The published catalog is
therefore *not* globally sorted by CIK. `snapshot.manifest.json` records
`sort_order: "source_part_order"` so a consumer cannot mistake one shard's
ordering for a dataset-wide guarantee. Phase 1 makes the same tradeoff and
documents it identically (`merger.publish_parts`). Consumers that need a total
order impose one — `plan` writes `ORDER BY document_locator_key, occurrence_id`
per form partition.

#### Guards, and the one that sharding added

Three guards are load-bearing invariants:

1. a source path under `chunks`, `checkpoints`, or `workers` is refused, so a
   transient Phase 1 work unit can never be mistaken for a finalized snapshot;
2. the source column list must equal `SUBMISSION_METADATA_SCHEMA.names` exactly,
   so a Phase 1 schema change fails loudly instead of producing a silently
   truncated catalog;
3. an existing snapshot directory is refused rather than overwritten, so a
   published snapshot stays immutable.

A fourth follows from sharding. Occurrence dedup is **per shard** and keyed on
`source_cik`, so it can only collapse duplicates it can see. If one CIK appeared in
two source parts, the same `occurrence_id` would be published into two shards — a
dataset-wide duplicate no per-shard check could catch. `_guard_ciks_are_disjoint`
therefore refuses a source whose parts share a CIK, using a column-pruned
aggregate over `cik` that never expands the nested arrays.

That guard is a precondition, not a repair. Phase 1 chunks partition the CIK index
and the merger already rejects a duplicate CIK, so a published snapshot satisfies
it; an input that violates the upstream contract is refused rather than silently
published. It is also why the committed fixture — which deliberately carries a
re-fetched registrant, `0000320193` twice with an identical `filings` array a week
apart — is split into test parts **by CIK**, as real chunks are. A row-count split
would put its two rows in different parts and be refused, correctly.

### `plan` and `plan_policy`

Both derive a `request` dict, hash it to a `plan_id`, ask `reuse_existing_plan`
whether the bundle is already published (raising on a conflict), and only then
enter `staged_plan_bundle`.

The deterministic scope discovers the available forms *after* applying the
amendment, suffix, and date filters, writes one `targets/form=<FORM>/data.parquet` per
form with `ORDER BY document_locator_key, occurrence_id`, applies `limit` as a
wrapping `LIMIT` inside the ordered subquery, and always writes
`locator_groups.parquet`. The policy scope builds a `FeatureSnapshotBuilder` over
the catalog's target and profile files, runs `DeficitSelector.select()`, loads the
selected and reserve keys into temp tables in batches of 5,000 rather than an
interpolated list, and writes the 18-column locator projection and the reserve
pool. Both then write `plan.json` and `selection_report.json` via
`write_plan_documents`, which stamps `plan_fingerprint` from the locator groups
the bundle actually holds and returns the stamped document so a later rewrite
cannot drop it. The plan document records `request_fingerprint` — a SHA-256 over
the canonicalized request — alongside the derived `plan_id`, so a plan's identity
and the request that produced it are both readable from the file.

The deterministic scope's fifth filter is a *date selection* over `report_date`:
`--dates` takes one comma-separated union of absolute intervals (`2005Q3..2008Q1`)
and recurring calendar periods (`@Q1[1999..2001]`). The grammar, its canonical
form, and its persisted representation live in
`domain.filing_catalog.filters`; both the CLI and the wizard go through that one
parser. Two consequences are deliberate:

- The **normalized** clauses, not the caller's spelling, enter the request, so
  `2023` and `2023-01-01..2023-12-31` resolve to one published plan rather than
  forking two bundles of the same rows.
- An empty selection is no date predicate at all and keeps rows whose
  `report_date` is unreadable; a nonempty one cannot place such a row and
  excludes it. Form discovery runs the date predicate too, so a form excluded
  only by date publishes no partition rather than an empty one.

The date filter runs on a parsed `DATE` column the planner projects once into a
`catalog_dated` view, so the predicate does not re-parse `report_date` per
reference. Partitions therefore project `TARGET_COLUMNS` by name rather than
taking that view's shape — selecting it would publish a column no consumer
declared.

### A policy's date selection and its era bands

A policy declares a **date selection** in the same grammar `--dates` uses, over
`report_date`, and it is enforced by the selection engine rather than applied to
the published rows afterwards. `CandidateFilters` compiles it into every pool
query — value pools, composite pools, seed-CIK pools, the weighted page, and the
cell-availability aggregate — so no phase can draw an out-of-range candidate, not
even transiently to consume quota on the way to being dropped. The same
single-parse relation wrapping the deterministic planner uses applies, keyed on
the feature snapshot's `report_date` column.

An **empty** `era_bands` list means *derived*, not unstratified: the planner
resolves bands from the report years the policy's own forms and date selection can
reach. Deriving from the unfiltered year range instead would band years selection
can never reach, and each would be an empty stratum in the report. Resolution
happens before the feature build because era is baked into the snapshot, and
before the request is hashed because the plan id should name the bands its locators
were chosen under. The resolved bands are written into `plan.json`, so a reader
never re-derives them. A selection that matches no dated row falls back to the
catalog's own year range rather than a synthetic one — a fabricated band would put
a coverage figure in the report that was never derived from data.

Because a published plan embeds its *resolved* policy, expansion compares a derived-band
draft against those bands leniently: a draft that derives bands inherits whatever its
parent resolved, while a draft that declares bands must declare the same ones. Editing
strata therefore produces a new root plan, never an expansion.

### Form-by-era allocation

Between the floor phase and the weighted fill, the selector allocates the remaining
budget across nonempty `(form, era)` cells. The weighted fill is proportional, so
without this the largest form takes the leftover budget and a rare form appears
only as far as a declared floor pushed it; with it, the default sample is balanced
and a floor becomes a *raise* above the balance.

Availability is read once per run, in one grouped aggregate. Allocation then runs in
rounds: each round gives every cell with room left an equal share of what remains,
and a later round redistributes what an exhausted cell could not take. Cells are
visited era-first, so a cap smaller than the cell count gives every era one row
before any era takes a second — ordering by form would spend the whole budget on
whichever form sorts first. Seeds, composites, and floors run before allocation and
share the same global cap, so allocation only ever draws from what they left, and a
floor that already filled a cell is credited rather than handed a second share. A
round refused in full ends allocation: that means the family cap rejected every
candidate, and re-querying the same cells would be refused identically.

`selection_report.json` carries `form_era_allocation` with per-cell
`available`/`selected`/`shortfall` plus the `equal_quota` and `unallocated` totals,
so a plan never claims a target it could not meet.

### Advisory inventory feasibility

A policy plan's `selection_report.json` carries an `inventory_feasibility` block
computed from the feature snapshot *after* selection has run. It answers, per
declared floor and composite, how many locators the corpus actually held
(`available`) against how many the policy asked for (`required`). Floors also
carry a `deficit`, which is the actionable part; composites carry `feasible`
alone, because a stratum's shortfall is not a number of filings a policy author
can adjust the way a floor minimum is. `infeasible_floors` and
`infeasible_composites` name the ones that could not have been met, and a policy
declaring neither records `checked: false` rather than scanning for nothing.

It is **advisory only** and cannot fail a fresh plan — a shortfall is still
reported in `underfilled_floors` and the plan publishes. Two reasons, both recorded
in `engine/selection/README.md`: the per-dimension counts are independent and do
not subtract competition between floors, the family cap, or the seeds; and a floor
can be satisfiable yet skipped once an earlier phase has claimed its candidates. A
prediction is weaker evidence than a completed selection, so a diagnostic that
disagrees with the result does not override it. "Cannot fail" is scoped to the ways
the inventory is known to decline — an unknown dimension, an occurrence-grain
composite, an unreadable snapshot — each reported as `checked: false` with the
reason; an unexpected DuckDB error still propagates and fails the plan, because a
snapshot that cannot be read is a broken run rather than a shortfall. A composite
stratum naming an occurrence-grain dimension (`accession_class`) is refused at
`SelectionPolicy` construction rather than reported, because the selector draws
composites from `locator_features` and could never match it.

### Seeded selection

A policy plan's seed set is the policy's `seed_cik_path`, loaded once and normalized
before anything consumes it. The same set feeds both the mandatory seed-filer phase
in `DeficitSelector` and the `CompanyFamilyIndex` that defines family boundaries,
so a plan and the features behind it cannot disagree about which registrants are
mandatory. The normalized set is published as `seed_filers.csv` and its fingerprint
participates in both the plan identity and the feature-snapshot cache identity, so
editing the seed manifest produces a different plan rather than silently reusing
stale family assignments. A policy naming a manifest that does not exist is not an
error: company-family data falls back to the profile corpus, an empty seed set is
published, and `seed_filer_count` says so. Expansion reads the seed set from the
**parent's published sidecar**, not the configured CSV, so a child reproduces its
parent's selection even if the original file has moved, been edited, or been
deleted.

### `expand`

In order: check the parent's scope *before anything else*, so a deterministic plan
gets "plan expansion requires a policy-driven parent plan" rather than a complaint
about a policy field it was never going to have; require `selection_policy` to be
embedded in the parent's `plan.json`; re-run the schema and fingerprint gate; read
the parent's `seed_filers.csv` when no seed set is supplied; refuse `target_units`
smaller than the parent's selected locator count (a contraction, not an expansion);
derive the child policy with `dataclasses.replace`, setting
`base_content_units=target_units`, `level = max(child level, parent level + 1)`, and
the parent's id and fingerprint — from the **parent's embedded policy** rather than
the caller's draft, so the child inherits the era bands the parent was stratified
under and reuses its feature snapshot instead of building a second one; run
`validate_parent`, which compares parent and child policies field by field after
removing the child-only fields, treating a derived-band draft as agreeing with any
resolved bands; take the suffix
vocabulary from the parent so a child cannot silently narrow the surface its parent
committed to; call `plan_policy` with `parent_active_keys=parent_keys`; refuse to
publish if the child's `unique_locators_count` fell short of `target_units`; and
finally write `expansion_metadata.json` and rewrite `plan.json` with the lineage
keys.

That last rewrite touches a file that is already published, because the lineage is a
function of the selection the plan just recorded and so is not known until the
bundle exists. The rewrite is atomic and "only ever gains keys, so a concurrent
reader sees either the pre-lineage or the post-lineage document, never a partial
one", and it carries the stamped `plan_fingerprint` with it, so the child still
verifies.

## Mirrored tests

`tests/pipelines/filing_catalog/` — one file per source module per AGENTS.md §6.

| File | Covers |
| :--- | :--- |
| `test_catalog_job.py` | The three guards, both publication modes, the pointer rule, and manifest source resolution. |
| `test_planner.py` | The five filters including the date selection, form discovery, the zero-row plan, the locator projection. |
| `test_policy_planner.py` | The quota profile, the resolved era bands, a policy's date selection, the allocation block, the 18-column projection, the reserve pool, the pinned seed set, and an independent-root rebuild comparison. |
| `test_expansion.py` | The 100%-retention invariant, every parent refusal, seeded expansion from the sidecar, and inheriting the parent's resolved era bands. |
| `test_publication.py` | Plan identity, completeness, reuse-versus-conflict, staging, the selection fingerprint. |
| `test_paths.py` | The artifact layout, the shared catalog/plan namespace, and identifier safety. |
| `test_discovery.py` | Manifest-only enumeration and `current` resolution. |
| `test_operator.py` | The five menu actions, their delegation to the CLI, discovery-driven catalog, draft, and expansion-parent selection, and the blank-is-New rule. |
| `test_cli.py` | Flags, the policy requirement, exit codes, the stdout/stderr split. |
| `test_phase25_contract.py` | The Phase 2 → 2.5 hand-off: the layout Phase 2.5 binds to, with the per-scope occurrence schemas pinned separately. |
| `test_catalog_fixtures.py` | DuckDB catalog materialization against committed fixtures. |
| `conftest.py` | Shared setup. Fixtures live under `tests/fixtures/catalog/`, accessed through `tests.support` rather than `parents[N]` arithmetic. |

`tests/test_network_isolation.py` at the test-tree root proves the zero-network
property by AST walk over this package. It is not mirrored here because the
invariant spans four packages, and a mirrored test "would have to be duplicated in
each to say something weaker."

## Deliberate gaps

- **`locator_groups.parquet` does not scale past a mid-sized plan.** Known defect,
  not a design choice. `_locator_groups_query` aggregates one row per
  `document_locator_key` carrying eight `arg_min` states, and those states are
  pinned rather than spilled: planning the full 13.85M-occurrence catalog fails
  with `OutOfMemoryException` at the locator copy (measured: identical failure
  with and without a date selection, so it is independent of any filter), while a
  selection of 347k occurrences across 85 forms completes in about two minutes.
  The determinism the grouping buys — a representative row chosen by a total
  order rather than by scan order — is worth keeping, but the current spelling
  holds all states for all groups at once. The fix is to make the aggregate
  spillable (ordering and deduplicating by `document_locator_key` before the
  representative is picked, or sorting the input so the aggregate streams), which
  is a change to a Stage A query that every consumer's expected output depends on.
  Until then, a large deterministic plan must be narrowed with `--forms`,
  `--dates`, or `--limit`.
- **`snapshots/` holds two kinds of snapshot, told apart by manifest.** Catalog
  snapshots are `<catalog_id>/` holding `snapshot.manifest.json`; the Stage B
  feature snapshot is a 32-hex directory holding `feature_snapshot.json`. Both
  land under `snapshots/` because `FeatureSnapshotBuilder` appends its own
  `snapshots/<digest>` segment to the root it is handed and `plan_policy` passes
  `catalog_root`. A separate `features/` directory would be cleaner, but the
  segment name lives in Layer 3 (`engine/selection/features.py`) while the layout
  is Layer 4's, so separating them means either changing the engine's published
  contract or passing a path shape designed to cancel out its hardcoded segment.
  Neither is worth a cross-layer change. `discover_catalogs` requires
  `snapshot.manifest.json`, so feature directories are skipped, and the two id
  spaces are disjoint by length (24 vs 32 hex characters).
- **Target shards are not globally sorted, and no consumer can make them so
  without a full re-sort.** Shard N is the unnest of source part N, so shards are
  ordered by Phase 1's `chunk_order`, whose CIK ranges overlap. Each shard is
  internally sorted by the projection key and the manifest records
  `sort_order: "source_part_order"`, so nothing claims more. Restoring a dataset
  total order would mean one sort over 13.8M rows, which is the memory ceiling
  this layout exists to avoid; `plan` imposes its own order per form partition
  instead.
- **No chunk workers, no resume, no partial progress.** The Phase 1
  plan/worker/merge lifecycle has no analogue here because there is nothing to
  fetch: a catalog materialization is a bounded DuckDB pass over one source part
  at a time, and a plan is a single publish. `cli.py` says so directly. If Phase 2
  ever needs to fetch, it must be a new pipeline, not a `run` command added here —
  and `tests/test_network_isolation.py` fails the gate if anything under this
  package reaches `edgar_sec.infra.sec_http`.
- **The wizard cannot target a non-default artifacts root.** Deliberate, not an
  oversight. The root already has one authority — the registered `artifacts.root`
  setting that `resolve_paths()` reads from `ARTIFACTS_ROOT`, `.env`, or the
  `.artifacts` default — and a per-action prompt both duplicated that authority and
  was asked before the catalog listing the root determines. The alternatives are
  named: `--artifacts` on each of the four subcommands for a single command, or
  `ARTIFACTS_ROOT` to redirect the whole workspace. `document_storage` is the matching
  precedent, except that its CLI has no root flag either.
- **`selection_report.json` is an audit artifact, and `inventory_feasibility`
  inside it is computed, not consumed.** No production machine reads either. The
  selection figures and the feasibility prediction exist for a human reviewing a
  run: "this policy asked for 40 filings in an era the corpus does not have" is
  the question the advisory answers, and `expansion_metadata.json`'s
  `added_locator_count` and `expansion_ratio` answer "how much did this expand". A
  diagnostic that cannot be read by a machine is not a regression, and no consumer
  was added to make the file look load-bearing. Consequently feasibility is still
  discovered rather than predicted for a *fresh* plan — the advisory explains a
  shortfall that has already happened.
- **The selection fingerprint covers the work order, not every bundle byte.** A
  digest over all Parquet payloads would make publication proportional to the size
  of the plan being published, which is the opposite of what the non-regression
  rules want. Per-file digests for the target shards are recorded in the *catalog*
  manifest, not the plan.
- **Deterministic planning has no date filter at all.** Not a missing flag: a date
  argument raises `TypeError` at the signature "rather than being ignored". Date
  slicing belongs to the Stage B selection engine, and `--scope policy` is the only
  scope that reasons about dates.
- **A fresh policy plan tolerates an underfilled quota; an expansion does not.** A
  shortfall in a fresh plan is reported in `underfilled_floors` rather than fatal;
  an expansion that cannot reach `target_units` publishes nothing. The asymmetry is
  deliberate: a first plan reflects a corpus, an expansion is a promise the caller
  made.
- **A deterministic plan cannot be expanded.** `validate_parent` refuses it
  outright — "A deterministic plan has no selection to extend" — because it is a
  slice, not a selection.
- **Catalog references accept an id or `current`, not a path.** v1's resolver
  accepted seven input forms, including a path to a `snapshot.manifest.json`, a
  directory containing one, and — as a last resort — an `rglob` across the whole
  artifacts root taking the first directory-name match. That last branch made a bare
  id resolve against whatever the filesystem enumerated first, with no error when
  the match was ambiguous. v2 resolves against a configured root, which is stricter
  and correct. The cost is that a snapshot outside the configured `--artifacts`
  root cannot be targeted by path; a user with one should point the root at it.
- **A catalog manifest is not returned to callers.** v1's resolver returned
  `(catalog_id, manifests)`, where `manifests` was a descriptor list of every
  `filing_targets/part-*.parquet` with row counts. v2 splits that: the planner
  globs the target files itself and reads the profile file by path, and
  `discover_catalogs` reads manifests in its own listing loop. The descriptor list
  was never ported because nothing consumes it.
- **Catalog snapshots and plan bundles are siblings, not a tree.** There is no
  separate `plans/` namespace to keep them apart; see the artifact-layout note
  above. This is the current layout and is pinned in `test_paths.py`.
- **No cross-plan lineage traversal.** `read_expansion_metadata` reads one plan's
  own record; there is no API to walk a plan back to the root of its chain.
  `plan.json` records `parent_plan_id`, so the link is present, but resolving a
  multi-generation chain means reading the parents yourself.
- **No snapshot, plan, or policy deletion command.** Nothing here prunes the
  catalog tree. Immutability is enforced by refusing, and pruning is a manual act;
  `PlanConflictError`'s message tells the operator to "remove it and rerun". The
  `PURGE` capability that does exist in this layer belongs to
  `document_storage/vacuum.py`, and even there it is dependency-guarded.
- **`auto_policy` reads Parquet, unlike every other `discovery` function.**
  `_catalog_year_bounds` opens a DuckDB connection over the catalog's `part-*.parquet`
  files to compute the observed year range. `auto_policy` is a command-time
  derivation, not part of `status`; `status` itself remains manifest-only.
- **`policy_search_dirs` exists because the layout lives in Layer 4**, so the
  engine cannot resolve it. It hands explicit directories to the engine-level
  policy scan.
- **The `create or replace` temp view is a DuckDB session object, not an artifact.**
  Each planner scope creates `catalog_targets` as a temp view and registers
  `selected_locator_keys` and `reserve_locator_keys` as temp tables. These vanish
  with the connection, so a plan's provenance must come from the published
  `plan.json`, not from a reconstruction of the selection.
- **The only settings this phase reads are two, and neither is phase-local.**
  `catalog.source_batch_size` and `catalog.row_group_size` come from
  `resolve_settings()` and are declared once in
  `foundation/runtime/settings/catalog.py`. There is no `settings.py` in this
  package; AGENTS.md §3.1's "new phases register their own spec dictionaries" is
  satisfied by that one Layer 0 module rather than by a parallel registry here.
- **v1's `defs/sql/` AST layer was deliberately removed, so `sql-boundary` was
  retired rather than ported.** The planner and catalog job build SQL strings
  directly, against `sql_literal`-quoted file lists. The AGENTS.md scanner list
  registers twelve scanners and `sql-boundary` is not among them. The compensating
  convention is that all Phase 2.5 consolidation SQL lives in
  `document_storage/queries.py` and executes only on connections from
  `infra/storage/duckdb.py`.