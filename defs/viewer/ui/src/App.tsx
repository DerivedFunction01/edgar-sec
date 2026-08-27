import { type UIEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  type ColumnFilter,
  type ColumnSchema,
  type DatasetSummary,
  type DocumentContent,
  fetchDatasets,
  fetchDocument,
  fetchDocuments,
  fetchRows,
  fetchSchema,
  fetchStats,
  type SqlResult,
} from "./api";
import ArtifactSidebar from "./components/ArtifactSidebar";
import CellFocus from "./components/CellFocus";
import DataTable from "./components/DataTable";
import RowDetail, { JsonDocument } from "./components/RowDetail";
import SqlConsole from "./components/SqlConsole";

const PAGE_SIZE = 200;
const MAX_LOADED_ROWS = 2000;

type Theme = "dark" | "cloud";

export default function App() {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("viewer-theme") as Theme) ?? "dark",
  );
  const [consoleOpen, setConsoleOpen] = useState(
    () => localStorage.getItem("viewer-console") !== "false",
  );
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem("viewer-sidebar") === "true",
  );

  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [documents, setDocuments] = useState<DatasetSummary[]>([]);
  const [selected, setSelected] = useState<DatasetSummary | null>(null);
  const [documentView, setDocumentView] = useState<DocumentContent | null>(null);

  const [schema, setSchema] = useState<ColumnSchema[]>([]);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [totalRows, setTotalRows] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRowIndex, setSelectedRowIndex] = useState<number | null>(null);

  const [filters, setFilters] = useState<ColumnFilter[]>([]);
  const [sqlResults, setSqlResults] = useState<{ result: SqlResult; query: string } | null>(null);
  const [cellFocus, setCellFocus] = useState<{
    row: Record<string, unknown>;
    index: number;
    column: ColumnSchema;
  } | null>(null);
  const [sort, setSort] = useState<{ column: string; dir: "asc" | "desc" } | null>(null);

  const nextCursorRef = useRef<number | null>(null);
  nextCursorRef.current = nextCursor;
  const rowsRef = useRef<Record<string, unknown>[]>([]);
  rowsRef.current = rows;
  const loadingRef = useRef(false);
  loadingRef.current = loading;
  const hasMoreRef = useRef(false);
  hasMoreRef.current = hasMore;

  useEffect(() => {
    if (theme === "cloud") {
      document.documentElement.dataset.theme = "cloud";
    } else {
      delete document.documentElement.dataset.theme;
    }
    localStorage.setItem("viewer-theme", theme);
  }, [theme]);

  const selectedRef = useRef<DatasetSummary | null>(null);
  selectedRef.current = selected;

  const refreshListings = useCallback(async () => {
    try {
      const [datasetList, documentList] = await Promise.all([fetchDatasets(), fetchDocuments()]);
      setDatasets(datasetList);
      setDocuments(documentList);

      // If the open artifact's backing file changed while the viewer was idle,
      // flip its revision so the data effects re-run against fresh data.
      const current = selectedRef.current;
      if (current) {
        const updated =
          current.format === "json"
            ? documentList.find((item) => item.id === current.id)
            : datasetList.find((item) => item.id === current.id);
        if (updated && updated.revision !== current.revision) {
          if (current.format === "json") {
            void fetchDocument(updated.id)
              .then(setDocumentView)
              .catch(() => {});
          }
          setSelected(updated);
        }
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, []);

  useEffect(() => {
    void refreshListings();
  }, [refreshListings]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void refreshListings();
    };
    const onFocus = () => void refreshListings();
    window.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onFocus);
    return () => {
      window.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onFocus);
    };
  }, [refreshListings]);

  useEffect(() => {
    localStorage.setItem("viewer-console", String(consoleOpen));
  }, [consoleOpen]);
  useEffect(() => {
    localStorage.setItem("viewer-sidebar", String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  const loadFirstPage = useCallback(async () => {
    if (!selected || selected.format === "json") return;
    setLoading(true);
    setError(null);
    setSelectedRowIndex(null);
    try {
      const page = await fetchRows(selected.id, {
        offset: 0,
        limit: PAGE_SIZE,
        sort: sort?.column,
        dir: sort?.dir,
        filters,
      });
      setRows(page.items);
      setHasMore(page.has_more);
      setNextCursor(page.next_cursor);
      setTotalRows(page.total_rows);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [selected, filters, sort]);

  useEffect(() => {
    setDocumentView(null);
    setSchema([]);
    setRows([]);
    setHasMore(false);
    setNextCursor(null);
    setTotalRows(null);
    setFilters([]);
    setSqlResults(null);
    setSort(null);
    setSelectedRowIndex(null);
    setCellFocus(null);
    setError(null);
    if (!selected || selected.format === "json") return;
    let cancelled = false;
    Promise.all([fetchSchema(selected.id), fetchStats(selected.id)])
      .then(([base, withStats]) => {
        if (cancelled) return;
        const topByColumn = new Map(
          withStats.map((column) => [column.name, column.top_values ?? []]),
        );
        setSchema(
          base.map((column) => ({
            ...column,
            top_values: topByColumn.get(column.name),
          })),
        );
      })
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)));
    return () => {
      cancelled = true;
    };
  }, [selected]);

  useEffect(() => {
    void loadFirstPage();
  }, [loadFirstPage]);

  const loadMore = useCallback(async () => {
    const cursor = nextCursorRef.current;
    if (
      !selected ||
      cursor === null ||
      loadingRef.current ||
      !hasMoreRef.current ||
      rowsRef.current.length >= MAX_LOADED_ROWS
    ) {
      return;
    }
    setLoading(true);
    try {
      const page = await fetchRows(selected.id, {
        offset: cursor,
        limit: PAGE_SIZE,
        sort: sort?.column,
        dir: sort?.dir,
        filters,
      });
      setRows((current) => {
        const merged = [...current, ...page.items];
        return merged.slice(0, MAX_LOADED_ROWS);
      });
      setHasMore(page.has_more);
      setNextCursor(page.next_cursor);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [selected, filters, sort]);

  const onTableScroll = useCallback(
    (event: UIEvent<HTMLDivElement>) => {
      const target = event.currentTarget;
      if (target.scrollTop + target.clientHeight >= target.scrollHeight - 240) {
        void loadMore();
      }
    },
    [loadMore],
  );

  const onSortToggle = useCallback((column: string) => {
    setSort((current) => {
      if (current?.column !== column) return { column, dir: "asc" };
      if (current.dir === "asc") return { column, dir: "desc" };
      return null;
    });
  }, []);

  const onFilterChange = useCallback((column: string, filter: ColumnFilter | null) => {
    setFilters((current) => {
      const next = current.filter((item) => item.column !== column);
      if (filter) next.push(filter);
      return next;
    });
  }, []);

  const onCellFocus = useCallback(
    (row: Record<string, unknown>, index: number, column: ColumnSchema) => {
      setCellFocus((current) =>
        current !== null && current.index === index && current.column.name === column.name
          ? null
          : { row, index, column },
      );
      setSelectedRowIndex(null);
    },
    [],
  );

  const onSelectDocument = useCallback(async (item: DatasetSummary) => {
    setSelected(item);
    try {
      setDocumentView(await fetchDocument(item.id));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, []);

  const isDocument = selected?.format === "json";
  const windowCapped = rows.length >= MAX_LOADED_ROWS && hasMore;

  return (
    <div
      className="shell"
      data-console={consoleOpen ? "open" : "closed"}
      data-sidebar={sidebarCollapsed ? "collapsed" : "open"}
    >
      <div className="topbar shell-topbar">
        <span className="topbar-title">EDGAR Dataset Viewer</span>
        {selected && (
          <span className="topbar-meta mono" title={selected.relative_path}>
            {selected.relative_path}
          </span>
        )}
        <span className="u-spacer" />
        <button className="btn btn-secondary" onClick={() => setConsoleOpen((open) => !open)}>
          {consoleOpen ? "Hide console" : "Show console"}
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
        >
          {sidebarCollapsed ? "Show explorer" : "Hide explorer"}
        </button>
        <button
          className="btn btn-ghost"
          onClick={() => setTheme(theme === "dark" ? "cloud" : "dark")}
        >
          {theme === "dark" ? "☾ dark" : "☀ cloud"}
        </button>
      </div>
      <ArtifactSidebar
        collapsed={sidebarCollapsed}
        datasets={datasets}
        documents={documents}
        selectedId={selected?.id ?? null}
        onRefresh={() => void refreshListings()}
        onSelect={(item) => {
          if (item.format === "json") {
            void onSelectDocument(item);
          } else {
            setSelected(item);
          }
        }}
      />
      <main className="shell-main">
        {isDocument && documentView ? (
          <div className="detail" style={{ flex: 1 }}>
            <div className="detail-header">
              <span className="panel-title mono">{documentView.summary.relative_path}</span>
            </div>
            <JsonDocument content={documentView.content} />
          </div>
        ) : sqlResults ? (
          <div className="results-view">
            <div className="table-toolbar">
              <button className="btn btn-secondary" onClick={() => setSqlResults(null)}>
                Back
              </button>
              <span className="breadcrumb mono">SQL: {sqlResults.query}</span>
            </div>
            <div className="table-wrap u-scroll-y">
              <table className="table">
                <thead>
                  <tr>
                    {sqlResults.result.columns.map((column) => (
                      <th key={column}>
                        <div className="table-headcell">
                          <span className="table-headcell-name mono">{column}</span>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sqlResults.result.rows.map((row, index) => (
                    <tr key={index}>
                      {sqlResults.result.columns.map((column) => (
                        <td key={column}>
                          {row[column] === null
                            ? "NULL"
                            : typeof row[column] === "object"
                              ? JSON.stringify(row[column])
                              : String(row[column])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pagination">
              {sqlResults.result.rows.length} rows in {sqlResults.result.elapsed_ms} ms
              {sqlResults.result.truncated ? " (truncated)" : ""}
            </div>
          </div>
        ) : (
          <>
            <div className="table-toolbar">
              {filters.length > 0 && (
                <div className="filter-chips">
                  {filters.map((filter) => (
                    <button
                      className="badge badge-kind filter-chip"
                      key={filter.column}
                      title="remove filter"
                      onClick={() => onFilterChange(filter.column, null)}
                    >
                      {filter.column} {filter.op}
                      {filter.value ? ` ${filter.value}` : ""} ×
                    </button>
                  ))}
                  <button className="btn btn-ghost" onClick={() => setFilters([])}>
                    Clear all
                  </button>
                </div>
              )}
              {totalRows !== null && (
                <span className="topbar-meta">{totalRows.toLocaleString()} rows</span>
              )}
              {rows.length > 0 && (
                <span className="topbar-meta">
                  showing {rows.length.toLocaleString()}
                  {totalRows === null ? "" : ` of ${totalRows.toLocaleString()}`}
                </span>
              )}
            </div>
            <div
              className="u-scroll-y"
              style={{ flex: 1, display: "flex", flexDirection: "column" }}
              onScroll={onTableScroll}
            >
              <DataTable
                schema={schema}
                rows={rows}
                totalRows={totalRows}
                sort={sort}
                onSortToggle={onSortToggle}
                hasMore={hasMore}
                loading={loading}
                onLoadMore={() => void loadMore()}
                onCellFocus={onCellFocus}
                selectedRowIndex={selectedRowIndex}
                error={error}
                windowCapped={windowCapped}
                filters={filters}
                onFilterChange={onFilterChange}
              />
              {selectedRowIndex !== null && rows[selectedRowIndex] ? (
                <RowDetail row={rows[selectedRowIndex]} onClose={() => setSelectedRowIndex(null)} />
              ) : cellFocus ? (
                <CellFocus
                  column={cellFocus.column}
                  value={cellFocus.row[cellFocus.column.name]}
                  onViewRow={() => setSelectedRowIndex(cellFocus.index)}
                  onClose={() => setCellFocus(null)}
                />
              ) : null}
            </div>
          </>
        )}
      </main>
      {consoleOpen && (
        <aside className="shell-right">
          <SqlConsole
            datasetId={selected && !isDocument ? selected.id : null}
            datasetName={selected ? (selected.relative_path.split("/").pop() ?? null) : null}
            onResult={(result, query) => setSqlResults({ result, query })}
          />
        </aside>
      )}
      <footer className="statusbar shell-status">
        <span>read-only viewer</span>
        <span className="u-spacer" />
        <span>theme: {theme}</span>
      </footer>
    </div>
  );
}
