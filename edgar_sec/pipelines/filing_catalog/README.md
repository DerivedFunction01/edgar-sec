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
  zero-heuristic slice on exactly four filters (`forms`, `amendment`,
  `document_suffixes`, `limit`), producing an **8-column** locator projection. It
  deliberately refuses to reason about dates, eras, or cohort balance.
- **Policy** (`plan --scope policy`) — the Stage B selection engine against a
  declared quota profile, producing an **18-column** locator projection plus a
  reserve pool. The only scope that reasons about dates.

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
| `planner.py` | `plan()` (four filters, 8 columns) and `plan_policy()` (quota profile, 18 columns). |
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
- **`plan()` accepts exactly four filters.** Passing a date is a `TypeError` at
  the signature, not a silently ignored argument.
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
  allocations the `resource-allocation` scanner exists to block. Heap is reclaimed
  between the two heavy stages.

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
| `plan_identity`, `plan_fingerprint`, `plan_locator_keys`, `plan_bundle_complete`, `reuse_existing_plan`, `staged_plan_bundle`, `publish_plan_bundle`, `write_plan_documents`, `PlanConflictError`, `TARGET_PLAN_SCHEMA_VERSION` (`"1.1"`) | `publication` |
| `discover_catalogs`, `discover_plans`, `discover_policies`, `current_catalog_id`, `resolve_catalog_reference`, `policy_search_dirs`, `auto_policy`, `status` | `discovery` |
| `FilingCatalogPaths`, `resolve_filing_catalog_paths`, `safe_identifier`, `form_partition_name`, `form_partition_dir`, `target_part_name`, `PIPELINE_DIR`, `CURRENT_ALIAS`, `REQUIRED_PLAN_FILES`, and every artifact-name constant | `paths` |
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
| `materialize` | `--source` (one Parquet part, treated as a one-part dataset), `--source-manifest` (Phase 1 snapshot manifest; its declared parts are resolved and verified), `--artifacts`, `--batch-size` | 0 with the manifest JSON on stdout, or 1 on `CatalogError` with `error: <msg>` on stderr. |
| `plan` | `--catalog` (**required**), `--scope` (`deterministic` default; choices `deterministic`, `policy`), `--policy`, `--auto-policy`, `--artifacts`, `--forms` (nargs `*`), `--amendment` (`both` default; choices `both`, `original`, `amendments`), `--suffixes` (nargs `*`), `--limit` | 0 with the plan document on stdout, or 1 on `PlanConflictError`, `ValueError`, or `OSError`. |
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

The wizard's four actions cover `status`, `materialize`, deterministic `plan`, and
`expand`. The catalog for a plan and the parent plan for an expansion are chosen by
number from what is published, with the pointer-resolved catalog offered as the
default, so neither a catalog id nor a plan directory has to be typed from memory.

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

- **Catalog snapshots and plan bundles share one namespace.** They are direct
  children of `filing_catalog/`: `snapshots_root` and `plans_root` both return
  `catalog_root`, so there is no `plans/` directory. Both ids are 24-character
  content digests taken from different inputs, so colliding them would take a hash
  collision. `tests/pipelines/filing_catalog/test_paths.py` pins this.
- **The feature snapshot is a sibling of the catalog directories, not a child.**
  `FeatureSnapshotBuilder.snapshot_dir` returns
  `output_root / "snapshots" / canonical_hash(payload)[:32]` and `plan_policy`
  passes `output_root=paths.catalog_root`. It is written only by the policy scope.
  `discover_catalogs` ignores the `snapshots` directory because it requires a
  `snapshot.manifest.json` inside each entry and the feature directory holds
  `feature_snapshot.json`.
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
it reconnects and runs `build_part_unnest_query` over the same parts to write
`filing_targets/part-00000.parquet`, accumulating per-form counts. The manifest
records `manifest_kind`, `catalog_id`/`snapshot_id`, the source part list and
digests, all three schema versions (`schema_version`, `target_schema_version`,
`profile_schema_version`), profile and target row counts, `target_columns`,
`form_counts`, per-part digests, `source_batch_size`, and `pipeline`. The manifest
is written into staging, `os.replace` publishes, and only then — and only for the
durable tree — is `current/pointer.json` written.

### `plan` and `plan_policy`

Both derive a `request` dict, hash it to a `plan_id`, ask `reuse_existing_plan`
whether the bundle is already published (raising on a conflict), and only then
enter `staged_plan_bundle`.

The deterministic scope discovers the available forms *after* applying the
amendment and suffix filters, writes one `targets/form=<FORM>/data.parquet` per
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
the parent's id and fingerprint; run `validate_parent`, which compares parent and
child policies field by field after removing the child-only fields; take the suffix
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
| `test_planner.py` | The four filters, form discovery, the zero-row plan, the locator projection. |
| `test_policy_planner.py` | The quota profile, the 18-column projection, the reserve pool, the pinned seed set, and an independent-root rebuild comparison. |
| `test_expansion.py` | The 100%-retention invariant, every parent refusal, and seeded expansion from the sidecar. |
| `test_publication.py` | Plan identity, completeness, reuse-versus-conflict, staging, the selection fingerprint. |
| `test_paths.py` | The artifact layout, the shared catalog/plan namespace, and identifier safety. |
| `test_discovery.py` | Manifest-only enumeration and `current` resolution. |
| `test_operator.py` | The four menu actions, their delegation to the CLI, and discovery-driven catalog and expansion-parent selection. |
| `test_cli.py` | Flags, the policy requirement, exit codes, the stdout/stderr split. |
| `test_phase25_contract.py` | The Phase 2 → 2.5 hand-off: the layout Phase 2.5 binds to, with the per-scope occurrence schemas pinned separately. |
| `test_catalog_fixtures.py` | DuckDB catalog materialization against committed fixtures. |
| `conftest.py` | Shared setup. Fixtures live under `tests/fixtures/catalog/`, accessed through `tests.support` rather than `parents[N]` arithmetic. |

`tests/test_network_isolation.py` at the test-tree root proves the zero-network
property by AST walk over this package. It is not mirrored here because the
invariant spans four packages, and a mirrored test "would have to be duplicated in
each to say something weaker."

## Deliberate gaps

- **No chunk workers, no resume, no partial progress.** The Phase 1
  plan/worker/merge lifecycle has no analogue here because there is nothing to
  fetch: a catalog materialization is a single DuckDB pass, and a plan is a single
  publish. `cli.py` says so directly. If Phase 2 ever needs to fetch, it must be a
  new pipeline, not a `run` command added here — and
  `tests/test_network_isolation.py` fails the gate if anything under this package
  reaches `edgar_sec.infra.sec_http`.
- **No operator action for `plan --scope policy`.** The wizard offers status,
  materialize, deterministic plan, and expand, and every one of those inputs is
  discoverable or defaultable. A policy scope is not: choosing one interactively
  means authoring or deriving a quota profile, a design decision with no menu
  vocabulary. `plan --scope policy` stays CLI-only. `expand` *is* offered — its two
  inputs are a parent plan and a target size, both discoverable — and the menu
  lists only policy-scope plans, because `expand` refuses a deterministic parent
  outright and listing one would be a choice that cannot succeed.
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