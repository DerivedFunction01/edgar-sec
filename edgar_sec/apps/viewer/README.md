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
| `tree.py` | The lazy filesystem explorer: directory children, reader classification, database table children, bounded text reads. |
| `session.py` | The single connection seam and the interrupt-based statement timeout. |
| `datasets.py` | `DatasetRef`, schema, paged rows, column stats, and BLOB fetch. |
| `console.py` | The guarded read-only SQL console. |
| `server.py` | The read-only HTTP endpoints and the optional static UI mount. |
| `cli.py` | `python -m edgar_sec.apps.viewer.cli`; argument parsing and the loopback default. |
| `ui/` | The React client. `dist/` is committed; see "The browser bundle". |

## How discovery works, and why it is not v1's approach

The explorer is a **lazy filesystem tree**, not a flat listing. One request
returns one directory's direct children; a second returns a database file's
tables. Nothing walks the whole root up front, so an artifacts tree with a
thousand files costs one `scandir` per expanded folder.

Mixed in with the physical entries are **virtual dataset nodes** produced by
manifest-driven loaders. v1 inferred each file's role from its **path shape**,
via a `classify_artifact_path` table that had to be taught every naming
convention and mislabelled anything that did not fit one. v2 asks the **owner**:
each loader knows the manifest of a dataset it owns and asks the owning pipeline
or `infra.storage` to interpret it.

| Dataset | Manifest | Read by |
| :--- | :--- | :--- |
| `metadata` | `metadata.manifest.json` | `metadata_sync.snapshot.read_snapshot_parts` |
| `filing_catalog` | `snapshot.manifest.json` | `loaders.py` (it owns the keys) |
| `document_storage` | `manifest.json` | `infra.storage.manifests.SnapshotReader` |

Adding a dataset means adding a loader, not extending a naming table. A
multipart snapshot is therefore **one** tree node reading all its verified parts,
not one node per part.

**Three manifest vocabularies exist**, which is why `loaders.py` is a registry
rather than one function. The hard part — reading a manifest, resolving and
verifying its parts — already lives in `infra.storage`, so each loader is thin.

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

Classification is by suffix for the tabular formats, and by content sniffing
(a 4 KB UTF-8 sample with no NUL) for text. A binary file with an unknown suffix
is not listed, which is why the explorer looks sparse against a directory of
images or archives: that is the filter working, not a listing bug.

## Contracts this package guarantees

- **The client never names a path.** A request carries an opaque base64 id;
  `model.artifact_path` resolves it and refuses anything outside the artifacts
  root, after resolving symlinks and `..` segments. The tree walk also skips
  symlinks and dot-paths, so the explorer cannot be walked out of the root.
- **Every connection is resource-budgeted.** Connections come from
  `infra.storage.duckdb.connect`, the single sanctioned seam, so they carry the
  cgroup-aware thread and memory limits. `tests/infra/storage/test_duckdb.py`
  pins that this package is not a second `duckdb.connect` site.
- **The client never names a column the dataset does not have.** A sort or filter
  column is matched against the schema DuckDB reported before it reaches SQL.
- **Reads are bounded twice over.** Row paging is `LIMIT ? OFFSET ?` with
  `limit + 1` for `has_more` — never a `COUNT` to answer a cursor question — and
  the page is additionally capped by serialized response bytes
  (`MAX_PAGE_BYTES`), because a page of 200 enormous rows passes a row check. The
  console caps rows (10,000) and accumulated payload (8 MiB) for the same reason.
  Every statement is interruptible via `conn.interrupt`.
- **Opening a table is cheap; statistics are opt-in.** `dataset_schema` is a
  `DESCRIBE` and no longer scans the relation, so selecting a dataset does not
  pay for a full-table aggregate. Null counts, approximate distinct counts, and
  total rows are computed only by `dataset_column_stats`, which the browser
  requests explicitly.
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

**Restriction 3 is why the console is disabled for native DuckDB files.** A
`.duckdb` source has to be `ATTACH`ed to be read at all, and an attached catalog
makes every table in that file addressable by name. The guard cannot prove a
query names only the selected table, so rather than widen the console's scope
quietly, `run_dataset_sql` refuses a `duckdb` source outright and the browser
hides the panel. Tables still browse as usual.

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

`GET /api/health`, `GET /api/tree`, `GET /api/files/{id}/text`,
`GET /api/datasets`, `GET /api/documents`,
`GET /api/datasets/{id}/schema`, `.../stats`, `.../rows`, `.../blob`,
`POST /api/datasets/{id}/sql`, `GET /api/documents/{id}`.

