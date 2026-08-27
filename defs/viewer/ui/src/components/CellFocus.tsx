import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { ColumnSchema } from "../api";
import { shortType } from "../lib/duckTypes";
import { JsonValue } from "./RowDetail";

/** Full text of a value: raw string, or pretty JSON for structures. */
function focusText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2) ?? String(value);
}

interface Props {
  column: ColumnSchema;
  value: unknown;
  onViewRow: () => void;
  onClose: () => void;
}

export default function CellFocus({ column, value, onViewRow, onClose }: Props) {
  const [wrap, setWrap] = useState(true);
  const [fullScreen, setFullScreen] = useState(false);
  const isObject = value !== null && typeof value === "object" && value !== undefined;
  const text = focusText(value);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (fullScreen) {
        setFullScreen(false);
      } else {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullScreen, onClose]);

  const body = (
    <div className={`cell-focus-body mono${wrap || isObject ? "" : " no-wrap"}`}>
      {value === null || value === undefined ? (
        <span className="badge badge-null">NULL</span>
      ) : isObject ? (
        <JsonValue value={value} />
      ) : (
        text
      )}
    </div>
  );

  const header = (inFullScreen: boolean) => (
    <>
      <span className="mono cell-focus-name">{column.name}</span>
      <span className="badge badge-type mono" title={column.duckdb_type}>
        {shortType(column.duckdb_type)}
      </span>
      <span className="u-spacer" />
      {!isObject && (
        <button
          className="btn btn-ghost"
          data-on={wrap}
          onClick={() => setWrap((current) => !current)}
        >
          wrap
        </button>
      )}
      <button className="btn btn-ghost" onClick={() => void navigator.clipboard?.writeText(text)}>
        Copy
      </button>
      {inFullScreen ? (
        <button className="btn btn-secondary" onClick={() => setFullScreen(false)}>
          Close full screen
        </button>
      ) : (
        <>
          <button className="btn btn-ghost" onClick={() => setFullScreen(true)}>
            Full screen
          </button>
          <button className="btn btn-secondary" onClick={onViewRow}>
            View full row
          </button>
          <button className="btn btn-ghost" onClick={onClose} title="close">
            ✕
          </button>
        </>
      )}
    </>
  );

  if (fullScreen) {
    return createPortal(
      <div className="cell-fullscreen">
        <div className="cell-fullscreen-head">{header(true)}</div>
        {body}
      </div>,
      document.body,
    );
  }

  return (
    <div className="detail cell-focus">
      <div className="detail-header cell-focus-head">{header(false)}</div>
      {body}
    </div>
  );
}
