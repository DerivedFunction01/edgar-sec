/**
 * Typed client for the viewer backend under /api. The client only ever sends
 * dataset ids, and trusts a cached payload only while its `revision` matches
 * the latest listing — the listing is the single invalidation source.
 */

import { metaKey, rowsKey, sqlKey } from "./lib/cache/keys";
import { type CacheStore, cache, estimateBytes, MAX_ENTRY_BYTES } from "./lib/cache/store";

/** Mirrors what the server emits; `sqlite` arrives as one dataset per table. */
export type ArtifactFormat = "parquet" | "sqlite" | "duckdb" | "csv" | "jsonl" | "text" | "json";

/**
 * The complete list of dataset kinds the server reports, from the per-dataset
 * loaders in `apps/viewer/loaders.py`. `<dataset>_run_union` is an in-flight run.
 */
export type ArtifactKind =
  | "metadata_snapshot"
  | "metadata_cik_index"
  | "metadata_chunk"
  | "metadata_run_union"
  | "catalog_profiles"
  | "catalog_targets"
  | "document_index"
  | "document_payload"
  | "filing_catalog_chunk"
  | "filing_catalog_run_union"
  | "document_storage_chunk"
  | "document_storage_run_union"
  | "sqlite_table"
  | "manifest";

export interface DatasetSummary {
  id: string;
  relative_path: string;
  phase: string;
  run_id: string | null;
  kind: ArtifactKind;
  format: ArtifactFormat;
  size_bytes: number;
  mtime: string | null;
  revision: string;
  source_paths?: string[];
}

export interface TreeEntry {
  id: string;
  name: string;
  relative_path: string;
  node_type: "directory" | "database" | "table" | "dataset" | "file";
  format: ArtifactFormat | null;
  has_children: boolean;
  size_bytes: number;
  mtime: string | null;
  revision: string;
  kind: string | null;
  phase: string | null;
  run_id: string | null;
  source_paths: string[];
  table: string | null;
}

export interface TextPage {
  relative_path: string;
  text: string;
  offset: number;
  next_offset: number | null;
  has_more: boolean;
  size_bytes: number;
}

export interface ColumnSchema {
  name: string;
  duckdb_type: string;
  null_count: number | null;
  approx_distinct: number | null;
  total_rows?: number;
  top_values?: { value: unknown; count: number }[];
}

export interface RowsPage {
  items: Record<string, unknown>[];
  has_more: boolean;
  next_cursor: number | null;
  total_rows: number | null;
  truncated: boolean;
}

export type FilterOp =
  | "contains"
  | "not_contains"
  | "eq"
  | "ne"
  | "empty"
  | "not_empty"
  | "gt"
  | "ge"
  | "lt"
  | "le";
export interface ColumnFilter {
  column: string;
  op: FilterOp;
  value?: string;
}

export interface DocumentContent {
  summary: DatasetSummary;
  content: unknown;
}

export interface SqlResult {
  columns: string[];
  rows: Record<string, unknown>[];
  elapsed_ms: number;
  truncated: boolean;
}

export interface BlobResponse {
  column: string;
  is_compressed: boolean;
  compressed_bytes: number;
  decompressed_bytes: number;
  compression_ratio: number;
  mime_type: string;
  text: string | null;
  preview: string | null;
}

export function fetchBlob(
  id: string,
  params: {
    column: string;
    pkCol?: string;
    pkVal?: string;
    rowIndex?: number;
  },
): Promise<BlobResponse> {
  const query = new URLSearchParams({ column: params.column });
  if (params.pkCol && params.pkVal !== undefined) {
    query.set("pk_col", params.pkCol);
    query.set("pk_val", params.pkVal);
  } else if (params.rowIndex !== undefined) {
    query.set("row_index", String(params.rowIndex));
  }
  return getJson<BlobResponse>(`/api/datasets/${encodeURIComponent(id)}/blob?${query}`);
}

/** Latest known revision per artifact id (populated from every listing). */
export const revisions = new Map<string, string>();

export function isCurrent(id: string, revision: string): boolean {
  return revisions.get(id) === revision;
}

