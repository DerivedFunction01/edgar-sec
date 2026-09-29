# `edgar_sec/pipelines/filing_catalog` — Phase 2: zero-network catalog materialization and target planning

This package turns a finalized Phase 1 `metadata.parquet` into an immutable
filing catalog and then into immutable, content-addressed **target plans** that
Phase 2.5 consumes. It performs no network I/O at all. It is not a fetcher, and
nothing in it constructs an HTTP client.

## Purpose

Phase 2 is the first *downstream consumer* of a Phase 1 artifact and the first
zero-network pipeline. In one sentence: read the published Phase 1 snapshot,
unnest its nested `filings` arrays into flat document targets, and publish a
selectable work order for a future acquisition phase.

It has two planning scopes with genuinely different jobs:

- **Deterministic** (`plan --scope deterministic`, the default) is a fast,
  zero-heuristic slice of the catalog on exactly four filters — `forms`,
  `amendment`, `document_suffixes`, `limit` — producing an 8-column locator
  projection. It deliberately refuses to reason about dates, eras, or cohort
  balance; those belong to the selection policy.
- **Policy** (`plan --scope policy`) runs the Stage B selection engine against a
  declared quota profile and produces an 18-column locator projection plus a
  reserve pool. It is the only scope that reasons about dates.

Status: **Phase 2, complete.** `roadmap/refactor_v2/phase_2.md` records
"Milestones 0–9 done. Stage A (M0–M4) and Stage B (M5–M9) both implemented."

The zero-network property is proved, not asserted. `tests/test_network_isolation.py`
walks the import graph by AST from every module of
`edgar_sec.pipelines.filing_catalog` and asserts none reaches
`edgar_sec.infra.sec_http`. A grep would miss a re-export, an alias import, and
a function-local import; all three are real ways a network dependency creeps in.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Docstring only (1 loc). No re-exports, per AGENTS.md §1.2. |
| `cli.py` | The four commands, policy resolution, and the stdout/stderr split (231 loc). |
| `operator.py` | Interactive wizard over `cmd_materialize` / `cmd_plan` / `cmd_status` (83 loc). |
| `catalog_job.py` | `materialize()`: one Phase 1 snapshot in, one immutable catalog out, behind three guards (316 loc). |
| `planner.py` | `plan()` (four filters, 8 columns) and `plan_policy()` (quota profile, 18 columns) (562 loc). |
| `expansion.py` | Parent validation, child derivation, and the 100%-retention invariant (352 loc). |
| `publication.py` | Content-addressed plan ids, staged bundles, and the reuse-or-conflict policy (192 loc). |
| `discovery.py` | Manifest-only catalog/plan/policy enumeration and `current` resolution (258 loc). |
| `paths.py` | `FilingCatalogPaths` and the artifact-name constants (189 loc). |

Total 2,184 lines across 9 files: 8 modules plus a one-line `__init__.py`.

## Contracts

**Guarantees this package makes to its callers**

- **Zero network, proved structurally.** No module here imports
  `edgar_sec.infra.sec_http` or constructs a `SecHttpClient`; `catalog_job.py:1-3`
  states "It never constructs an HTTP client." The AST walk in
  `tests/test_network_isolation.py` is the enforcement.
- **`materialize` refuses a transient Phase 1 work unit.** A source path with a
  `chunks`, `checkpoints`, or `workers` component is rejected
  (`catalog_job.py:66-68, 124-129`). A resumability checkpoint must never be
  mistaken for a finalized snapshot.
- **`materialize` refuses a schema-mismatched source.** The source column list
  must equal `SUBMISSION_METADATA_SCHEMA.names` *exactly*, and the error reports
  `missing=` and `unexpected=` separately, so a Phase 1 schema change fails
  loudly instead of producing a silently truncated catalog
  (`catalog_job.py:132-142`).
- **`materialize` refuses to overwrite a published snapshot.** The immutability
  guard applies to *both* publication modes, not only the durable one — v1
  enforced it only on the durable path, so an explicit `--output-root` could
  silently destroy a published snapshot (`catalog_job.py:202-210`).
- **Publication is atomic and never partially visible.** A catalog is staged
  under `transient/filing_catalog/<catalog_id>/` and published with a single
  `os.replace` (`catalog_job.py:283-285`). A plan bundle is staged as a
  *sibling* of its destination, precisely so that `os.replace` stays on one
  filesystem, and the staging directory is removed on any failure
  (`publication.py:147-169`).
