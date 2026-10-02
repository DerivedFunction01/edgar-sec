# `edgar_sec.apps.viewer` — the dataset viewer

Layer 5. A read-only browser and SQL console over the artifacts a pipeline
published. It fetches nothing, transforms nothing, and writes nothing.

## Purpose

Answer two questions an operator has while a run is in flight or after it
finishes: *what is on disk right now*, and *what is in that file*. The second is
why the SQL console exists — a schema and a sample row rarely settle "did the CIK
index agree with the payload", and reading a hundred-thousand-row Parquet file by
other means is not a workflow.

## Module layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Docstring only. No re-exports, per AGENTS.md §1.2. |
| `model.py` | `ArtifactSummary` and the opaque id/path/revision vocabulary. Owns the wire field names. |
| `loaders.py` | One loader per published dataset type; runs them all; lists browsable documents. |
| `tree.py` | The lazy filesystem explorer: directory children, reader classification, database table children, bounded text reads. |
| `session.py` | The single connection seam and the interrupt-based statement timeout. |
| `datasets.py` | `DatasetRef`, schema, paged rows, column stats, BLOB fetch. |
| `console.py` | The guarded read-only SQL console. |
| `server.py` | The read-only HTTP endpoints and the optional static UI mount. |
| `cli.py` | `python -m edgar_sec.apps.viewer.cli`; argument parsing and the loopback default. |
| `ui/` | The React client. See "The browser bundle". |

## Discovery

The explorer is a **lazy filesystem tree**, not a flat listing. One request
returns one directory's direct children; a second returns a database file's
tables. Nothing walks the root up front, so a thousand-file artifacts tree costs
one `scandir` per expanded folder.

Mixed into the physical entries are **virtual dataset nodes** from
manifest-driven loaders. Each loader knows the manifest of a dataset it owns and
asks the owning pipeline or `infra.storage` to interpret it, so the only thing
guessed is the dataset's root — a known path per pipeline, not a naming
convention. Three manifest vocabularies exist, which is why `loaders.py` is a
registry; `loaders.py`'s module docstring names them and which reader owns each.
Adding a dataset means adding a loader, and a multipart snapshot is one tree node
reading all its verified parts.

### What a file can be

| Suffix | Node | Opened with |
| :--- | :--- | :--- |
| `.parquet` | file | `read_parquet` (multi-part for a virtual dataset) |
| `.csv`, `.tsv` | file | `read_csv_auto` |
| `.jsonl`, `.ndjson` | file | `read_json_auto(format='newline_delimited')` |
| `.db`, `.sqlite` | database | `sqlite_scan`, one child per table |
| `.duckdb` | database | `ATTACH … (READ_ONLY)`, one child per table |
| any UTF-8 text | file | bounded byte-range text reader |
| anything else | *hidden* | — |

Tabular formats classify by suffix, text by content sniffing (a 4 KB UTF-8 sample
with no NUL). A binary with an unknown suffix is not listed, which is why the
explorer looks sparse against a directory of images: that is the filter working.

## Contracts this package guarantees

- **The client never names a path.** A request carries an opaque base64 id;
  `model.artifact_path` resolves it and refuses anything outside the artifacts
  root, after resolving symlinks and `..`. The tree walk skips symlinks and
  dot-paths too.
- **Every connection is resource-budgeted.** Connections come from
  `infra.storage.duckdb.connect`, the single sanctioned seam, so they carry the
  cgroup-aware thread and memory limits.
  `tests/infra/storage/test_duckdb.py` pins that `duckdb.connect(` is reachable
  from exactly one file in the package, this one included.
- **The client never names a column the dataset does not have.** A sort, search,
  or filter column is matched against the schema DuckDB reported before it reaches
  SQL; a range operator on a non-orderable type is refused by name rather than
  silently answered.
- **Reads are bounded twice over.** Paging is `LIMIT ? OFFSET ?` with `limit + 1`
  for `has_more` — never a `COUNT` to answer a cursor question — and the page is
  additionally capped by serialized response bytes (`MAX_PAGE_BYTES`). The console
  caps rows (10,000) and accumulated payload (8 MiB) for the same reason. Every
  statement is interruptible via `conn.interrupt`.