/** Merge a listing into the revision map, pruning entries whose revision moved. */
async function recordRevisions<T extends { id: string; revision: string }>(
  list: T[],
): Promise<T[]> {
  const prune: Promise<void>[] = [];
  for (const item of list) {
    const previous = revisions.get(item.id);
    revisions.set(item.id, item.revision);
    if (previous !== undefined && previous !== item.revision) {
      prune.push(cache.deleteByPrefix(`meta:${item.id}:`));
      prune.push(cache.deleteByPrefix(`rows:${item.id}:`));
      prune.push(cache.deleteByPrefix(`sql:${item.id}:`));
    }
  }
  await Promise.all(prune);
  return list;
}

const inFlightGets = new Map<string, Promise<unknown>>();

async function getJson<T>(url: string): Promise<T> {
  const existing = inFlightGets.get(url);
  if (existing) return (await existing) as T;
  const request = (async () => {
    const response = await fetch(url);
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`GET ${url} failed: ${response.status} ${detail}`);
    }
    return response.json();
  })();
  inFlightGets.set(url, request);
  try {
    return (await request) as T;
  } finally {
    if (inFlightGets.get(url) === request) inFlightGets.delete(url);
  }
}

export async function fetchDatasets(): Promise<DatasetSummary[]> {
  const list = await getJson<DatasetSummary[]>("/api/datasets");
  return recordRevisions(list);
}

export async function fetchDocuments(): Promise<DatasetSummary[]> {
  const list = await getJson<DatasetSummary[]>("/api/documents");
  return recordRevisions(list);
}

export async function fetchTreeChildren(parentId?: string): Promise<TreeEntry[]> {
  const query = parentId ? `?parent_id=${encodeURIComponent(parentId)}` : "";
  const list = await getJson<TreeEntry[]>(`/api/tree${query}`);
  return recordRevisions(list);
}

export function fetchText(id: string, offset = 0): Promise<TextPage> {
  const query = new URLSearchParams({ offset: String(offset) });
  return getJson<TextPage>(`/api/files/${encodeURIComponent(id)}/text?${query}`);
}

/**
 * Fetch a revision-gated payload. Serves from cache when the listing revision is
 * unchanged; on network failure falls back to any cached copy (stale-on-error).
 */
async function gatedMeta<T>(id: string, kind: string, fetchFn: () => Promise<T>): Promise<T> {
  const revision = revisions.get(id);
  if (revision) {
    try {
      const cached = await cache.get(metaKey(id, revision, kind));
      if (cached) {
        await cache.touch(cached.key);
        return cached.payload as T;
      }
    } catch {
      // fall through to network
    }
  }
  try {
    const payload = await fetchFn();
    if (revision) {
      const bytes = estimateBytes(payload);
      if (bytes <= MAX_ENTRY_BYTES) {
        await cache.put({
          key: metaKey(id, revision, kind),
          kind,
          revision,
          payload,
          bytes,
          storedAt: Date.now(),
          lastReadAt: Date.now(),
        });
      }
    }
    return payload;
  } catch (exc) {
    const stale = await cache.getByKeyPrefix(`meta:${id}:`);
    if (stale) {
      await cache.touch(stale.key);
      console.warn(`viewer: served cached ${kind} for ${id} after fetch failure`);
      return stale.payload as T;
    }
    throw exc;
  }
}

export function fetchSchema(id: string): Promise<ColumnSchema[]> {
  return gatedMeta(id, "schema", () =>
    getJson<ColumnSchema[]>(`/api/datasets/${encodeURIComponent(id)}/schema`),
  );
}

export function fetchStats(id: string): Promise<ColumnSchema[]> {
  return gatedMeta(id, "stats", () =>
    getJson<ColumnSchema[]>(`/api/datasets/${encodeURIComponent(id)}/stats`),
  );
}

export function fetchDocument(id: string): Promise<DocumentContent> {
  return gatedMeta(id, "document", () =>
    getJson<DocumentContent>(`/api/documents/${encodeURIComponent(id)}`),
  );
}

interface RowsWindow {
  items: Record<string, unknown>[];
  hasMore: boolean;
  totalRows: number | null;
  windowEnd: number;
}

