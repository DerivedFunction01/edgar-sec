# `edgar_sec.apps.viewer` — the dataset viewer

Layer 5. A read-only browser and SQL console over the artifacts a pipeline
published. It fetches nothing, transforms nothing, and writes nothing.

## Purpose

Answer two questions an operator actually has while a run is in flight or after
it finishes: *what is on disk right now*, and *what is in that file*. The second
is why the SQL console exists — a schema and a sample row rarely answer "did the
CIK index agree with the payload", and reading a hundred-thousand-row Parquet
file by other means is not a workflow.

## Module layout

| Module | Responsibility |
| :--- | :--- |
| `model.py` | `ArtifactSummary` and the opaque id/path/revision vocabulary. Owns the wire field names. |
| `loaders.py` | One loader per published dataset type; runs them all; lists browsable documents. |
| `session.py` | The single connection seam and the interrupt-based statement timeout. |
| `datasets.py` | `DatasetRef`, schema, paged rows, column stats, and BLOB fetch. |
| `console.py` | The guarded read-only SQL console. |
| `server.py` | Seven HTTP endpoints and the optional static UI mount. |
| `cli.py` | `python -m edgar_sec.apps.viewer.cli`; argument parsing and the loopback default. |
| `ui/` | The React client. `dist/` is committed; see "The browser bundle". |

## How discovery works, and why it is not v1's approach

v1 inferred each file's role from its **path shape**, via a `classify_artifact_path`
table that had to be taught every naming convention and mislabelled anything that
did not fit one. v2 asks the **owner**: each loader knows the manifest of a
dataset it owns and asks the owning pipeline or `infra.storage` to interpret it.

| Dataset | Manifest | Read by |
| :--- | :--- | :--- |
| `metadata` | `metadata.manifest.json` | `metadata_sync.snapshot.read_snapshot_parts` |
| `filing_catalog` | `snapshot.manifest.json` | `loaders.py` (it owns the keys) |
| `document_storage` | `manifest.json` | `infra.storage.manifests.SnapshotReader` |

Adding a dataset means adding a loader, not extending a naming table.

**Three manifest vocabularies exist**, which is why `loaders.py` is a registry
rather than one function. The hard part — reading a manifest, resolving and
verifying its parts — already lives in `infra.storage`, so each loader is thin.

## Contracts this package guarantees

- **No artifact is ever opened as a database.** Every connection is in-memory
  and artifacts are bound only as *table-function arguments*
  (`read_parquet([...])`). Opening a file as a DuckDB database would take a lock
  on it and could write; a table function only reads. This is stronger than an
  `access_mode='read_only'` flag, because there is no write path to flag off.
- **Every connection is resource-budgeted.** Connections come from
  `infra.storage.duckdb.connect`, the single sanctioned seam, so they carry the
  cgroup-aware thread and memory limits. `tests/infra/storage/test_duckdb.py`
  pins that this package is not a second `duckdb.connect` site.
- **The client never names a path.** A request carries an opaque base64 id;
  `model.artifact_path` resolves it and refuses anything outside the artifacts
  root, after resolving symlinks and `..` segments.
- **The client never names a column the dataset does not have.** A sort or filter
  column is matched against the schema DuckDB reported before it reaches SQL.
- **Reads are bounded.** Row paging is `LIMIT ? OFFSET ?` with `limit + 1` for
  `has_more` — never a `COUNT` to answer a cursor question. The console caps rows
  (10,000) *and* accumulated payload (8 MiB), because 9,999 enormous rows pass a
  row check. Every statement is interruptible via `conn.interrupt`.
- **A published dataset is content-addressed.** Its `revision` is a digest of its
  manifest, which is immutable by contract. A transient run has no manifest yet,
  so its revision is a stat-based composite instead. Both are what the browser's
  IndexedDB cache is keyed on.
- **A damaged dataset does not hide healthy ones.** A loader that raises is
  logged and skipped; a snapshot whose declared parts are missing or whose digest
  does not match is left out of the listing rather than shown with wrong
  contents.

## The SQL console's threat model

A human's own text becoming SQL is the one place in this package with an attack
surface, so four restrictions stack. Removing any one is a hole:

1. `foundation.sql.guard.validate_read_only` — a single read statement only.
2. Table functions (`read_parquet`, `read_csv`, `read_json_auto`, `sqlite_scan`)
   are refused, so the console cannot name any other file on disk.
3. The dataset is bound as a private view named `dataset`; nothing else is in
   scope, so the reachable data is exactly the selected part list.
4. Row and payload caps plus an interrupt-based timeout.

DuckDB's built-in `information_schema` is always queryable. That is harmless
because it exposes only the `dataset` view this process created — and a test
asserts exactly that, because "one relation exists" is the property that makes
restrictions 2 and 3 meaningful.

## Public surface