- **Plan identity is a function of the request.** `plan_identity` hashes the
  canonicalized request payload, so the same catalog and the same filters always
  resolve to the same published bundle and an exact rerun reuses it instead of
  forking a new one (`publication.py:41-48`).
- **A diverging published bundle is a conflict, never a rewrite.**
  `reuse_existing_plan` returns `None` when nothing is published, returns the
  published plan when it satisfies the request, and raises `PlanConflictError`
  when a directory exists but is incomplete or describes a different request —
  "because silently rewriting it would destroy an immutable published artifact"
  (`publication.py:90-134`).
- **A plan bundle is complete when it matches its own recorded counts.**
  `plan_bundle_complete` requires every entry of `REQUIRED_PLAN_FILES` and
  compares the on-disk `form=*` partition set against the `counts` recorded in
  `plan.json` (`publication.py:51-77`). v1 used
  `any(glob('form=*/data.parquet'))`, which reported a legitimately empty plan as
  incomplete and therefore unreusable; the correction also catches a bundle that
  lost a shard.
- **A zero-row plan is still structurally complete and reusable.** The
  `targets/` directory and `locator_groups.parquet` are always written, and when
  no partition matches, the locator query runs over `WHERE false` against the
  catalog view so the file is schema-correct at zero rows
  (`planner.py:241-283`).
- **One row per document locator.** Grouping is on `document_locator_key` alone,
  with representative columns chosen by `arg_min` over a total order, so the
  representative is deterministic. v1 selected `DISTINCT` over *all* columns
  including `source_cik`, so two co-filers sharing one locator produced two rows
  and `unique_locators_count` over-counted — "precisely the multiplicity Stage B
  selection must not inherit" (`planner.py:86-122`).
- **The `amendment` filter is actually applied.** v1 validated the value and
  recorded it in `plan.json` but never filtered on it, so `--amendment original`
  silently behaved like `both` (`planner.py:9-13`). Here the amendment clause
  participates in *form discovery*, so a filter that removes a form removes its
  partition instead of writing an empty one (`planner.py:216-237`).
- **The `amendment` policy is the only scope-sensitive filter, and dates are
  refused.** `plan()` accepts exactly four filters. Passing a date is a `TypeError`
  at the signature, not a silently ignored argument
  (`planner.py:1-7`).
- **Expansion retains 100% of the parent.** The child's selection runs with the
  parent's keys as `parent_active_keys`, so they are in the exclusion set before
  any candidate pool is drawn, and no pool query can offer one again
  (`expansion.py:10-17`).
- **Parent compatibility is checked before selection, not after.** A mismatched
  scope, catalog, corpus, form set, or seed set fails immediately rather than
  after an expensive feature build (`expansion.py:148-185`).
- **`status` reads manifests only.** `discovery.py:1-6` states it: it never opens
  a Parquet payload, never materializes a catalog, and never contacts the
  network, so it stays cheap enough for a menu loop. The one exception is
  `auto_policy`, which is a separate command-time concern.
- **Identifiers are validated as path segments.** `safe_identifier` rejects any
  character outside `[A-Za-z0-9_.-]`, so a caller-supplied catalog id can never
  escape the snapshots tree (`paths.py:60-68`, `discovery.py:80-96`).
- **Progress goes to stderr, result to stdout.** `_emit_progress` writes to
  `sys.stderr` so `... | jq` works; mixing a human-readable trace into stdout
  would corrupt the payload (`cli.py:42-51`).
- **Resource limits are not parameters.** `materialize` deliberately does not
  accept `threads` or `memory_limit`: `connect()` derives them from the
  cgroup-aware `derive_resources()`, and "re-exposing them as arguments invites
  the hardcoded allocations the `resource-allocation` scanner exists to block"
  (`catalog_job.py:159-164`).
- **Heap is reclaimed between the two heavy stages.** `reclaim()` runs after the
  profile query and after the target unnesting (`catalog_job.py:234, 262`).
- **Only the durable tree advances `current`.** With an explicit `output_root`,
  the snapshot directory is still written atomically but the pointer is not
  moved, so a scratch directory can be planned from without disturbing published
  state (`catalog_job.py:196-198, 283-297`).