`ArtifactSummary`'s field names are part of this contract: the compiled browser
bundle reads those keys directly, so renaming one is a breaking API change.
`TreeEntry` is the same situation: the explorer renders its fields directly.

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

> [!IMPORTANT]
> `dist/` is kept committable by **two** rules, and both are load-bearing.
> `ui/.gitignore` must not list `dist/` (a nearer file overrides a root one),
> and the root `.gitignore` must carry `!edgar_sec/apps/viewer/ui/dist/` **after**
> every `dist` rule — git gives the last matching pattern the win, so a negation
> placed near the top is silently overridden. `git check-ignore` on a built asset
> is the cheap check that this has not regressed.

## Mirrored tests

| Test | Covers |
| :--- | :--- |
| `tests/apps/viewer/test_model.py` | id round-trip, traversal refusal, revision algebra, wire field names |
| `tests/apps/viewer/test_loaders.py` | each dataset type, tampered parts, absent parts, damaged manifests, union revisions |
| `tests/apps/viewer/test_tree.py` | supported/unsupported detection, symlink refusal, one-node databases with lazy table children, bounded text pages |
| `tests/apps/viewer/test_session.py` | the connection seam, timer cancellation on success *and* failure, interruption |
| `tests/apps/viewer/test_datasets.py` | scan-free schema, paging, byte caps, filter composition, type-aware operator refusal, blob marking and decompression |
| `tests/apps/viewer/test_console.py` | read acceptance, write and table-function refusal, DuckDB refusal, row cap, JSON safety, interruption |
| `tests/apps/viewer/test_server.py` | every endpoint, tree and text reads, CSV/JSONL relations, read-only DuckDB tables, forged-id refusal |
| `tests/apps/viewer/test_cli.py` | argument parsing, and the loopback bind default |
| `tests/test_network_isolation.py` | the viewer cannot reach `infra.sec_http` |

## Deliberate gaps

- **This is not a batch pipeline.** No chunks, no plan, no worker, no
  resumability, and none of AGENTS.md §4's pipeline contracts bind it. That is
  why it is in `apps/` and not `pipelines/`.
- **JSONL is an input, never an output.** The explorer reads `.jsonl` because an
  operator may find one on disk, and the viewer is read-only. Nothing in v2
  *writes* JSONL: it is formally purged as a storage and checkpoint format
  (`roadmap/refactor_v2/v2_refactor_roadmap.md` §3), and no pipeline emits one.
  Supporting the format here does not reinstate it as a backend.
- **Native DuckDB files are read, never queried.** They are attached
  `READ_ONLY` and their tables browse normally, but the SQL console refuses them
  so that the one-table console scope survives. The alternative — letting a
  console query reach any table in an attached file — is a real widening of the
  current contract and is not taken without deciding it deliberately.
- **Opening a database shows one node, not one per table.** Tables are children,
  discovered on expand. A database with 200 tables costs one node in the sidebar
  and one request when it is opened.
- **Text reads are byte-ranged and bounded** (64 KB per request) rather than
  whole-file. Long files page in; the browser appends chunks on demand.
- **The explorer hides unsupported binaries.** A file it cannot read as text or
  as a DuckDB relation simply does not appear, and there is no override. The
  trade-off is that the tree is not a faithful copy of the filesystem; it is a
  view of what this app can show.
- **Documents are not rendered as pages.** The payload parts carry
  zstd-compressed filings; `/blob` decompresses and returns a text preview with a
  size cap. There is no HTML sanitizing renderer, so raw markup is returned as
  text rather than injected into the page.
- **Discovery re-runs per request.** Deliberately uncached: the revision token is
  the browser's only invalidation source, and a server-side cached listing would
  defeat it. The tree is lazy, so this is one `scandir` per expanded directory
  rather than a walk of the whole root.
- **No server-side result cache.** A repeated page re-queries. Correct, and
  cheap at operator browsing rates; wrong if this ever serves many users, which
  it is not designed to.
- **No HTTP streaming.** Pages are ordinary bounded JSON responses. A very wide
  or very slow page is bounded and interrupted, not streamed progressively; a
  future need for streaming should be measured before it is built.
- **No diffing between two snapshots.** Comparing runs is a real need and is not
  implemented; `source_snapshot_ids` in a document manifest is the raw material
  for it.
- **One app, so no shared app framework.** When a second app exists, the HTTP
  shell and the UI shell are the duplication candidates. Extracting them before
  there is a second consumer would be speculative.