| Symbol | Module |
| :--- | :--- |
| `create_app(artifacts_root)`, `UI_DIST` | `server` |
| `DatasetRef`, `dataset_schema`, `dataset_rows`, `dataset_column_stats`, `dataset_blob`, `MAX_LIMIT` | `datasets` |
| `run_dataset_sql`, `MAX_SQL_ROWS`, `MAX_PAYLOAD_BYTES` | `console` |
| `ArtifactSummary`, `artifact_id`, `artifact_path`, `artifact_table`, `manifest_revision`, `compute_union_revision` | `model` |
| `DatasetError` | `model` (re-exported by `datasets`) |
| `LOADERS`, `DatasetLoader`, `run_all`, `iter_documents` | `loaders` |

`apps/viewer/__init__.py` is a docstring and re-exports nothing, per AGENTS.md
§1.2. Consumers import from the leaf module.

## Command surface

```bash
python -m edgar_sec.apps.viewer.cli                       # 127.0.0.1:8500
python run.py viewer                                      # same, via the launcher
python -m edgar_sec.apps.viewer.cli --api-only            # no static mount
python -m edgar_sec.apps.viewer.cli --artifacts-root DIR  # browse another root
python -m edgar_sec.apps.viewer.cli --host 0.0.0.0        # prints a warning
```

The entry module is named `cli` to match the other three launch targets, so the
root launcher's `module` field means the same thing for every entry.

The default bind is loopback and a non-loopback `--host` prints a warning naming
what it exposes. There is no authentication; this is a local operator tool, not a
service.

### Endpoints

`GET /api/health`, `GET /api/datasets`, `GET /api/documents`,
`GET /api/datasets/{id}/schema`, `.../stats`, `.../rows`, `.../blob`,
`POST /api/datasets/{id}/sql`, `GET /api/documents/{id}`.

`ArtifactSummary`'s field names are part of this contract: the compiled browser
bundle reads those keys directly, so renaming one is a breaking API change.

## The browser bundle

`ui/dist/` is **committed**. The gate is Python-only, and `bun`, `node`, and the
npm registry are not guaranteed on a machine that clones this repo — a clone
without `dist/` would get a working API and a "UI not built" message instead of a
usable viewer. `node_modules/` stays ignored.

To change the UI:

```bash
cd edgar_sec/apps/viewer/ui
bun install && bun run build   # regenerates dist/; commit the result
bun test                        # 15 tests
```

Never hand-edit `dist/`. The bundle in the tree was rebuilt from the ported
source, not copied from v1: the sidebar's kind labels and the badge colours both
changed with the v2 dataset vocabulary, so a copied bundle would have rendered v1
labels.

## Mirrored tests

| Test | Covers |
| :--- | :--- |
| `tests/apps/viewer/test_model.py` | id round-trip, traversal refusal, revision algebra, wire field names |
| `tests/apps/viewer/test_loaders.py` | each dataset type, tampered parts, absent parts, damaged manifests, union revisions |
| `tests/apps/viewer/test_session.py` | the connection seam, timer cancellation on success *and* failure, interruption |
| `tests/apps/viewer/test_datasets.py` | schema, paging, filter composition, type-aware operator refusal, blob marking and decompression |
| `tests/apps/viewer/test_console.py` | read acceptance, write and table-function refusal, row cap, JSON safety, interruption |
| `tests/apps/viewer/test_server.py` | every endpoint, forged-id refusal, 404/400/422 paths |
| `tests/apps/viewer/test_cli.py` | argument parsing, and the loopback bind default |
| `tests/test_network_isolation.py` | the viewer cannot reach `infra.sec_http` |

## Deliberate gaps

- **This is not a batch pipeline.** No chunks, no plan, no worker, no
  resumability, and none of AGENTS.md §4's pipeline contracts bind it. That is
  why it is in `apps/` and not `pipelines/`.
- **No JSONL, ever.** v1's reader had a JSONL branch. JSONL is formally purged
  (`grep -rl jsonl edgar_sec/` returns 0 files), so the branch is gone rather
  than disabled.
- **SQLite is listed but not validated.** A `.db` under the artifacts root is
  exposed one record per table. The payload store and the transient chunk writer
  both produce them, and an operator debugging a failed fetch will want in. The
  read path itself is DuckDB's `sqlite_scan`.
- **Documents are listed but not rendered as pages.** The payload parts carry
  zstd-compressed filings; `/blob` decompresses and returns a text preview with a
  size cap. There is no HTML sanitizing renderer, so raw markup is returned as
  text rather than injected into the page.
- **Discovery re-runs per request.** Deliberately uncached: the revision token is
  the browser's only invalidation source, and a server-side cached listing would
  defeat it. Stat-only discovery over a published tree is cheap.
- **No server-side result cache.** A repeated page re-queries. Correct, and
  cheap at operator browsing rates; wrong if this ever serves many users, which
  it is not designed to.
- **No diffing between two snapshots.** Comparing runs is a real need and is not
  implemented; `source_snapshot_ids` in a document manifest is the raw material
  for it.
- **One app, so no shared app framework.** When a second app exists, the HTTP
  shell and the UI shell are the duplication candidates. Extracting them before
  there is a second consumer would be speculative.
