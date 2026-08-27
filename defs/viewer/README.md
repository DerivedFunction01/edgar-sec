# Dataset Viewer (`defs/viewer`)

A local, **read-only** web viewer over the artifacts workspace
(`.artifacts`). It discovers tabular datasets and JSON documents produced by
phases and serves them through a JSON API plus a built browser UI. The viewer
never writes, mutates, or re-fetches artifacts; it only stats and reads.

## What it serves

- **Datasets** — Parquet / JSONL artifacts discovered by walking the artifacts
  root. Multi-chunk runs are grouped into a synthetic `run_union` so a whole
  partition or run can be browsed as one table.
- **Documents** — JSON plans (`plan.json`), partition manifests, and merge
  reports, shown with their raw content.

## Architecture

```text
defs/viewer/
  __main__.py    # entry point: `python -m defs.viewer`
  server.py      # FastAPI app: /api/datasets, /api/documents, /api/health, UI mount
  discover.py    # stat-only artifact discovery + classification (defs.runtime.paths)
  datasets.py    # DuckDB-backed reads (schema, stats, paged rows, SQL console)
  serialize.py   # pandas-free JSON-safe serialization
  sql_guard.py   # validates console SQL is read-only
  ui/            # TypeScript UI (vite build -> ui/dist), served statically
```

Reads go through DuckDB table functions (`read_parquet` / `read_json_auto`)
with server-bound paths; the browser never supplies SQL paths or identifiers
that are not resolved here.

## Run it

```bash
# Built UI + API on http://127.0.0.1:8500
.venv/bin/python -m defs.viewer --artifacts-root .artifacts

# API only (pair with `bun run dev` in defs/viewer/ui for hot reload)
.venv/bin/python -m defs.viewer --api-only

# From the root launcher:
python run.py            # pick "Dataset Viewer"
python run.py viewer
```

`--artifacts-root` defaults to `EDGAR_ARTIFACTS_ROOT` then `.artifacts`.
`--host` / `--port` override the bind (default `127.0.0.1:8500`).

## API surface

| Endpoint | Purpose |
| --- | --- |
| `GET /api/datasets` | list discovered datasets (with revision tokens) |
| `GET /api/datasets/{id}/schema` | columns, DuckDB types, null counts, approx distinct |
| `GET /api/datasets/{id}/stats` | per-column top values for low-cardinality strings |
| `GET /api/datasets/{id}/rows` | one bounded page (`limit` 1–1000, `offset`, `sort`, `filters`, `search`) |
| `POST /api/datasets/{id}/sql` | single guarded, read-only SQL console query |
| `GET /api/documents` | list JSON plans/manifests/reports |
| `GET /api/documents/{id}` | document summary + content |
| `GET /api/health` | status + resolved artifacts root |

## Safety boundaries

- **Read-only SQL.** `sql_guard.validate_read_only` rejects any non-SELECT
  statement; table functions (`read_parquet`, `read_json`, `read_csv`) are
  forbidden in console queries. SQL is wrapped and capped at `MAX_SQL_ROWS`
  (10,000) with a `DEFAULT_TIMEOUT_S` (15s) interrupt.
- **Path confinement.** Dataset ids are opaque, URL-safe encodings of relative
  paths; resolution refuses anything that escapes the artifacts root.
- **Bounded scans.** Row paging uses `LIMIT ? OFFSET ?` with `limit+1` to
  compute `has_more`; no unbounded client-side scans.
- **No pandas.** Rows serialize through `defs.viewer.serialize` so nested Arrow
  structures stay intact.

## UI

The production UI is the prebuilt `ui/dist` (served by FastAPI `StaticFiles`).
For development, `cd defs/viewer/ui && bun install && bun run dev` serves the
UI on vite (proxying the API); pass `--api-only` to the server in that case.
