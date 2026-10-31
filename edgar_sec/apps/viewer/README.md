# `edgar_sec.apps.viewer` — the dataset viewer

Layer 5. A read-only browser and SQL console over the artifacts a pipeline
published. It fetches nothing, transforms nothing, and writes nothing.

## Purpose

Answer the two questions an operator has while a run is in flight or after it
finishes: *what is on disk right now*, and *what is in that file*. The second is
why the SQL console exists — a schema and a sample row rarely settle "did the CIK
index agree with the payload", and reading a hundred-thousand-row Parquet file by
other means is not a workflow.

## Discovery

The explorer is a **lazy filesystem tree**, not a flat listing: one request returns
one directory's direct children, a second returns a database file's tables.
Nothing walks the root up front, so a large artifacts tree costs one `scandir` per
expanded folder.

Mixed into the physical entries are **virtual dataset nodes** from manifest-driven
loaders. Each loader knows the manifest of the dataset it owns and asks the owning
pipeline or `infra.storage` to interpret it, so the only thing guessed is the
dataset's root — a known path per pipeline, not a naming convention. The pipeline
manifests are not one vocabulary; [`loaders.py`](loaders.py) tabulates them and
which reader owns each. Adding a dataset means adding a loader.

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

Tabular formats classify by suffix, text by content sniffing. A binary with an
unknown suffix is not listed, which is why the explorer looks sparse against a
directory of images: that is the filter working.

## Contracts this package guarantees

- **The client never names a path.** A request carries an opaque base64 id;
  `model.artifact_path` resolves it and refuses anything outside the artifacts
  root, after resolving symlinks and `..`. The tree walk skips symlinks and
  dot-paths too.
- **Every connection is resource-budgeted.** Connections come from
  `infra.storage.duckdb.connect`, the single sanctioned seam, so they carry the
  cgroup-aware thread and memory limits.
- **The client never names a column the dataset does not have.** A sort, search,
  or filter column is matched against the schema DuckDB reported before it reaches
  SQL, and a range operator on a non-orderable type is refused by name.
- **Reads are bounded twice over.** Paging is `LIMIT ? OFFSET ?` with `limit + 1`
  for `has_more` — never a `COUNT` — and each page is additionally capped by
  serialized bytes (`MAX_PAGE_BYTES`). The console caps rows (`MAX_SQL_ROWS`) and
  accumulated payload (`MAX_PAYLOAD_BYTES`). Every statement is interruptible.
- **Opening a table is cheap; statistics are opt-in.** `dataset_schema` is a
  `DESCRIBE`; null counts, approximate distinct counts, and total rows are
  computed only by `dataset_column_stats`.
- **A published dataset is content-addressed.** Its `revision` is a digest of its
  immutable manifest, or a stat-based composite over its parts while a run is still
  in flight. Both are what the browser's IndexedDB cache is keyed on.
- **A damaged dataset does not hide healthy ones.** A loader that raises is logged
  and skipped; a snapshot whose declared parts are missing or whose digest does not
  match is left out rather than shown with wrong contents.

## The SQL console

A human's own text becoming SQL is the one place in this package with an attack
surface. [`console.py`](console.py) states the restrictions that stack to bound it.
One of them has a caller-visible consequence: a native DuckDB source has to be
`ATTACH`ed to be read at all, and an attached catalog makes every table in that
file addressable by name, so `run_dataset_sql` refuses a `duckdb` source outright
and `App.tsx` renders a disabled panel instead. The tables still browse.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
`python -m edgar_sec.apps.viewer.cli` — Serve the read-only dataset viewer (API + built UI).
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
# Start viewer on default port
python run.py viewer

# Browse a custom artifacts root
python -m edgar_sec.apps.viewer.cli --artifacts /path/to/artifacts

# Bind to a different port
python -m edgar_sec.apps.viewer.cli --port 8080

# API-only mode (no static UI mount)
python -m edgar_sec.apps.viewer.cli --api-only
```

### Endpoints

`GET /api/health`, `GET /api/tree`, `GET /api/files/{id}/text`,
`GET /api/datasets`, `GET /api/documents`, `GET /api/datasets/{id}/schema`,
`.../stats`, `.../rows`, `.../blob`, `POST /api/datasets/{id}/sql`,
`GET /api/documents/{id}`. The OpenAPI document is served under `/api` so it can
never collide with the static mount at `/`.

`ArtifactSummary`'s and `TreeEntry`'s field names are part of this contract: the
compiled bundle reads those keys directly, so renaming one is a breaking change.

## The browser bundle

`ui/` is a bun + vite + React client. To change it:

```bash
cd edgar_sec/apps/viewer/ui
bun install && bun run build   # regenerates dist/
bun test
```

`dist/` is not tracked.

## Deliberate gaps

- **This is not a batch pipeline.** No chunks, no plan, no worker, no
  resumability, so none of `AGENTS.md` §4's pipeline contracts bind it.
- **JSONL is an input, never an output.** Nothing here writes JSONL: it is not a
  storage or checkpoint format, and reading one in the explorer does not reinstate
  it as a backend.
- **Native DuckDB files are read, never queried.** They are attached `READ_ONLY`
  and their tables browse normally; the console refuses them so the one-table
  scope survives.
- **Opening a database shows one node, not one per table.** Tables are children,
  discovered on expand.
- **Text reads are byte-ranged and bounded** (`MAX_TEXT_BYTES`) rather than
  whole-file. Long files page in; the browser appends chunks on demand.
- **The explorer hides unsupported binaries.** A file it cannot read as text or as
  a relation does not appear and there is no override. The tree is a view of what
  this app can show, not a faithful copy of the filesystem.
- **Documents are not rendered as pages.** Payload parts carry zstd-compressed
  filings; `/blob` decompresses and returns the full text plus a `preview`
  truncated to `MAX_BLOB_PREVIEW` (500 chars). There is no cap on the returned
  `text` itself, so the response size is bounded by the filing, not by the app.
  There is no HTML-sanitizing renderer, and `ui/src/` injects no raw markup, so
  filing HTML arrives as text rather than injected.
- **Discovery re-runs per request.** Deliberately uncached: the revision token is
  the browser's only invalidation source, and a server-side cached listing would
  defeat it. The tree is lazy, so this is one `scandir` per expanded directory.
- **No server-side result cache.** A repeated page re-queries. Cheap at operator
  browsing rates; wrong if this ever served many users, which it is not designed
  to.
- **No HTTP streaming.** Pages are ordinary bounded JSON responses, bounded and
  interrupted rather than streamed progressively.
- **No diffing between two snapshots.** `source_snapshot_ids` in a document
  manifest is the raw material; comparing runs is a real need and is not
  implemented.
- **One app, so no shared app framework.** The HTTP shell and the UI shell are the
  duplication candidates, to be extracted when a second app exists.