**Obligations callers place on this package**

- Publish a Phase 1 snapshot before materializing. With no `--source` and no
  `--source-manifest`, `resolve_source` follows the Phase 1 `current` pointer and
  raises `CatalogError` if nothing is published
  (`catalog_job.py:105-117`).
- Treat a published catalog or plan bundle as permanent. To change one, remove it
  deliberately; the code will not do it for you and will not repair it in place.
- Do not expect a `run` command. There is none, and the reason is at
  `cli.py:8-9`: nothing in this phase performs network work, so Phase 1's
  resumable-chunk lifecycle has no analogue here.
- For `plan --scope policy`, supply exactly one of `--policy PATH` or
  `--auto-policy`. A policy plan built from an assumed quota profile would be
  indistinguishable from a deliberate one in the published `plan.json`
  (`cli.py:99-114`).
- Do not widen `plan()` with policy-only parameters. `selection_policy_path`,
  `seed_cik_path`, `parent_plan_dir`, and `target_units` are absent from that
  signature by design; they reappear with the policy scope and with expansion
  (`planner.py:14-16`).
- Do not treat a shortfall as a failure of a fresh plan. A fresh policy plan
  publishes whatever the corpus could supply, reporting the shortfall in
  `underfilled_floors`. Only an *expansion* is refused for failing to reach
  `target_units` (`expansion.py:218-230`).

## Public surface

- `build_parser`, `main` — the argparse surface for
  `python run.py filing-catalog`. `cli.py`.
- `cmd_materialize`, `cmd_plan`, `cmd_expand`, `cmd_status` — the four command
  implementations. `cli.py`.
- `build_operator_menu` — three `MenuAction` entries. `operator.py`.
- `materialize` — build one immutable catalog snapshot; returns the manifest.
  `catalog_job.py`.
- `resolve_source` — resolve the Phase 1 dataset from an explicit artifact, an
  explicit manifest, or the `current` pointer. `catalog_job.py`.
- `CatalogError` — a catalog invariant was violated. `catalog_job.py`.
- `TRANSIENT_SOURCE_PARTS` (`{"chunks", "checkpoints", "workers"}`).
  `catalog_job.py`.
- `FALLBACK_POLICY_VERSION` (`"1.1.0"`) — bump it when the archive-URL fallback
  rule changes, so the derived catalog id changes with it
  (`catalog_job.py:62-64`). `catalog_job.py`.
- `plan` — publish one immutable deterministic target-plan bundle; returns the
  plan document. `planner.py`.
- `plan_policy` — publish one immutable policy-driven bundle; returns the plan
  document. `planner.py`.
- `SCOPE_DETERMINISTIC` (`"deterministic"`), `SCOPE_POLICY` (`"policy"`).
  `planner.py`.
- `expand` — publish an immutable child plan that retains every parent locator.
  `expansion.py`.
- `prepare_parent` — validate a parent and derive the child policy that extends
  it. `expansion.py`.
- `validate_parent`, `validate_target` — the pre-selection and pre-publication
  refusals. `expansion.py`.
- `plan_fingerprint` — a content digest binding a plan's identity to its
  *selection*, so two runs that requested the same thing but selected
  differently do not share an id. `expansion.py`.
- `plan_locator_keys` — read a published plan's locator keys via an in-memory
  DuckDB connection. `expansion.py`.
- `read_expansion_metadata` — a plan's lineage record, or `{}` for a root plan.
  `expansion.py`.
- `ExpansionLineage` — `parent_plan_id`, `parent_plan_fingerprint`,
  `target_units`, `parent_locator_count`, `child_locator_count`, with
  `added_locator_count`, `expansion_ratio`, and `to_dict()`. `expansion.py`.
- `ParentPlanError` — a plan cannot be expanded from the requested parent.
  `expansion.py`.
- `plan_identity` — the content-addressed plan id from the request.
  `publication.py`.
- `plan_bundle_complete` — does a bundle hold every required artifact and the
  partition set its own `plan.json` records? `publication.py`.
- `reuse_existing_plan` — the reuse-or-`PlanConflictError` decision.
  `publication.py`.
- `staged_plan_bundle` — context manager yielding a sibling staging directory.
  `publication.py`.
