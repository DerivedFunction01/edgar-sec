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

`plan`, `status`, `merge`, `export`, `import`, and `sources compare` never touch
the network. `run`, `worker`, `augment`, and `sources refresh` fetch from SEC. The
published layout is in the [root README](../../../README.md#artifact-layout); the
bundle-relative locations this package adds are:

| Command | Writes |
| :--- | :--- |
| `plan`, `augment` | `metadata/cohorts/<key>/ciks.parquet` plus its `cohort.json` — the compiled cohort, keyed by the digest of what produced it |
| `sources compare` | `metadata/registries/<registry_id>/datasets/effective_ciks.parquet` (the roster a plan consumes) and `metadata/registries/<registry_id>/effective_cik_input.csv` (an export) |
| `export` | `<destination>/<worker_id>/` holding the plan manifest, roster, input diagnostics, and one assignment: byte-identical bundles, disjoint assignments |
| `worker` | `<bundle>/chunks/chunk_NNNN.parquet` and `<bundle>/receipt.json` |

A cohort appears twice on disk, and the two copies are not interchangeable.
`metadata/cohorts/<key>/` is the shared store a cohort is compiled into once, keyed
by the digest of its input, so re-planning an unchanged seed reuses it. A plan
bundle carries its own byte-identical copy at `plans/<plan_id>/roster/ciks.parquet`,
because `export` copies the bundle directory to another machine and a worker reading
it has no access to the coordinator's store. The bundle copy is what
`plan.json`'s `roster_artifact_sha256` names.

## Module layout

| Module | Responsibility |
| :--- | :--- |
| `roster.py` | The CIK cohort: content-addressed identity derived by streaming the dataset, ordinal-range reads, atomic Parquet IO, the published CIK index. |
| `manifest.py` | Compiling a CIK CSV into a cohort: one DuckDB pass that normalizes, validates, deduplicates, numbers, and zero-pads, plus the cheap count used to list a candidate input. |
| `planner.py` | `Plan`: chunk layout as ordinal ranges, plan identity, bundle write and validated load. |
| `assignment.py` | Static chunk-to-worker assignment, and the worker receipt that crosses the machine boundary. |
| `distribution.py` | Copy-based multi-machine distribution: export, select, adopt. The import trust boundary. |
| `options.py` | The one typed options model the CLI and the operator both build; bundle path resolution. |
| `progress.py` | This pipeline's progress events rendered for a person. |
| `paths.py` | `MetadataPaths` / `RunPaths`; the published-vs-transient split, plan bundle, registry, and source locations. |
| `checkpoints.py` | What counts as a *complete* chunk on disk. |
| `worker.py` | Resumable chunk execution over a thread pool; the never-refetch guarantee. |
| `snapshot.py` | Resolve a published snapshot to a verified, ordered Parquet part list; both manifest versions. |
| `merger.py` | Coordinator validation, multipart publication, CIK index, snapshot manifest, pointer advance, and explicit pointer selection. |
| `augmentation.py` | Delta planning and merge onto a published snapshot without refetching the base. |
| `validation.py` | The merge-time cohort checks: one row per CIK, and reportable duplicate-accession fan-out. |
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

- **A cohort is stored once and referenced by identity.** `plan.json` records the
  roster identity and the chunk layout; the cohort lives once in
  `roster/ciks.parquet`, and chunk membership is a range over roster ordinals, so
  the manifest is constant in cohort size.
- **A roster is a handle, not a pair of tuples.** It carries its identity, its row
  count, and the path of its dataset, and callers read the slice they need — one
  chunk's ordinal range, the whole cohort streamed for an identity or a CSV export.
  Nothing holds the whole cohort in the Python heap, which is what keeps a
  full-universe run inside the configured memory budget.
- **A CIK input is compiled, not parsed.** `plan` and `augment` reduce a curated CSV
  to a cohort in one DuckDB statement: normalize, validate, deduplicate, number, and
  zero-pad. The reader is fully specified and never auto-detects, because inference
  reads a 20,480-row sample — it would type the CIK column as an integer and discard
  padding a curated file already carries, and hard-error on a non-numeric cell past
  the sample. Every cell is validated as text before it becomes an integer, because a
  cast alone reads `12.5` as 13, `1e5` as 100000, and `0x10` as 16 — all real
  registrants, so an unguarded compile would publish members the curator never named.
- **Plan identity is the cohort, not the schedule.** `derive_plan_id` covers the
  roster identity, the chunk size, the plan kind, and — for a delta — the base
  snapshot. It never covers an assignment, a worker count, or a timestamp, so
  reassigning a cohort keeps the same plan directory and the same checkpoints.
  `--limit` is applied while the cohort is compiled, *before* identity is derived, so
  a bounded run cannot collide with a full run over one file. Reordering a curated
  file also changes the cohort, because `--limit` selects a prefix: the order is part
  of what the run covers.
- **A delta plan is bound to its base.** The same requested CIK list against two
  bases is two plans with two delta rosters. The difference is compiled into a cohort
  of its own, numbered from zero, because an ordinal is a position within a cohort
  and chunk ranges start at zero. Augmentation publishes `base_ciks ∪ delta_ciks` and
  records the parent, the delta roster, and both digests in the new manifest.
- **Row-level `snapshot_id` is provenance, not container identity.** Augmentation
  copies base rows verbatim, so an augmented snapshot legitimately carries rows
  stamped with the base's id; rewriting them would misstate where data came from.
- **Every chunk is complete or absent.** A checkpoint counts only when the file
  exists, matches the canonical schema, holds exactly the CIKs its plan range
  covers, and carries the plan's input fingerprint. Expected CIKs come from the
  plan's roster range, so the same check covers a chunk that arrived from another
  machine under a copied bundle.
- **Merge separates failures from reportable fan-out** (AGENTS.md §4.3).
  Rejected: duplicate or null CIKs, schema drift, plan coverage gaps, row-count
  mismatch, foreign chunk files, foreign input fingerprints, and non-terminal
  statuses. Duplicate *accession numbers* are a warning on the merge report, never
  a rejection — the same filing is legitimately listed by more than one registrant.
- **Publication is immutable, and the manifest is the commit record.** A merge
  validates every chunk, then publishes the validated chunks as an ordered `parts/`
  set, a sorted distinct `ciks.parquet` derived from the *published rows*, a
  manifest listing every part with digest and row count, and a pointer advance. A
  snapshot is read through the part list its manifest declares, every listed part is
  verified against the recorded digest, listed-but-absent means the publication did
  not finish, and present-but-unlisted is not part of it. The manifest is written
  before the pointer, so a crash between them leaves a complete-but-unpublished
  snapshot rather than a pointer naming an unfinished one.
- **A returned chunk is proven before it is adopted.** Import checks the plan and
  assignment identities, the per-file SHA-256, the canonical schema, the row
  count, and the chunk's CIK coverage. A byte-identical re-import is a no-op; a
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
  written, no snapshot is published, and the pointer does not move. The delta is
  always `requested - base`, including for a file that already looks like a delta.
- **A delta plan cannot be merged.** `merge_chunks` publishes exactly the chunks a
  plan produced, and a delta plan's chunks hold only what its base is missing, so
  merging one would drop every base row while recording that base as its parent.
  Generic `merge` therefore refuses a delta plan and names `augment`;
  recombination is augmentation's job, and only augmentation knows which base to
  carry forward. An unreadable base is an error, never an empty one.

## Public surface

The supported boundary, not an inventory of module exports. Everything below is
documented in the owning module; anything not named here is package-internal.

| Entry point | Owner | Who calls it |
| :--- | :--- | :--- |
| `python run.py metadata <command>`; `main`, `build_parser`, and the `cmd_*` callables | `cli` | The operator, a shell, and the wizard |
| `python run.py metadata` with no command | `operator` | The interactive operator |
| `read_snapshot_parts`, manifest loading, `SnapshotLayoutError` | `snapshot` | Phase 2 and the viewer, reading a published snapshot |
| `MetadataPaths`, `resolve_metadata_paths` | `paths` | Phase 2 and the viewer, resolving dataset locations |
| `parts_digest` | `merger` | Phase 2 catalog identity |

Each CLI command is a thin wrapper over a callable, so the lifecycle is drivable
from Python as well: `planner` builds and loads plans, `worker` runs chunks,
`merger` validates and publishes, `augmentation` preflights and augments,
`distribution` exports and adopts, `roster` and `sec_client` supply the cohort and
the transport, and `registry` / `source_registry` own the comparison and the source
snapshot.

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
manifest, or a cohort (`--input` / `--roster`) to re-derive; they are one mutually
exclusive group on `status`, `run`, `merge`, `worker`, `export`, and `import`, and
only the cohort pair is accepted by `plan` and `augment` (required there).
`--artifacts`, `--chunk-size`, and `--workers` are accepted on every subcommand
except `sources refresh` / `sources compare`, which take `--artifacts` only.
`--worker-count` and `--destination` are required on `export`; `--source` is
required on `import`; `--base-snapshot-id` is required on `augment`; `--chunks` and
`--chunk` exist on `run` only. Worked transcripts are in the
[root README](../../../README.md#metadata-sync-pipeline).

**No command asks for an artifacts root.** The root is the configured project
default, read from `ARTIFACTS_ROOT` or `.env`, and the wizard routes every action
through its own session root, so a session can be scoped to another tree without
any action prompting for it. A non-default root for one command is `--artifacts`
on the subcommands. `filing_catalog` and `document_storage` are the matching
precedents — see their READMEs.

The plan id follows the effective chunk size, so planning with one chunk size and
running with another resolves a *different* plan rather than reusing another
plan's checkpoints. `--new-snapshot-id` is optional; omitting it publishes under
the derived delta plan id — a content address over the base snapshot, the
effective delta roster, and the chunk layout — the same rule `merge` follows, so a
row's `snapshot_id` can never disagree with the artifact holding it. Supply it only
when the distribution path needs a worker to stamp rows with a snapshot the
coordinator will publish under.

The interactive operator *discovers* rather than demands: it lists the plans on
disk with size and progress when nothing is chosen, adopts a lone plan without
prompting, and offers published effective-CIK rosters alongside the curated CSV.
Anything that reaches SEC confirms first and defaults to no. Two menu actions exist
because CLI operations needed an entry point prompting did not provide: `p` moves
the current pointer back to an earlier published snapshot (a pointer move and
nothing else, and an unknown target is refused), and `c` prints the distributed
lifecycle — coordinator `export`, one `worker` per machine, one `import` per
returned bundle, then `merge` — with worker ids and bundle names drawn from the
same assignment division `export` performs and empty assignments omitted.

## Deliberate gaps

These are decisions, not oversights. Each names the alternative.

- **Input diagnostics are counts, not per-row detail.** The compiled cohort's
  `cohort.json` records how many rows were rejected and how many were duplicate
  CIKs, which is what a curator needs to trust a seed. It does not name the offending
  rows or their line numbers: the compile is a single DuckDB statement and the reader
  exposes no line ordinal, so recovering them would mean a second pass in Python over
  the whole input — the cost this change exists to remove. Recompile a narrowed file
  to see which rows survived.
- **The registry comparison is still built in Python.** `sources compare` folds a
  whole curated file against the active listings to build the four published registry
  datasets, and it does that with a name map and a dict of listings. That is a
  one-time projection over two immutable files rather than a per-run or per-chunk
  path, and it publishes a schema other packages read; rewriting it as a SQL join is
  a separate change to that contract, not a consequence of the cohort becoming a
  dataset.
- **The compiled cohort store is never garbage collected.** `metadata/cohorts/<key>/`
  accumulates one entry per distinct input digest, including every delta derived
  against a base. Phase 1 has no vacuum for it, the same trade the transient and
  published trees make.
- **A published snapshot is not globally sorted by CIK.** Parts are byte copies
  of the validated chunk files, so the snapshot is in chunk order and each part
  is in fetch-completion order, not roster order. The manifest records this as
  `sort_order: chunk_order` so a consumer cannot mistake one for the other, and
  `ciks.parquet` remains the sorted membership index for lookups by CIK.
  Anything needing globally sorted rows must sort in its own query; Phase 2
  aggregates, so it does not.
- **Parts are copied, not moved.** Publication copies each validated chunk, so a
  resumed plan still finds its checkpoints and an aborted publication leaves the
  transient tree intact — at the cost of the transient and published trees each
  holding the data. Phase 1 has no snapshot garbage collector; that trade is
  revisited with vacuuming.
- **A multipart manifest deliberately names no single payload.** `output_path` and
  `artifact_sha256` stay empty for a multipart snapshot; pointing them at part zero
  would let a reader that understands only the legacy shape silently ingest a
  fraction of the dataset. Snapshots published before the multipart contract keep
  both fields and resolve as a one-part dataset.
- **No dynamic claiming, leases, or scheduler.** Assignment is static and copied.
  A worker that dies mid-run is not detected or reassigned; the coordinator
  re-exports, because a chunk nobody returned is a chunk nobody fetched. A real
  scheduler needs a lease protocol and a heartbeat, which this pipeline does not
  justify.
- **No worker-level rate-limit division.** Each worker process constructs its own
  rate limiter from the configured SEC rate, so N workers together request N times
  the configured rate. Divide the budget with `SEC_RATE_LIMIT_RPS` when
  distributing across machines.
- **`augment` is single-host.** It derives its delta plan, runs every chunk
  in-process, and publishes; there is no export/worker/import path for a delta,
  because recombination happens inside the call. A delta large enough to want
  distributing is not currently expressible.
- **Augmentation cannot build on an unpublished artifact.** Only published
  snapshots are offered as bases, because a delta over data no reader can resolve
  to would be worse than no delta.
- **No `--limit` in augmentation.** A bounded augmentation would fetch a bounded
  delta, which is legitimate, but the flag is not offered because the requested
  cohort is normally a comparison's output rather than an ad-hoc subset.
- **The wizard discovers; it does not orchestrate.** It finds the plan, shows its
  progress, and runs the command the operator picked. It never sequences the
  pipeline and never runs a step that was not chosen. Interactive infrastructure
  stays phase-local for the same reason: discovery, session state, and consent are
  not shared, so promote them to `foundation` when a second pipeline needs them,
  with two consumers.
- **A settings-to-client break can hide behind a fully green gate.** The suite
  injects a fake transport, so the path turning resolved settings into a live
  client is executed by almost nothing — and it did break, disabling *every*
  fetching action while the suite passed. Two tests now drive sentinels through
  `from_settings` and through this pipeline's own construction path, so a renamed
  field raises rather than silently comparing.
- **The HTTP response cache root comes from the settings registry, not
  `resolve_paths()`.** `cache.root` (`CACHE_ROOT`, defaulting to
  `<artifacts_root>/caches`) is where the populated store actually lives, so a
  relocated artifacts root does not by itself move it. An already-populated store
  is read in place, so a re-fetch over covered CIKs spends no request budget.
- **The CSV is an export, not the internal carrier.**
  `effective_cik_input.csv` is written beside `effective_ciks.parquet` for the
  benefit of whatever reads it by hand, and `read_cik_manifest` still parses CIK
  manifests. Nothing in the fetch path parses a CSV to learn which CIKs a run
  covers.
- **No persisted run configuration.** Options are resolved once, held in memory,
  and recorded in the artifacts they produce; there is no `--configure` and no
  `project.json`. Either would add a second source of truth for values the
  settings registry already owns.
- **Source freshness is shown, never enforced.** A source snapshot carries its
  retrieval time and the operator sees it, and a refresh is offered explicitly, but
  nothing refuses to build a cohort from an old observation and no TTL is imposed.
  A stale *source* is as misleading as a stale seed, and silently rejecting one
  would be a policy this pipeline does not have.
- **Input manifests are discovered from the project `uploads` directory**, not from
  the session's artifacts root. `uploads` is an input location and `ARTIFACTS_ROOT`
  is an output location, so a session scoped to another artifacts root still finds
  the committed inputs. A path outside `uploads` is still accepted by typing it.
- **A candidate CIK manifest is never classified.** `cik-sec.csv` might be the
  original universe or a two-CIK increment, and nothing in the file says which.
  Candidates are listed with their row count and no interpretation, because the
  only question that matters — what the base is missing — is answered by
  subtraction, not by the filename.
- **`smoke_test.py` remains credential-gated and excluded from the default gate.**

## Mirrored tests

`tests/pipelines/metadata_sync/` — one test file per source module per AGENTS.md
§6, with `conftest.py` providing the offline fake transport. `test_end_to_end.py`
covers the full chain over a scripted transport; `test_scale.py` covers
constant-size plans at scale, reassignment stability, and distributed
convergence.
