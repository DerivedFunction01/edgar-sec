import { useEffect, useState } from "react";
import type { ColumnFilter, ColumnSchema } from "../api";
import { hasTypeArgs, shortType } from "../lib/duckTypes";
import FilterPopup from "./FilterPopup";
import TypePopup from "./TypePopup";

interface Props {
  schema: ColumnSchema[];
  rows: Record<string, unknown>[];
  totalRows: number | null;
  sort: { column: string; dir: "asc" | "desc" } | null;
  onSortToggle: (column: string) => void;
  hasMore: boolean;
  loading: boolean;
  onLoadMore: () => void;
  onCellFocus: (row: Record<string, unknown>, index: number, column: ColumnSchema) => void;
  selectedRowIndex: number | null;
  error: string | null;
  windowCapped: boolean;
  filters: ColumnFilter[];
  onFilterChange: (column: string, filter: ColumnFilter | null) => void;
}

function cellText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function previewText(value: unknown, max = 200): string {
  const text = cellText(value);
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

const MAX_LOADED_ROWS = 2000;

export default function DataTable({
  schema,
  rows,
  totalRows,
  sort,
  onSortToggle,
  hasMore,
  loading,
  onLoadMore,
  onCellFocus,
  selectedRowIndex,
  error,
  windowCapped,
  filters,
  onFilterChange,
}: Props) {
  const [openFilter, setOpenFilter] = useState<string | null>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const [typeInfo, setTypeInfo] = useState<{
    name: string;
    type: string;
    rect: DOMRect;
  } | null>(null);
  const filterFor = (name: string) => filters.find((item) => item.column === name);

  useEffect(() => setOpenFilter(null), [schema]);

  const toggleFilter = (column: string, button: HTMLButtonElement) => {
    if (openFilter === column) {
      setOpenFilter(null);
      return;
    }
    setAnchorRect(button.getBoundingClientRect());
    setOpenFilter(column);
  };

  return (
    <>
      <div className="table-wrap">
        {schema.length === 0 && !loading ? (
          <div className="table-empty">{error ?? "Select a dataset from the sidebar."}</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                {schema.map((column) => {
                  const active = sort?.column === column.name;
                  const filter = filterFor(column.name);
                  const expandableType = hasTypeArgs(column.duckdb_type);
                  const denominator = totalRows !== null && totalRows > 0 ? totalRows : 1;
                  const nullShare = (column.null_count / denominator) * 100;
                  return (
                    <th key={column.name}>
                      <div className="table-headcell">
                        <span
                          className="table-headcell-name"
                          onClick={() => onSortToggle(column.name)}
                        >
                          {column.name}
                          {active && (
                            <span className="sort-arrow">{sort?.dir === "asc" ? "▲" : "▼"}</span>
                          )}
                        </span>
                        <span className="table-headcell-meta">
                          <span
                            className="badge badge-type mono"
                            title={column.duckdb_type}
                            data-clickable={expandableType}
                            onClick={(event) => {
                              if (!expandableType) return;
                              event.stopPropagation();
                              setTypeInfo({
                                name: column.name,
                                type: column.duckdb_type,
                                rect: event.currentTarget.getBoundingClientRect(),
                              });
                            }}
                          >
                            {shortType(column.duckdb_type)}
                          </span>
                          <span title="approx distinct">~{column.approx_distinct}</span>
                          <span
                            className="minibar"
                            title={`nulls: ${column.null_count}, ~distinct: ${column.approx_distinct}`}
                          >
                            <span
                              className="minibar-fill"
                              style={{ width: `${Math.min(100, nullShare)}%` }}
                            />
                          </span>
                          <button
                            className="head-filter-btn"
                            data-active={filter !== undefined}
                            title={
                              filter
                                ? `${filter.op}${filter.value ? ` ${filter.value}` : ""}`
                                : "filter column"
                            }
                            onClick={(event) => toggleFilter(column.name, event.currentTarget)}
                          >
                            <svg width="10" height="10" viewBox="0 0 16 16" aria-hidden="true">
                              <path d="M1 2h14L10 8.6V14l-4-2.2V8.6L1 2z" fill="currentColor" />
                            </svg>
                          </button>
                        </span>
                      </div>
                      {openFilter === column.name && anchorRect && (
                        <FilterPopup
                          column={column}
                          filter={filter}
                          anchor={anchorRect}
                          onApply={(next) => onFilterChange(column.name, next)}
                          onClose={() => setOpenFilter(null)}
                        />
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr
                  key={`${index}:${JSON.stringify(row).slice(0, 64)}`}
                  data-selected={index === selectedRowIndex}
                >
                  {schema.map((column) => {
                    const value = row[column.name];
                    return (
                      <td
                        key={column.name}
                        title={previewText(value)}
                        onClick={() => onCellFocus(row, index, column)}
                      >
                        {value === null || value === undefined ? (
                          <span className="badge badge-null">NULL</span>
                        ) : typeof value === "object" ? (
                          <span className="mono">{JSON.stringify(value).slice(0, 120)}</span>
                        ) : (
                          cellText(value)
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
              {rows.length === 0 && !loading && (
                <tr>
                  <td colSpan={Math.max(schema.length, 1)}>
                    <div className="table-empty">No rows.</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
      <div className="pagination">
        {error && <span className="console-error">{error}</span>}
        {loading && <span className="u-muted">loading…</span>}
        {windowCapped && (
          <span className="u-muted">
            row window capped at {MAX_LOADED_ROWS}; refine filters or sort to narrow results
          </span>
        )}
        <span className="u-spacer" />
        {hasMore && !windowCapped && (
          <button className="btn btn-secondary" onClick={onLoadMore} disabled={loading}>
            Load more
          </button>
        )}
      </div>
      {typeInfo && (
        <TypePopup
          name={typeInfo.name}
          type={typeInfo.type}
          anchor={typeInfo.rect}
          onClose={() => setTypeInfo(null)}
        />
      )}
    </>
  );
}