- `publish_plan_bundle` — the `os.replace` that moves staging into place.
  `publication.py`.
- `write_plan_documents` — write `plan.json` and `selection_report.json`.
  `publication.py`.
- `PlanConflictError`. `publication.py`.
- `TARGET_PLAN_SCHEMA_VERSION` (`"1.0"`), `REQUIRED_PLAN_FILES`
  (`plan.json`, `selection_report.json`, `locator_groups.parquet`).
  `publication.py`.
- `discover_catalogs`, `discover_plans`, `discover_policies` — manifest-only
  enumeration. `discovery.py`.
- `current_catalog_id`, `resolve_catalog_reference`, `resolve_catalog_manifest`
  — `current` resolution. `discovery.py`.
- `policy_search_dirs` — the directories a policy may live in. Exists because
  "the layout lives in Layer 4, so the engine cannot resolve it"
  (`discovery.py:163-171`). `discovery.py`.
- `auto_policy` — derive a baseline `SelectionPolicy` from a catalog's own forms
  and observed year range. `discovery.py`.
- `status` — summarize published state from manifests alone. `discovery.py`.
- `CURRENT_ALIAS` (`"current"`). `discovery.py`.
- `FilingCatalogPaths`, `resolve_filing_catalog_paths`. `paths.py`.
- `safe_identifier`, `form_partition_name`, `form_partition_dir`,
  `target_part_name`. `paths.py`.
- `PIPELINE_DIR` (`"filing_catalog"`), `SNAPSHOT_FILE_NAME`
  (`"company_profiles.parquet"`), `SNAPSHOT_MANIFEST_NAME`
  (`"snapshot.manifest.json"`), `TARGETS_DIR_NAME` (`"filing_targets"`),
  `PLAN_TARGETS_DIR_NAME` (`"targets"`), `SELECTION_REPORT_NAME`,
  `LOCATOR_GROUPS_NAME`, `RESERVE_TARGETS_NAME`, `EXPANSION_METADATA_NAME`,
  `POLICIES_DIR_NAME`, `PLAN_FILE_NAME`, `POINTER_FILE_NAME`. `paths.py`.

The artifact names are declared once, here, because "a literal repeated in two
modules is how a rename desynchronizes a writer from its reader"
(`paths.py:36-38`). Phase 2.5 binds to this layout, which is why these constants
are a cross-package contract rather than an internal detail.

## Commands

Entry point: `python run.py filing-catalog <command>`, dispatched through `runpy`
to `edgar_sec/pipelines/filing_catalog/operator.py`. With no argument,
`operator_entrypoint` shows the wizard; with an argument it calls `cli.main`.

```bash
python run.py filing-catalog materialize --source <phase1>/metadata.parquet
python run.py filing-catalog plan --catalog current --forms 10-K --amendment original
python run.py filing-catalog plan --catalog current --scope policy \
    --policy artifacts/filing_catalog/policies/corpus.json
python run.py filing-catalog plan --catalog current --scope policy --auto-policy
python run.py filing-catalog expand --parent-plan artifacts/filing_catalog/plans/<id> \
    --target-units 10000
python run.py filing-catalog status
```

| Subcommand | Flags | Returns |
| :--- | :--- | :--- |
| `materialize` | `--source` (Phase 1 `metadata.parquet` path), `--source-manifest` (Phase 1 snapshot manifest path), `--artifacts`, `--batch-size` (int, default `None`) | 0 with the manifest JSON on stdout, or 1 on `CatalogError` with `error: <msg>` on stderr. |
| `plan` | `--catalog` (**required**), `--scope` (`deterministic` default; choices `deterministic`, `policy`), `--policy`, `--auto-policy`, `--artifacts`, `--forms` (nargs `*`), `--amendment` (`both` default; choices `both`, `original`, `amendments`), `--suffixes` (nargs `*`), `--limit` (int) | 0 with the plan document on stdout, or 1 on `PlanConflictError`, `ValueError`, or `OSError`. |
| `expand` | `--parent-plan` (**required**, a published policy plan directory), `--target-units` (**required**, int), `--artifacts` | 0 with the child plan document, or 1 on `PlanConflictError`, `ParentPlanError`, `ValueError`, or `OSError`. |
| `status` | `--artifacts` | 0, with the published-state JSON on stdout. |

