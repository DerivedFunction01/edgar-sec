/**
 * Typed client for the viewer backend under /api.
 *
 * The server owns file paths; the client only ever sends dataset ids. Listing
 * responses publish a per-artifact `revision` token (size + nanosecond mtime,
 * or a composite for run unions). The client trusts a cached payload only when
 * its `revision` matches the latest listing — so the tiny listings (always
 * fetched fresh) are the single invalidation source, and repeat visits render
 * from IndexedDB without re-fetching.
 */

import { metaKey, rowsKey, sqlKey } from "./lib/cache/keys";
import { type CacheStore, cache, estimateBytes, MAX_ENTRY_BYTES } from "./lib/cache/store";

export type ArtifactFormat = "parquet" | "jsonl";

export type ArtifactKind =
  | "run_plan"
  | "partition_manifest"
  | "partition_chunk"
  | "preview"
  | "published_dataset"
  | "published_manifest"
  | "merge_report"
  | "worker_fragment"
  | "unknown"
  | "run_union";

export interface DatasetSummary {
  id: string;
  relative_path: string;
  phase: string;
  run_id: string | null;
  kind: ArtifactKind;
  format: ArtifactFormat | "json";
  size_bytes: number;
  mtime: string | null;
  revision: string;
  source_paths?: string[];
}

export interface ColumnSchema {
  name: string;
  duckdb_type: string;
  null_count: number;
  approx_distinct: number;
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

/** Latest known revision per artifact id (populated from every listing). */
export const revisions = new Map<string, string>();

/** True when `revision` is still the current listing token for `id`. */
export function isCurrent(id: string, revision: string): boolean {
  return revisions.get(id) === revision;
}

/**
 * Merge a fresh listing into the revision map, pruning stale cache entries for
 * any artifact whose revision changed. Returns the same list for chaining.
 */
async function recordRevisions(list: DatasetSummary[]): Promise<DatasetSummary[]> {
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

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`GET ${url} failed: ${response.status} ${detail}`);
  }
  return (await response.json()) as T;
}

export async function fetchDatasets(): Promise<DatasetSummary[]> {
  const list = await getJson<DatasetSummary[]>("/api/datasets");
  return recordRevisions(list);
}

export async function fetchDocuments(): Promise<DatasetSummary[]> {
  const list = await getJson<DatasetSummary[]>("/api/documents");
  return recordRevisions(list);
}

/**
 * Fetch a revision-gated payload (schema/stats/document). Serves from cache
 * instantly when the listing revision is unchanged; otherwise fetches and
 * caches. On network failure, falls back to any cached copy (stale-on-error).
 */
async function gatedMeta<T>(id: string, kind: string, fetchFn: () => Promise<T>): Promise<T> {
  const revision = revisions.get(id);
  if (revision) {
    try {
      const cached = await cache.get(metaKey(id, revision));
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
          key: metaKey(id, revision),
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

/**
 * Accumulated rows windows keyed by view (revision + sort + filters). The key
 * is offset-independent so pages accumulate into one entry; a revisit with the
 * same key restores the whole window instantly, and `loadMore` extends it.
 */
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