- **Opening a table is cheap; statistics are opt-in.** `dataset_schema` is a
  `DESCRIBE`, so selecting a dataset pays no aggregate. Null counts, approximate
  distinct counts, and total rows are computed only by `dataset_column_stats`.
- **A published dataset is content-addressed.** Its `revision` is a digest of its
  immutable manifest. A transient run has no manifest yet, so its revision is a
  stat-based composite over its parts. Both are what the browser's IndexedDB cache
  is keyed on.
- **A damaged dataset does not hide healthy ones.** A loader that raises is logged
  and skipped; a snapshot whose declared parts are missing or whose digest does not
  match is left out rather than shown with wrong contents.

## The SQL console's threat model

A human's own text becoming SQL is the one place in this package with an attack
surface, so four restrictions stack. Removing any one is a hole:

1. `foundation.sql.guard.validate_read_only` — a single read statement only.
2. Table functions (`read_parquet`, `read_csv*`, `read_json*`, `sqlite_scan`) are
   refused, so the console cannot name any other file on disk.
3. The dataset is bound as a private view named `dataset` and nothing else is in
   scope, so the reachable data is exactly the selected part list.
4. Row and payload caps plus an interrupt-based timeout.

DuckDB's built-in `information_schema` is always queryable. That is harmless
because it exposes only the `dataset` view this process created —
`tests/apps/viewer/test_console.py` asserts exactly that, because "one relation
exists" is what makes restrictions 2 and 3 meaningful.

**Restriction 3 is why the console is disabled for native DuckDB files.** A
`.duckdb` source has to be `ATTACH`ed to be read at all, and an attached catalog
makes every table in that file addressable by name. Rather than widen the
console's scope quietly, `run_dataset_sql` refuses a `duckdb` source outright and
`App.tsx` renders a disabled panel instead. The tables still browse.

## Public surface

| Symbol | Module |
| :--- | :--- |
| `create_app(artifacts_root)`, `UI_DIST` | `server` |
| `DatasetRef`, `dataset_schema`, `dataset_rows`, `dataset_column_stats`, `dataset_blob`, `MAX_LIMIT`, `MAX_PAGE_BYTES` | `datasets` |
| `run_dataset_sql`, `MAX_SQL_ROWS`, `MAX_PAYLOAD_BYTES` | `console` |
| `ArtifactSummary`, `artifact_id`, `artifact_path`, `artifact_table`, `manifest_revision`, `compute_union_revision` | `model` |
| `DatasetError` | `model` (re-exported by `datasets`) |
| `LOADERS`, `DatasetLoader`, `run_all`, `iter_documents` | `loaders` |
| `TreeEntry`, `tree_children`, `read_text_file`, `MAX_TEXT_BYTES`, `ROOT_NODE_ID` | `tree` |

`viewer/__init__.py` is a docstring and re-exports nothing, per AGENTS.md §1.2.
Consumers import from the leaf module.

## Command surface

```bash
python -m edgar_sec.apps.viewer.cli                       # 127.0.0.1:8500
python run.py viewer                                      # same, via the launcher
python -m edgar_sec.apps.viewer.cli --api-only            # no static mount
python -m edgar_sec.apps.viewer.cli --artifacts-root DIR  # browse another root
python -m edgar_sec.apps.viewer.cli --port N              # default 8500
python -m edgar_sec.apps.viewer.cli --host 0.0.0.0        # prints a warning
```

The entry module is named `cli` to match the other three launch targets, so the
root launcher's `module` field means the same thing for every entry. There is no
`__main__.py`: `python -m edgar_sec.apps.viewer` does not work, and the `.cli`
suffix is required.

The default bind is loopback and a non-loopback `--host` prints a warning naming
what it exposes. There is no authentication; this is a local operator tool.

### Endpoints

`GET /api/health`, `GET /api/tree`, `GET /api/files/{id}/text`,
`GET /api/datasets`, `GET /api/documents`, `GET /api/datasets/{id}/schema`,
`.../stats`, `.../rows`, `.../blob`, `POST /api/datasets/{id}/sql`,
`GET /api/documents/{id}`. The OpenAPI document is served under `/api` so it can
never collide with the static mount at `/`.