`--artifacts` is a root override on every subcommand; empty means
`resolve_paths().artifacts_root`.

Exit behaviour. `filing_catalog/cli.py` has **no top-level `try`/`except`** —
unlike the other two pipelines, which wrap their dispatch. Each command function
catches its own errors, prints `error: <msg>` to stderr, and returns 1
(`cli.py:58-135, 227-231`). `main` returns `int(parsed.func(parsed))` and
nothing else. `ParentPlanError` subclasses `ValueError`, so a plan-expansion
refusal is caught by the same handler as a bad flag.

`_load_policy` raises before any work starts: passing both `--policy` and
`--auto-policy` is `pass either --policy or --auto-policy, not both`, and passing
neither is `--scope policy requires --policy PATH or --auto-policy`
(`cli.py:99-114`).

There is deliberately **no `run` subcommand** and no `--output-root` flag; the
artifacts root is overridden with `--artifacts`.

## Resumability and publication

Phase 2 has no chunk workers, so there is no chunk-level resume. It has the
other half of the contract, and it holds it strictly.

### Artifact layout

```text
{artifacts_root}/filing_catalog/
├── <catalog_id>/                             immutable catalog snapshot
│   ├── snapshot.manifest.json
│   ├── company_profiles.parquet
│   └── filing_targets/part-00000.parquet
├── plans/{plan_id}/                          immutable plan bundle
│   ├── plan.json
│   ├── selection_report.json
│   ├── locator_groups.parquet                8 cols (deterministic) or 18 (policy)
│   ├── reserve_targets.parquet               policy scope only
│   ├── expansion_metadata.json               child plans only
│   └── targets/form=<FORM>/data.parquet
├── snapshots/<32-char-digest>/               content-addressed feature snapshot
│   ├── feature_snapshot.json                 (policy scope only)
│   ├── occurrence_features.parquet
│   └── locator_features.parquet
├── policies/
└── current/pointer.json

{artifacts_root}/transient/filing_catalog/{catalog_id}/    staging, never published
```

The feature snapshot is a *sibling* of the catalog directories, not a child:
`FeatureSnapshotBuilder.snapshot_dir` returns
`output_root / "snapshots" / canonical_hash(payload)[:32]`, and
`plan_policy` passes `output_root=paths.catalog_root`
(`planner.py:423-429`; `engine/selection/features.py:197-206`). It is written
only by the policy scope. `discover_catalogs` ignores the `snapshots` directory
because it requires a `snapshot.manifest.json` inside each entry, and the
feature directory holds `feature_snapshot.json`
(`discovery.py:111-114`).

`FilingCatalogPaths` composes from `ProjectPaths.artifacts_root` rather than the
v1 `manifests_root`/`transient_root` accessors, which do not exist in v2; the
shape otherwise matches the v1 contract "because the artifact names and the
transient/published split are the interface Phase 2.5 consumes"
(`paths.py:1-15`).

### `materialize`

`resolve_source` picks the Phase 1 dataset (explicit path, explicit manifest, or
the `current` pointer), then the three guards run in order: not transient, schema
exactly matches, target directory not already published. The `catalog_id` is the
Phase 1 `snapshot_id` when the handoff supplies one, otherwise
`sha256([source_hash, SOURCE_SCHEMA_VERSION, SCHEMA_VERSION,
FALLBACK_POLICY_VERSION])[:24]` (`catalog_job.py:75-81, 190-191`).

Inside one DuckDB connection it builds a temp view over the source and runs
`build_profile_query` to write `company_profiles.parquet`; after `reclaim()` it
reconnects and runs `build_part_unnest_query` to write
`filing_targets/part-00000.parquet`, accumulating per-form counts. The manifest
records `manifest_kind`, both schema versions, profile and target row counts,
`target_columns`, `form_counts`, per-part digests, `source_batch_size`, and
`pipeline`. The manifest is written into staging, then
`os.replace(staging_dir, final_dir)` publishes, and only then — and only for the
durable tree — is `current/pointer.json` written.

### `plan` and `plan_policy`

Both follow the same shape: derive a `request` dict, hash it to a `plan_id`, ask
`reuse_existing_plan` whether the bundle is already published (and raise on a
conflict), and only then enter `staged_plan_bundle`.

