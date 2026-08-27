import { useState } from "react";
import { createPortal } from "react-dom";
import type { ColumnFilter, ColumnSchema, FilterOp } from "../api";
import { shortType } from "../lib/duckTypes";

type Family = "text" | "number" | "date" | "bool" | "other";

function familyOf(duckdbType: string): Family {
  const t = duckdbType.toUpperCase();
  if (t.startsWith("BOOLEAN")) return "bool";
  if (/INT|DECIMAL|DOUBLE|FLOAT|REAL|NUMERIC|HUGEINT/.test(t)) return "number";
  if (t.startsWith("DATE") || t.startsWith("TIME")) return "date";
  if (
    t.startsWith("VARCHAR") ||
    t.startsWith("CHAR") ||
    t.includes("TEXT") ||
    t.includes("STRING")
  ) {
    return "text";
  }
  return "other";
}

const OP_LABELS: Record<FilterOp, string> = {
  contains: "contains",
  not_contains: "does not contain",
  eq: "=",
  ne: "≠",
  gt: ">",
  ge: "≥",
  lt: "<",
  le: "≤",
  empty: "is empty",
  not_empty: "is not empty",
};

const FAMILY_OPS: Record<Family, FilterOp[]> = {
  text: ["contains", "not_contains", "eq", "ne", "empty", "not_empty"],
  number: ["gt", "ge", "lt", "le", "eq", "ne", "empty", "not_empty"],
  date: ["gt", "ge", "lt", "le", "eq", "ne", "empty", "not_empty"],
  bool: ["eq", "ne", "empty", "not_empty"],
  other: ["contains", "not_contains", "empty", "not_empty"],
};

interface Props {
  column: ColumnSchema;
  filter: ColumnFilter | undefined;
  anchor: DOMRect;
  onApply: (filter: ColumnFilter | null) => void;
  onClose: () => void;
}

export default function FilterPopup({ column, filter, anchor, onApply, onClose }: Props) {
  const family = familyOf(column.duckdb_type);
  const ops = FAMILY_OPS[family];
  const [op, setOp] = useState<FilterOp>(
    filter?.op && ops.includes(filter.op) ? filter.op : ops[0],
  );
  const [value, setValue] = useState(filter?.value ?? "");
  const needsValue = op !== "empty" && op !== "not_empty";
  const numericInvalid =
    needsValue &&
    (family === "number" || family === "date") &&
    value.trim() !== "" &&
    (family === "number" ? !Number.isFinite(Number(value)) : Number.isNaN(Date.parse(value)));
  const canApply = !needsValue || (value.trim() !== "" && !numericInvalid);

  const apply = () => {
    if (!canApply) return;
    onApply(
      needsValue ? { column: column.name, op, value: value.trim() } : { column: column.name, op },
    );
    onClose();
  };

  const left = Math.min(anchor.left, window.innerWidth - 260);
  const top = anchor.bottom + 6;

  return createPortal(
    <>
      <div className="pop-backdrop" onClick={onClose} />
      <div
        className="filter-pop"
        style={{ left, top }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="filter-pop-head">
          <span className="mono filter-pop-name">{column.name}</span>
          <span className="badge badge-type mono" title={column.duckdb_type}>
            {shortType(column.duckdb_type)}
          </span>
        </div>
        <select
          className="select"
          value={op}
          onChange={(event) => setOp(event.target.value as FilterOp)}
        >
          {ops.map((candidate) => (
            <option key={candidate} value={candidate}>
              {OP_LABELS[candidate]}
            </option>
          ))}
        </select>
        {needsValue && family === "bool" ? (
          <select
            className="select"
            value={value || "true"}
            onChange={(event) => setValue(event.target.value)}
          >
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        ) : needsValue ? (
          <input
            className="input"
            placeholder={
              family === "number" ? "number" : family === "date" ? "YYYY-MM-DD…" : "value"
            }
            value={value}
            autoFocus
            onKeyDown={(event) => {
              if (event.key === "Enter") apply();
              if (event.key === "Escape") onClose();
            }}
            onChange={(event) => setValue(event.target.value)}
          />
        ) : null}
        {numericInvalid && (
          <div className="filter-pop-error">
            enter a valid {family === "number" ? "number" : "date"}
          </div>
        )}
        <div className="filter-pop-actions">
          {filter && (
            <button
              className="btn btn-danger"
              onClick={() => {
                onApply(null);
                onClose();
              }}
            >
              Clear
            </button>
          )}
          <span className="u-spacer" />
          <button className="btn btn-primary" onClick={apply} disabled={!canApply}>
            Apply
          </button>
        </div>
      </div>
    </>,
    document.body,
  );
}
