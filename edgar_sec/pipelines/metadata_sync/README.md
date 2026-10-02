# metadata_sync — Phase 1

Builds the SEC submissions metadata dataset from a CIK cohort: plan a cohort,
fetch each CIK's submissions document, checkpoint the work, and publish an
immutable Parquet *dataset* — a manifest-described set of parts — that Phase 2
consumes.

## Purpose

Turn a *roster* (a set of CIKs) into a *snapshot*: an immutable, verified dataset
of one row per registrant, reproducible from immutable inputs, resumable after
interruption, and producible by more than one machine. Everything else in this
package serves that.

`refresh` and `compare` are pure projections over immutable inputs and perform no
network access; `plan` performs no network access. Only `run`, `worker`, and
`augment` fetch. The published layout is in the
[root README](../../../README.md#4-metadata-sync-pipeline); the bundle-relative
locations this package adds are:

| Command | Writes |
| :--- | :--- |
| `sources compare` | `metadata/registries/<registry_id>/datasets/effective_ciks.parquet` (roster carrier) and `effective_cik_input.csv` (export) |
| `export` | `<destination>/worker-NN/{plan.json, roster/, assignments/}` — byte-identical bundles, disjoint assignments |
| `worker` | `<bundle>/chunks/chunk_NNNN.parquet` plus `receipt.json` |

Progress goes to stderr on `isatty`: a terminal gets a `tqdm` bar, a pipe or a
captured log gets one plain line per event prefixed by the phase that emitted it.
`run` bars per CIK, `merge` per stage, and `augment` runs both in sequence — a
rate-limited fetch of the delta, then the merge — so it announces a `delta_plan`
event to size the fetch bar; a no-op augmentation prints its preflight line and
opens no bar. All of that lives in `progress.py`; `cli.py` owns the argparse
surface and the `cmd_*` callables the operator also calls. The renderer is
deliberately not in `foundation`, which knows nothing about which phases a pipeline
has — `roadmap/refactor_v2/phase_1.md` records why v1's shared `run_interactive`
did not survive being hardcoded to Phase 01.

## Module layout

| Module | Responsibility |
| :--- | :--- |
| `roster.py` | The CIK roster: content-addressed identity, atomic Parquet IO, set operations, the published CIK index. |
| `manifest.py` | CIK CSV ingestion: normalization, deduplication, curated names, the input fingerprint. |
| `planner.py` | `Plan`: chunk layout as ordinal ranges, plan identity, bundle write and validated load. |
| `assignment.py` | Static chunk-to-worker assignment, and the worker receipt that crosses the machine boundary. |
| `distribution.py` | Copy-based multi-machine distribution: export, select, adopt. The import trust boundary. |
| `options.py` | The one typed options model the CLI and the operator both build; bundle path resolution. |
| `progress.py` | This pipeline's progress events rendered for a person: phase-labelled log lines, single-phase bars, the two-phase augment router. |
| `paths.py` | `MetadataPaths` / `RunPaths`; the published-vs-transient split, plan bundle, registry, and source locations. |
| `checkpoints.py` | What counts as a *complete* chunk on disk. |
| `worker.py` | Resumable chunk execution over a thread pool; the never-refetch guarantee. |
| `snapshot.py` | Resolve a published snapshot to a verified, ordered Parquet part list; both manifest versions. |
| `merger.py` | Coordinator validation, multipart publication, progress events, CIK index, snapshot manifest, pointer advance, and explicit pointer selection. |
| `augmentation.py` | Delta planning and merge onto a published snapshot without refetching the base. |
| `registry.py` | Curated-versus-source comparison, the effective CIK roster, and the CSV export. |
| `source_registry.py` | Write-once, content-addressed `company_tickers.json` snapshots. |
| `sec_client.py` | One CIK to its submissions document plus every historical file it lists. |
| `cli.py` | The argparse surface; each `cmd_*` is a plain callable the operator also calls. |
| `operator.py` | Interactive wizard: session state, on-disk discovery, auto-resolution, and network consent over the same `cmd_*` functions. |
| `augment_flow.py` | The augmentation journey: source observation, cohort choice, base choice, and the preflight that settles the arithmetic before any fetch. |
| `worker_commands.py` | Renders the distributed lifecycle as copy-pasteable shell commands. |
| `discovery.py` | What is already on disk: plans with progress, published snapshots, the current pointer, and published effective-CIK rosters. Manifests only; never opens a Parquet payload. |
| `smoke_test.py` | Credential-gated live check that never publishes. |

## Contracts this package guarantees

AGENTS.md §4 is normative for the plan/worker/merge lifecycle. What this package
adds on top:

- **A roster is stored once and referenced by identity.** `plan.json` records the
  roster identity and the chunk layout; the cohort lives once in
  `roster/ciks.parquet`, and chunk membership is a range over roster ordinals, so
  the manifest is constant in cohort size. The previous format embedded the CIK
  list three times.
- **Plan identity is the cohort, not the schedule.** `derive_plan_id` covers the
  roster identity, the chunk size, the plan kind, and — for a delta — the base
  snapshot. It never covers an assignment, a worker count, or a timestamp, so
  reassigning a cohort keeps the same plan directory and the same checkpoints.
- **A bounded plan is a different plan.** `--limit` is applied to the roster
  *before* identity is derived, so a bounded run cannot collide with a full run
  over one file.
- **A delta plan is bound to its base.** The same requested CIK list against two
  bases is two plans with two delta rosters. Augmentation publishes
  `base_ciks ∪ delta_ciks` and records the parent, the delta roster, and both
  digests in the new manifest.
- **Row-level `snapshot_id` is provenance, not container identity.** Augmentation
  copies base rows verbatim, so an augmented snapshot legitimately carries rows
  stamped with the base's id; rewriting them would misstate where data came from.
- **Every chunk is complete or absent.** A checkpoint counts only when the file
  exists, matches the canonical schema, holds exactly the CIKs its plan range
  covers, and carries the plan's input fingerprint. Expected CIKs come from the
  plan's roster range, not a plan document, so the same check covers a chunk that
  arrived from another machine under a copied bundle.
- **Merge separates failures from reportable fan-out** (AGENTS.md §4.3).
  Rejected: duplicate or null CIKs, schema drift, plan coverage gaps, row-count
  mismatch, foreign chunk files, foreign input fingerprints, and non-terminal
  statuses. Duplicate *accession numbers* are a warning on the merge report, never
  a rejection — the same filing is legitimately listed by more than one registrant.
- **Published artifacts are immutable and self-describing.** A merge validates
  every chunk, then publishes the validated chunks as an ordered `parts/` set, a
  sorted distinct `ciks.parquet` derived from the *published rows*, a manifest
  listing every part with digest and row count, and a pointer advance.
- **The manifest is the commit record.** A snapshot is read through the part list
  its manifest declares and every listed part is verified against the recorded
  digest. Listed-but-absent means the snapshot was not fully published;
  present-but-unlisted is not part of it. The manifest is written before the
  pointer, so a crash between them leaves a complete-but-unpublished snapshot
  rather than a pointer naming an unfinished one.
- **A returned chunk is proven before it is adopted.** Import checks the plan
  identity, the assignment identity, that the receipt names only chunks its
  assignment claims, the per-file SHA-256, the canonical schema, the row count,
  and the chunk's CIK coverage. A byte-identical re-import is a no-op; a
  conflicting one is an error.
- **Published input is never implicitly refreshed.** `plan`, `run`, and `augment`
  never fetch a new source observation. A cohort is either a curated CSV or a
  published registry roster, and both resolve to the same `Roster`; building one
  from a seed and a source snapshot *is* a comparison over two immutable files, so
  augmentation may run one on demand. Fetching a new observation is always a
  separate, consented act.
- **An augmentation decides its work before it spends any.** The cohort is reduced
  against the base's published CIK index — answerable from two published artifacts
  — and the requested / already-present / to-fetch split is shown before the
  operator is asked for fetch consent. When the base already covers the request the
  command exits 0 with `no_op` set: no client is constructed, no delta plan is
  written, no snapshot is published, and the pointer does not move.
- **Every cohort is a request, not a claim.** The delta is always
  `requested - base`, including for a file that already looks like a delta.
- **A delta plan cannot be merged.** `merge_chunks` publishes exactly the chunks a
  plan produced, and a delta plan's chunks hold only what its base is missing, so
  merging one would drop every base row while recording that base as its parent.
  Generic `merge` therefore refuses a delta plan and names `augment`;
  recombination is augmentation's job, and only augmentation knows which base to
  carry forward.

## Public surface

| Symbol | Module |
| :--- | :--- |
| `Roster`, `build_roster`, `read_roster`, `write_roster`, `without_ciks`, `union_rosters`, `read_cik_index`, `write_cik_index` | `roster` |
| `read_cik_manifest`, `InputManifest` | `manifest` |
| `Plan`, `build_plan`, `load_plan`, `write_plan`, `derive_plan_id` | `planner` |
| `Assignment`, `ChunkReceipt`, `divide_chunks`, `write_receipt`, `read_receipt` | `assignment` |
| `export_bundle`, `select_assignment`, `adopt_chunks`, `load_returned_plan`, `build_worker_receipt` | `distribution` |
| `PlanOptions`, `RunOptions`, `BundleRunPaths`, `plan_options`, `run_options`, `augment_options`, `resolve_cohort`, `resolve_chunk_size` | `options` |
| `progress_renderer`, `AugmentProgress`, `MERGE_PROGRESS_STAGES`, `AUGMENT_MERGE_STAGES` | `progress` |
| `resolve_metadata_paths`, `resolve_run_paths`, `MetadataPaths`, `RunPaths` | `paths` |
| `discover_completed_chunks`, `inspect_chunk`, `schema_matches` | `checkpoints` |
| `run_chunk`, `run_chunk_ids`, `resolve_workers` | `worker` |
| `merge_chunks`, `publish_snapshot`, `publish_current_snapshot`, `publish_parts`, `parts_digest`, `MergeReport`, `MergeError` | `merger` |
| `read_snapshot_parts`, `load_snapshot_manifest`, `resolve_part_path`, `SnapshotParts`, `SnapshotLayout`, `SNAPSHOT_MANIFEST_VERSION` | `snapshot` |
| `augment`, `augment_from_manifest`, `augment_from_roster`, `derive_delta_plan`, `snapshot_cik_roster`, `preflight_augment`, `AugmentPreflight` | `augmentation` |
| `compare_sources`, `ensure_registry`, `load_registry_roster`, `load_registry_manifest` | `registry` |
| `refresh_company_tickers`, `load_source_snapshot`, `source_snapshot_id` | `source_registry` |
| `SubmissionsClient`, `CikFetchResult` | `sec_client` |
| `list_plans`, `list_snapshots`, `list_rosters`, `list_source_snapshots`, `list_input_manifests`, `current_snapshot_id`, `resolve_plan_choice`, `resolve_snapshot_choice` | `discovery` |
| `render_worker_commands` | `worker_commands` |
| `build_operator_menu`, `WizardState`, `confirm_network` | `operator` |
| `run_augment`, `ask_augment_cohort`, `ask_base_snapshot` | `augment_flow` |
| `build_parser`, `main`, `cmd_plan`, `cmd_status`, `cmd_run`, `cmd_merge`, `cmd_worker`, `cmd_export`, `cmd_import`, `cmd_augment`, `cmd_refresh`, `cmd_compare` | `cli` |

## Command surface

```text
metadata plan     --input <csv> | --roster <registry_id> [--limit N]
metadata status   <plan reference>
metadata run      <plan reference> [--chunks 0-3,7] [--chunk N]
metadata merge    <plan reference>
metadata worker   <plan reference> [--worker <id>]
metadata export   <plan reference> --worker-count N --destination <dir>
metadata import   <plan reference> --source <dir>
metadata augment  --input <csv> | --roster <registry_id> --base-snapshot-id <id>
                  [--new-snapshot-id <id>]
metadata sources refresh  [--artifacts <dir>]
metadata sources compare  --input <csv> --source-manifest <manifest.json>
```

A *plan reference* is `--plan-id`, a `--bundle` that names its own plan in its
manifest, or a cohort (`--input` / `--roster`) to re-derive; all four are one
mutually exclusive group on `status`, `run`, `merge`, `worker`, `export`, and
`import`, and only the cohort pair is accepted by `plan` and `augment` (required
there). `--artifacts`, `--chunk-size`, and `--workers` are accepted on every
subcommand except `sources refresh`/`sources compare`, which take `--artifacts`
only. `--worker-count` and `--destination` are required on `export`; `--source` is
required on `import`; `--base-snapshot-id` is required on `augment`; `--chunks` and
`--chunk` exist on `run` only. Worked transcripts are in the
[root README](../../../README.md#4-metadata-sync-pipeline).

There is no persisted configuration: effective values follow the environment and
the settings registry, and the plan id follows the effective chunk size, so
planning with one chunk size and running with another resolves a *different* plan
rather than reusing another plan's checkpoints. `--new-snapshot-id` is optional;
omitting it publishes under the derived delta plan id — a content address over the
base snapshot, the effective delta roster, and the chunk layout — the same rule
`merge` follows, so a row's `snapshot_id` can never disagree with the artifact
holding it. Supply it only when the distribution path needs a worker to stamp rows
with a snapshot the coordinator will publish under.

The interactive operator (`python run.py metadata` with no command) offers the
same actions over the same `cmd_*` functions and *discovers* rather than demands:
it keeps a `WizardState` across menu visits, lists the plans on disk with size and
progress when nothing is chosen, and adopts a lone plan without prompting. Cohort
prompts offer published effective-CIK rosters alongside the curated CSV. Anything
that reaches SEC confirms first and defaults to no. Two menu actions exist because
CLI operations needed an entry point prompting did not provide: `p` moves the
current pointer back to an earlier published snapshot via
`publish_current_snapshot` (a pointer move and nothing else — no snapshot is
written, removed, or rewritten, and an unknown target is refused), and `c` prints
the distributed lifecycle — coordinator `export`, one `worker` per machine, one
`import` per returned bundle, then `merge` — with worker ids and bundle names
drawn from the same assignment division `export` performs and empty assignments
omitted. Discovery lives in `discovery.py` and reads manifests only.

**No action asks for an artifacts root.** The root is the configured project default —
the `artifacts.root` setting `resolve_paths()` reads from `ARTIFACTS_ROOT` or `.env` —
and every action routes through `WizardState.artifacts_root`, so a caller can scope a
whole session to another tree without any action prompting for it. `refresh` and
`compare` used to prompt for the root; `refresh` then ignored the session field and
resolved the project default regardless, which was a divergence the augmentation
flow's own refresh never had. A non-default root for one command is `--artifacts` on
the subcommands. `filing_catalog` and `document_storage` are the matching precedents —
see their READMEs.

## Deliberate gaps

These are decisions, not oversights. Each names the alternative.

- **The HTTP response cache reads the settings registry, not `resolve_paths()`.**
  `cache.root` (`CACHE_ROOT`, defaulting to `<artifacts_root>/caches`) is where the
  populated store actually lives — `{artifacts_root}/caches/responses.sqlite`.
  `resolve_paths()` no longer exposes a cache root at all, so the two-authority
  divergence the v2 inventory recorded is half-resolved: the registry is the only
  reader left, and reconciling any remaining `resolve_paths()` cache surface is
  separate work. v1's store is read in place with no migration — identical schema,
  same filename, same zstd framing and expiry rule — so a re-fetch over already
  covered CIKs consumes no request budget and the failure ledger skips known-bad
  URLs without a request.
- **The wizard discovers; it does not orchestrate.** It finds the plan, shows its
  progress, and runs the command the operator picked. It never sequences the
  pipeline and never runs a step that was not chosen — v1's bound, deliberately
  kept. Interactive infrastructure stays phase-local for the same reason: discovery,
  session state, and consent are not shared, and only the genuinely shared parts
  (entrypoint policy, terminal prompting, the manifest scan) are consumed. Promote
  them to `foundation` when a second pipeline needs them, with two consumers.
- **A settings-to-client break can hide behind a fully green gate.** The suite
  injects a fake transport, so the path turning resolved settings into a live
  client is executed by almost nothing — and it did break
  (`SubmissionsClient.from_settings` read a renamed settings field and disabled
  *every* fetching action while the suite passed). The guards are
  `test_from_settings_maps_every_declared_setting`, which drives sentinels so a
  renamed field raises rather than silently comparing, and
  `test_client_builds_from_resolved_settings`, which drives the pipeline's own
  construction path. The underlying risk is unchanged: a path nothing executes is a
  path nothing protects.
- **A published snapshot is no longer globally sorted by CIK.** Parts are byte
  copies of the validated chunk files, so the snapshot is in chunk order and each
  part is in roster order. The manifest records this as `sort_order: chunk_order`
  so a consumer cannot mistake one for the other, and `ciks.parquet` remains the
  sorted membership index for lookups by CIK. Anything needing globally sorted
  rows must sort in its own query; Phase 2 aggregates, so it does not.
- **Parts are copied, not moved.** Publication copies each validated chunk, so a
  resumed plan still finds its checkpoints and an aborted publication leaves the
  transient tree intact — at the cost of the transient and published trees each
  holding the data. Phase 1 has no snapshot garbage collector; that trade is
  revisited with vacuuming.
- **A multipart manifest deliberately names no single payload.** `output_path`
  and `artifact_sha256` stay empty for a multipart snapshot; pointing them at
  part zero would let a reader that understands only the legacy shape silently
  ingest a fraction of the dataset. Snapshots published before the multipart
  contract keep both fields and resolve as a one-part dataset.
- **No dynamic claiming, leases, or scheduler.** Assignment is static and copied.
  A worker that dies mid-run is not detected or reassigned; the coordinator
  re-exports, because a chunk nobody returned is a chunk nobody fetched. A real
  scheduler needs a lease protocol and a heartbeat, which a four-command pipeline
  does not justify. Roadmap: the multi-machine section of
  `roadmap/refactor_v2/phase_1.md`.
- **No worker-level rate-limit division.** Each worker process constructs its own
  `RateLimiter` from `sec.rate_limit_rps`, so N workers together request N times
  the configured rate. This was already true of `--partition N`. Divide the budget
  with `SEC_RATE_LIMIT_RPS` when distributing across machines.
- **The CSV is an export, not the internal carrier.**
  `effective_cik_input.csv` is still written beside `effective_ciks.parquet` so
  v1-era scripts keep working, and `read_cik_manifest` still parses CIK manifests.
  Nothing in the fetch path parses a CSV to learn which CIKs a run covers.
- **No persisted run configuration.** Options are resolved once, held in memory,
  and recorded in the artifacts they produce. A `project.json` would add a second
  source of truth for values the settings registry already owns.
- **Snapshots published before the CIK index existed still resolve.** Reading a
  base snapshot's membership falls back to projecting the `cik` column of every
  part its manifest lists, so the index is an addition rather than a migration. A
  base with no manifest is *not* readable — a merge that was never published is not
  a snapshot — and a missing base is still an error, because an unreadable base
  must never be read as an empty one.
- **No `--limit` in augmentation.** A bounded augmentation would fetch a bounded
  delta, which is legitimate, but the flag is not offered because the requested
  cohort is normally a comparison's output rather than an ad-hoc subset.
- **Source freshness is shown, never enforced.** A source snapshot carries its
  retrieval time and the operator sees it, and a refresh is offered explicitly,
  but nothing refuses to build a cohort from an old observation and no TTL is
  imposed. A stale *source* is as misleading as a stale seed, and silently
  rejecting one would be a policy this pipeline does not have.
- **Input manifests are discovered from the project `uploads` directory**, not
  from the session's artifacts root. `uploads` is an input location and
  `ARTIFACTS_ROOT` is an output location, so a session scoped to another artifacts
  root still finds the committed inputs. A path outside `uploads` is still
  accepted by typing it.
- **A candidate CIK manifest is never classified.** `cik-sec.csv` might be the
  original universe or a two-CIK increment, and nothing in the file says which.
  Candidates are listed with their row count and no interpretation, because the
  only question that matters — what the base is missing — is answered by
  subtraction, not by the filename.
- **`augment` is single-host.** It derives its delta plan, runs every chunk
  in-process, and publishes; there is no export/worker/import path for a delta,
  because recombination happens inside the call. A delta large enough to want
  distributing is not currently expressible. Roadmap: the multi-machine section of
  `roadmap/refactor_v2/phase_1.md`.
- **Augmentation cannot build on an unpublished artifact.** Only published
  snapshots are offered as bases. v1 also offered a finalized-but-unpublished
  manifest, which would publish a delta over data no reader can resolve to.
- **`smoke_test.py` remains credential-gated and excluded from the default gate.**
  Its guards are pure and are covered by `test_smoke_test.py`.

## Mirrored tests

`tests/pipelines/metadata_sync/` — one file per source module per AGENTS.md §6.

| File | Covers |
| :--- | :--- |
| `test_roster.py` | Identity, ordering, atomic IO, set operations, and a 250,000-CIK derivation/IO budget. |
| `test_manifest.py` | CIK CSV ingestion, normalization, deduplication, fingerprinting. |
| `test_planner.py` | Chunk ranges, identity including the limit and delta cases, manifest-size constantness, and every staleness and version rejection. |
| `test_assignment.py` | Assignment identity, the receipt digest, and receipt tampering. |
| `test_distribution.py` | Export, worker, import, and every import refusal. |
| `test_options.py` | The options boundary and settings resolution. |
| `test_progress.py` | Phase-labelled log lines, the single-phase renderers, the two-phase router's bar lifecycle, and that closing a run that never reached its merge opens no bar. |
| `test_paths.py` | The published-vs-transient split, the bundle layout, and bundle-rooted path resolution. |
| `test_checkpoints.py` | Completeness, including a chunk belonging to a different plan. |
| `test_worker.py` | Per-CIK fan-out and the never-refetch guarantee. |
| `test_snapshot.py` | Part-list resolution and verification: legacy single-file manifests, tampered parts, incomplete publications, unlisted files, and repeated or digestless part entries. |
| `test_merger.py` | Every hard failure, the duplicate-accession warning, and the published CIK index. |
| `test_augmentation.py` | Delta identity, base preservation, union semantics, and the two-phase progress event sequence. |
| `test_registry.py` | The comparison projection and the published roster. |
| `test_source_registry.py` | Write-once content-addressed source snapshots. |
| `test_sec_client.py` | One CIK to its submissions document plus its historical files. |
| `test_worker_commands.py` | Parser round-tripping of every emitted command, bundle naming, and destination quoting. |
| `test_discovery.py` | Plan, snapshot, and roster listing, ordering, unreadable and version-incompatible plans, pointer marking, and the numbered pickers. |
| `test_operator.py` | Session state across menu visits, plan auto-resolution, the numbered pick, headers, roster cohort choice, snapshot-pointer selection, network consent, and the interrupt message. |
| `test_augment_flow.py` | The cohort journey, the consented source refresh, the preflight shown before consent, and the no-op path through both the wizard and `augment`. |
| `test_cli.py` | The parser, the settings regression, and the refresh/compare/plan/merge chain. |
| `test_smoke_test.py` | The credential guards of the live smoke check. |
| `test_scale.py` | Constant-size plans at scale, reassignment stability, single-host/distributed convergence, and the Phase 2 handoff surface. |
| `test_end_to_end.py` | The full chain over a scripted transport. |