Inside the staging context the deterministic scope discovers the available forms
*after* applying the amendment and suffix filters, writes one
`targets/form=<FORM>/data.parquet` per form with `ORDER BY
document_locator_key, occurrence_id`, applies `limit` as a wrapping `LIMIT`
inside the ordered subquery, and always writes `locator_groups.parquet`. The
policy scope builds a `FeatureSnapshotBuilder` over the catalog's target and
profile files, runs `DeficitSelector.select()`, loads the selected and reserve
keys into temp tables in batches of 5,000 (`_KEY_INSERT_BATCH`) rather than an
interpolated list, and writes the 18-column locator projection and the reserve
pool.

Both then write `plan.json` and `selection_report.json` via
`write_plan_documents`, and the context manager publishes with `os.replace`. The
plan document records `request_fingerprint` (a SHA-256 over the canonicalized
request) alongside the derived `plan_id`, so a plan's identity and the request
that produced it are both readable from the file.

### `expand`

`expand` checks the parent's scope *before anything else*, so a deterministic
plan gets "plan expansion requires a policy-driven parent plan" rather than a
complaint about a policy field it was never going to have
(`expansion.py:266-270`). It then:

1. requires `selection_policy` to be embedded in the parent's `plan.json` —
   without it the plan "cannot be expanded" (`expansion.py:276-281`);
2. refuses `target_units` smaller than the parent's selected locator count,
   because that is a contraction, not an expansion
   (`expansion.py:199-202`);
3. derives the child policy with `dataclasses.replace`, setting
   `base_content_units=target_units`, `level = max(child level, parent level +
   1)`, and the parent's id and fingerprint (`expansion.py:204-213`);
4. runs `validate_parent`, which compares the parent and child policies
   **field by field after removing the child-only fields**
   (`expansion.py:140-146, 179-184`);
5. takes the suffix vocabulary from the parent, "so a child cannot silently
   narrow the surface its parent committed to" (`expansion.py:288-292`);
6. calls `plan_policy` with `parent_active_keys=parent_keys`;
7. refuses to publish if the child's `unique_locators_count` fell short of
   `target_units` (`expansion.py:302`, `validate_target` at 218-230);
8. writes `expansion_metadata.json` and rewrites `plan.json` with the lineage
   keys.

Step 8 rewrites a file that is already published. The rewrite is atomic and
"only ever gains keys, so a concurrent reader sees either the pre-lineage or the
post-lineage document, never a partial one" (`expansion.py:330-339`). The
reason is that the bundle must be published before the lineage is known, because
the lineage is a function of the selection the plan just recorded
(`expansion.py:331-337`).

## Tests

- `tests/pipelines/filing_catalog/test_catalog_job.py` (297 loc, 24 tests) — the
  three guards, both publication modes, the pointer rule.
- `tests/pipelines/filing_catalog/test_planner.py` (307 loc, 22) — the four
  filters, form discovery, the zero-row plan, the locator projection.
- `tests/pipelines/filing_catalog/test_policy_planner.py` (303 loc, 17) — the
  quota profile, the 18-column projection, the reserve pool.
- `tests/pipelines/filing_catalog/test_expansion.py` (315 loc, 20) — the
  100%-retention invariant and every parent refusal.
- `tests/pipelines/filing_catalog/test_publication.py` (218 loc, 20) — plan
  identity, completeness, reuse-versus-conflict, staging.
- `tests/pipelines/filing_catalog/test_discovery.py` (177 loc, 14) —
  manifest-only enumeration and `current` resolution.
- `tests/pipelines/filing_catalog/test_cli.py` (270 loc, 25) — flags, the
  policy requirement, exit codes, the stdout/stderr split.
- `tests/pipelines/filing_catalog/test_catalog_fixtures.py` (235 loc, 20) — the
  DuckDB catalog materialization against committed fixtures.
- `tests/pipelines/filing_catalog/test_phase25_contract.py` (236 loc, 7) — the
  Phase 2 → 2.5 hand-off: the layout Phase 2.5 binds to.
- `tests/pipelines/filing_catalog/conftest.py` (57 loc) — shared setup.

2,416 lines total. Offline and deterministic, below the AGENTS.md §6.1 one-second
budget as part of the whole suite.