`ArtifactSummary`'s field names are part of this contract: the compiled bundle
reads those keys directly, so renaming one is a breaking API change. `TreeEntry`
is the same situation.

## The browser bundle

`ui/` is a bun + vite + React client. To change it:

```bash
cd edgar_sec/apps/viewer/ui
bun install && bun run build   # regenerates dist/
bun test                        # 16 tests
```

`dist/` is **not** tracked.

## Mirrored tests

| Test | Covers |
| :--- | :--- |
| `tests/apps/viewer/test_model.py` | id round-trip, traversal refusal, revision algebra, wire field names |
| `tests/apps/viewer/test_loaders.py` | each dataset type, tampered parts, absent parts, damaged manifests, union revisions |
| `tests/apps/viewer/test_tree.py` | supported/unsupported detection, symlink refusal, one-node databases with lazy table children, bounded text pages |
| `tests/apps/viewer/test_session.py` | the connection seam, timer cancellation on success *and* failure, interruption |
| `tests/apps/viewer/test_datasets.py` | scan-free schema, paging, byte caps, filter composition, type-aware operator refusal, blob marking and decompression |
| `tests/apps/viewer/test_console.py` | read acceptance, write and table-function refusal, DuckDB refusal, row cap, single-relation scope, interruption |
| `tests/apps/viewer/test_server.py` | every endpoint, tree and text reads, CSV/JSONL relations, read-only DuckDB tables, forged-id refusal |
| `tests/apps/viewer/test_cli.py` | argument parsing, and the loopback bind default |
| `tests/test_network_isolation.py` | the viewer cannot reach `infra.sec_http` |

## Deliberate gaps

- **This is not a batch pipeline.** No chunks, no plan, no worker, no
  resumability, so none of AGENTS.md §4's pipeline contracts bind it.
- **JSONL is an input, never an output.** The explorer reads `.jsonl` because an
  operator may find one on disk. Nothing in v2 *writes* JSONL: it is formally
  purged as a storage and checkpoint format (roadmap
  [§3](../../../roadmap/refactor_v2/v2_refactor_roadmap.md)). Reading the format
  here does not reinstate it as a backend.
- **Native DuckDB files are read, never queried.** They are attached `READ_ONLY`
  and their tables browse normally; the console refuses them so the one-table
  scope survives.
- **Opening a database shows one node, not one per table.** Tables are children,
  discovered on expand.
- **Text reads are byte-ranged and bounded** (64 KB per request, `MAX_TEXT_BYTES`)
  rather than whole-file. Long files page in; the browser appends chunks on demand
  via `TextFileView.tsx`.
- **The explorer hides unsupported binaries.** A file it cannot read as text or as
  a relation does not appear and there is no override. The tree is a view of what
  this app can show, not a faithful copy of the filesystem.
- **Documents are not rendered as pages.** Payload parts carry zstd-compressed
  filings; `/blob` decompresses and returns the full text plus a `preview`
  truncated to `MAX_BLOB_PREVIEW` (500 chars). There is no cap on the returned
  `text` itself, so the response size is bounded by the filing, not by the app.
  There is no HTML-sanitizing renderer, and `ui/src/` contains no
  `dangerouslySetInnerHTML`, so raw markup arrives as text rather than injected.
- **Discovery re-runs per request.** Deliberately uncached: the revision token is
  the browser's only invalidation source, and a server-side cached listing would
  defeat it. The tree is lazy, so this is one `scandir` per expanded directory.
- **No server-side result cache.** A repeated page re-queries. Cheap at operator
  browsing rates; wrong if this ever served many users, which it is not designed
  to.
- **No HTTP streaming.** Pages are ordinary bounded JSON responses, bounded and
  interrupted rather than streamed progressively. Measure before building it.
- **No diffing between two snapshots.** `source_snapshot_ids` in a document
  manifest is the raw material; comparing runs is a real need and is not
  implemented.
- **One app, so no shared app framework.** The HTTP shell and the UI shell are the
  duplication candidates, to be extracted when a second app exists.
