import { type UIEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  type ColumnFilter,
  type ColumnSchema,
  fetchRows,
  fetchSchema,
  fetchStats,
  type SqlResult,
  type TreeEntry,
} from "./api";
import ArtifactSidebar from "./components/ArtifactSidebar";
import CellFocus from "./components/CellFocus";
import DataTable from "./components/DataTable";
import RowDetail from "./components/RowDetail";
import SqlConsole from "./components/SqlConsole";
import TextFileView from "./components/TextFileView";

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

  const [selected, setSelected] = useState<TreeEntry | null>(null);

  const [schema, setSchema] = useState<ColumnSchema[]>([]);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [totalRows, setTotalRows] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRowIndex, setSelectedRowIndex] = useState<number | null>(null);
  const [statsLoaded, setStatsLoaded] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);

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

  const selectedRef = useRef<TreeEntry | null>(null);
  selectedRef.current = selected;
  const rowRequestVersion = useRef(0);
  const statsRequestVersion = useRef(0);

  useEffect(() => {
    localStorage.setItem("viewer-console", String(consoleOpen));
  }, [consoleOpen]);
  useEffect(() => {
    localStorage.setItem("viewer-sidebar", String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  const loadFirstPage = useCallback(async () => {
    const version = ++rowRequestVersion.current;
    if (!selected || selected.format === "text") return;
    loadingRef.current = true;
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
      if (version !== rowRequestVersion.current || selectedRef.current?.id !== selected.id) {
        return;
      }
      setRows(page.items);
      setHasMore(page.has_more);
      setNextCursor(page.next_cursor);
      setTotalRows(page.total_rows);
    } catch (exc) {
      if (version === rowRequestVersion.current) {
        setError(exc instanceof Error ? exc.message : String(exc));
      }
    } finally {
      if (version === rowRequestVersion.current) {
        loadingRef.current = false;
        setLoading(false);
      }
    }
  }, [selected, filters, sort]);

  useEffect(() => {
    statsRequestVersion.current++;
    setSchema([]);
    setRows([]);
    setHasMore(false);
    setNextCursor(null);
    setTotalRows(null);
    setSqlResults(null);
    setSelectedRowIndex(null);
    setCellFocus(null);
    setError(null);
    setStatsLoaded(false);
    setStatsLoading(false);
    if (!selected || selected.format === "text") return;
    let cancelled = false;
    void fetchSchema(selected.id)
      .then((base) => {
        if (cancelled) return;
        setSchema(base);
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
    const version = rowRequestVersion.current;
    const datasetId = selected.id;
    loadingRef.current = true;
    setLoading(true);
    try {
      const page = await fetchRows(selected.id, {
        offset: cursor,
        limit: PAGE_SIZE,
        sort: sort?.column,
        dir: sort?.dir,
        filters,
      });
      if (version !== rowRequestVersion.current || selectedRef.current?.id !== datasetId) {
        return;
      }
      setRows((current) => {
        const merged = [...current, ...page.items];
        return merged.slice(0, MAX_LOADED_ROWS);
      });
      setHasMore(page.has_more);
      setNextCursor(page.next_cursor);
    } catch (exc) {
      if (version === rowRequestVersion.current) {
        setError(exc instanceof Error ? exc.message : String(exc));
      }
    } finally {
      if (version === rowRequestVersion.current) {
        loadingRef.current = false;
        setLoading(false);
      }
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

  const onSelect = useCallback((entry: TreeEntry) => {
    if (selectedRef.current?.id === entry.id) return;
    selectedRef.current = entry;
    setFilters([]);
    setSort(null);
    setSelected(entry);
  }, []);

  const loadStats = async () => {
    if (!selected || statsLoading || statsLoaded) return;
    const id = selected.id;
    const version = ++statsRequestVersion.current;
    setStatsLoading(true);
    try {
      const stats = await fetchStats(id);
      if (version === statsRequestVersion.current && selectedRef.current?.id === id) {
        setSchema(stats);
        setStatsLoaded(true);
      }
    } catch (exc) {
      if (version === statsRequestVersion.current && selectedRef.current?.id === id) {
        setError(exc instanceof Error ? exc.message : String(exc));
      }
    } finally {
      if (version === statsRequestVersion.current) setStatsLoading(false);
    }
  };

  const isText = selected?.format === "text";
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
        selectedId={selected?.id ?? null}
        onSelect={onSelect}
      />
      <main className="shell-main">
        {isText && selected ? (
          <TextFileView key={selected.id} id={selected.id} path={selected.relative_path} />
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
              {selected && schema.length > 0 && !statsLoaded && (
                <button
                  className="btn btn-ghost"
                  onClick={() => void loadStats()}
                  disabled={statsLoading}
                >
                  {statsLoading ? "Calculating stats…" : "Load column stats"}
                </button>
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
                  datasetId={selected?.id}
                  column={cellFocus.column}
                  value={cellFocus.row[cellFocus.column.name]}
                  row={cellFocus.row}
                  rowIndex={cellFocus.index}
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
          {selected?.format === "duckdb" ? (
            <div className="console">
              <div className="panel-header">SQL Console</div>
              <div className="tree-message">
                The console is disabled for native DuckDB files to keep queries scoped to one
                selected table.
              </div>
            </div>
          ) : (
            <SqlConsole
              datasetId={selected && !isText ? selected.id : null}
              datasetName={selected?.name ?? null}
              onResult={(result, query) => setSqlResults({ result, query })}
            />
          )}
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