`tests/test_network_isolation.py` at the test-tree root proves the zero-network
property by AST walk over this package. It is not mirrored here because the
invariant spans four packages, and a mirrored test "would have to be duplicated
in each to say something weaker."

Fixtures live under `tests/fixtures/catalog/`, accessed through `tests.support`
rather than `parents[N]` arithmetic.

## Deliberate gaps

- **No chunk workers, no resume, no partial progress.** The Phase 1
  plan/worker/merge lifecycle has no analogue here because there is nothing to
  fetch: a catalog materialization is a single DuckDB pass, and a plan is a
  single publish. `cli.py:8-9` says so directly. If Phase 2 ever needs to fetch,
  it must be a new pipeline, not a `run` command added here.
- **No `run` command and no network client, deliberately.** Covered above. Do not
  read the absence as a missing feature: `tests/test_network_isolation.py` fails
  the gate if anything under this package reaches `edgar_sec.infra.sec_http`.
- **No operator action for `expand`, and none for `plan --scope policy`.** The
  wizard offers status, materialize, and deterministic plan
  (`operator.py:68-74`). Policy-scoped planning and expansion are CLI-only,
  because both need arguments an interactive prompt has no vocabulary for.
- **Deterministic planning has no date filter at all.** Not a missing flag: a
  date argument raises `TypeError` at the signature, "rather than being ignored"
  (`planner.py:1-7`). Date slicing belongs to the Stage B selection engine, and
  `--scope policy` is the only scope that reasons about dates.
- **A fresh policy plan tolerates an underfilled quota; an expansion does not.**
  A shortfall in a fresh plan is reported in `underfilled_floors` in `plan.json`
  rather than fatal (`expansion.py:218-225`). An expansion that cannot reach
  `target_units` publishes nothing. The asymmetry is deliberate: a first plan
  reflects a corpus, an expansion is a promise the caller made.
- **A deterministic plan cannot be expanded.** `validate_parent` refuses it
  outright: "A deterministic plan has no selection to extend" — it is a slice,
  not a selection (`expansion.py:161-162`).
- **No cross-plan lineage traversal.** `read_expansion_metadata` reads one
  plan's own record; there is no API to walk a plan back to the root of its
  chain. `plan.json` records `parent_plan_id`, so the link is present, but
  resolving a multi-generation chain means reading the parents yourself.
- **The only settings this phase reads are two, and neither is phase-local.**
  `catalog.source_batch_size` and `catalog.row_group_size` come from
  `resolve_settings()` (`catalog_job.py:166-178`) and are declared once in
  `foundation/runtime/settings/catalog.py`. There is no `settings.py` in this
  package; AGENTS.md §3.1's "new phases register their own spec dictionaries" is
  satisfied by that one Layer 0 module rather than by a parallel registry here.
- **v1's `defs/sql/` AST layer was deliberately removed, so `sql-boundary` was
  retired rather than ported.** The planner and catalog job build SQL strings
  directly (`planner.py:109-122, 324-328`; `catalog_job.py:216-262`), against
  `sql_literal`-quoted file lists. The AGENTS.md scanner list registers eleven
  scanners and `sql-boundary` is not among them. The compensating convention is
  that all Phase 2.5 consolidation SQL lives in `document_storage/queries.py`
  and executes only on connections from `infra/storage/duckdb.py`.
- **No snapshot, plan, or policy deletion command.** Nothing here prunes the
  catalog tree. Immutability is enforced by refusing, and pruning is a manual
  act; `PlanConflictError`'s message tells the operator to "remove it and rerun."
  The `PURGE` capability that does exist in this layer belongs to
  `document_storage/vacuum.py`, and even there it is dependency-guarded.
- **`auto_policy` reads Parquet, unlike every other `discovery` function.**
  `_catalog_year_bounds` opens a DuckDB connection over the catalog's
  `part-*.parquet` files to compute the observed year range
  (`discovery.py:198-225`). `auto_policy` is a command-time derivation, not part
  of `status`; `status` itself remains manifest-only.
- **The `create or replace` temp view is a DuckDB session object, not an
  artifact.** Each planner scope creates `catalog_targets` as a temp view and
  registers `selected_locator_keys` and `reserve_locator_keys` as temp tables
  (`planner.py:208-214, 331-353`). These vanish with the connection, so a plan's
  provenance must come from the published `plan.json`, not from a reconstruction
  of the selection.
