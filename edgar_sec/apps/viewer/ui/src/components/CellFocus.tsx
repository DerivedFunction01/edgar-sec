import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { type BlobResponse, type ColumnSchema, fetchBlob } from "../api";
import { shortType } from "../lib/duckTypes";
import { JsonValue } from "./RowDetail";

/** Full text of a value: raw string, or pretty JSON for structures. */
function focusText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2) ?? String(value);
}

interface Props {
  datasetId?: string;
  column: ColumnSchema;
  value: unknown;
  row?: Record<string, unknown>;
  rowIndex?: number;
  onViewRow: () => void;
  onClose: () => void;
}

export default function CellFocus({
  datasetId,
  column,
  value,
  row,
  rowIndex,
  onViewRow,
  onClose,
}: Props) {
  const [wrap, setWrap] = useState(true);
  const [fullScreen, setFullScreen] = useState(false);
  const [renderHtml, setRenderHtml] = useState(false);

  const isBlobDescriptor =
    value !== null && typeof value === "object" && "__blob__" in (value as Record<string, unknown>);
  const isObject =
    !isBlobDescriptor && value !== null && typeof value === "object" && value !== undefined;

  const [blobData, setBlobData] = useState<BlobResponse | null>(null);
  const [blobLoading, setBlobLoading] = useState(false);
  const [blobError, setBlobError] = useState<string | null>(null);

  useEffect(() => {
    if (!isBlobDescriptor || !datasetId) {
      setBlobData(null);
      return;
    }
    let cancelled = false;
    setBlobLoading(true);
    setBlobError(null);

    let pkCol: string | undefined;
    let pkVal: string | undefined;
    if (row) {
      if (row.accession_number !== undefined && row.accession_number !== null) {
        pkCol = "accession_number";
        pkVal = String(row.accession_number);
      } else if (row.id !== undefined && row.id !== null) {
        pkCol = "id";
        pkVal = String(row.id);
      } else if (row.cik !== undefined && row.cik !== null) {
        pkCol = "cik";
        pkVal = String(row.cik);
      }
    }

    fetchBlob(datasetId, {
      column: column.name,
      pkCol,
      pkVal,
      rowIndex: pkCol ? undefined : rowIndex,
    })
      .then((res) => {
        if (!cancelled) {
          setBlobData(res);
          setBlobLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setBlobError(err instanceof Error ? err.message : String(err));
          setBlobLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [datasetId, column.name, isBlobDescriptor, row, rowIndex]);

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

  const rawText = focusText(value);
  const displayText =
    blobData?.text !== undefined && blobData.text !== null ? blobData.text : rawText;

  const body = (
    <div
      className={`cell-focus-body mono${wrap || isObject || renderHtml ? "" : " no-wrap"}`}
      style={renderHtml ? { padding: 0, overflow: "hidden" } : undefined}
    >
      {blobLoading ? (
        <div style={{ padding: "1rem" }}>
          <span className="u-muted">⚡ Decompressing BLOB payload ({column.name})…</span>
        </div>
      ) : blobError ? (
        <div style={{ padding: "1rem" }}>
          <span className="console-error">Failed to decompress BLOB: {blobError}</span>
        </div>
      ) : renderHtml && blobData?.text ? (
        <iframe
          srcDoc={blobData.text}
          title="HTML Preview"
          sandbox="allow-same-origin"
          style={{
            width: "100%",
            height: "100%",
            minHeight: "400px",
            border: "none",
            background: "#ffffff",
          }}
        />
      ) : value === null || value === undefined ? (
        <span className="badge badge-null">NULL</span>
      ) : isObject ? (
        <JsonValue value={value} />
      ) : (
        displayText
      )}
    </div>
  );

  const header = (inFullScreen: boolean) => (
    <>
      <span className="mono cell-focus-name">{column.name}</span>
      <span className="badge badge-type mono" title={column.duckdb_type}>
        {shortType(column.duckdb_type)}
      </span>
      {blobData && (
        <>
          <span className="badge badge-kind mono">
            {blobData.is_compressed ? "⚡ ZSTD" : "BLOB"}{" "}
            {blobData.compressed_bytes.toLocaleString()} B →{" "}
            {blobData.decompressed_bytes.toLocaleString()} B ({blobData.compression_ratio}x)
          </span>
          <span className="badge badge-type mono">{blobData.mime_type}</span>
        </>
      )}
      <span className="u-spacer" />
      {blobData?.mime_type === "text/html" && (
        <button
          className="btn btn-ghost"
          data-on={renderHtml}
          onClick={() => setRenderHtml((current) => !current)}
        >
          {renderHtml ? "View Source" : "Render HTML"}
        </button>
      )}
      {!isObject && !renderHtml && (
        <button
          className="btn btn-ghost"
          data-on={wrap}
          onClick={() => setWrap((current) => !current)}
        >
          wrap
        </button>
      )}
      <button
        className="btn btn-ghost"
        onClick={() => void navigator.clipboard?.writeText(displayText)}
      >
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