/** Rows windows keyed by view; the key is offset-independent, so `loadMore` extends one entry. */
const sessionWindows = new Map<string, RowsWindow>();

function pageFromWindow(window: RowsWindow, offset: number, limit: number): RowsPage {
  const slice = window.items.slice(offset, offset + limit);
  const end = offset + slice.length;
  const hasMore = end < window.items.length || window.hasMore;
  return {
    items: slice,
    has_more: hasMore,
    next_cursor: hasMore ? end : null,
    total_rows: window.totalRows,
    truncated: false,
  };
}

export function fetchRows(
  id: string,
  params: {
    offset: number;
    limit: number;
    sort?: string;
    dir?: "asc" | "desc";
    filters?: ColumnFilter[];
  },
): Promise<RowsPage> {
  const revision = revisions.get(id) ?? "unknown";
  const key = rowsKey(id, revision, params.sort, params.dir, params.filters);
  const offset = params.offset;
  const limit = params.limit;

  return (async () => {
    if (revision !== "unknown" && !sessionWindows.has(key)) {
      try {
        const cached = await cache.get(key);
        if (cached) sessionWindows.set(key, cached.payload as RowsWindow);
      } catch {
        // fall through to network
      }
    }
    const window = sessionWindows.get(key);
    if (window) {
      await cache.touch(key);
      return pageFromWindow(window, offset, limit);
    }

    const page = await networkRows(id, params);
    const existing = sessionWindows.get(key);
    let nextWindow: RowsWindow;
    if (offset === 0 || !existing) {
      nextWindow = {
        items: page.items,
        hasMore: page.has_more,
        totalRows: page.total_rows,
        windowEnd: page.items.length,
      };
    } else {
      const items = existing.items.slice();
      const at = Math.min(offset, items.length);
      items.splice(at, items.length - at, ...page.items);
      nextWindow = {
        items,
        hasMore: page.has_more,
        totalRows: page.total_rows,
        windowEnd: items.length,
      };
    }
    sessionWindows.set(key, nextWindow);

    const bytes = estimateBytes(nextWindow);
    if (revision !== "unknown" && bytes <= MAX_ENTRY_BYTES) {
      await cache.put({
        key,
        kind: "rows",
        revision,
        payload: nextWindow,
        bytes,
        storedAt: Date.now(),
        lastReadAt: Date.now(),
      });
    }
    return pageFromWindow(nextWindow, offset, limit);
  })();
}

function networkRows(
  id: string,
  params: {
    offset: number;
    limit: number;
    sort?: string;
    dir?: "asc" | "desc";
    filters?: ColumnFilter[];
  },
): Promise<RowsPage> {
  const query = new URLSearchParams({
    offset: String(params.offset),
    limit: String(params.limit),
  });
  if (params.sort) query.set("sort", params.sort);
  if (params.dir) query.set("dir", params.dir);
  if (params.filters?.length) query.set("filters", JSON.stringify(params.filters));
  return getJson<RowsPage>(`/api/datasets/${encodeURIComponent(id)}/rows?${query}`);
}

/** In-memory LRU for SQL results; nothing is persisted. */
const sqlCache = new Map<string, SqlResult>();

export async function runSql(id: string, query: string): Promise<SqlResult> {
  const revision = revisions.get(id) ?? "unknown";
  const key = sqlKey(id, revision, query);
  const hit = sqlCache.get(key);
  if (hit) {
    sqlCache.delete(key);
    sqlCache.set(key, hit);
    return hit;
  }
  const result = await networkRunSql(id, query);
  sqlCache.delete(key);
  sqlCache.set(key, result);
  while (sqlCache.size > 10) {
    const oldest = sqlCache.keys().next().value;
    if (oldest === undefined) break;
    sqlCache.delete(oldest);
  }
  return result;
}

function networkRunSql(id: string, query: string): Promise<SqlResult> {
  return (async () => {
    const response = await fetch(`/api/datasets/${encodeURIComponent(id)}/sql`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail);
    }
    return (await response.json()) as SqlResult;
  })();
}

export type { CacheStore };
