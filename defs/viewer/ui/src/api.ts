/**
 * Typed client for the viewer backend under /api.
 * The server owns file paths; the client only ever sends dataset ids.
 */

export type ArtifactFormat = "parquet" | "jsonl";

export type ArtifactKind =
  | "run_plan"
  | "partition_manifest"
  | "partition_chunk"
  | "chunk"
  | "preview"
  | "canonical"
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

export async function fetchStats(id: string): Promise<ColumnSchema[]> {
  return getJson<ColumnSchema[]>(`/api/datasets/${encodeURIComponent(id)}/stats`);
}

export async function fetchDocument(id: string): Promise<DocumentContent> {
  return getJson<DocumentContent>(`/api/documents/${encodeURIComponent(id)}`);
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`GET ${url} failed: ${response.status} ${detail}`);
  }
  return (await response.json()) as T;
}

export function fetchDatasets(): Promise<DatasetSummary[]> {
  return getJson<DatasetSummary[]>("/api/datasets");
}

export function fetchDocuments(): Promise<DatasetSummary[]> {
  return getJson<DatasetSummary[]>("/api/documents");
}

export function fetchSchema(id: string): Promise<ColumnSchema[]> {
  return getJson<ColumnSchema[]>(`/api/datasets/${encodeURIComponent(id)}/schema`);
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
  const query = new URLSearchParams({
    offset: String(params.offset),
    limit: String(params.limit),
  });
  if (params.sort) query.set("sort", params.sort);
  if (params.dir) query.set("dir", params.dir);
  if (params.filters?.length) query.set("filters", JSON.stringify(params.filters));
  return getJson<RowsPage>(`/api/datasets/${encodeURIComponent(id)}/rows?${query}`);
}

export interface SqlResult {
  columns: string[];
  rows: Record<string, unknown>[];
  elapsed_ms: number;
  truncated: boolean;
}

export async function runSql(id: string, query: string): Promise<SqlResult> {
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
}
